"""
Navigation et import de fichiers depuis un smartphone connecté en MTP
(Media Transfer Protocol) — la manière dont Android se présente à Windows
par défaut (pas de lettre de lecteur, donc os.listdir() ne fonctionne pas
dessus, contrairement à une clé USB classique). Windows uniquement : l'API
Windows Portable Devices (WPD) n'existe pas sur macOS/Linux. Sur ces OS,
toutes les fonctions renvoient un résultat vide/lèvent MTPError plutôt que
de planter à l'import, pour que Hub.pyw puisse importer ce module sans se
soucier de la plateforme (cf. CLAUDE.md : app tri-OS).

S'appuie sur comtypes pour piloter l'API COM WPD (portabledeviceapi.dll /
portabledevicetypes.dll, fournies par Windows lui-même). Les liaisons COM
sont générées par comtypes au premier appel (comtypes.client.GetModule),
pas figées au moment du build — comtypes les met en cache sur disque après
la première génération.

Usage lecture seule (parcourir + copier vers le PC) : pas d'écriture sur
le téléphone, inutile pour l'import de photos.

Adapté de github.com/KasparNagu/PortableDevices (licence MIT), converti en
Python 3.

NON TESTÉ sur matériel réel — écrit à partir de la doc WPD et d'une
implémentation tierce existante, mais jamais exécuté contre un vrai
téléphone/Windows depuis cette machine (pas de Windows disponible ici).
À valider et corriger au premier usage réel.
"""
import ctypes
import os
import platform

IS_WINDOWS = platform.system() == "Windows"

# WPD_CONTENT_TYPE_FOLDER et WPD_CONTENT_TYPE_FUNCTIONAL_OBJECT (la racine
# d'un appareil se présente comme un objet fonctionnel, pas un vrai dossier,
# mais se parcourt de la même façon).
_FOLDER_CONTENT_TYPES = {
    "{27E2E392-A111-48E0-AB0C-E17705A05F85}",
    "{99ED0160-17FF-4C44-9D98-1D7A6F941921}",
}

_wpd = None  # cache lazy, voir _ensure_wpd()


class MTPError(Exception):
    """Erreur d'accès à un appareil MTP (COM indisponible, appareil
    déconnecté, verrouillé, autorisation refusée sur le téléphone...)."""


def _ensure_wpd():
    """Charge et met en cache les liaisons COM WPD. Lève MTPError si
    indisponible (pas Windows, composants manquants...)."""
    global _wpd
    if _wpd is not None:
        return _wpd
    if not IS_WINDOWS:
        raise MTPError("Accès MTP disponible uniquement sous Windows")
    try:
        import comtypes
        import comtypes.client
        port = comtypes.client.GetModule("portabledeviceapi.dll")
        types_ = comtypes.client.GetModule("portabledevicetypes.dll")
    except Exception as exc:
        raise MTPError(
            "Impossible de charger l'API Windows Portable Devices "
            f"({exc}). Vérifie que Windows Media Player / le framework "
            "WPD est présent (installé par défaut sur Windows 10/11)."
        ) from exc

    def _key(fmtid, pid):
        k = comtypes.pointer(port._tagpropertykey())
        k.contents.fmtid = comtypes.GUID(fmtid)
        k.contents.pid = pid
        return k

    _wpd = {
        "comtypes": comtypes,
        "port": port,
        "types": types_,
        "OBJECT_NAME": _key("{EF6B490D-5CD8-437A-AFFC-DA8B60EE4A3C}", 4),
        "OBJECT_ORIGINAL_FILE_NAME":
            _key("{EF6B490D-5CD8-437A-AFFC-DA8B60EE4A3C}", 12),
        "OBJECT_SIZE": _key("{EF6B490D-5CD8-437A-AFFC-DA8B60EE4A3C}", 11),
        "OBJECT_PARENT_ID": _key("{EF6B490D-5CD8-437A-AFFC-DA8B60EE4A3C}", 3),
        "OBJECT_CONTENT_TYPE":
            _key("{EF6B490D-5CD8-437A-AFFC-DA8B60EE4A3C}", 7),
        "RESOURCE_DEFAULT":
            _key("{E81E79BE-34F0-41BF-B53F-F1A06AE87842}", 0),
        "device_manager": None,
    }
    return _wpd


class MTPItem:
    """Un fichier ou dossier sur l'appareil (identifié par son objectID
    WPD, pas par un chemin — le "chemin" n'existe que via la hiérarchie
    parent/enfant qu'on reconstruit en parcourant)."""

    def __init__(self, object_id, content, name=None):
        self.object_id = object_id
        self._content = content
        self._name = name
        self._content_type = None
        self._properties = None

    def _read_props(self):
        if self._name is not None:
            return
        wpd = _ensure_wpd()
        comtypes = wpd["comtypes"]
        properties = self._content.Properties()
        to_read = comtypes.client.CreateObject(
            wpd["types"].PortableDeviceKeyCollection,
            clsctx=comtypes.CLSCTX_INPROC_SERVER,
            interface=wpd["port"].IPortableDeviceKeyCollection)
        to_read.Add(wpd["OBJECT_NAME"])
        to_read.Add(wpd["OBJECT_ORIGINAL_FILE_NAME"])
        to_read.Add(wpd["OBJECT_CONTENT_TYPE"])
        values = properties.GetValues(self.object_id, to_read)
        self._content_type = str(
            values.GetGuidValue(wpd["OBJECT_CONTENT_TYPE"]))
        if self._content_type in _FOLDER_CONTENT_TYPES:
            self._name = values.GetStringValue(wpd["OBJECT_NAME"])
        else:
            # Le nom de fichier "réel" (avec extension) est dans
            # OBJECT_ORIGINAL_FILE_NAME, pas OBJECT_NAME sur la plupart
            # des appareils Android.
            self._name = values.GetStringValue(
                wpd["OBJECT_ORIGINAL_FILE_NAME"])

    @property
    def name(self):
        self._read_props()
        return self._name

    @property
    def is_folder(self):
        self._read_props()
        return self._content_type in _FOLDER_CONTENT_TYPES

    def children(self):
        """Liste les enfants directs (fichiers + sous-dossiers)."""
        wpd = _ensure_wpd()
        port = wpd["port"]
        results = []
        enum_ids = self._content.EnumObjects(
            ctypes.c_ulong(0), self.object_id,
            ctypes.POINTER(port.IPortableDeviceValues)())
        while True:
            block = ctypes.c_ulong(32)
            id_array = (ctypes.c_wchar_p * block.value)()
            fetched = ctypes.pointer(ctypes.c_ulong(0))
            enum_ids.Next(
                block,
                ctypes.cast(id_array, ctypes.POINTER(ctypes.c_wchar_p)),
                fetched)
            if fetched.contents.value == 0:
                break
            for i in range(fetched.contents.value):
                results.append(MTPItem(id_array[i], self._content))
        return results

    def find_child(self, name):
        for child in self.children():
            if child.name == name:
                return child
        return None

    def download_to(self, dest_folder):
        """Copie ce fichier (pas un dossier) vers dest_folder sur le PC.
        Retourne le chemin local créé."""
        if self.is_folder:
            raise MTPError(f"{self.name} est un dossier, pas un fichier")
        wpd = _ensure_wpd()
        resources = self._content.Transfer()
        stgm_read = ctypes.c_uint(0)
        optimal_size = ctypes.pointer(ctypes.c_ulong(0))
        stream_ptr = ctypes.POINTER(wpd["port"].IStream)()
        optimal_size, stream_ptr = resources.GetStream(
            self.object_id, wpd["RESOURCE_DEFAULT"], stgm_read,
            optimal_size, stream_ptr)
        block_size = optimal_size.contents.value or 65536
        stream = stream_ptr.value

        os.makedirs(dest_folder, exist_ok=True)
        dest_path = _unique_local_path(dest_folder, self.name)
        buf = (ctypes.c_ubyte * block_size)()
        with open(dest_path, "wb") as out:
            while True:
                buf, n = stream.RemoteRead(buf, ctypes.c_ulong(block_size))
                if n == 0:
                    break
                out.write(bytearray(buf)[:n])
        return dest_path


def _unique_local_path(folder, name):
    base, ext = os.path.splitext(name)
    path = os.path.join(folder, name)
    n = 1
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({n}){ext}")
        n += 1
    return path


class MTPDevice:
    """Un appareil connecté (téléphone, tablette...). `id` est l'ID PnP
    Windows du périphérique, pas quelque chose de lisible par un humain —
    utiliser .description pour l'affichage."""

    def __init__(self, pnp_id):
        self.id = pnp_id
        self._description = None
        self._device = None

    @property
    def description(self):
        if self._description is not None:
            return self._description
        wpd = _ensure_wpd()
        manager = _get_device_manager()
        name_len = ctypes.pointer(ctypes.c_ulong(0))
        manager.GetDeviceDescription(
            self.id, ctypes.POINTER(ctypes.c_ushort)(), name_len)
        buf = ctypes.create_unicode_buffer(name_len.contents.value)
        manager.GetDeviceDescription(
            self.id, ctypes.cast(buf, ctypes.POINTER(ctypes.c_ushort)),
            name_len)
        self._description = buf.value
        return self._description

    def _open(self):
        if self._device is not None:
            return self._device
        wpd = _ensure_wpd()
        comtypes = wpd["comtypes"]
        client_info = comtypes.client.CreateObject(
            wpd["types"].PortableDeviceValues,
            clsctx=comtypes.CLSCTX_INPROC_SERVER,
            interface=wpd["port"].IPortableDeviceValues)
        self._device = comtypes.client.CreateObject(
            wpd["port"].PortableDevice,
            clsctx=comtypes.CLSCTX_INPROC_SERVER,
            interface=wpd["port"].IPortableDevice)
        self._device.Open(self.id, client_info)
        return self._device

    def close(self):
        if self._device is not None:
            self._device.Release()
            self._device = None

    def root(self):
        """Racine de l'arborescence de l'appareil, pour appeler .children()
        ou .find_child(name) dessus."""
        content = self._open().Content()
        return MTPItem(ctypes.c_wchar_p("DEVICE"), content, name="")


def _get_device_manager():
    wpd = _ensure_wpd()
    comtypes = wpd["comtypes"]
    if wpd["device_manager"] is None:
        wpd["device_manager"] = comtypes.client.CreateObject(
            wpd["port"].PortableDeviceManager,
            clsctx=comtypes.CLSCTX_INPROC_SERVER,
            interface=wpd["port"].IPortableDeviceManager)
    return wpd["device_manager"]


def list_devices():
    """Liste les appareils MTP actuellement connectés. Renvoie une liste
    vide (sans erreur) sur macOS/Linux, ou si aucun appareil n'est
    branché. Lève MTPError si l'API WPD est indisponible sous Windows
    (composants manquants)."""
    if not IS_WINDOWS:
        return []
    manager = _get_device_manager()
    count = ctypes.pointer(ctypes.c_ulong(0))
    manager.GetDevices(ctypes.POINTER(ctypes.c_wchar_p)(), count)
    if count.contents.value == 0:
        return []
    id_array = (ctypes.c_wchar_p * count.contents.value)()
    manager.GetDevices(
        ctypes.cast(id_array, ctypes.POINTER(ctypes.c_wchar_p)), count)
    return [MTPDevice(pnp_id) for pnp_id in id_array]


# Sous-dossiers usuels où trouver les photos sur un Android : la racine de
# l'appareil WPD expose en général un dossier par carte de stockage (nom
# variable selon le fabricant), chacun contenant DCIM, Pictures,
# WhatsApp/Media/WhatsApp Images, etc. Pas de chemin universel garanti —
# _find_photo_folders() les cherche par nom plutôt que de supposer un
# chemin fixe.
_PHOTO_FOLDER_NAMES = {
    "dcim", "camera", "pictures", "whatsapp images", "download",
    "screenshots",
}


def find_photo_folders(device):
    """Parcourt les cartes de stockage de l'appareil et renvoie la liste
    des MTPItem correspondant à des dossiers photo usuels (DCIM, Pictures,
    WhatsApp Images...), tous storages confondus. Best-effort : les noms
    de dossiers varient selon la marque/version d'Android, donc ceci peut
    manquer des dossiers légitimes — la navigation manuelle via .children()
    reste possible en secours."""
    found = []
    for storage in device.root().children():
        if not storage.is_folder:
            continue
        for child in storage.children():
            if child.is_folder and child.name.strip().lower() in \
                    _PHOTO_FOLDER_NAMES:
                found.append(child)
            elif child.is_folder and child.name.strip().lower() == \
                    "whatsapp":
                # WhatsApp Images est 2 niveaux sous la racine WhatsApp.
                media = child.find_child("Media")
                if media:
                    wa_imgs = media.find_child("WhatsApp Images")
                    if wa_imgs:
                        found.append(wa_imgs)
    return found
