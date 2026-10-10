"""
Stockage de mots de passe/identifiants dans le coffre natif de l'OS :
Windows Credential Manager, macOS Keychain, Secret Service sur Linux
(GNOME Keyring / KWallet). Le secret n'est jamais écrit en clair sur
le disque et ne transite jamais par un prompt IA : les scripts qui en
ont besoin appellent get_credential() et l'utilisent directement.

Linux sans session graphique (headless) : installer 'secretstorage'
et un service DBus/Secret Service (gnome-keyring), sinon keyring
échoue avec "No recommended backend was available".
"""

__version__ = "2.8.9"

import json
import os
import sys

import keyring

_SERVICE_PREFIX = "ImageManipulations"

# Windows Credential Manager plafonne chaque entrée à 2560 octets
# (CRED_MAX_CREDENTIAL_BLOB_SIZE), et le backend keyring encode la valeur
# en UTF-16 (2 octets/caractère) — donc ~1280 caractères max en théorie.
# Un jeton OAuth JWT (access + refresh token) dépasse facilement cette
# taille et fait échouer CredWrite avec une erreur peu explicite
# (WinError 1783). On découpe donc toute valeur en plusieurs entrées
# (marge large pour l'overhead), ce qui ne coûte rien sur macOS/Linux où
# la limite est bien plus haute.
_CHUNK_SIZE = 1000


def set_credential(service, username, password):
    """Enregistre/écrase un identifiant dans le coffre de l'OS."""
    key = f"{_SERVICE_PREFIX}:{service}"
    chunks = [password[i:i + _CHUNK_SIZE]
              for i in range(0, len(password), _CHUNK_SIZE)] or [""]
    keyring.set_password(key, f"{username}__count", str(len(chunks)))
    for i, chunk in enumerate(chunks):
        keyring.set_password(key, f"{username}__{i}", chunk)


def get_credential(service, username):
    """Retourne le mot de passe stocké, ou None s'il n'existe pas."""
    key = f"{_SERVICE_PREFIX}:{service}"
    count_raw = keyring.get_password(key, f"{username}__count")
    if count_raw is None:
        return keyring.get_password(key, username)   # ancien format
    parts = [keyring.get_password(key, f"{username}__{i}")
             for i in range(int(count_raw))]
    return "".join(parts) if all(p is not None for p in parts) else None


def delete_credential(service, username):
    """Supprime un identifiant du coffre de l'OS (no-op s'il n'existe pas)."""
    key = f"{_SERVICE_PREFIX}:{service}"
    count_raw = keyring.get_password(key, f"{username}__count")
    names = [username]
    if count_raw is not None:
        names = [f"{username}__count"] + [f"{username}__{i}" for i in range(int(count_raw))]
    for name in names:
        try:
            keyring.delete_password(key, name)
        except keyring.errors.PasswordDeleteError:
            pass


# ── Identifiants saisis dans Hub (fenêtre « Identifiants ») ─────────
# Fichier JSON par utilisateur, lisible par lui seul : le trousseau OS
# bloque sur certaines sessions (KWallet verrouillé sur le Pi) et ne se
# configure pas sans aide sur une nouvelle machine.
# ponytail: en clair comme les anciens ~/.notion / ~/.meta ; chiffrer si
# la machine est partagée entre plusieurs comptes.
SECRETS = [
    # (clé, libellé, masqué, exemple affiché dans le champ vide)
    ("gemini", "Clé Gemini", True, "AIza…"),
    ("anthropic", "Clé Claude", True, "sk-ant-…"),
    ("muse", "Clé Muse", True, ""),
    ("notion", "Jeton Notion", True, "ntn_…"),
    ("topaz", "Clé Topaz", True, ""),
    ("mail_user", "Adresse mail", False, "login@mail.com"),
    ("mail_password", "Mot de passe mail", True, ""),
    ("mail_host", "Serveur mail", False, "ex2.mail.ovh.net"),
]


def _secrets_path():
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser(
            "~/.config")
    return os.path.join(base, "ImageManipulations", "secrets.json")


def load_secrets():
    try:
        with open(_secrets_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def get_secret(name):
    """Valeur saisie dans Hub, ou "" (l'appelant garde ses anciens
    emplacements en repli : variables d'environnement, ~/.notion…)."""
    return (load_secrets().get(name) or "").strip()


def _read_lines(path):
    try:
        with open(os.path.expanduser(path), encoding="utf-8-sig") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except OSError:
        return []


def existing_secrets():
    """Identifiants déjà présents ailleurs (anciens fichiers cachés,
    variables d'environnement) — pré-remplissent la fenêtre Identifiants,
    qui les reprend à l'enregistrement."""
    found = {}
    for name, var in _ENV.items():
        if os.environ.get(var, "").strip():
            found[name] = os.environ[var].strip()
    notion = _read_lines("~/.notion_token") or _read_lines("~/.notion")
    if notion:
        found["notion"] = notion[0]
    meta = _read_lines("~/.meta")
    if meta:
        found.setdefault("muse", meta[0])
    mail = _read_lines("~/.mail")
    for key, value in zip(("mail_user", "mail_password", "mail_host"), mail):
        found[key] = value
    try:
        import ai_tools
        found.setdefault("gemini", ai_tools._get_gemini_api_key() or "")
        found.setdefault("anthropic",
                         ai_tools._get_anthropic_api_key() or "")
        import meta_ai
        found.setdefault("muse", meta_ai._key() or "")
    except Exception:
        pass
    return {k: v for k, v in found.items() if v}


def save_secrets(values):
    path = _secrets_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {k: v.strip() for k, v in values.items() if v and v.strip()}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    if os.name != "nt":
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


_ENV = {"gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
        "muse": "MUSE_API_KEY"}


def export_env():
    """Copie les clés saisies dans l'environnement : les outils lancés
    par Hub (sous-processus) et le code qui lit l'environnement les
    voient sans autre configuration."""
    for name, var in _ENV.items():
        value = get_secret(name)
        if value:
            os.environ[var] = value


def _selftest():
    service, username, value = "selftest", "demo", "correct horse battery staple"
    set_credential(service, username, value)
    assert get_credential(service, username) == value, "round-trip échoué"
    delete_credential(service, username)
    assert get_credential(service, username) is None, "suppression échouée"

    # Valeur > 2560 octets (taille d'un jeton OAuth JWT) : doit être
    # découpée/recollée sans erreur CredWrite sur Windows.
    big_value = "x" * 6000
    set_credential(service, username, big_value)
    assert get_credential(service, username) == big_value, "round-trip (valeur longue) échoué"
    delete_credential(service, username)
    assert get_credential(service, username) is None, "suppression (valeur longue) échouée"

    print("[OK] credentials.py : stockage/lecture/suppression fonctionnent")


if __name__ == "__main__":
    import sys
    import getpass

    if len(sys.argv) == 2 and sys.argv[1] == "--selftest":
        _selftest()
    elif len(sys.argv) == 4 and sys.argv[1] == "set":
        _, _, service, username = sys.argv
        password = getpass.getpass(f"Mot de passe pour {service}/{username} (invisible) : ")
        set_credential(service, username, password)
        print(f"[OK] Identifiant enregistré pour {service}/{username}")
    elif len(sys.argv) == 4 and sys.argv[1] == "delete":
        _, _, service, username = sys.argv
        delete_credential(service, username)
        print(f"[OK] Identifiant supprimé pour {service}/{username}")
    else:
        print("Usage :")
        print("  python credentials.py set <service> <username>     (saisie masquée)")
        print("  python credentials.py delete <service> <username>")
        print("  python credentials.py --selftest")
