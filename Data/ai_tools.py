# -*- coding: utf-8 -*-
"""
Utilitaires IA partagés entre Hub.pyw et les scripts de Data/.

Fonctions et constantes exposées :
  _fetch_url_content(url, max_chars)         — récupère le texte d'une URL HTTP(S)
  _web_search(query, max_results)            — recherche DuckDuckGo, retourne les résultats formatés
  _ollama_chat_once(url, model, messages)    — appel non-streaming à /api/chat, retourne le dict message
  _ollama_chat_stream(url, model, messages)  — appel streaming à /api/chat, génère les tokens

Outils dossier (partagés) :
  _folder_tool_definitions(folder_path)      — retourne les 7 définitions d'outils dossier pour Ollama/Gemma
  _gemini_tool_definitions(folder_path)       — version allégée pour Gemini (sans analyze_images)
  _folder_list_contents(folder_path)         — liste les fichiers avec taille et date
  _folder_read_file(folder_path, filename)   — lit le contenu texte d'un fichier
  _folder_create_file(folder_path, filename, content)
                                             — crée un fichier texte dans le dossier ouvert
  _encode_image_for_analysis(image_path)     — encode une image en base64 JPEG pour un modèle vision
  _analyze_images_batched(...)               — analyse des images par lots et retourne les résultats
  _gemini_generate_image(prompt, ...)        — génère/modifie une image via Nano Banana 2
  _gemini_interactions_create(input, ...)   — Interactions API : appel simple avec previous_interaction_id
  _gemini_interactions_get(interaction_id)  — Interactions API : polling pour background=True (agents)
  _gemini_generate_music(prompt, model, images)
                                             — génère de la musique via Lyria 3 (retourne bytes MP3/WAV)

Helpers système (partagés) :
  _WEB_TOOLS                                 — liste des 2 définitions d'outils web (web_search + fetch_url)
  _TERMINAL_TOOLS                            — définition de l'outil run_terminal_command
  _run_terminal_command(command, cwd, timeout, admin)
                                             — exécute une commande shell et retourne la sortie
                                               (admin=True → élévation via _run_elevated)
  _run_elevated(command, cwd, timeout)       — exécute une commande avec élévation de
                                               privilèges (UAC / osascript / pkexec selon l'OS)
  _get_gemini_cached_content(client, model, system_instr, raw_tools)
                                             — réutilise/crée un cache de contexte Gemini (cachedContent)
  _compact_history_summary(ai_conversation, history_limit, state)
                                             — résume (Gemini, repli Gemma) les tours qui sortent de la fenêtre d'historique, pour tous les modèles

Voix — TTS :
  _gemini_tts(text, ...)                     — génère l'audio TTS en une seule requête (bytes PCM)
  _gemini_tts_stream(text, ...)              — TTS multi-requêtes pipeline (compatible tous modèles)
  _gemini_live_tts_stream(text, ...)         — TTS via Gemini Live WebSocket (voix cohérente, modèle Live)
  _voice_play_audio(pcm_bytes, ...)          — joue des bytes PCM via sounddevice

Dictée — STT (push-to-talk) :
  _MicRecorder(sample_rate)                  — enregistre le micro (start/stop → WAV bytes)
  _gemini_transcribe_audio(wav_bytes, ...)   — transcrit un WAV via Gemini, retourne le texte
"""

__version__ = "2.10.94"


import ast as _ast
import gzip
import hashlib as _hashlib
import json
import logging
import os as _os
import re
import sys as _sys
import time as _time
import urllib.request
import urllib.parse
import html.parser

import CONSTANTS
import mail_reader

# Erreurs "best-effort" (fallback silencieux volontaire) — voir chaque site
# d'appel pour le contexte. Un sous-ensemble seulement est loggé ici : ceux
# qui peuvent masquer un vrai bug (ex. arguments d'un tool call perdus),
# pas les dizaines de fallbacks cosmétiques (DPI, audio, dates...).
_logger = logging.getLogger("ai_tools")
if not _logger.handlers:
    _log_path = CONSTANTS.state_file(".ai_tools_errors.log")
    _handler = logging.FileHandler(_log_path, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    _logger.addHandler(_handler)
    _logger.setLevel(logging.WARNING)

# Rend le processus DPI-aware sous Windows : sans ça, si l'affichage a une
# mise à l'échelle > 100%, Windows "virtualise" les coordonnées de la souris
# (SetCursorPos/click) sur une résolution logique réduite alors que les
# captures d'écran (pyautogui.screenshot) restent en pixels physiques —
# décalage systématique entre ce que le modèle voit et où le clic atterrit.
if _sys.platform == "win32":
    try:
        import ctypes as _ctypes_dpi
        _ctypes_dpi.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            _ctypes_dpi.windll.user32.SetProcessDPIAware()  # fallback Windows 7/8
        except Exception:
            pass


_GEMINI_API_KEY_CACHE = None




def _get_gemini_api_key():
    """Tente de récupérer la clé d'API Gemini de façon extrêmement robuste sur Windows, macOS et Linux."""
    global _GEMINI_API_KEY_CACHE
    if _GEMINI_API_KEY_CACHE is not None:
        return _GEMINI_API_KEY_CACHE

    import os
    import re
    import subprocess
    
    import credentials
    # 0. Saisie dans Hub (fenêtre Identifiants)
    key = credentials.get_secret("gemini")
    if key:
        _GEMINI_API_KEY_CACHE = key
        return key
    # 1. Directement dans l'environnement
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        _GEMINI_API_KEY_CACHE = key
        return key
        
    # 2. Dans un fichier .env (relatif au dossier de l'app ou racine du dépôt)
    for env_dir in [os.getcwd(), os.path.dirname(os.path.abspath(__file__)), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]:
        env_path = os.path.join(env_dir, ".env")
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip() and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            if k.strip() == "GEMINI_API_KEY":
                                key = v.strip().strip('"').strip("'")
                                if key:
                                    os.environ["GEMINI_API_KEY"] = key
                                    _GEMINI_API_KEY_CACHE = key
                                    return key
            except Exception:
                pass

    # 3. macOS / Linux uniquement : charger depuis le login shell (pour .zshrc, .bashrc, .profile)
    if os.name != "nt":
        for shell in ["/bin/zsh", "/bin/bash"]:
            if os.path.exists(shell):
                try:
                    # "-li" (login + interactif), pas seulement "-l" : la
                    # plupart des .bashrc (Debian/Raspberry Pi OS...)
                    # commencent par "si non interactif, ne rien faire" et
                    # s'arrêtent avant d'atteindre l'export de la clé sinon.
                    result = subprocess.run(
                        [shell, "-li", "-c", "echo $GEMINI_API_KEY"],
                        capture_output=True, text=True, timeout=2
                    )
                    # Un shell interactif (-i) peut imprimer une bannière
                    # avant la sortie de la commande (ex. "Restored
                    # session: ..." de Terminal.app/iTerm2) : seule la
                    # dernière ligne est la vraie valeur échappée.
                    lines = [l for l in result.stdout.splitlines() if l.strip()]
                    key = lines[-1].strip() if lines else ""
                    if key:
                        os.environ["GEMINI_API_KEY"] = key
                        _GEMINI_API_KEY_CACHE = key
                        return key
                except Exception:
                    pass

        # Fallback : lecture directe des fichiers RC de l'utilisateur
        home = os.path.expanduser("~")
        for rc_file in [".zshrc", ".bashrc", ".bash_profile", ".profile"]:
            rc_path = os.path.join(home, rc_file)
            if os.path.isfile(rc_path):
                try:
                    with open(rc_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    # match "export GEMINI_API_KEY=xxx" or "GEMINI_API_KEY=xxx"
                    # re.MULTILINE : sans lui, "$" ne matche que la fin du
                    # fichier entier (pas la fin de chaque ligne), donc la
                    # recherche échouait dès que la ligne n'était pas la
                    # toute dernière du fichier RC.
                    match = re.search(
                        r'(?:export\s+)?GEMINI_API_KEY\s*=\s*["\']?(.*?)["\']?\s*(?:#|$)',
                        content, re.MULTILINE)
                    if match:
                        key = match.group(1).strip()
                        if key:
                            os.environ["GEMINI_API_KEY"] = key
                            _GEMINI_API_KEY_CACHE = key
                            return key
                except Exception:
                    pass
                    
    return ""














def _md_dark(text: str) -> str:
    """Remplace les blockquotes Markdown par un équivalent lisible sur thème sombre."""
    lines = text.split("\n")
    result = []
    for line in lines:
        if line.startswith("> "):
            result.append("**›** " + line[2:])
        elif line == ">":
            result.append("")
        else:
            result.append(line)
    return "\n".join(result)












def _format_ai_conversation(conversation, user_name="Toi", separator_width=80):
    """
    Formate une liste de messages IA en texte Markdown exportable.

    Chaque tour est un bloc H1 avec le nom du rôle. Les blocs de réflexion
    (thinking) sont rendus en blockquote avant le contenu. Les blocs sont
    séparés par une ligne de tirets.

    Args:
        conversation : liste de dicts avec les clés 'role', 'content', 'thinking'.
        user_name    : nom affiché pour le rôle 'user'.

    Returns:
        Chaîne Markdown prête à être copiée ou insérée dans le bloc-notes.
    """
    blocks = []
    separator = "\n\n" + "#" * separator_width + "\n\n"
    for message in conversation:
        role = message.get("role", "")
        content = message.get("content", "")
        thinking = message.get("thinking", "")
        events = message.get("events", [])
        if role == "user":
            prefix = user_name
        elif role == "assistant":
            prefix = "IA"
        else:
            continue
        if thinking:
            thinking_lines = "\n".join(
                f"> {line}" if line.strip() else ">" for line in thinking.split("\n")
            )
            block = f"> 💭 **Réflexion**\n>\n{thinking_lines}\n\n# {prefix}\n\n"
        else:
            block = f"# {prefix}\n\n"
        if events:
            events_text = "\n".join(f"  • {e}" for e in events)
            block += f"**Actions :**\n{events_text}\n\n"
        block += content.strip()
        blocks.append(block.strip())
    return separator.join(blocks).strip()




# ─── Outils dossier partagés ──────────────────────────────────────────────────
import os as _os
import datetime as _datetime_module









# Sentinelle : renvoyée par dispatch_folder_tool quand fn_name n'appartient pas
# au groupe d'outils « purs » géré ici (l'appelant traite alors ses propres
# branches UI-lourdes : generate_image, organize_files, delete_files, etc.).






def _prune_backup_dir(base_dir, max_entries):
    """Garde seulement les `max_entries` sauvegardes les plus récentes dans
    `base_dir` (fichiers ou dossiers copiés par _backup_file), supprime le
    reste — la sauvegarde avant modification est un filet anti-perte, pas
    un historique permanent (retour user : le dossier a atteint 30 Go
    avant d'être vidé à la main). `index.jsonl` (le journal, pas une
    sauvegarde) n'est jamais compté ni supprimé. Ne lève jamais."""
    try:
        import shutil as _sh_prune
        entries = [e for e in _os.scandir(base_dir) if e.name != "index.jsonl"]
        entries.sort(key=lambda e: e.stat().st_mtime, reverse=True)
        for stale in entries[max_entries:]:
            if stale.is_dir():
                _sh_prune.rmtree(stale.path, ignore_errors=True)
            else:
                try:
                    _os.remove(stale.path)
                except OSError:
                    pass
    except Exception as exc:
        _logger.warning("purge des anciennes sauvegardes échouée : %r", exc)


def _backup_file(path):
    """
    Copie un fichier/dossier existant dans le dossier de sauvegarde AVANT qu'il
    ne soit écrasé ou supprimé — filet anti-perte de données, général (appelé
    par toute opération destructrice locale). Un index.jsonl trace
    origine → sauvegarde pour permettre une restauration manuelle.

    Ne lève jamais : retourne le chemin de sauvegarde, ou None si rien à sauver.
    """
    try:
        if not getattr(CONSTANTS, "AI_BACKUP_ENABLED", True):
            return None
        if not path or not _os.path.exists(path):
            return None
        import shutil as _sh_bak
        _dirname = getattr(CONSTANTS, "AI_BACKUP_DIRNAME", ".ai_backups")
        _base_dir = _os.path.join(
            _os.path.dirname(_os.path.abspath(__file__)), _dirname, "files")
        _os.makedirs(_base_dir, exist_ok=True)
        _ts = _time.strftime("%Y%m%d_%H%M%S")
        _name = _os.path.basename(path.rstrip("/\\")) or "root"
        _dest = _os.path.join(_base_dir, f"{_ts}_{_name}")
        _n = 1
        while _os.path.exists(_dest):
            _dest = _os.path.join(_base_dir, f"{_ts}_{_name}_{_n}")
            _n += 1
        if _os.path.isdir(path):
            _sh_bak.copytree(path, _dest)
        else:
            _sh_bak.copy2(path, _dest)
        try:
            with open(_os.path.join(_base_dir, "index.jsonl"),
                      "a", encoding="utf-8") as _idx:
                _idx.write(json.dumps(
                    {"timestamp": _ts,
                     "original": _os.path.abspath(path),
                     "backup": _dest},
                    ensure_ascii=False) + "\n")
        except Exception:
            pass
        _prune_backup_dir(_base_dir, getattr(
            CONSTANTS, "AI_BACKUP_MAX_ENTRIES", 5))
        return _dest
    except Exception as exc:
        _logger.warning("backup fichier échoué pour %r : %r", path, exc)
        return None


def _folder_create_file(folder_path, filename, content):
    """
    Crée ou remplace un fichier texte.
    Accepte un chemin absolu ou un nom/chemin relatif au dossier ouvert.
    Crée les répertoires parents si nécessaire.
    """
    try:
        if not filename:
            return "Nom de fichier invalide."
        file_path = _resolve_path(folder_path, filename)
        if _os.path.exists(file_path):
            _backup_file(file_path)  # écrasement -> on sauve l'ancienne version
        _os.makedirs(_os.path.dirname(_os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as file_handle:
            file_handle.write(content)
        return f"Fichier créé : {file_path} ({len(content)} caractère(s))"
    except Exception as exc:
        return f"Erreur lors de la création du fichier : {exc}"


def _resolve_path(folder_path, path_arg):
    """Résout path_arg en chemin absolu. Absolu → inchangé. Relatif → joint à folder_path."""
    if _os.path.isabs(path_arg):
        return path_arg
    return _os.path.join(folder_path, path_arg) if folder_path else path_arg


































def _copy_scored_photos(folder_path):
    """
    Copie dans folder_path/CONSTANTS.AI_PHOTO_SCORE_SELECTION_FOLDER les
    images du fichier de scores (CONSTANTS.AI_PHOTO_SCORE_FILE) dont le
    score_global atteint CONSTANTS.AI_PHOTO_SCORE_THRESHOLD.

    Retourne une chaîne de résumé (copiés / déjà présents / introuvables).
    Action déterministe déclenchée par Charles (bouton Hub), pas un
    outil IA — la copie n'est jamais décidée par le modèle seul.
    """
    import shutil as _shutil_cp2

    scores_path = _os.path.join(folder_path, CONSTANTS.AI_PHOTO_SCORE_FILE)
    if not _os.path.isfile(scores_path):
        return f"Aucun fichier de scores trouvé ({CONSTANTS.AI_PHOTO_SCORE_FILE})."
    try:
        with open(scores_path, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except Exception as exc:
        return f"Fichier de scores illisible : {exc}"

    dest_dir = _os.path.join(folder_path, CONSTANTS.AI_PHOTO_SCORE_SELECTION_FOLDER)
    copied, already, missing = [], [], []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        score = entry.get("score_global")
        if not isinstance(score, (int, float)):
            continue
        if score < CONSTANTS.AI_PHOTO_SCORE_THRESHOLD:
            continue
        fname = (entry.get("fichier") or "").strip()
        if not fname:
            continue
        source = _os.path.join(folder_path, fname)
        dest   = _os.path.join(dest_dir, fname)
        if not _os.path.isfile(source):
            missing.append(fname)
            continue
        if _os.path.isfile(dest):
            already.append(fname)
            continue
        try:
            _os.makedirs(dest_dir, exist_ok=True)
            _shutil_cp2.copy2(source, dest)
            copied.append(fname)
        except Exception as exc:
            missing.append(f"{fname} ({exc})")

    lines = [f"{len(copied)} image(s) copiée(s) dans "
             f"{CONSTANTS.AI_PHOTO_SCORE_SELECTION_FOLDER}/."]
    if already:
        lines.append(f"{len(already)} déjà présente(s).")
    if missing:
        lines.append(f"{len(missing)} introuvable(s)/erreur : "
                      + ", ".join(missing[:10]))
    return " ".join(lines)


# ─── Outils terminal partagés ───────────────────────────────────────────────
import subprocess as _subprocess










# ─── Outils web partagés ──────────────────────────────────────────────────────



# ─── Outils bloc-notes ───────────────────────────────────────────────────────







# ─── Outils interface utilisateur ────────────────────────────────────────────

# ─── Intégration Google Gemini ───────────────────────────────────────────────

def _format_gemini_error(exc, *, prefix="Erreur Gemini"):
    """Rend les erreurs Gemini plus lisibles sans masquer le message brut."""
    import re as _re_ge

    raw = str(exc).strip()
    compact = " ".join(raw.split())
    details = []

    if "429" in compact or "RESOURCE_EXHAUSTED" in compact:
        details.append("quota/rate limit Google atteint")
    elif "503" in compact or "UNAVAILABLE" in compact:
        details.append("service Google temporairement indisponible")

    retry_match = _re_ge.search(r'retryDelay[^0-9]*(\d+(?:\.\d+)?)', compact)
    if retry_match:
        details.append(f"retryDelay={retry_match.group(1)}s")

    if "GenerateContentResponse" in compact:
        compact = compact.split("GenerateContentResponse", 1)[0].strip(" :-")

    suffix = f" ({', '.join(details)})" if details else ""
    if compact:
        return f"[{prefix}{suffix} : {compact}]"
    return f"[{prefix}{suffix}]"


def _extract_gemini_feedback_messages(response):
    """Extrait les signaux de blocage/arrêt Gemini (prompt_feedback, safety, finish_reason)."""
    messages = []

    def _normalize_enum_name(value):
        raw = str(value).strip()
        if not raw:
            return ""
        if "." in raw:
            raw = raw.split(".")[-1]
        return raw.upper()

    prompt_feedback = getattr(response, "prompt_feedback", None)
    if prompt_feedback is not None:
        block_reason = getattr(prompt_feedback, "block_reason", None)
        block_msg = getattr(prompt_feedback, "block_reason_message", None) or getattr(prompt_feedback, "message", None)
        if block_reason and str(block_reason) not in {"BLOCK_REASON_UNSPECIFIED", "0"}:
            messages.append(f"Prompt bloqué ({block_reason})")
        if block_msg:
            messages.append(str(block_msg).strip())

    for cand in (getattr(response, "candidates", None) or []):
        finish_reason = getattr(cand, "finish_reason", None)
        finish_name = _normalize_enum_name(finish_reason) if finish_reason else ""
        if finish_name and finish_name not in {"STOP", "FINISH_REASON_UNSPECIFIED", "UNSPECIFIED", "0"}:
            messages.append(f"Arrêt modèle : {finish_reason}")

        for rating in (getattr(cand, "safety_ratings", None) or []):
            blocked = getattr(rating, "blocked", False)
            if blocked:
                category = getattr(rating, "category", "UNKNOWN")
                probability = getattr(rating, "probability", "UNKNOWN")
                messages.append(f"Blocage sécurité : {category} ({probability})")

    # Dédupliquer en conservant l'ordre
    deduped = []
    seen = set()
    for msg in messages:
        key = msg.strip()
        if key and key not in seen:
            deduped.append(key)
            seen.add(key)
    return deduped





# ── Cache de contexte Gemini ─────────────────────────────────────────────────
# system.md + memoire/user/skills + les ~18 definitions d'outils sont
# quasi-identiques a chaque tour (~9000 tokens) et etaient jusqu'ici renvoyes
# et factures en entier a chaque message. Gemini permet de les mettre en
# cache cote serveur (cachedContent) : on ne paie le plein tarif que la
# premiere fois, les tours suivants relisent le cache pour une fraction du
# prix, tant que system_instruction/tools n'ont pas change.




# ── Compactage de l'historique de conversation ───────────────────────────────
# La fenêtre glissante (AI_HISTORY_LIMIT_CLOUD) tronque déjà les tours trop
# anciens sans rien renvoyer à leur sujet — mais le modèle perd toute mémoire
# de ce qui précède. On remplace la troncature sèche par un résumé court et
# cumulatif des tours qui sortent de la fenêtre, injecté dans le message
# système à la place du texte brut (beaucoup moins de tokens que les tours
# originaux, tout en gardant le fil de la conversation).







_GEMINI_SUPPORTED_ASPECT_RATIOS = {
    "1:1": 1.0, "2:3": 2 / 3, "3:2": 3 / 2, "3:4": 3 / 4, "4:3": 4 / 3,
    "9:16": 9 / 16, "16:9": 16 / 9, "21:9": 21 / 9,
}


def _gemini_nearest_aspect_ratio(ratio_str):
    """Ramène un ratio quelconque (ex. calculé à partir d'un canevas
    d'outpainting) au plus proche des 8 valeurs que `ImageConfig.aspect_ratio`
    accepte réellement — un ratio hors énum est silencieusement ignoré par
    l'API (retombe sur 1:1)."""
    import math as _math_gar
    if ratio_str in _GEMINI_SUPPORTED_ASPECT_RATIOS:
        return ratio_str
    try:
        w_str, h_str = ratio_str.split(":")
        target = float(w_str) / float(h_str)
    except (ValueError, ZeroDivisionError):
        return "1:1"
    return min(_GEMINI_SUPPORTED_ASPECT_RATIOS,
               key=lambda k: abs(_math_gar.log(_GEMINI_SUPPORTED_ASPECT_RATIOS[k] / target)))


def _gemini_generate_image(prompt, input_image_bytes=None, aspect_ratio="1:1",
                            resolution="1K", model=None):
    """
    Génère ou modifie une image avec Nano Banana 2.
    Utilise gemini-nano-banana-2.1 avec bascule automatique (fallback) vers
    gemini-3.1-flash-lite-image si surchargé ou indisponible.

    - prompt            : description textuelle de l'image souhaitée
    - input_image_bytes : bytes de l'image source pour édition (None = génération pure)
    - aspect_ratio      : format de sortie, ex. "1:1", "16:9", "3:2" … (ramené au plus
                          proche des 8 valeurs supportées si besoin, cf.
                          `_gemini_nearest_aspect_ratio`)
    - resolution        : résolution réelle demandée à l'API : "1K", "2K", "4K"
                          (`ImageConfig.image_size` — sans ce paramètre structuré,
                          Gemini génère silencieusement en 1K quel que soit le
                          canevas envoyé)
    - model             : modèle Nano Banana 2.1 à essayer en premier (choix
                          explicite, ex. depuis un dropdown UI). None =
                          ordre par défaut (full puis Lite en repli).

    Retourne (text_response: str, image_bytes: bytes | None).
    """
    try:
        from google import genai as _genai_img
        from google.genai import types as _gtypes_img
        import os as _os_img
        import io as _io_img
    except ImportError:
        return ("Erreur : bibliothèque google-genai non installée.", None)

    _api_key = _get_gemini_api_key()

    if not _api_key:
        return (
            "Erreur : la variable d'environnement GEMINI_API_KEY n'est pas définie. "
            "Veuillez la configurer dans votre environnement (.zshrc, .bashrc) ou créer un fichier .env contenant GEMINI_API_KEY=votre_cle.",
            None
        )

    import time as _time_gi
    import re as _re_gi

    _default_models = [
        "gemini-nano-banana-2.1",
        "gemini-3.1-flash-image",
        "gemini-3.1-flash-lite-image",
    ]
    if model in _default_models:
        _candidate_models = (
            [model] + [m for m in _default_models if m != model])
    else:
        _candidate_models = _default_models
    _last_error = None

    for _model in _candidate_models:
        _MAX_RETRIES_GI = 1  # Retries courts par modèle pour éviter d'attendre indéfiniment
        for _attempt_gi in range(_MAX_RETRIES_GI + 1):
            try:
                _client = _genai_img.Client(api_key=_api_key)

                # Construire le contenu : [prompt texte, image source optionnelle]
                # On évite d'envoyer response_format, qui peut provoquer l'erreur
                # "Extra inputs are not permitted" selon la version du SDK/API.
                _contents = [prompt]
                if input_image_bytes:
                    try:
                        from PIL import Image as _PILImg, ImageOps as _PILOps
                        _pil = _PILImg.open(_io_img.BytesIO(input_image_bytes))
                        # Transposer EXIF et convertir en RGB pour supprimer la transparence RGBA potentiellement rejetée
                        _pil = _PILOps.exif_transpose(_pil).convert("RGB")
                        # Redimensionnement préventif au format 4K max pour préserver la qualité maximale
                        _pil.thumbnail((4096, 4096), _PILImg.Resampling.LANCZOS)
                        _buf = _io_img.BytesIO()
                        _pil.save(_buf, format="JPEG", quality=100, optimize=True)
                        _compressed_bytes = _buf.getvalue()
                        _contents.append(
                            _gtypes_img.Part.from_bytes(data=_compressed_bytes, mime_type="image/jpeg")
                        )
                    except Exception:
                        _contents.append(
                            _gtypes_img.Part.from_bytes(data=input_image_bytes, mime_type="image/jpeg")
                        )

                # Config minimale et robuste pour compatibilité multi-versions.
                # image_config est le VRAI levier de résolution/ratio (paramètre
                # structuré de l'API) — un simple rappel dans le texte du prompt
                # est un vœu pieux que Gemini ignore silencieusement (retombe
                # sur 1K, cf. retour user : 4K demandé en texte -> qualité 1K).
                #
                # aspect_ratio n'accepte que 8 valeurs fixes : imposer un ratio
                # hors de cette liste en mode édition (image source fournie)
                # force Gemini à recadrer le résultat pour coller au ratio
                # arrondi, ce qui décale le contenu par rapport au canevas
                # envoyé (retour user : marge d'outpainting décalée vers la
                # droite) — en édition, on laisse Gemini garder le cadrage de
                # l'image source et on ne pilote que la résolution.
                _cfg_kwargs: dict = {"response_modalities": ["TEXT", "IMAGE"]}
                if input_image_bytes:
                    if resolution != "1K":
                        _cfg_kwargs["image_config"] = _gtypes_img.ImageConfig(
                            image_size=resolution,
                        )
                elif aspect_ratio != "1:1" or resolution != "1K":
                    _cfg_kwargs["image_config"] = _gtypes_img.ImageConfig(
                        aspect_ratio=_gemini_nearest_aspect_ratio(aspect_ratio),
                        image_size=resolution,
                    )

                _response = _client.models.generate_content(
                    model=_model,
                    contents=_contents,
                    config=_gtypes_img.GenerateContentConfig(**_cfg_kwargs),
                )

                _text_out = ""
                _image_out = None
                _feedback_messages = _extract_gemini_feedback_messages(_response)

                # Les SDK Gemini peuvent exposer les parts à différents niveaux
                # (_response.parts ou _response.candidates[*].content.parts).
                _parts = []
                try:
                    if getattr(_response, "parts", None):
                        _parts.extend(_response.parts)
                except Exception:
                    pass
                if not _parts:
                    try:
                        for _cand in (getattr(_response, "candidates", None) or []):
                            _content = getattr(_cand, "content", None)
                            _cand_parts = getattr(_content, "parts", None) if _content is not None else None
                            if _cand_parts:
                                _parts.extend(_cand_parts)
                    except Exception:
                        pass

                for _part in _parts:
                    if getattr(_part, "thought", False):
                        continue
                    _part_text = getattr(_part, "text", None)
                    if _part_text:
                        _text_out += _part_text
                        continue
                    _inline = getattr(_part, "inline_data", None)
                    if _inline is not None and getattr(_inline, "data", None):
                        _image_out = _inline.data  # bytes PNG/JPEG

                if _feedback_messages:
                    _feedback_text = "\n".join(f"[Gemini] {_m}" for _m in _feedback_messages)
                    if _text_out:
                        _text_out = (_text_out + "\n\n" + _feedback_text).strip()
                    elif _image_out is None:
                        _text_out = _feedback_text

                return (_text_out.strip(), _image_out)

            except Exception as _exc:
                _exc_str = str(_exc)
                _last_error = _exc
                # Retry automatique très rapide sur quota 429 ou erreur 503
                if ("429" in _exc_str or "503" in _exc_str or "UNAVAILABLE" in _exc_str) and _attempt_gi < _MAX_RETRIES_GI:
                    _delay_gi = 2.0
                    _m_gi = _re_gi.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', _exc_str)
                    if _m_gi:
                        _delay_gi = float(_m_gi.group(1)) + 1.0
                    _time_gi.sleep(_delay_gi)
                    continue
                # Si erreur irrémédiable ou épuisement des essais, on tente le modèle suivant immédiatement
                break

    return (_format_gemini_error(_last_error, prefix="ERREUR Gemini Image"), None)


def _gemini_refine_image_prompt(
    intent_prompt,
    user_request="",
    mode="edit_image",
    source_filename="",
    model="gemini-3.5-flash",
):
    """
    Raffine un prompt d'intention en prompt d'édition/génération très précis
    pour Nano Banana 2.

    Retourne toujours une chaîne exploitable : en cas d'échec, renvoie intent_prompt.
    """
    intent_prompt = (intent_prompt or "").strip()
    if not intent_prompt:
        return ""

    _mode_label = "édition" if mode == "edit_image" else "génération"
    _source_line = f"- Fichier source: {source_filename}\n" if source_filename else ""
    _user_req_block = user_request.strip() if user_request else "(non fourni)"

    _instruction = (
        "Tu es directeur artistique et expert en prompt engineering pour un "
        "modèle image-to-image / text-to-image (Nano Banana 2).\n"
        "Ta mission : transformer l'intention en UN prompt d'image ultra précis, "
        "concret et directement exécutable.\n\n"
        "Couvre systématiquement, en une formulation fluide (pas une liste) :\n"
        "1. SUJET principal + détails clés\n"
        "2. STYLE / medium (photo réaliste, aquarelle, 3D, illustration…)\n"
        "3. LUMIÈRE & ambiance (direction, dureté, heure, humeur)\n"
        "4. COMPOSITION / cadrage / angle\n"
        "5. PALETTE de couleurs dominante\n"
        "6. NIVEAU DE DÉTAIL & rendu (netteté, texture, qualité)\n\n"
        "Règles strictes :\n"
        "- Réponds UNIQUEMENT avec le prompt final : pas de commentaire, pas de "
        "Markdown, pas de guillemets, pas de préambule.\n"
        "- Interdit les mots vagues ('améliore', 'plus beau', 'sympa') sans "
        "critère visuel concret.\n"
        "- Pour une ÉDITION : préserver composition, proportions, cadrage, "
        "perspective et identité du sujet, sauf demande explicite de les changer ; "
        "ne décrire QUE ce qui change et ce qui doit rester intact.\n"
        "- Intention ambiguë → interprétation la plus sûre et conservatrice.\n"
        "- Écrire en français.\n\n"
        "Exemple —\n"
        "Intention : un chat mignon\n"
        "Prompt : Portrait rapproché d'un chaton roux tigré aux grands yeux "
        "verts, fourrure duveteuse très détaillée, assis sur un plaid en laine "
        "crème ; lumière douce de fin d'après-midi venant de la gauche, ambiance "
        "chaleureuse ; cadrage serré légèrement en plongée, faible profondeur de "
        "champ, arrière-plan flou ; palette chaude ocre et crème ; rendu "
        "photoréaliste net, textures fines.\n\n"
        f"Mode : {_mode_label}\n"
        f"{_source_line}"
        f"Demande utilisateur originale :\n{_user_req_block}\n\n"
        f"Intention brute à raffiner :\n{intent_prompt}\n"
    )

    result, _ = _gemini_interactions_create(_instruction, model=model)
    return result.strip() if result.strip() else intent_prompt






# Outil autonome (annoncé uniquement par Hub, qui possède le dispatch).


# ─── Interactions API ─────────────────────────────────────────────────────────

def _gemini_interactions_create(
    input_text,
    model="gemini-3.5-flash",
    previous_interaction_id=None,
    system_instruction=None,
    background=False,
    agent=None,
):
    """
    Appel simple Interactions API Gemini (non-streaming, sans outils).
    Supporte les conversations à états via previous_interaction_id.

    Agents disponibles :
      "deep-research-preview-04-2026"     — Deep Research rapide
      "deep-research-max-preview-04-2026" — Deep Research exhaustif
      "antigravity-preview-05-2026"       — Agent généraliste (code, web, fichiers)

    Les agents nécessitent background=True. Utiliser _gemini_interactions_get()
    pour récupérer le résultat.

    Retourne (output_text: str, interaction_id: str | None).
    """
    try:
        from google import genai as _genai_ia
    except ImportError:
        return ("", None)

    api_key = _get_gemini_api_key()
    if not api_key:
        return ("", None)

    try:
        client = _genai_ia.Client(api_key=api_key)
    except Exception:
        return ("", None)

    kwargs = {"input": input_text}
    if agent:
        kwargs["agent"] = agent
    else:
        kwargs["model"] = model
    if previous_interaction_id:
        kwargs["previous_interaction_id"] = previous_interaction_id
    if system_instruction:
        kwargs["system_instruction"] = system_instruction
    if background:
        kwargs["background"] = True

    try:
        interaction = client.interactions.create(**kwargs)
        return (interaction.output_text or "", interaction.id)
    except Exception as exc:
        return (_format_gemini_error(exc), None)




# ─── Musique — Lyria ──────────────────────────────────────────────────────────



# ─── Voix — TTS ───────────────────────────────────────────────────────────────



def _gemini_tts_stream(text, voice_name="Puck", tts_model="gemini-3.1-flash-tts-preview", sample_rate=24000, language_code=None, stop_event=None, preroll_ms=0):
    """
    Génère et joue le TTS via l'API Gemini en streaming audio réel :
    une seule requête ``generate_content_stream``, lecture dès le premier
    chunk audio reçu (comme le mode "live", mais texte lu tel quel — pas
    de session conversationnelle qui reformule).

    Remplace l'ancien découpage du texte en phrases + plusieurs requêtes
    ``generate_content`` complètes : ça n'apportait aucun gain de latence
    pour une réponse courte (un seul "chunk" = exactement le même coût
    qu'un appel unique, retour user), et le streaming réel est de toute
    façon plus rapide même pour les textes longs.

    La réception réseau (producteur) et l'écriture audio (consommateur)
    tournent dans deux threads séparés, avec un petit coussin de
    pré-lecture (``preroll_ms``) avant la première écriture : sans ça, une
    pause de génération entre deux phrases (gigue réseau) affamait
    directement le flux de sortie et produisait un accroc audible entre
    les phrases (retour user) — même mécanisme que le mode "live".

    language_code (ex : "fr", "en") : accent de la synthèse.
    stop_event (threading.Event) : si activé, interrompt immédiatement
    la lecture et la génération en cours (barge-in).
    Bloquant : attend la fin de la lecture avant de retourner.
    """
    try:
        from google import genai as _genai
        from google.genai import types as _gtypes
    except ImportError:
        raise ImportError("google-genai n'est pas installé")

    api_key = _get_gemini_api_key()
    if not api_key:
        raise RuntimeError("Clé API Gemini introuvable — vérifier GEMINI_API_KEY")

    import queue as _queue
    import threading as _threading
    import sounddevice as _sd

    client = _genai.Client(api_key=api_key)
    config = _gtypes.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=_gtypes.SpeechConfig(
            voice_config=_gtypes.VoiceConfig(
                prebuilt_voice_config=_gtypes.PrebuiltVoiceConfig(
                    voice_name=voice_name,
                )
            ),
            language_code=language_code,
        ),
    )

    # Découpe en morceaux de ~600 caractères aux frontières de phrases
    # (retour user : les réponses longues coupaient net après ~1/3 de
    # l'audio en un seul appel generate_content_stream — plafond côté
    # serveur sur la durée générée par requête, propre au streaming de ce
    # modèle TTS preview, absent en non-streaming). Plus long que l'ancien
    # découpage par phrases (~300 car., qui pipelinait des appels bloquants
    # un par un) : moins de requêtes, tout en restant sous ce plafond.
    import re as _re
    raw_sentences = _re.split(r'(?<=[.!?])\s+', text.strip())
    text_chunks: list = []
    current_chunk = ""
    for sentence in raw_sentences:
        if not sentence.strip():
            continue
        candidate = (current_chunk + " " + sentence).strip() if current_chunk else sentence
        if current_chunk and len(candidate) > 600:
            text_chunks.append(current_chunk)
            current_chunk = sentence
        else:
            current_chunk = candidate
    if current_chunk:
        text_chunks.append(current_chunk)
    if not text_chunks:
        text_chunks = [text]

    _SENTINEL = object()
    audio_queue: _queue.Queue = _queue.Queue(maxsize=40)
    error_holder: list = [None]

    def _producer():
        try:
            for text_chunk in text_chunks:
                if stop_event is not None and stop_event.is_set():
                    break
                for chunk in client.models.generate_content_stream(
                    model=tts_model, contents=text_chunk, config=config,
                ):
                    if stop_event is not None and stop_event.is_set():
                        break
                    if not chunk.candidates:
                        continue
                    for part in chunk.candidates[0].content.parts:
                        inline = getattr(part, "inline_data", None)
                        if inline and getattr(inline, "data", None):
                            audio_queue.put(inline.data)
        except Exception as exc:
            error_holder[0] = exc
        finally:
            audio_queue.put(_SENTINEL)

    _threading.Thread(target=_producer, daemon=True).start()

    output_stream = _sd.RawOutputStream(
        samplerate=sample_rate, channels=1, dtype="int16",
        blocksize=1024, latency="low")
    output_stream.start()
    got_audio = False
    preroll_bytes = int(sample_rate * 2 * max(preroll_ms, 0) / 1000.0)
    prebuf = bytearray()
    started = preroll_bytes <= 0
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            try:
                item = audio_queue.get(timeout=0.1)
            except Exception:
                continue
            if item is _SENTINEL:
                if error_holder[0] is not None:
                    raise error_holder[0]
                if not got_audio and (stop_event is None or not stop_event.is_set()):
                    raise RuntimeError(
                        f"Aucun audio généré — vérifier la clé API et le modèle TTS ({tts_model})"
                    )
                if prebuf and (stop_event is None or not stop_event.is_set()):
                    output_stream.write(bytes(prebuf))
                break
            got_audio = True
            if started:
                output_stream.write(item)
            else:
                prebuf += item
                if len(prebuf) >= preroll_bytes:
                    output_stream.write(bytes(prebuf))
                    prebuf = bytearray()
                    started = True
    finally:
        output_stream.stop()
        output_stream.close()


def _gemini_live_tts_stream(
    text,
    model="gemini-3.1-flash-live-preview",
    voice_name="Kore",
    sample_rate=24000,
    language_code=None,
    stop_event=None,
    preroll_ms=0,
):
    """
    Génère et joue le TTS via l'API Gemini Live (connexion WebSocket persistante).

    Contrairement à _gemini_tts_stream qui enchaîne plusieurs requêtes indépendantes,
    cette fonction utilise une seule session Live : la voix est parfaitement cohérente
    du début à la fin (même intonation, même timbre, pas de rupture entre les phrases).

    text           : texte complet (str) OU queue.Queue de fragments de texte pour
                     une lecture incrémentale — pousser les morceaux au fil de la
                     génération, puis None pour signaler la fin. Même session Live
                     dans les deux cas : voix et langue restent verrouillées.
    model          : modèle Gemini Live (ex. "gemini-3.5-flash-live")
    voice_name     : voix Gemini (ex. "Kore", "Puck" — mêmes noms que le TTS classique)
    sample_rate    : fréquence de sortie PCM (24000 Hz par défaut)
    language_code  : code langue ISO 639-1 (ex. "fr") ou None pour auto-détection
    stop_event     : threading.Event — si activé, interrompt la lecture (barge-in)
    preroll_ms     : coussin audio accumulé avant de démarrer la lecture (jitter
                     buffer) — lisse les à-coups réseau au prix d'un léger retard.

    Bloquant : attend la fin de la lecture avant de retourner.
    Lève ImportError si google-genai n'est pas installé ou si le modèle n'est pas disponible.
    """
    import asyncio as _asyncio
    import queue as _queue
    import threading as _threading

    text_is_stream = isinstance(text, _queue.Queue)

    api_key = _get_gemini_api_key()
    if not api_key:
        raise RuntimeError("Clé API Gemini introuvable — vérifier GEMINI_API_KEY")

    audio_queue: _queue.Queue = _queue.Queue(maxsize=40)
    _SENTINEL = object()
    error_holder: list = [None]

    async def _run_live():
        try:
            from google import genai as _genai
            from google.genai import types as _gtypes

            client = _genai.Client(api_key=api_key)
            live_config = _gtypes.LiveConnectConfig(
                response_modalities=["AUDIO"],
                speech_config=_gtypes.SpeechConfig(
                    voice_config=_gtypes.VoiceConfig(
                        prebuilt_voice_config=_gtypes.PrebuiltVoiceConfig(
                            voice_name=voice_name,
                        )
                    ),
                    language_code=language_code,
                ),
            )
            async with client.aio.live.connect(model=model, config=live_config) as session:
                # Gemini 3.1 Live: pendant la conversation, envoyer le texte via
                # send_realtime_input (send_client_content sert surtout à l'amorçage
                # d'historique initial avec history_config dédié).
                feeder = None
                if text_is_stream:
                    # Mode incrémental : draine la file de fragments et les envoie
                    # au fil de l'eau, sans bloquer la boucle d'événements.
                    _loop = _asyncio.get_event_loop()

                    async def _feed():
                        while True:
                            frag = await _loop.run_in_executor(None, text.get)
                            if frag is None:
                                break
                            await session.send_realtime_input(text=frag)

                    feeder = _asyncio.create_task(_feed())
                else:
                    await session.send_realtime_input(text=text)
                async for message in session.receive():
                    if stop_event is not None and stop_event.is_set():
                        break
                    # Source officielle (Get_started_LiveAPI.py) : les données audio
                    # sont dans server_content.model_turn.parts[n].inline_data.data
                    server_content = getattr(message, "server_content", None)
                    if server_content:
                        model_turn = getattr(server_content, "model_turn", None)
                        if model_turn:
                            for part in getattr(model_turn, "parts", []):
                                inline = getattr(part, "inline_data", None)
                                if inline and getattr(inline, "data", None):
                                    audio_queue.put(inline.data)
                        if getattr(server_content, "turn_complete", False):
                            # En mode incrémental, un turn_complete peut tomber
                            # entre deux fragments : ne s'arrêter qu'une fois tout
                            # le texte envoyé (feeder terminé).
                            if feeder is None or feeder.done():
                                break
                    # Fallback : certaines versions SDK exposent .data directement
                    elif getattr(message, "data", None):
                        audio_queue.put(message.data)
                if feeder is not None and not feeder.done():
                    feeder.cancel()
        except Exception as exc:
            error_holder[0] = exc
        finally:
            audio_queue.put(_SENTINEL)

    def _producer():
        loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run_live())
        finally:
            loop.close()

    _threading.Thread(target=_producer, daemon=True).start()

    # Lecture en streaming : on ouvre UN seul OutputStream sounddevice et on y
    # écrit chaque chunk dès qu'il arrive — pas de latence d'accumulation, pas de
    # saccades (un seul stream ouvert en continu, comme le cookbook officiel Google).
    import sounddevice as _sd_tts

    got_audio = False
    output_stream = _sd_tts.RawOutputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="int16",
        blocksize=1024,
        latency="low",
    )
    output_stream.start()
    # Coussin de pré-lecture : on accumule preroll_ms d'audio avant la 1re
    # écriture pour absorber la gigue réseau (int16 mono → 2 octets/échantillon).
    preroll_bytes = int(sample_rate * 2 * max(preroll_ms, 0) / 1000.0)
    prebuf = bytearray()
    started = preroll_bytes <= 0
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            try:
                item = audio_queue.get(timeout=0.1)
            except Exception:
                continue
            if item is _SENTINEL:
                if error_holder[0] is not None:
                    raise error_holder[0]
                if not got_audio and (stop_event is None or not stop_event.is_set()):
                    raise RuntimeError(
                        f"Aucun audio reçu du modèle Live ({model}) — "
                        "vérifier que le modèle est disponible sur votre compte"
                    )
                # Vider le coussin si la lecture n'a pas encore démarré (réponse
                # plus courte que le pré-buffer).
                if prebuf and (stop_event is None or not stop_event.is_set()):
                    output_stream.write(bytes(prebuf))
                break
            got_audio = True
            if started:
                output_stream.write(item)
            else:
                prebuf += item
                if len(prebuf) >= preroll_bytes:
                    output_stream.write(bytes(prebuf))
                    prebuf = bytearray()
                    started = True
    finally:
        # Attendre que le buffer interne du stream soit vidé avant de fermer
        output_stream.stop()
        output_stream.close()




# ── Dictée vocale — STT (push-to-talk) ────────────────────────────────────────

class _MicRecorder:
    """Enregistreur micro push-to-talk basé sur sounddevice.

    ``start()`` ouvre un flux d'entrée et accumule les échantillons ;
    ``stop()`` ferme le flux et retourne les octets WAV (PCM 16 bits, mono)
    prêts à être envoyés à Gemini, ou ``None`` si rien n'a été capté.
    Chaque instance ne sert qu'à un seul enregistrement.
    """

    def __init__(self, sample_rate=None):
        # sample_rate falsy (0/None) → fréquence native du micro. Forcer une
        # fréquence non supportée par le périphérique déforme l'audio (l'audio
        # part trop vite/lent) et casse la transcription.
        self.sample_rate = sample_rate or None
        self._stream = None
        self._device = None
        self._frames = []
        self._ready = False
        self._on_ready = None
        self._overflows = 0     # nb de callbacks signalant une perte (xrun BT)
        self._t_start = None    # horloge de démarrage (mesure des pertes)
        self.elapsed = 0.0      # durée réelle d'enregistrement (mur)

    @staticmethod
    def _resolve_input_device(_sd):
        """Retourne l'index du micro par défaut via une API stable.

        Laissé au défaut implicite, PortAudio tombe sur le « Mappeur de sons
        Microsoft » (device virtuel de Windows) qui interrompt la capture au
        bout de ~3 s. On cible donc le micro **par défaut de WASAPI** (l'API
        moderne de Windows, celle qu'utilise Wispr Flow), puis MME, puis
        DirectSound. Retourne None si rien de fiable → repli sur le défaut
        implicite de PortAudio.

        Repli machine-spécifique (variable d'environnement AI_VOICE_MIC_DEVICE,
        jamais committée) : sous-chaîne du nom de périphérique à préférer,
        insensible à la casse. Utile quand le device "par défaut" du système
        n'est en réalité pas câblé au micro physique — vu sur un Raspberry
        Pi où "default"/"pulse" (ALSA/PulseAudio) capturaient du silence
        pur alors que le device matériel brut du micro (DJI Mic 2 en USB)
        fonctionnait. Lister les devices disponibles :
          python3 -c "import sounddevice as sd; print(sd.query_devices())"
        """
        try:
            hostapis = _sd.query_hostapis()
            devices = _sd.query_devices()
        except Exception:
            return None

        override = _os.environ.get("AI_VOICE_MIC_DEVICE", "").strip().lower()
        if override:
            for candidate, info in enumerate(devices):
                if (info.get("max_input_channels", 0) > 0
                        and override in (info.get("name") or "").lower()):
                    return candidate

        # Noms écartés : Mappeur de sons (virtuel) et boucles de sortie.
        exclude = ("mapp", "mixage", "stereo mix", "loopback",
                   "primary", "principal")

        def _is_valid(index):
            if not isinstance(index, int) or index < 0:
                return False
            try:
                info = devices[index]
            except Exception:
                return False
            if info.get("max_input_channels", 0) <= 0:
                return False
            name = (info.get("name") or "").lower()
            return not any(token in name for token in exclude)

        for api_name in ("Windows WASAPI", "MME", "Windows DirectSound"):
            for api_index, hostapi in enumerate(hostapis):
                if hostapi.get("name") != api_name:
                    continue
                # 1) micro par défaut de cette API s'il est exploitable
                index = hostapi.get("default_input_device", -1)
                if _is_valid(index):
                    return index
                # 2) sinon, premier micro réel rattaché à cette API
                for candidate, info in enumerate(devices):
                    if (info.get("hostapi") == api_index
                            and _is_valid(candidate)):
                        return candidate
        return None

    def start(self, on_ready=None):
        """Ouvre le flux micro et commence à accumuler l'audio.

        Le périphérique met ~1 s à démarrer sous Windows (initialisation
        pilote) : aucun échantillon n'arrive avant. ``on_ready`` est appelé
        (depuis le thread audio) au tout premier échantillon capté, pour que
        l'UI n'affiche « enregistrement » qu'une fois le micro réellement actif
        et éviter de perdre le début de la phrase.
        """
        import sounddevice as _sd

        self._device = self._resolve_input_device(_sd)

        if not self.sample_rate:
            try:
                info = _sd.query_devices(
                    self._device if self._device is not None else None,
                    kind="input")
                self.sample_rate = int(info["default_samplerate"])
            except Exception:
                self.sample_rate = 44100

        import time as _time

        self._frames = []
        self._ready = False
        self._on_ready = on_ready
        self._overflows = 0
        self._t_start = _time.monotonic()

        def _callback(indata, frames, time_info, status):
            if status:
                # input_overflow = échantillons perdus (tampon trop court /
                # source Bluetooth qui hoquette).
                self._overflows += 1
            if not self._ready:
                self._ready = True
                if self._on_ready is not None:
                    try:
                        self._on_ready()
                    except Exception:
                        pass
            self._frames.append(indata.copy())

        # latency="high" → gros tampon d'entrée : absorbe la gigue du lien
        # Bluetooth (HFP) et limite les pertes d'échantillons en cours de route.
        self._stream = _sd.InputStream(
            device=self._device,
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            latency="high",
            callback=_callback,
        )
        self._stream.start()

    def stop(self):
        import io
        import time
        import wave

        import numpy as _np

        if self._t_start is not None:
            self.elapsed = time.monotonic() - self._t_start

        if self._stream is not None:
            # Laisser le tampon d'entrée se vider avant d'arrêter : en Bluetooth,
            # l'audio capté arrive au callback avec un retard de transport ; sans
            # cette pause, la fin de la phrase (encore « en vol ») est perdue.
            try:
                latency = float(getattr(self._stream, "latency", 0.0) or 0.0)
            except Exception:
                latency = 0.0
            time.sleep(min(max(latency + 0.3, 0.3), 1.0))
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
        if not self._frames:
            return None
        audio = _np.concatenate(self._frames, axis=0)

        # Retire les blancs en tête/queue avant l'envoi (retour user : moins
        # d'audio à transmettre/transcrire = plus rapide) — seuil d'amplitude
        # simple, pas de VAD dédiée, avec une marge de 150 ms de chaque côté
        # pour ne jamais couper le début/la fin de la parole.
        flat = audio.reshape(-1)
        above = _np.where(_np.abs(flat) > 500)[0]
        if above.size:
            pad = int(self.sample_rate * 0.15)
            start = max(0, above[0] - pad)
            end = min(len(flat), above[-1] + pad)
            flat = flat[start:end]

        # Plafonne aussi les blancs internes trop longs (pause de réflexion
        # en cours de phrase, retour user) : découpe en fenêtres de 20 ms,
        # énergie RMS par fenêtre, et toute pause interne au-delà de 500 ms
        # est tronquée à 500 ms — les pauses courtes naturelles entre les
        # mots restent intactes.
        frame_len = max(1, int(self.sample_rate * 0.02))
        n_frames = len(flat) // frame_len
        if n_frames > 1:
            usable = flat[:n_frames * frame_len].reshape(n_frames, frame_len)
            frame_rms = _np.sqrt(_np.mean(usable.astype(_np.float64) ** 2, axis=1))
            voiced = frame_rms > 300
            max_silence_frames = int(0.5 / 0.02)
            keep = []
            silence_run = 0
            for i, is_voiced in enumerate(voiced):
                if is_voiced:
                    silence_run = 0
                    keep.append(i)
                else:
                    silence_run += 1
                    if silence_run <= max_silence_frames:
                        keep.append(i)
            if keep:
                remainder = flat[n_frames * frame_len:]
                flat = _np.concatenate([usable[keep].reshape(-1), remainder])

        audio = flat.reshape(-1, 1)

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)  # int16 → 2 octets
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(audio.tobytes())
        return buffer.getvalue()


def _gemini_transcribe_audio(wav_bytes, language_code="fr",
                             model="gemini-3.1-flash-lite"):
    """Transcrit un audio WAV via Gemini et retourne le texte (ou None).

    L'audio est envoyé comme Part inline (même mécanisme que les images),
    avec une consigne stricte pour n'obtenir que la transcription brute.
    Nécessite GEMINI_API_KEY. Retourne None en cas d'erreur ou d'audio vide.
    """
    try:
        from google import genai as _genai
        from google.genai import types as _gtypes
    except ImportError:
        return None

    api_key = _get_gemini_api_key()
    if not api_key or not wav_bytes:
        return None

    lang = language_code or "fr"
    prompt = (
        "Transcris fidèlement cet enregistrement audio. Réponds UNIQUEMENT "
        "avec le texte prononcé, sans guillemets, sans commentaire et sans "
        f"préambule. Langue attendue : {lang}. Si l'audio est vide ou "
        "inaudible, réponds par une chaîne vide."
    )
    # Pas de try/except ici : une erreur d'appel API (réseau, quota, clé
    # invalide…) doit remonter à l'appelant, qui la logge déjà
    # (Hub.pyw : "[ERREUR] Transcription : ..."). L'avaler
    # silencieusement transformait toute panne réelle en un opaque "Aucun
    # texte reconnu" sans piste de diagnostic.
    client = _genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=[
            _gtypes.Content(
                role="user",
                parts=[
                    _gtypes.Part.from_bytes(
                        data=wav_bytes, mime_type="audio/wav"),
                    _gtypes.Part(text=prompt),
                ],
            )
        ],
    )
    text = (response.text or "").strip()
    return text or None


# ── Claude (Anthropic) ────────────────────────────────────────────────────────

def _get_anthropic_api_key():
    """Récupère ANTHROPIC_API_KEY depuis l'env, un fichier .env ou le shell de login."""
    import os
    import re
    import subprocess

    import credentials
    key = (credentials.get_secret("anthropic")
           or os.environ.get("ANTHROPIC_API_KEY", "").strip())
    if key:
        return key

    for env_dir in [
        os.getcwd(),
        os.path.dirname(os.path.abspath(__file__)),
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ]:
        env_path = os.path.join(env_dir, ".env")
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip() and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            if k.strip() == "ANTHROPIC_API_KEY":
                                key = v.strip().strip('"').strip("'")
                                if key:
                                    os.environ["ANTHROPIC_API_KEY"] = key
                                    return key
            except Exception:
                pass

    if os.name != "nt":
        for shell in ["/bin/zsh", "/bin/bash"]:
            if os.path.exists(shell):
                try:
                    # "-li" (login + interactif) : la plupart des .bashrc
                    # (Debian/Raspberry Pi OS...) s'arrêtent avant l'export
                    # de la clé si le shell n'est pas interactif.
                    result = subprocess.run(
                        [shell, "-li", "-c", "echo $ANTHROPIC_API_KEY"],
                        capture_output=True, text=True, timeout=2,
                    )
                    # Cf. commentaire équivalent pour GEMINI_API_KEY plus
                    # haut : ne garder que la dernière ligne (banal de
                    # session restaurée possible avant la vraie valeur).
                    lines = [l for l in result.stdout.splitlines() if l.strip()]
                    key = lines[-1].strip() if lines else ""
                    if key:
                        os.environ["ANTHROPIC_API_KEY"] = key
                        return key
                except Exception:
                    pass

        home = os.path.expanduser("~")
        for rc_file in [".zshrc", ".bashrc", ".bash_profile", ".profile"]:
            rc_path = os.path.join(home, rc_file)
            if os.path.isfile(rc_path):
                try:
                    with open(rc_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    # re.MULTILINE : sinon "$" ne matche que la fin du
                    # fichier, pas la fin de chaque ligne.
                    match = re.search(
                        r'(?:export\s+)?ANTHROPIC_API_KEY\s*=\s*["\']?(.*?)["\']?\s*(?:#|$)',
                        content, re.MULTILINE,
                    )
                    if match:
                        key = match.group(1).strip()
                        if key:
                            os.environ["ANTHROPIC_API_KEY"] = key
                            return key
                except Exception:
                    pass

    return ""








# ==============================================================================
# ─── Outil édition partielle (Edit) ──────────────────────────────────────────
# ==============================================================================









# ==============================================================================
# ─── Outils recherche (Grep / Glob) ──────────────────────────────────────────
# ==============================================================================

import glob as _glob_mod








# ==============================================================================
# ─── Outil git ────────────────────────────────────────────────────────────────
# ==============================================================================







# ==============================================================================
# ─── Outil gestion de tâches (TodoWrite) ─────────────────────────────────────
# ==============================================================================







# ==============================================================================
# ─── Outil lecture PDF ────────────────────────────────────────────────────────
# ==============================================================================







# ==============================================================================
# ─── Outil sous-agent (délégation IA) ────────────────────────────────────────
# ==============================================================================











# ==============================================================================
# ─── Outil planification (Schedule) ──────────────────────────────────────────
# ==============================================================================





# ── http_request ─────────────────────────────────────────────────────────────

import urllib.request as _urllib_req
import urllib.error as _urllib_err
import json as _json_mod






# ── ssh_command ───────────────────────────────────────────────────────────────
# Le mot de passe est fourni par l'appelant (résolu via credentials.py côté
# Hub, avec boîte de dialogue si besoin) : cette fonction ne
# le stocke jamais et ne le fait jamais réapparaître dans le texte retourné.





# ── read_spreadsheet ──────────────────────────────────────────────────────────



