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

_VECTOR_EXTS = {".svg", ".pdf"}


def _render_vector(image_path: str, ext: str, size_px: int):
    """Rasterise un fichier vectoriel (.pdf, .svg) en image PIL.

    Rendu à ~2x size_px avant le thumbnail() de _generate_b64 (marge de
    qualité pour l'écran) plutôt qu'à la résolution native du fichier —
    évite de rastériser un poster A0 en pleine résolution pour une
    miniature de 320px.
    """
    if ext == ".pdf":
        import fitz  # PyMuPDF
        with fitz.open(image_path) as doc:
            if doc.page_count == 0:
                return None
            page = doc[0]
            longest = max(page.rect.width, page.rect.height) or 1
            zoom = min(4.0, max(0.5, (size_px * 2) / longest))
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            return _PILImage.frombytes(
                "RGB", (pix.width, pix.height), pix.samples)
    if ext == ".svg":
        from wand.image import Image as _WandImage
        # Une résolution fixe (150 DPI, quelle que soit la taille du SVG)
        # rasterisait TOUJOURS à la taille "physique" du fichier — pour un
        # gros viewBox, souvent bien plus que les 320px utiles à une
        # miniature. Sur un dossier de centaines de SVG, ce travail perdu
        # ralentissait toute l'app pendant le chargement (retour user).
        # Comme pour les PDF ci-dessus : on vise ~2x size_px, jamais plus.
        native = _svg_native_size(image_path)
        if native:
            longest = max(native) or 1
            resolution = 96 * min(4.0, max(0.3, (size_px * 2) / longest))
        else:
            resolution = 150
        with _WandImage(filename=image_path, resolution=resolution) as wand_img:
            wand_img.format = "png"
            blob = wand_img.make_blob()
        return _PILImage.open(io.BytesIO(blob)).convert("RGB")
    return None


def _svg_native_size(path):
    """Largeur/hauteur "naturelles" d'un SVG (attributs width/height, sinon
    viewBox), lues via un parsing XML — gratuit, contrairement à Wand qui
    doit rasteriser tout le fichier rien que pour connaître sa taille."""
    try:
        import xml.etree.ElementTree as _ET

        root = _ET.parse(path).getroot()

        def _num(s):
            if not s:
                return None
            s = s.strip()
            for suffix in ("px", "pt", "mm", "cm", "in", "%"):
                if s.endswith(suffix):
                    s = s[:-len(suffix)]
                    break
            try:
                return float(s)
            except ValueError:
                return None

        w, h = _num(root.get("width")), _num(root.get("height"))
        if w and h:
            return w, h
        view_box = root.get("viewBox")
        if view_box:
            parts = view_box.replace(",", " ").split()
            if len(parts) == 4:
                return float(parts[2]), float(parts[3])
    except Exception:
        pass
    return None


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
    ext = os.path.splitext(image_path)[1].lower()
    try:
        if ext in _VECTOR_EXTS:
            img = _render_vector(image_path, ext, size_px)
            if img is None:
                return None
        else:
            img = _PILImage.open(image_path)
            img = _PILImageOps.exif_transpose(img)
        with img:
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
    ou la génère si absente.

    Une entrée en cache est utilisée sans revalider mtime/ctime à chaque
    appel (retour user) : les cartes SD d'appareil photo (FAT32/exFAT) ont
    des timestamps peu fiables — le ctime en particulier n'est pas garanti
    stable d'une lecture à l'autre sur ces systèmes de fichiers — donc cette
    revalidation faisait régénérer TOUTES les miniatures à chaque retour
    dans le dossier, même sans aucun changement.

    La taille en octets, elle, reste comparée : c'est un signal fiable
    (contrairement à mtime/ctime sur SD) qui détecte le cas d'un NOM de
    fichier réutilisé pour un contenu différent — ex. "Renommer séquence"
    relancé une 2e fois sur une sélection différente, où "emoji_011.png"
    désigne maintenant une autre photo qu'au premier passage. Sans ce
    contrôle, l'ancienne vignette restait affichée indéfiniment sous le
    nouveau nom (retour user). invalidate_stale() reste le mécanisme
    explicite pour purger une entrée devenue obsolète par ailleurs.

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

    lock = _get_db_lock(folder_path)
    db_path = _get_db_path(folder_path)

    if db_path is not None:
        try:
            # stat() se fait AVANT le lookup (coût négligeable — simple
            # métadonnée, contrairement à la génération d'image — même sur
            # SD/réseau lent) pour pouvoir comparer size_bytes au hit de
            # cache, cf. docstring ci-dessus.
            try:
                stat_result = os.stat(image_path)
            except OSError:
                return None
            mtime = stat_result.st_mtime
            mtime_ns = getattr(stat_result, "st_mtime_ns", int(mtime * 1_000_000_000))
            size_bytes = stat_result.st_size
            ctime = getattr(stat_result, "st_ctime", mtime)
            ctime_ns = getattr(stat_result, "st_ctime_ns", int(ctime * 1_000_000_000))

            with lock:
                conn = _open_db(db_path)
                try:
                    row = conn.execute(
                        "SELECT b64, size_bytes FROM thumbs"
                        " WHERE filename=? AND size_px=? AND grayscale=?",
                        (filename, size_px, grayscale_int),
                    ).fetchone()
                finally:
                    conn.close()
            if row and row[1] == size_bytes:
                return base64.b64decode(row[0])

            # Cache absent OU taille différente (nom réutilisé pour un
            # autre fichier) — génération HORS verrou : Wand/PyMuPDF/PIL
            # font le gros du travail ici, et le garder hors du verrou
            # permet à plusieurs threads de générer plusieurs miniatures EN
            # PARALLÈLE au lieu de se sérialiser sur un fichier à la fois —
            # sinon le verrou annulait tout le bénéfice du pool de threads
            # sur un dossier de centaines de SVG/PDF (retour user).
            b64 = _generate_b64(image_path, size_px, quality, grayscale)
            if b64 is not None:
                with lock:
                    conn = _open_db(db_path)
                    try:
                        conn.execute(
                            "INSERT OR REPLACE INTO thumbs"
                            "(filename, size_px, grayscale, mtime, mtime_ns, size_bytes, ctime_ns, b64)"
                            " VALUES(?,?,?,?,?,?,?,?)",
                            (filename, size_px, grayscale_int, mtime, mtime_ns, size_bytes, ctime_ns, b64),
                        )
                        conn.commit()
                    finally:
                        conn.close()
            return base64.b64decode(b64) if b64 is not None else None
        except Exception:
            pass  # Fallback session ci-dessous

    # ── Fallback session (dossier en lecture seule, ou DB inaccessible) ───────
    # Cache en mémoire seulement (process courant) : ici la resignature à
    # chaque appel est peu coûteuse (pas de disque SD en jeu, juste stat()),
    # donc on la garde comme filet de sécurité pour ce chemin plus rare.
    fallback_key = (folder_path, filename, size_px, grayscale_int)
    try:
        stat_result = os.stat(image_path)
        signature = (
            getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000)),
            stat_result.st_size,
            getattr(stat_result, "st_ctime_ns", 0),
        )
    except OSError:
        return None

    if fallback_key in _session_fallback:
        cached_signature, cached_bytes = _session_fallback[fallback_key]
        if cached_signature == signature:
            return cached_bytes

    b64 = _generate_b64(image_path, size_px, quality, grayscale)
    if b64 is not None:
        image_bytes = base64.b64decode(b64)
        _session_fallback[fallback_key] = (signature, image_bytes)
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


def purge_folder(folder_path: str) -> None:
    """Vide tout le cache d'un dossier, sans comparer aux signatures.

    invalidate_stale() ne repère un fichier changé que si son mtime/size
    diffère du stat() courant — inutile si ce stat() est lui-même périmé
    (métadonnées de partage réseau/NAS mises en cache côté OS un court
    instant après l'écriture par un autre programme) ou si l'édition a
    par coïncidence produit exactement la même taille. "Rafraîchir" est un
    geste explicite et rare de l'utilisateur ("je sais que ça a changé") :
    on vide donc la table sans condition plutôt que de refaire confiance
    à un stat() qui vient justement de tromper get_or_generate() une
    première fois (retour user : miniature restée périmée après
    modification d'une photo sur le NAS, y compris après "Rafraîchir").
    """
    db_path = _get_db_path(folder_path)
    if db_path is None or not os.path.exists(db_path):
        return
    lock = _get_db_lock(folder_path)
    with lock:
        try:
            conn = _open_db(db_path)
            try:
                conn.execute("DELETE FROM thumbs")
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass


def _demo():
    """Auto-test : miniature raster, SVG (taille ~size_px, pas la taille
    physique du fichier) et accès concurrent (verrou DB) sans exception."""
    import shutil
    import tempfile
    import concurrent.futures

    tmp = tempfile.mkdtemp(prefix="thumb_cache_demo_")
    try:
        png_path = os.path.join(tmp, "a.png")
        _PILImage.new("RGB", (500, 500), "red").save(png_path)
        data = get_or_generate(png_path, size_px=100)
        assert data, "miniature raster non générée"
        assert _PILImage.open(io.BytesIO(data)).size == (100, 100)

        svg_path = os.path.join(tmp, "b.svg")
        with open(svg_path, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" '
                   'width="1000" height="1000"><rect width="1000" '
                   'height="1000" fill="blue"/></svg>')
        svg_data = get_or_generate(svg_path, size_px=100)
        assert svg_data, "miniature SVG non générée"
        assert _PILImage.open(io.BytesIO(svg_data)).size == (100, 100), (
            "le SVG n'est pas redimensionné à size_px (résolution excessive ?)")

        # Régénération concurrente (2 threads, même dossier) : le verrou
        # DB ne doit jamais planter, doublon ou pas.
        paths = [png_path, svg_path] * 5
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda p: get_or_generate(p, size_px=100), paths))
        assert all(results), "un appel concurrent a échoué"

        # Un hit de cache doit être utilisé tel quel, même si mtime/ctime
        # ont l'air d'avoir changé (carte SD peu fiable) — c'est le bug
        # que ce cache existence-only corrige (retour user).
        os.utime(png_path, (1000000000, 1000000000))
        data2 = get_or_generate(png_path, size_px=100)
        assert data2 == data, (
            "un mtime différent a fait régénérer un hit de cache existant")

        # Mais un même NOM réutilisé pour un contenu différent (ex.
        # "Renommer séquence" relancé une 2e fois) doit, lui, invalider le
        # cache — la taille en octets reste un signal fiable (retour user :
        # sans ce contrôle, l'ancienne vignette restait affichée sous le
        # nouveau nom indéfiniment).
        _PILImage.new("RGB", (900, 900), "blue").save(png_path)
        data3 = get_or_generate(png_path, size_px=100)
        assert data3 != data, (
            "le cache a renvoyé l'ancienne vignette malgré un contenu "
            "différent sous le même nom")

        # purge_folder() doit vider la table SANS condition — utile
        # justement quand size_bytes ne suffit pas à détecter un
        # changement (édition recompressée par coïncidence à la même
        # taille, ou stat() périmé sur un dossier NAS/réseau). Vérifié
        # directement en base plutôt que sur les bytes retournés : sur ce
        # fichier inchangé, get_or_generate() régénérerait de toute façon
        # les mêmes bytes déterministes, donc les comparer ne prouverait
        # rien (retour user : "Rafraîchir" restait bloqué sur l'ancienne
        # vignette d'une photo modifiée sur le NAS).
        db_path = _get_db_path(tmp)
        row_count_before = sqlite3.connect(db_path).execute(
            "SELECT COUNT(*) FROM thumbs").fetchone()[0]
        assert row_count_before > 0, "cache vide avant purge (test invalide)"
        purge_folder(tmp)
        row_count_after = sqlite3.connect(db_path).execute(
            "SELECT COUNT(*) FROM thumbs").fetchone()[0]
        assert row_count_after == 0, "purge_folder() n'a pas vidé le cache"

        print("[OK] thumb_cache : miniatures raster/SVG + accès concurrent "
             "+ cache non revalidé sur mtime changé, mais invalidé sur "
             "taille différente + purge_folder() vide le cache")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    _demo()
