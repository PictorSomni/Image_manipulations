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


def set_credential(service, username, password):
    """Enregistre/écrase un identifiant dans le coffre de l'OS."""
    keyring.set_password(f"{_SERVICE_PREFIX}:{service}", username, password)


def get_credential(service, username):
    """Retourne le mot de passe stocké, ou None s'il n'existe pas."""
    return keyring.get_password(f"{_SERVICE_PREFIX}:{service}", username)


def delete_credential(service, username):
    """Supprime un identifiant du coffre de l'OS (no-op s'il n'existe pas)."""
    try:
        keyring.delete_password(f"{_SERVICE_PREFIX}:{service}", username)
    except keyring.errors.PasswordDeleteError:
        pass


def _selftest():
    service, username, value = "selftest", "demo", "correct horse battery staple"
    set_credential(service, username, value)
    assert get_credential(service, username) == value, "round-trip échoué"
    delete_credential(service, username)
    assert get_credential(service, username) is None, "suppression échouée"
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
