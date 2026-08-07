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

Attention aux signatures générées : comtypes construit les méthodes à
partir du typelib, et les paramètres tableau déclarés [out, size_is(n)]
en IDL deviennent de simples [out] — comtypes alloue alors *un seul*
élément et renvoie la valeur au lieu de remplir un tampon fourni par
l'appelant. C'est le cas de IEnumPortableDeviceObjectIDs::Next, d'où
_enum_next() qui passe par la vtable. Ne pas « deviner » une signature :
l'introspecter (interface._methods_ -> .paramflags) avant de l'appeler.
"""
import ctypes
import datetime
import os
import platform
import threading

IS_WINDOWS = platform.system() == "Windows"

# COM s'initialise par thread, pas par processus : un thread qui n'a pas
# appelé CoInitialize se voit refuser tout CoCreateInstance. Hub.pyw scanne
# et importe depuis des threads de travail (pour ne pas figer l'UI Flet),
# donc chacun doit s'initialiser. On choisit l'apartment "multithread"
# (MTA) : les pointeurs d'interface y sont partageables entre threads sans
# marshaling, ce dont on a besoin puisque le thread d'import réutilise les
# MTPItem produits par le thread de scan. En STA ce partage serait illégal.
_COINIT_MULTITHREADED = 0x0
_RPC_E_CHANGED_MODE = -2147417850
_com_state = threading.local()

# WPD_CONTENT_TYPE_FOLDER et WPD_CONTENT_TYPE_FUNCTIONAL_OBJECT (la racine
# d'un appareil se présente comme un objet fonctionnel, pas un vrai dossier,
# mais se parcourt de la même façon).
_FUNCTIONAL_OBJECT_TYPE = "{99ED0160-17FF-4C44-9D98-1D7A6F941921}"
_FOLDER_CONTENT_TYPES = {
    "{27E2E392-A111-48E0-AB0C-E17705A05F85}",
    _FUNCTIONAL_OBJECT_TYPE,
}

_STGM_READ = 0  # mode d'ouverture du flux de transfert (lecture seule)

# WPD_DEVICE_OBJECT_ID : identifiant conventionnel de la racine d'un
# appareil, point de départ de tout parcours.
_DEVICE_OBJECT_ID = "DEVICE"

_wpd = None  # cache lazy, voir _ensure_wpd()


class MTPError(Exception):
    """Erreur d'accès à un appareil MTP (COM indisponible, appareil
    déconnecté, verrouillé, autorisation refusée sur le téléphone...)."""


def _ensure_com():
    """Initialise COM pour le thread courant (idempotent)."""
    if getattr(_com_state, "ready", False):
        return
    hr = ctypes.windll.ole32.CoInitializeEx(None, _COINIT_MULTITHREADED)
    if hr < 0 and hr != _RPC_E_CHANGED_MODE:
        # RPC_E_CHANGED_MODE = le thread est déjà dans un apartment d'un
        # autre type (typiquement le thread principal, mis en STA par
        # comtypes à l'import) : ce n'est pas une erreur, on l'utilise
        # tel quel.
        raise MTPError(
            f"Initialisation COM impossible (0x{hr & 0xFFFFFFFF:08X})")
    _com_state.ready = True


def _ensure_wpd():
    """Charge et met en cache les liaisons COM WPD. Lève MTPError si
    indisponible (pas Windows, composants manquants...)."""
    global _wpd
    if not IS_WINDOWS:
        raise MTPError("Accès MTP disponible uniquement sous Windows")
    if _wpd is not None:
        # L'initialisation COM, elle, est par thread : à refaire à chaque
        # passage même quand les liaisons sont déjà en cache.
        _ensure_com()
        return _wpd
    try:
        # Import avant _ensure_com() : comtypes appelle lui-même
        # CoInitializeEx (en STA) au premier import, et échouerait si on
        # avait déjà mis ce thread en MTA.
        import comtypes
        import comtypes.client
        _ensure_com()
        port = comtypes.client.GetModule("portabledeviceapi.dll")
        types_ = comtypes.client.GetModule("portabledevicetypes.dll")
    except MTPError:
        raise
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
        # DATE_MODIFIED et pas DATE_CREATED : cette dernière n'est pas
        # renseignée par tous les appareils (absente sur le Mi 10T de
        # test, où DATE_MODIFIED correspond bien à la prise de vue).
        "OBJECT_DATE_MODIFIED":
            _key("{EF6B490D-5CD8-437A-AFFC-DA8B60EE4A3C}", 19),
        "OBJECT_PARENT_ID": _key("{EF6B490D-5CD8-437A-AFFC-DA8B60EE4A3C}", 3),
        "OBJECT_CONTENT_TYPE":
            _key("{EF6B490D-5CD8-437A-AFFC-DA8B60EE4A3C}", 7),
        "RESOURCE_DEFAULT":
            _key("{E81E79BE-34F0-41BF-B53F-F1A06AE87842}", 0),
    }
    return _wpd


_ENUM_BLOCK = 64  # objets demandés par appel à Next()

# IEnumPortableDeviceObjectIDs::Next(cObjects, pObjIDs, pcFetched), appelée
# via la vtable : IUnknown occupe les slots 0-2 (QueryInterface, AddRef,
# Release), Next suit immédiatement.
_ENUM_NEXT_SLOT = 3

# WINFUNCTYPE, HRESULT et windll n'existent que dans le ctypes de Windows :
# tout ce bloc doit rester sous le garde IS_WINDOWS, sinon le module ne
# s'importerait plus du tout sur macOS/Linux (cf. CLAUDE.md, appli tri-OS).
if IS_WINDOWS:
    _ENUM_NEXT_PROTO = ctypes.WINFUNCTYPE(
        ctypes.HRESULT,           # restype : ctypes lève seul si FAILED
        ctypes.c_void_p,          # this
        ctypes.c_ulong,           # cObjects
        ctypes.POINTER(ctypes.c_void_p),   # pObjIDs (tableau de LPWSTR)
        ctypes.POINTER(ctypes.c_ulong),    # pcFetched
    )
    # argtypes explicite : sans lui ctypes traite le pointeur comme un int
    # C (32 bits) et déborde sur les adresses 64 bits.
    _co_task_mem_free = ctypes.windll.ole32.CoTaskMemFree
    _co_task_mem_free.argtypes = [ctypes.c_void_p]
    _co_task_mem_free.restype = None
else:
    _ENUM_NEXT_PROTO = None
    _co_task_mem_free = None


def _enum_next(enum_ids, count):
    """Récupère jusqu'à `count` object IDs de l'énumérateur. Renvoie une
    liste de chaînes (vide en fin d'énumération).

    Passe par la vtable plutôt que par la méthode générée par comtypes :
    l'IDL déclare pObjIDs en [out, size_is(cObjects)], mais comtypes ne
    voit qu'un [out] simple, alloue donc *un seul* LPWSTR et le renvoie.
    L'appeler avec cObjects > 1 ferait écrire l'appareil au-delà du
    tampon d'un élément (corruption mémoire), et la méthode générée
    n'accepte de toute façon pas de tableau fourni par l'appelant.
    """
    vtable = ctypes.cast(
        ctypes.cast(enum_ids, ctypes.POINTER(ctypes.c_void_p))[0],
        ctypes.POINTER(ctypes.c_void_p))
    next_fn = _ENUM_NEXT_PROTO(vtable[_ENUM_NEXT_SLOT])
    id_array = (ctypes.c_void_p * count)()
    fetched = ctypes.c_ulong(0)
    next_fn(ctypes.cast(enum_ids, ctypes.c_void_p), count, id_array,
            ctypes.byref(fetched))
    object_ids = []
    for i in range(min(fetched.value, count)):
        ptr = id_array[i]
        if not ptr:
            continue
        object_ids.append(ctypes.wstring_at(ptr))
        # Les chaînes sont allouées par l'appareil avec CoTaskMemAlloc :
        # c'est à nous de les libérer une fois recopiées côté Python.
        _co_task_mem_free(ptr)
    return object_ids


def _parse_wpd_date(raw):
    """Convertit une date WPD ("2025/02/20:15:44:23.000") en datetime.
    Renvoie None si le format n'est pas celui-là — la spec autorise des
    variantes selon l'appareil, et une date manquante n'est pas une
    erreur bloquante (on retombe sur un tri par nom)."""
    if not raw:
        return None
    try:
        return datetime.datetime.strptime(raw[:19], "%Y/%m/%d:%H:%M:%S")
    except (ValueError, TypeError):
        return None


class MTPItem:
    """Un fichier ou dossier sur l'appareil (identifié par son objectID
    WPD, pas par un chemin — le "chemin" n'existe que via la hiérarchie
    parent/enfant qu'on reconstruit en parcourant)."""

    def __init__(self, object_id, content, name=None, content_type=None):
        self.object_id = object_id
        self._content = content
        self._name = name
        self._content_type = content_type
        self._size = None
        self._date = None
        self._read = False

    def _read_props(self):
        if self._read or self._name is not None:
            return
        self._read = True
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
        to_read.Add(wpd["OBJECT_SIZE"])
        to_read.Add(wpd["OBJECT_DATE_MODIFIED"])
        # Un seul aller-retour pour les cinq propriétés (~0,2 ms/objet) :
        # les demander séparément multiplierait d'autant le temps de scan.
        values = properties.GetValues(self.object_id, to_read)
        try:
            self._size = values.GetUnsignedLargeIntegerValue(
                wpd["OBJECT_SIZE"])
        except Exception:
            self._size = None
        try:
            self._date = _parse_wpd_date(
                values.GetStringValue(wpd["OBJECT_DATE_MODIFIED"]))
        except Exception:
            self._date = None
        try:
            self._content_type = str(
                values.GetGuidValue(wpd["OBJECT_CONTENT_TYPE"]))
        except Exception:
            # Propriété absente sur certains objets : on retombe sur
            # "fichier", le cas le plus fréquent.
            self._content_type = ""
        # Le nom de fichier "réel" (avec extension) est dans
        # OBJECT_ORIGINAL_FILE_NAME, pas OBJECT_NAME, sur la plupart des
        # appareils Android — mais les dossiers n'ont que OBJECT_NAME, et
        # certains fichiers non plus. On essaie donc les deux clés.
        keys = ["OBJECT_NAME", "OBJECT_ORIGINAL_FILE_NAME"]
        if self._content_type not in _FOLDER_CONTENT_TYPES:
            keys.reverse()
        for key in keys:
            try:
                self._name = values.GetStringValue(wpd[key])
            except Exception:
                continue
            if self._name:
                return
        self._name = self.object_id

    @property
    def name(self):
        self._read_props()
        return self._name

    @property
    def is_folder(self):
        self._read_props()
        return self._content_type in _FOLDER_CONTENT_TYPES

    @property
    def size(self):
        """Taille en octets, ou None si l'appareil ne la publie pas."""
        self._read_props()
        return self._size

    @property
    def date(self):
        """Date de dernière modification (datetime), ou None."""
        self._read_props()
        return self._date

    def children(self):
        """Liste les enfants directs (fichiers + sous-dossiers)."""
        wpd = _ensure_wpd()
        port = wpd["port"]
        results = []
        enum_ids = self._content.EnumObjects(
            0, self.object_id,
            ctypes.POINTER(port.IPortableDeviceValues)())
        while True:
            object_ids = _enum_next(enum_ids, _ENUM_BLOCK)
            if not object_ids:
                break
            for object_id in object_ids:
                results.append(MTPItem(object_id, self._content))
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
        # GetStream a deux paramètres de sortie (taille de bloc optimale,
        # puis le flux) : comtypes les renvoie tous les deux.
        optimal_size = ctypes.pointer(ctypes.c_ulong(0))
        out_params = resources.GetStream(
            self.object_id, wpd["RESOURCE_DEFAULT"], _STGM_READ,
            optimal_size)
        stream = out_params[-1]
        block_size = optimal_size.contents.value or 262144

        os.makedirs(dest_folder, exist_ok=True)
        dest_path = _unique_local_path(dest_folder, self.name)
        with open(dest_path, "wb") as out:
            while True:
                # RemoteRead est réimplémentée par comtypes.stream : elle
                # alloue elle-même le tampon et renvoie (tampon, lus).
                buf, n = stream.RemoteRead(block_size)
                if n == 0:
                    break
                out.write(memoryview(buf)[:n].tobytes())
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
        # Pas de Release() explicite : comtypes gère le compteur de
        # références du pointeur, l'appeler à la main provoquerait une
        # double libération au passage du ramasse-miettes.
        if self._device is not None:
            self._device.Close()
            self._device = None

    def root(self):
        """Racine de l'arborescence de l'appareil, pour appeler .children()
        ou .find_child(name) dessus."""
        content = self._open().Content()
        # content_type explicite : la racine se parcourt comme un dossier,
        # mais lire ses propriétés échouerait (ce n'est pas un vrai objet).
        return MTPItem(_DEVICE_OBJECT_ID, content, name="",
                       content_type=_FUNCTIONAL_OBJECT_TYPE)


def _get_device_manager():
    """Le gestionnaire est mis en cache *par thread* : il est créé dans
    l'apartment COM du thread appelant, le partager entre threads reste
    incorrect même en MTA vu qu'un thread STA peut être dans le lot."""
    wpd = _ensure_wpd()
    comtypes = wpd["comtypes"]
    manager = getattr(_com_state, "device_manager", None)
    if manager is None:
        manager = comtypes.client.CreateObject(
            wpd["port"].PortableDeviceManager,
            clsctx=comtypes.CLSCTX_INPROC_SERVER,
            interface=wpd["port"].IPortableDeviceManager)
        _com_state.device_manager = manager
    return manager


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


def list_folder(item):
    """Contenu d'un dossier, prêt à afficher : (dossiers, fichiers).

    Les dossiers sont triés par nom, les fichiers du plus récent au plus
    ancien (les photos qu'on vient de prendre sont celles qu'on veut
    importer). Les appareils qui ne publient pas de date retombent sur un
    tri par nom décroissant, qui donne le même ordre avec les noms
    horodatés d'Android (IMG_20250220_154422.jpg)."""
    folders, files = [], []
    for child in item.children():
        if child.is_folder:
            if not child.name.startswith("."):
                folders.append(child)
        else:
            files.append(child)
    folders.sort(key=lambda f: f.name.lower())
    files.sort(key=lambda f: (f.date is not None, f.date, f.name),
               reverse=True)
    return folders, files


# Profondeur suffisante pour couvrir le pire cas courant depuis la racine
# de l'appareil : stockage > DCIM > Camera > sous-dossier. Bornée pour ne
# pas parcourir tout le téléphone si on part de trop haut.
_MAX_WALK_DEPTH = 4


def walk_files(item, max_depth=_MAX_WALK_DEPTH):
    """Tous les fichiers de `item` et de ses sous-dossiers.

    Indispensable pour les dossiers "conteneurs" : sur Android, DCIM ne
    contient aucun fichier, seulement Camera, Screenshots, etc. Le
    parcourir sans descendre renverrait une liste vide."""
    folders, files = list_folder(item)
    found = list(files)
    if max_depth > 1:
        for sub in folders:
            found.extend(walk_files(sub, max_depth - 1))
    return found


def find_photo_folders(device):
    """Parcourt les cartes de stockage de l'appareil et renvoie la liste
    des MTPItem correspondant à des dossiers photo usuels (DCIM, Pictures,
    WhatsApp Images...), tous storages confondus. Best-effort : les noms
    de dossiers varient selon la marque/version d'Android, donc ceci peut
    manquer des dossiers légitimes — la navigation manuelle via .children()
    reste possible en secours."""
    found = []
    seen = set()

    def add(item):
        if item.object_id not in seen:
            seen.add(item.object_id)
            found.append(item)

    for storage in device.root().children():
        if not storage.is_folder:
            continue
        for child in storage.children():
            if not child.is_folder:
                continue
            name = child.name.strip().lower()
            if name in _PHOTO_FOLDER_NAMES:
                add(child)
                # DCIM ne contient presque jamais les photos directement :
                # Android range celles de l'appareil photo dans
                # DCIM/Camera, les captures dans DCIM/Screenshots, etc.
                # (constaté sur un Mi 10T : 7 sous-dossiers, 0 fichier).
                # Idem pour Pictures selon les applis installées.
                for sub in child.children():
                    # Les dossiers cachés sont des caches d'applis, pas
                    # des photos de l'utilisateur : DCIM/.thumbnails à lui
                    # seul contient 3131 miniatures sur le Mi 10T de test,
                    # soit plus de la moitié du temps de scan.
                    if sub.is_folder and not sub.name.startswith("."):
                        add(sub)
            elif name == "whatsapp":
                # WhatsApp Images est 2 niveaux sous la racine WhatsApp.
                media = child.find_child("Media")
                if media:
                    wa_imgs = media.find_child("WhatsApp Images")
                    if wa_imgs:
                        add(wa_imgs)
    return found
