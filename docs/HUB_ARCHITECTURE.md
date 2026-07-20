# Hub.pyw — Comment ça marche

> Documentation "as-built" pour intervenir soi-même sur `Hub.pyw` sans repartir
> de zéro. Contrairement à `docs/HUB_SPEC.md` (vision/feuille de route écrite
> **avant** l'implémentation, en partie datée), ce document décrit le code
> **tel qu'il existe aujourd'hui** : fonctions, variables, flux de données.
>
> Les numéros de ligne cités sont ceux au moment de la rédaction — ils
> bougeront au fil des modifications. Pour se repérer de façon fiable,
> chercher (Ctrl+F) le texte du **bandeau de section** (`# ══════...`), ils
> sont stables et servent de table des matières dans le fichier lui-même.

## 1. Vue d'ensemble

`Hub.pyw` est **un seul fichier** (~7300 lignes) contenant **une seule
fonction géante** : `main(page: ft.Page)` (ligne 273 → fin). Tout — état,
widgets, callbacks — vit dans le scope de cette fonction et communique par
**closures** (pas de classes, pas de modules internes séparés). C'est
volontaire : ça évite d'avoir à faire circuler l'état entre modules, au prix
d'un fichier long. Chaque section est délimitée par un bandeau commentaire :

```python
# ═════════════════════════════════════════════════════════════════════
#  Nom de la section
# ═════════════════════════════════════════════════════════════════════
```

Avant `main()` (lignes 1-271) : imports, constantes de module, et une
douzaine de petites fonctions `_load_xxx`/`_save_xxx` qui lisent/écrivent les
fichiers `.json` de configuration à la racine du repo (persistance simple,
pas de base de données — voir §2).

Après `main()` (lignes 7300+) : `_install_crash_logger()` (logge les
exceptions non gérées dans `Data/.hub_crash.log`) et le point d'entrée
`ft.run(main)`.

### Le point d'entrée

```python
if __name__ == "__main__":
    _install_crash_logger()
    ft.run(main)
```

Flet appelle `main(page)` une fois, construit toute l'UI en synchrone, puis
tourne sur sa propre boucle asyncio. `page.run_task(...)` est la façon
d'exécuter du code async depuis un thread (voir §11 sur les threads).

## 2. Fichiers de config / persistance (racine du repo)

Chacun a une paire `_load_x()` / `_save_x()` en tête de fichier (lignes
84-231), en JSON, avec `try/except: pass` en cas d'erreur (best-effort,
jamais bloquant) :

| Fichier | Variable | Rôle |
|---|---|---|
| `.recent_folders.json` | via `_load_recent`/`_save_recent`/`_add_recent` | 10 derniers dossiers ouverts (menu Ouvrir ▾) |
| `.favorites.json` | `_load_favorites`/`_save_favorites` | favoris `{path, label}` |
| `open_with.json` | `_load_open_with_programs`/`_save_open_with_programs` | programmes externes ("Ouvrir avec") |
| `.order.json` | `order` | commande en cours : `{chemin: {format: nombre}}` |
| `.order_bw.json` | `order_bw` | `{chemin: bool}` — tirage N&B par photo |
| `.recadrage_auto_config.json` | via `_load_crop_auto_config` | dernier format utilisé pour "Recadrage automatique" |
| `.liste.json` (par défaut) | `liste_entries` | fichier ouvert dans la surface Liste (n'importe quel `.json` peut être ouvert à la place) |
| `.notes.md` | `note_target["path"]` | bloc-notes |
| `.ai_conversation_hub.json` | `ai_conversation` | historique de chat IA |

Ces fichiers sont à la racine du repo et **ignorés par git** (données
locales/utilisateur, pas du code).

## 3. Modules partagés (`Data/`)

Hub ne réimplémente pas la logique métier : il l'importe depuis `Data/`
(le "cerveau" partagé avec les scripts outils) :

- **`Data/CONSTANTS.py`** — toutes les constantes/config (couleurs, tailles,
  tarifs, formats, prompts IA...). Fichier long mais indexé par un sommaire en
  tête (§1 à §13) — voir §4 plus bas.
- **`Data/ai_tools.py`** — le cœur agentique : `build_tool_list()` (liste des
  outils exposés au modèle), `dispatch_folder_tool()` (exécute les outils
  "génériques fichiers"), les fonctions `_gemini_chat_stream_with_tools` /
  `_claude_chat_stream_with_tools` (appel du modèle en streaming), et plein de
  petits outils (`_web_search`, `_run_terminal_command`, TTS, génération
  d'image, etc.).
- **`Data/image_ops.py`** — opérations image bas niveau.
- **`Data/thumb_cache.py`** — génération/cache disque des miniatures (gère
  aussi SVG/PDF via Wand/PyMuPDF).
- **`Data/mcp_client.py`** — client MCP (`mcp_get_all_tools`, `mcp_call_tool`).
- **`Data/credentials.py`** — broker d'identifiants (keyring cross-OS) ;
  **ne jamais lire/écrire un mot de passe en clair**, toujours passer par ce
  module (`_ai_get_credential` dans Hub s'en sert).

Si une modif touche à une des sections ci-dessus (tarifs, prompts IA, couleurs,
formats papier...), c'est presque toujours dans `Data/CONSTANTS.py` qu'il faut
aller, pas dans `Hub.pyw`.

## 4. Sommaire de `Data/CONSTANTS.py`

Le fichier a son propre sommaire en tête (lignes 15-41) :

```
1. VERSION
2. FICHIERS & EXTENSIONS
3. COULEURS               (3bis. Système de design — rôles ICON_*/TEXT_*)
4. IMPRESSION              (4.1 DPI, 4.2 formats, 4.3 planche ID, 4.4 2-en-1)
5. RECADRAGE MANUEL.PYW
6. INTERFACE (DASHBOARD)
7. FICHIERS & DOSSIERS
8. RÉSEAU & KIOSKS
9. CACHE DE MINIATURES
10. INTELLIGENCE ARTIFICIELLE  (10.1 modèles, 10.3 voix TTS/STT, 10.7 MCP...)
11. KIOSK FLET
12. DÉBRUITAGE & GRAIN PELLICULE
13. WAND / IMAGEMAGICK
```

## 5. État partagé dans `main()` (lignes ~274-397)

Variables déclarées tôt dans `main()`, lues/modifiées par (presque) toutes les
sections ensuite. Comme tout est en closures, il n'y a **pas de classe
"State"** — juste des dicts/listes mutables partagés par référence :

| Variable | Type | Contenu |
|---|---|---|
| `state` | dict | `surface` (onglet actif), `folder` (dossier ouvert), `view` (grille/liste), `thumb_size`, `sort`, `search`, `only_selected`, `last_selected` |
| `content` | dict | `dirs`/`imgs`/`other` : listes de chemins **non filtrées** du dossier courant, remplies par `_navigate()` |
| `selected` | list | chemins actuellement cochés (liste, pas un set — l'ordre de clic compte, ex. pour numéroter dans "Renommer séquence") |
| `clipboard` | dict | `{paths, mode}` — presse-papiers interne (copier/couper) |
| `order` / `order_bw` | dict | commande en cours (voir §2) |
| `thumb_mem` | dict | cache mémoire `chemin -> bytes miniature` (évite de relire le disque) |
| `grid_card_refs` / `sel_checkbox_refs` | dict | `chemin -> control Flet`, pour mettre à jour une case/bordure **sans reconstruire toute la grille** (perf sur gros dossiers) |

Couleurs (lignes 274-286) : alias locaux vers `CONSTANTS.COLOR_*`
(`DARK`, `BACKGROUND`, `GREY`, `WHITE`, `BLUE`, `RED`, `GREEN`, `ORANGE`,
`YELLOW`, `VIOLET`, `LIGHT_GREY`) — utilisés partout dans le fichier au lieu
de répéter `CONSTANTS.COLOR_xxx`.

## 6. Les sections de `main()`, dans l'ordre du fichier

### 6.1 Surface Fichiers / Explorateur (~L398-1033)
Vue liste (`files_list`, `ft.ListView`) et vue grille (`files_grid`,
`ft.GridView`) échangées dans un conteneur unique `files_body` (jamais de
`Stack`, ça posait des soucis d'`expand`, cf. commentaires). Fonctions clés :
- `_navigate(path)` (L1431) — **point de passage central** : change
  `state["folder"]`, relit le dossier (`os.scandir`), remplit `content`,
  réinitialise la sélection/recherche, appelle `_render()`. Toute action qui
  change le contenu du dossier (suppression, déplacement, outil lancé...)
  repasse par ici.
- `_render()` (L870) — reconstruit `files_list`/`files_grid` à partir de
  `content` + filtres (`_visible_entries()`), lance le chargement des
  miniatures manquantes (`_start_thumb_loader`).
- `_start_thumb_loader(pending)` (L928) — génère les miniatures dans un
  `ThreadPoolExecutor` (2 workers, priorité CPU abaissée), met à jour l'UI par
  petits paquets (`page.update(*batch)`, jamais `page.update()` seul — sinon
  ça sature la boucle d'événements sur un gros dossier).
- `_set_selected(path, on)` / `_clear_selection_visuals()` — cochent/décochent
  sans reconstruire toute la vue (perf).

### 6.2 Presse-papiers / opérations fichiers (~L1033-1844)
`_do_copy`, `_do_cut`, `_do_paste`, `_do_delete`, `_do_duplicate`, `_do_zip`,
`_do_unzip`, `_rename_item`, `_reveal_in_explorer`, `_show_exif_dialog`,
`_add_open_with_program`. Toutes prennent une liste de chemins et retournent
via `_navigate()` pour rafraîchir. Pas de dialogue de confirmation sur
Supprimer (politique du projet) — **la protection, c'est le backup**
(`_backup_file`, importé de `ai_tools.py`, appelé avant toute écriture
destructrice).

### 6.3 Visionneuse plein écran (~L1844-2159)
Overlay unique (`viewer_overlay`, posé sur `page.overlay`, donc en dehors de
l'arbre de layout normal) réutilisé partout où on ouvre une image en grand.
État : `viewer_state = {"paths": [], "index": 0}`. Swipe tactile via
`ft.PageView` si dispo (`_HAS_PAGE_VIEW`, désactivé sous Linux). Fonctions :
`_open_viewer(start_path)`, `_viewer_nav(delta)`, `_rotate_current(direction)`
(rotation en mémoire, `viewer_rotated_bytes`), `_close_viewer()`.

### 6.4 Éditeur — lancement de Recadrage manuel.pyw (~L2159-2212)
`_launch_editor_for_current(script_name)` (L2168) — ouvre `Recadrage
manuel.pyw` sur la photo actuellement affichée dans la visionneuse.

### 6.5 Menu "Ouvrir ▾" (~L2212-2841)
`_build_open_menu()` assemble favoris + récents + lecteurs amovibles
(`_get_removable_drives`, `_eject_drive`) dans un seul menu déroulant — pas de
tiroir dédié.

### 6.6 Barre d'outils Fichiers + panneau Actions (boutons dans cette zone)
Les icônes **Recadrage manuel / Recadrage automatique / 2 en 1**
(`recadrage_manuel_btn`, `recadrage_auto_btn`, `two_en_un_btn`, ~L2631-2643)
et les icônes fichier de la barre de recherche (**Renommer, Copier, Couper,
Coller, Dupliquer, Zipper, Ajouter à l'IA, Supprimer** — `renommer_btn` etc.,
~L2732-2767, groupées dans `edit_btns_row`) sont **toujours actives**, avec ou
sans sélection : sans sélection, les outils lancés traitent tout le dossier
(convention `SELECTED_FILES` absent/vide = tout le dossier, voir §8). Seuls
Renommer/Copier/Couper/Dupliquer/Zipper/Ajouter à l'IA/Supprimer restent
grisés tant qu'aucune sélection n'est faite (`_refresh_edit_buttons`,
`_sel_edit_btns`, L2797) — logique de dépendance à la sélection.

Le panneau **Actions** (overlay demi-écran, `_open_actions`/`_close_actions`,
~L6217-6457) reprend les catégories `_ACTION_CATEGORIES` (L6222) : c'est une
simple liste `(nom_catégorie, [(label, icône, couleur, handler), ...])`
rendue par `_action_row`/`_action_category`. Plusieurs entrées **réutilisent
directement** les `on_click` des boutons de la barre d'outils (ex.
`recadrage_manuel_btn.on_click`) — un seul endroit à modifier si le
comportement change. C'est ici qu'atterrit le clic droit sur une image
(cf. commentaire L6311 : "le clic droit ouvre désormais ce panneau").

### 6.7 Bloc-notes (~L2841-3112)
Éditeur générique `.notes.md` (ou n'importe quel `.py`/`.json`/`.md`/`.txt`
ouvert depuis Fichiers). Coloration syntaxique via `flet_code_editor`
(désactivée sous Linux, repli en `TextField` brut — `_HAS_CODE_EDITOR`).
Auto-save avec debounce (`notes_autosave_timer`).

### 6.8 Surface IA — chat + outils (~L3112-4787, la plus grosse section)
État : `ai_conversation` (historique complet envoyé au modèle),
`ai_streaming["value"]` (garde anti-double-envoi), `ai_pending_images` /
`ai_pending_files` (pièces jointes en attente).

Flux d'un message (`_send_ai_message(text)`, L4453) :
1. Construit `user_message`, l'ajoute à `ai_conversation`, l'affiche
   (`_ai_add_bubble`).
2. Lance un thread (`_run`) qui boucle jusqu'à 20 tours
   (`for _round in range(20)`) : appelle `_gemini_chat_stream_with_tools` ou
   `_claude_chat_stream_with_tools` (selon `ai_model_dropdown.value`) avec la
   liste d'outils de `build_tool_list()`, exécute chaque `tool_call` reçu via
   `_ai_run_tool`, boucle tant que le modèle continue à appeler des outils.
3. `_ai_run_tool(fn_name, fn_args, ui)` (L4091) — **le routeur d'outils** :
   - `mcp__*` → `mcp_client.mcp_call_tool`
   - dans `_AI_SPECIAL_TOOLS` (L3984, ex. `generate_image`, `iterate_image`,
     `score_photos`, `take_screenshot`...) → fonctions `_ai_tool_*` locales à
     Hub (besoin d'accès à l'UI/état de Hub)
   - sinon → `dispatch_folder_tool()` (outils "fichiers" génériques)
   - sinon → `_AI_FALLBACK_TOOLS` (L4053, ex. `list_folder_contents`,
     `create_file`, `web_search`, `run_terminal_command`, `read_notepad`...)
   - sinon → message "outil indisponible"

**Pour ajouter un nouvel outil IA** : soit il est déjà générique (fichiers,
web...) et vit dans `Data/ai_tools.py` (`dispatch_folder_tool`), soit il a
besoin de l'UI de Hub → écrire une fonction `_ai_tool_xxx(fn_name, args)` et
l'ajouter à `_AI_SPECIAL_TOOLS` ou `_AI_FALLBACK_TOOLS`, **et** déclarer
l'outil (nom, description, paramètres) côté `build_tool_list()` dans
`Data/ai_tools.py` pour que le modèle sache qu'il existe.

Autres morceaux notables : dictée vocale (`_mic_start`/`_mic_stop`,
raccourci global `_mic_hotkey_start`), TTS (`_speak_bubble`), génération
image/musique Gemini (`_ai_tool_generate_image`, `_ai_tool_generate_music`),
credential broker (`_ai_get_credential`, L3410 — jamais de mot de passe en
clair, cf. `Data/credentials.py`).

### 6.9 Mode commande (~L4787-4877)
`order[path] = {format: nombre}`. Tarif dégressif par palier
(`_order_unit_price`, mêmes seuils que `Data/kiosk_flet.pyw`) + frais
d'amorce (`CONSTANTS.ORDER_SETUP_FEE`). `_create_order_folder` matérialise la
commande : un sous-dossier par format, fichiers copiés (convertis en N&B si
`order_bw[path]`), `commande.txt` récapitulatif avec le total.

### 6.10 Surface Liste — éditeur `.json` générique (~L4877-5149)
Lecteur/éditeur de fichier `.json` quelconque (liste de dicts) : mots-clés,
fiches produit, etc. — l'IA peut y écrire directement (`create_file`/
`edit_file`) sans outil dédié. **Colonnes adaptatives** depuis 2024 : au lieu
d'un schéma figé `{nom, description}`, `_liste_columns()` (L4892) calcule les
colonnes comme l'union ordonnée des clés trouvées dans les entrées (fallback
`nom`/`description` si le fichier est vide) ; `_liste_header()` affiche un
en-tête de colonnes, `_liste_row`/`_liste_edit` s'adaptent en conséquence.
Détail non trivial : `_liste_open_path` (L5058) — sélectionner un `.json`
dans Fichiers ouvre directement cette surface (pas de bouton "Ouvrir" séparé).

### 6.11 Rail gauche / droit, changement de surface (~L5149-5273)
`SURFACES` (déclaré en tête de module, L68-73) liste les 4 onglets
(`files`/`liste`/`ia`/`notes`). `surface_content` (dict, L5140) mappe chaque
clé vers son widget racine. `_select_surface(key)` (L5183) bascule
`center.content` et recolore l'onglet actif ; `_focus_active_surface()`
(async, L5155) redonne le focus au bon champ selon l'onglet.

**Pour ajouter une 5e surface** : ajouter une entrée à `SURFACES`, construire
son widget racine quelque part dans `main()`, l'ajouter à `surface_content`.

### 6.12 Rail droit / lanceurs d'outils externes (~L5240-6459)
`_launch_tool(script_name, is_local=False, extra_env=None)` (L5273) — **le
point commun à tous les outils externes** (`Data/*.py`/`*.pyw` lancés en
sous-processus). Passe `FOLDER_PATH` (dossier ouvert) et `SELECTED_FILES`
(basenames séparés par `|`, **absent si rien n'est sélectionné** → convention
"tout le dossier" respectée par chaque script, voir `Data/skills.md`). Lit la
sortie du process ligne à ligne en temps réel (log dans le terminal intégré),
intercepte des lignes spéciales (`NAVIGATE_TO:`, `SELECTED_FILES:`). Chaque
outil a son propre petit lanceur (`_launch_recadrage_auto`,
`_launch_two_in_one`, `_launch_redimensionner`, `_launch_grain_pellicule`...)
qui ouvre un dialogue de paramètres puis appelle `_launch_tool` avec
`extra_env`.

**Pour ajouter un nouvel outil externe** : créer le script dans `Data/`
(respectant la convention `FOLDER_PATH`/`SELECTED_FILES`, cf.
`Data/skills.md`), écrire un petit `_launch_xxx` s'il faut un dialogue de
paramètres (sinon `lambda e: _launch_tool("MonScript.py")` suffit), l'ajouter
à `_ACTION_CATEGORIES` (§6.6) dans la bonne catégorie.

### 6.13 Terminal intégré (~L6459-6989)
Exécute une commande shell dans `state["folder"]` (PowerShell sur Windows,
zsh/bash ailleurs). Auto-affichage/masquage avec debounce
(`_show_terminal_and_schedule_hide`) : apparaît à chaque message loggé
(`_log_to_terminal`), se referme après un délai de silence
(`CONSTANTS.HUB_TERMINAL_AUTOHIDE_DELAY`), sauf s'il est "épinglé"
(`_terminal_autohide["pinned"]`, manuellement ou via `_busy_start`/`_busy_end`
pendant une opération longue).

### 6.14 Barre d'état, barre de titre, assemblage (~L6989-7214)
`statusbar` (terminal + curseur taille), `titlebar` (sans cadre, drag de
fenêtre via `ft.WindowDragArea`, boutons réduire/maximiser/fermer). Assemblage
final : `page.add(ft.Column([titlebar, body]))`.

### 6.15 Raccourcis clavier globaux (~L7214-7276)
`_on_global_key(event)`, branché sur `page.on_keyboard_event`. Actifs
seulement sur la surface Fichiers, hors saisie texte et dialogue ouvert :
`Ctrl+A` (tout sélectionner), `Ctrl+C/X/V` (copier/couper/coller), `Ctrl+I`
(inverser sélection), `Ctrl+D` (même date), `Ctrl+N` (nouveau dossier),
`Ctrl+R` (rafraîchir), `Suppr` (supprimer sélection), `Ctrl+↑` (terminal),
flèches (rappel d'historique terminal/IA).

## 7. Threads et mise à jour de l'UI — piège à connaître

Flet exige que toute modification de l'UI passe par la boucle asyncio de la
page. Or plusieurs opérations tournent dans des **threads Python classiques**
(génération de miniatures, exécution d'outils externes, streaming IA,
dictée...) pour ne pas geler la fenêtre. Deux idiomes reviennent partout dans
le fichier :

- Depuis un thread : ne **jamais** appeler `page.update()` directement de
  façon fiable → passer par `page.run_task(ma_fonction_async)`.
- `page.update()` **sans argument** rediffuse tout l'arbre de contrôles (coût
  proportionnel à la taille de l'UI) ; `page.update(*controls)` ne patche que
  les contrôles listés. Sur les boucles qui mettent à jour beaucoup d'éléments
  (miniatures, streaming de texte), préférer la seconde forme et grouper les
  mises à jour (voir `_start_thumb_loader`, §6.1).

## 8. Convention `FOLDER_PATH` / `SELECTED_FILES`

Tous les scripts de `Data/` lancés par `_launch_tool` suivent la même
convention d'entrée (variables d'environnement, voir `Data/skills.md`) :

- `FOLDER_PATH` — dossier sur lequel travailler.
- `SELECTED_FILES` — noms de fichiers (basenames) séparés par `|`.
  **Absent ou vide → tout le dossier.** C'est pourquoi les boutons Recadrage/
  2-en-1/etc. n'ont pas besoin d'une sélection active pour fonctionner.

## 9. Où toucher pour un changement courant

| Je veux... | Aller dans... |
|---|---|
| Changer une couleur, un tarif, un format papier, un prompt IA | `Data/CONSTANTS.py` (voir sommaire §4) |
| Ajouter un outil externe (script `Data/*.py`) au menu Actions | `_ACTION_CATEGORIES` (~L6222) + créer le script dans `Data/` |
| Ajouter un outil que l'IA peut appeler | `Data/ai_tools.py` (`build_tool_list`/`dispatch_folder_tool`) si générique, sinon `_AI_SPECIAL_TOOLS`/`_AI_FALLBACK_TOOLS` dans Hub (~L3984/L4053) |
| Changer le comportement de la sélection de fichiers | `_set_selected`, `_toggle_all`, `_refresh_edit_buttons` (~L424-1033) |
| Modifier la visionneuse plein écran | ~L1844-2159 |
| Modifier le mode commande / tarifs | ~L4787-4877 + `Data/CONSTANTS.py` §4/§11.3 |
| Modifier la surface Liste (`.json`) | ~L4877-5149 |
| Ajouter une nouvelle surface (onglet) | `SURFACES` (L68) + `surface_content` (~L5140) |
| Ajouter un raccourci clavier global | `_on_global_key` (~L7224) |
