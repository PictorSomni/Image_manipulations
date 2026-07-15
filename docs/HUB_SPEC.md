# Hub unifié — Spécification

> Fusion de **Dashboard** (hub « tous mes outils ») et **SidePanel** (compagnon
> « chaque chose à sa place ») en **une seule application adaptative**.
> Maquette de disposition de référence : voir l'artefact `concept-v7`
> (Explorateur outillé · visionneuse · mode commande · kiosque).
>
> Statut : **spécification** — feuille de route avant implémentation. Le
> « cerveau » agentique est déjà mutualisé (voir §14).

---

## 1. Objectif

Une application unique qui couvre **deux modes d'usage** aujourd'hui séparés :

- **Hub plein écran** (ex-Dashboard) : poste de commande, plusieurs facettes.
- **Compagnon demi-écran** (ex-SidePanel) : collé à un navigateur / client mail
  pour préparer une commande, poser des questions à l'IA, cocher une liste.

Une seule app, **adaptative à sa largeur**. Plus de double maintenance.

## 2. Principes d'architecture

1. **Surfaces principales interchangeables** — `Explorateur`, `Liste/Commande`,
   `IA`, `Bloc-notes`. Une seule remplit la fenêtre à la fois, choisie par de fins
   onglets verticaux à gauche. La surface active **persiste** (ne disparaît pas
   quand la fenêtre perd le focus — cas compagnon à côté du navigateur).
   *(Dock moitié droite : reporté — cf. §15.)*
2. **Visionneuse = overlay unique réutilisable** — un seul composant
   `ouvrir(photo, contexte)` appelé depuis la grille, la liste, les lignes de
   commande et le kiosque. Voir §6.
3. **Surfaces de support en tiroirs** — Favoris/périphériques (droite),
   Terminal (barre d'état). Fins, épinglables, superposés (ne volent jamais la
   largeur du centre).
4. **Actions contextuelles en overlay** — déclenché par une sélection ; inclut
   les apps de `apps_list` (« Ouvrir avec »).
5. **Adaptateur UI** — le cœur logique parle à l'UI via un petit jeu de rappels
   (`set_status`, `bubble`, `event`, `refresh`, `paint`, `credential`). Déjà en
   place (`dispatch_folder_tool` dans `Data/ai_tools.py`).
6. **Backup avant toute opération destructrice** — déjà généralisé (fichiers +
   MCP), dans `Data/.ai_backups/` (gitignoré). Aucun garde-fou de confirmation :
   c'est le backup qui protège.

## 3. Modes

| Mode | Déclencheur | Comportement |
|---|---|---|
| **Hub plein écran** | largeur large | toutes les surfaces/tiroirs disponibles |
| **Compagnon demi-écran** | largeur ~⅓–½ écran | tiroirs fermés, le centre garde toute la largeur ; surface active persistante |
| **Kiosque (client)** | bascule explicite `🔒` | chrome verrouillé, tarif visible, **aucun accès au reste de la machine** (voir §9) |

Responsive : implémenter **d'abord** les tiroirs/overlays (rend l'app utilisable
en demi-écran) ; n'ajouter un point de rupture `page.width` **que si** le centre
reste à l'étroit (repli du contenu). Pas de responsive spéculatif.

## 4. Disposition & navigation

```
┌─┬─────────────────────────────┐
│E│                             │  E/L/I = onglets verticaux (surfaces)
│x│   SURFACE ACTIVE            │
│p│   (Explorateur / Liste /    │
│·│    IA — remplit tout)       │
│L│                             │
│·│                             │
│I│                             │
├─┴─────────────────────────────┤
│ [Terminal]   [Actions]  [Taille]│  ← barre d'état
└────────────────────────────────┘
```

- **Rail gauche** : onglets verticaux fins (flèche + texte vertical) = changer de
  surface. Extensible (~6–7 avant de repenser).
- **Barre d'état (bas)** : `Terminal` **au centre** (**remonte seul en cas
  d'erreur**), curseur **Taille des vignettes** (droite).
- **Rail droit** : **Actions** (texte **coloré en évidence**) → **overlay plein
  écran** d'actions (pas un panneau docké).
- **Terminal** : **pas un overlay** — il **« relève » l'interface** (pousse le
  contenu vers le haut, l'espace lui est réservé) pour ne pas perdre ses outils.
  Peut rester présent en permanence.
- **Favoris / récents / périphériques** : **pas de tiroir droite** — tout est
  regroupé dans le menu **Ouvrir ▾** (§5).

## 5. Explorateur

### Barre d'outils
- **Ouvrir ▾** : menu regroupant **emplacements récents** (comme les 2 apps
  actuelles) + **Favoris** + Parcourir… (sélecteur système). Inclut
  **★ Ajouter ce dossier aux favoris** ; les favoris sont **retirables** (✕)
  quand il y en a.
- **Fil d'Ariane** cliquable.
- **Recherche** avec **✕** pour vider en un clic ; filtre la grille en direct.
- **Tri** : Date ↓ / Nom / Type.
- **Vues** : **Vignettes ⇄ Liste**. La *Liste* (façon `preview_list` Dashboard)
  est plus facile à cocher et à lire ; les *Vignettes* servent au choix avec un
  client, **taille réglable** (curseur en barre d'état).

### Sélection
- **Case à cocher grande et alignée** sur chaque vignette (façon Dashboard) :
  simple, imposante, toujours visible. **Le clic sur l'image ouvre la
  visionneuse** ; le clic sur la case sélectionne. (Fini les ouvertures
  involontaires.)
- Barre de sélection : **un seul bouton** *Tout sélectionner ⇄ Tout désélectionner*,
  **Inverser**, **Même date de modification**, **Afficher uniquement la sélection**
  (pratique pour des fichiers éparpillés).
- La **sélection simple est indépendante de la commande** : on peut choisir des
  photos **sans taille ni nombre** (ex. pour un montage).

### Menu clic-droit
Copier · Couper · Coller · Renommer · Nouveau dossier · **Dossier depuis la
sélection** · Supprimer (avec backup). (Peut aussi apparaître dans l'overlay
Actions.)

### Actions (bouton central de la barre d'état)
S'applique à la **sélection** ; si rien n'est coché, à **tout le dossier**.
Overlay groupé : Créer/organiser (dossier commande, dossier depuis sélection,
ajouter à la liste) · Traiter (Retoucher IA, Convertir, Exporter, Mail, Supprimer)
· **Ouvrir avec** (apps de `apps_list`).

## 6. Visionneuse (overlay réutilisable)

Un seul composant, ouvert de partout. Contient :
- Grande image, navigation **◀ ▶** (+ flèches clavier, `Échap`), compteur *n / N*.
- **Choisir** (coche synchronisée avec la grille) — indépendant de la commande.
- **N&B** (aperçu grisé ; attribut par photo/ligne de commande).
- **Retouche légère** (réglages de base, non destructifs) : **exposition /
  luminosité**, **ombres** (relevées), **saturation**, **balance des blancs**,
  **teintes**, et **garantie de fond blanc**. Rattrape une lumière changeante ou
  un réglage modifié par erreur — crucial pour les **photos d'identité**. Reprend
  l'usage de `Recadrage manuel.pyw` (à intégrer, pas à garder à part).
- **Rotation 90°** (pas) **+ rotation fine / redressement** (curseur d'angle) —
  remplace le besoin de `Recadrage.pyw` (à intégrer, pas à garder à part).
- **Recadrage** (voir §7).
- **Supprimer** l'image courante (backup).
- En contexte commande : composer **format + nombre + N&B** et **➕ Ajouter** une
  ligne (voir §8).
- **Panneaux d'options à la demande** : afficher **nombres, dimensions,
  recadrages, retouches** via des **onglets latéraux et en bas** de la
  visionneuse (montrer +/− d'options selon la tâche) — même logique de
  dévoilement que l'interface principale.
- **Bloc-notes** : surface de notes libres (ré-introduite) ; l'IA peut y écrire.
  Séparée de l'IA (rarement utiles ensemble ; outils de transfert déjà présents).

## 7. Recadrage & impression

- Le cadre est **verrouillé sur la taille d'impression** choisie (10×15 … A3).
  Si aucune taille n'est fixée : choisir dans la liste **ou** saisir un **format
  perso** en **mm (à 300 DPI)** ou en **px** (conversion affichée en direct).
- **Orientation** portrait/paysage (recadrer en portrait une photo prise en
  paysage).
- **Cadre déplaçable** : repositionner la zone (recentrer un visage sur le bord,
  montrer moins de plafond / plus d'invités).
- **Rotation fine** intégrée (redressement d'horizon).

### Redressement & bords (impression)  ⚠️
Quand on **redresse** une image (rotation fine), la zone recadrée doit **toujours
rester dans l'image d'origine** — **pas de coins vides**, c'est pour l'impression.
Le cadre est donc contraint à la surface valide après rotation. **Alternative /
complément** : intégrer l'**outpainting Gemini** (comme dans `Augmentation IA.py`)
pour **remplir les bords manquants**, et la **retouche** avec (cf. §6). → *à trancher.*

### Décision structurante — copie vs original  ⚠️
**Recommandé (défaut proposé)** : recadrage / rotation / N&B produisent une
**copie d'impression dérivée** (dans le dossier de commande), l'**original
préservé**, avec backup. Alternative : modifier le fichier (backup avant).
→ *À confirmer avant implémentation.*

## 8. Mode commande

Contexte métier : reportages publics (ex. spectacle de danse) où les parents
commandent des photos de leur enfant. La commande reçue par mail est un
**tableau** : aperçu · nom · **taille d'impression** · **nombre d'exemplaires**.

### Modèle de données  ⚠️ (changement vs état actuel)
Une commande n'est **pas** « une ligne par photo » mais **plusieurs lignes par
photo** — un client veut parfois la même image en **plusieurs formats** et/ou en
**N&B**. Chaque ligne :

```
{ photo, format, nombre, n&b: bool, recadrage: {format, orientation, cadre, angle} }
```

### Interface
- Dans l'Explorateur (Mode commande) et/ou la visionneuse : dropdown **taille** +
  stepper **nombre** + **N&B** ; **➕ Ajouter** crée une ligne (répéter pour un
  autre format).
- La surface **Liste devient le tableau de commande** : aperçu · nom · taille ·
  N&B · nombre · **prix ligne**, avec **total**. Lignes **cliquables** (ouvrent
  la visionneuse pour voir en grand / retirer / modifier).
- **Tarifs** : prix par format → total en direct (aussi affiché au client en
  kiosque).
- **Créer le dossier de commande** : copie la sélection (+ recadrages/N&B en
  copies dérivées, cf. §7) → dossier prêt à livrer.

### Disposition d'impression (imposition)
Au-delà du format et du nombre : définir la **disposition sur la planche** — N
exemplaires agencés sur une page (typiquement une **planche de photos
d'identité** sur un 10×15 / A4). Combiné à la retouche (§6 : luminosité + fond
blanc), le **workflow photo d'identité en une passe** = éclaircir → garantir le
fond blanc → recadrer au format → imposer N exemplaires → imprimer.

## 9. Kiosque (mode client)

But : laisser le **client choisir sa commande** lui-même (remplace `kiosk_flet`,
en corrigeant son manque : **le recadrage y est disponible**).

- **Chrome verrouillé** : plus de rail, tiroirs, barre d'outils, explorateur
  libre. Uniquement : voir en grand · choisir · format/nombre/N&B · recadrer ·
  **total tarifé** · Valider ma commande.
- **Sécurité (comportement, hors maquette)** — exigences fermes :
  - **Aucun accès au système de fichiers** hors de la sélection curatée.
  - **Aucune copie possible vers une clé USB / support externe.**
  - **Sortie directe (✕)** : pas de code studio — usage en présentiel sur
    écran tactile, l'opérateur est physiquement là pour fermer le kiosque.
  - Objectif : empêcher qu'un client copie discrètement des photos **non payées**.
- **Vue vignettes disponible** pour le client (parcourir la sélection en grille,
  taille réglable) — gros plus pour choisir.

## 10. Surfaces de support

- **Favoris, périphériques & récents** : regroupés dans le menu **Ouvrir ▾**
  (pas de tiroir droite dédié). Accès rapides + volumes (SD, SSD, NAS) +
  emplacements récents. Priorité **rapidité** (client présent).
- **Terminal** (barre d'état) : invocable ; **remonte seul en cas de sortie ou
  d'erreur** (« voir l'avancée / le problème »).
- **IA** (surface) : agit partout ; typiquement questions à propos de la fenêtre
  active (rédaction de fiches PrestaShop, etc.), et **remplit la Liste/commande**
  depuis un mail reçu.

## 11. Apps

Les apps de `apps_list` ne sont **pas** un tiroir dédié : elles apparaissent dans
l'overlay **Actions → « Ouvrir avec »** sur une sélection. (Prévoir aussi un
lancement « à vide » — à trancher : entrée dans `Ouvrir ▾` ou Favoris.)

## 12. Sécurité & données

- **Backup systématique** avant toute opération destructrice (déjà en place,
  fichiers + MCP).
- **Kiosque** : cf. §9 (verrouillage réel, pas d'exfiltration USB).
- Recadrage/rotation : copies dérivées par défaut (cf. §7).

## 13. Design / charte

Charte non figée. La maquette utilise des couleurs/typo **indicatives**. À
l'implémentation, réutiliser le **système de design existant** (`CONSTANTS` §3bis
— rôles `ICON_*`, échelle `TEXT_*` ; SidePanel = modèle de clarté).

## 14. État du code & migration

**Déjà fait** (mutualisation du « cerveau », commit `39bca8c`) :
- `build_tool_list()` — assemblage unique de la liste d'outils.
- `dispatch_folder_tool()` + adaptateur UI (6 rappels) — 21 branches d'outils
  « pures » partagées entre les deux apps.
- Nettoyage de 89 imports morts.
- Fiabilisation du démontage client MCP (cancel scope).

**Restant (incrémental, pas de big-bang)** :
1. Adaptateur UI pour les branches UI-lourdes divergentes (delete, notepad,
   image, organize…).
2. Extraction du squelette de la boucle agentique.
3. Construction de la coquille unique (rail + surfaces + tiroirs + barre d'état)
   réutilisant le cerveau mutualisé.
4. Migration Explorateur / Liste-Commande / IA en surfaces.
5. Visionneuse-overlay réutilisable (§6).
6. Mode commande + tarifs + kiosque (§8–9).

## 15. Décisions ouvertes

1. **Recadrage/rotation/N&B : copie dérivée (défaut proposé) ou fichier ?** (§7)
2. **Lancement d'app « à vide »** : où ? (`Ouvrir ▾` / Favoris) (§11)
3. **Kiosque** : mode du hub (recommandé) ou app séparée partageant le moteur ?
4. **Grille des tarifs** par format : source (config `CONSTANTS` ?).
5. **Point de rupture responsive** : nécessaire ou les tiroirs suffisent ? (§3)
