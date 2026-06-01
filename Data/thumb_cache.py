# -*- coding: utf-8 -*-
"""
Cache persistant de miniatures d'images — partagé entre Dashboard, SidePanel et Kiosk.

Un fichier SQLite (.thumbcache.db) est créé dans chaque dossier d'images.
Les miniatures sont stockées en base64 (TEXT) dans la DB, mais get_or_generate() retourne des
bytes décodés — directement utilisables dans ft.Image(src=bytes) sous Flet 0.84+.
Si le dossier est en lecture seule, un cache session en mémoire est utilisé (non persistant).

API publique :
  get_or_generate(image_path, size_px, quality, grayscale) -> bytes | None
  preload_folder(folder_path, filenames, size_px, quality, grayscale, progress_cb, stop_token, token_value)
  invalidate_stale(folder_path)
"""

import os
import sys
import io
import base64
import sqlite3
import threading
from typing import Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import CONSTANTS

try:
    from PIL import Image as _PILImage, ImageOps as _PILImageOps
    _HAS_PIL = True
except ImportError:
    _PILImage = None       # type: ignore[assignment]
    _PILImageOps = None    # type: ignore[assignment]
    _HAS_PIL = False


# ── Thread-safety : un verrou par dossier ────────────────────────────────────
_db_locks: dict[str, threading.Lock] = {}
_locks_mutex = threading.Lock()

# ── Fallback lecture seule : cache session en mémoire ────────────────────────
# Clé : (folder_path, filename, size_px, grayscale_int) → (mtime, b64)
_session_fallback: dict[tuple, tuple] = {}

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS thumbs (
    filename  TEXT    NOT NULL,
    size_px   INTEGER NOT NULL,
    grayscale INTEGER NOT NULL DEFAULT 0,
    mtime     REAL    NOT NULL,
    mtime_ns  INTEGER NOT NULL DEFAULT 0,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    ctime_ns  INTEGER NOT NULL DEFAULT 0,
    b64       TEXT    NOT NULL,
    PRIMARY KEY (filename, size_px, grayscale)
)
"""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Ajoute les colonnes de signature fichier si la DB provient d'une ancienne version."""
    existing_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(thumbs)").fetchall()
    }
    if "mtime_ns" not in existing_columns:
        conn.execute("ALTER TABLE thumbs ADD COLUMN mtime_ns INTEGER NOT NULL DEFAULT 0")
    if "size_bytes" not in existing_columns:
        conn.execute("ALTER TABLE thumbs ADD COLUMN size_bytes INTEGER NOT NULL DEFAULT 0")
    if "ctime_ns" not in existing_columns:
        conn.execute("ALTER TABLE thumbs ADD COLUMN ctime_ns INTEGER NOT NULL DEFAULT 0")


def _get_db_lock(folder_path: str) -> threading.Lock:
    with _locks_mutex:
        if folder_path not in _db_locks:
            _db_locks[folder_path] = threading.Lock()
        return _db_locks[folder_path]


def _get_db_path(folder_path: str) -> Optional[str]:
    """
    Retourne le chemin vers .thumbcache.db dans folder_path,
    ou None si le dossier n'est pas accessible en écriture.
    """
    try:
        db_path = os.path.join(folder_path, CONSTANTS.THUMB_CACHE_DB_NAME)
        if os.path.exists(db_path):
            return db_path
        # Tester la création (ouvre en mode ajout, ne tronque pas)
        with open(db_path, "ab"):
            pass
        return db_path
    except OSError:
        return None


def _open_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(_CREATE_TABLE_SQL)
    _ensure_schema(conn)
    conn.commit()
    return conn


def _generate_b64(
    image_path: str,
    size_px: int,
    quality: int,
    grayscale: bool,
) -> Optional[str]:
    """Génère une miniature avec PIL et retourne sa représentation base64 JPEG."""
    if not _HAS_PIL:
        return None
    try:
        with _PILImage.open(image_path) as img:
            img = _PILImageOps.exif_transpose(img)
            if grayscale:
                img = img.convert("L").convert("RGB")
            else:
                img = img.convert("RGB")
            img.thumbnail((size_px, size_px), _PILImage.LANCZOS)
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=quality, optimize=True)
            return base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:
        return None


def get_or_generate(
    image_path: str,
    size_px: int = None,
    quality: int = None,
    grayscale: bool = False,
) -> Optional[bytes]:
    """
    Retourne les bytes de la miniature (JPEG décodé) depuis le cache SQLite,
    ou la génère si absente/périmée.
    Retourne None si PIL n'est pas disponible ou si la génération échoue.
    Compatible directement avec ft.Image(src=bytes) sous Flet 0.84+.
    """
    if size_px is None:
        size_px = CONSTANTS.THUMB_CACHE_SIZE
    if quality is None:
        quality = CONSTANTS.THUMB_CACHE_QUALITY

    folder_path = os.path.dirname(os.path.abspath(image_path))
    filename = os.path.basename(image_path)
    grayscale_int = 1 if grayscale else 0

    try:
        stat_result = os.stat(image_path)
    except OSError:
        return None
    mtime = stat_result.st_mtime
    mtime_ns = getattr(stat_result, "st_mtime_ns", int(mtime * 1_000_000_000))
    size_bytes = stat_result.st_size
    ctime = getattr(stat_result, "st_ctime", mtime)
    ctime_ns = getattr(stat_result, "st_ctime_ns", int(ctime * 1_000_000_000))

    lock = _get_db_lock(folder_path)
    db_path = _get_db_path(folder_path)

    if db_path is not None:
        with lock:
            try:
                conn = _open_db(db_path)
                try:
                    row = conn.execute(
                        "SELECT mtime, mtime_ns, size_bytes, ctime_ns, b64 FROM thumbs"
                        " WHERE filename=? AND size_px=? AND grayscale=?",
                        (filename, size_px, grayscale_int),
                    ).fetchone()
                    if row:
                        row_mtime, row_mtime_ns, row_size, row_ctime_ns, row_b64 = row
                        # Compatibilité avec anciens enregistrements : si signature absente (0),
                        # on retombe sur l'ancienne comparaison au mtime.
                        if row_mtime_ns and row_size and row_ctime_ns:
                            if (
                                row_mtime_ns == mtime_ns
                                and row_size == size_bytes
                                and row_ctime_ns == ctime_ns
                            ):
                                return base64.b64decode(row_b64)
                        elif abs(row_mtime - mtime) < 0.5:
                            return base64.b64decode(row_b64)
                    # Absent ou périmé — générer, puis insérer
                    b64 = _generate_b64(image_path, size_px, quality, grayscale)
                    if b64 is not None:
                        conn.execute(
                            "INSERT OR REPLACE INTO thumbs"
                            "(filename, size_px, grayscale, mtime, mtime_ns, size_bytes, ctime_ns, b64)"
                            " VALUES(?,?,?,?,?,?,?,?)",
                            (filename, size_px, grayscale_int, mtime, mtime_ns, size_bytes, ctime_ns, b64),
                        )
                        conn.commit()
                    return base64.b64decode(b64) if b64 is not None else None
                finally:
                    conn.close()
            except Exception:
                pass  # Fallback session ci-dessous

    # ── Fallback session (dossier en lecture seule) ───────────────────────────
    fallback_key = (folder_path, filename, size_px, grayscale_int)
    if fallback_key in _session_fallback:
        cached_signature, cached_bytes = _session_fallback[fallback_key]
        if cached_signature == (mtime_ns, size_bytes, ctime_ns):
            return cached_bytes

    b64 = _generate_b64(image_path, size_px, quality, grayscale)
    if b64 is not None:
        image_bytes = base64.b64decode(b64)
        _session_fallback[fallback_key] = ((mtime_ns, size_bytes, ctime_ns), image_bytes)
        return image_bytes
    return None


def preload_folder(
    folder_path: str,
    filenames: list,
    size_px: int = None,
    quality: int = None,
    grayscale: bool = False,
    progress_cb: Callable = None,
    stop_token: dict = None,
    token_value: int = None,
) -> None:
    """
    Pré-génère les miniatures manquantes pour une liste de fichiers (appeler dans un thread).
    progress_cb(done, total) est appelé après chaque image traitée.
    Annulé si stop_token["value"] != token_value.
    """
    if size_px is None:
        size_px = CONSTANTS.THUMB_CACHE_SIZE
    if quality is None:
        quality = CONSTANTS.THUMB_CACHE_QUALITY

    total = len(filenames)
    for index, filename in enumerate(filenames):
        if stop_token is not None and stop_token["value"] != token_value:
            return
        image_path = os.path.join(folder_path, filename)
        get_or_generate(image_path, size_px, quality, grayscale)
        if progress_cb is not None:
            progress_cb(index + 1, total)


def invalidate_stale(folder_path: str) -> None:
    """Supprime du cache les entrées dont la mtime a changé ou dont le fichier a disparu."""
    db_path = _get_db_path(folder_path)
    if db_path is None or not os.path.exists(db_path):
        return
    lock = _get_db_lock(folder_path)
    with lock:
        try:
            conn = _open_db(db_path)
            try:
                rows = conn.execute(
                    "SELECT DISTINCT filename, mtime, mtime_ns, size_bytes, ctime_ns FROM thumbs"
                ).fetchall()
                stale_filenames = []
                for filename, cached_mtime, cached_mtime_ns, cached_size, cached_ctime_ns in rows:
                    file_path = os.path.join(folder_path, filename)
                    try:
                        stat_result = os.stat(file_path)
                        current_mtime = stat_result.st_mtime
                        current_mtime_ns = getattr(stat_result, "st_mtime_ns", int(current_mtime * 1_000_000_000))
                        current_size = stat_result.st_size
                        ctime = getattr(stat_result, "st_ctime", current_mtime)
                        current_ctime_ns = getattr(stat_result, "st_ctime_ns", int(ctime * 1_000_000_000))

                        if cached_mtime_ns and cached_size and cached_ctime_ns:
                            if (
                                current_mtime_ns != cached_mtime_ns
                                or current_size != cached_size
                                or current_ctime_ns != cached_ctime_ns
                            ):
                                stale_filenames.append(filename)
                        elif abs(current_mtime - cached_mtime) >= 0.5:
                            stale_filenames.append(filename)
                    except OSError:
                        stale_filenames.append(filename)  # Fichier disparu
                if stale_filenames:
                    conn.executemany(
                        "DELETE FROM thumbs WHERE filename=?",
                        [(f,) for f in stale_filenames],
                    )
                    conn.commit()
            finally:
                conn.close()
        except Exception:
            pass
