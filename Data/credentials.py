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
