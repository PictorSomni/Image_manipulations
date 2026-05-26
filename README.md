# 📸 Dashboard Image Manipulation

Application de gestion et manipulation d'images avec interface graphique.  
Compatible **Windows**, **macOS** et **Linux**.

![Dashboard](screenshots/dashboard01.jpg)
![Recadrage](screenshots/dashboard02.jpg)
![Selecteur](screenshots/dashboard03.jpg)
![Augmentation IA](screenshots/dashboard04.jpg)
![Kiosk](screenshots/dashboard05.jpg)

---

## 🆕 Nouveautés

### Dashboard (v2.6)
- **Mémoire persistante de l'IA** : l'assistant peut désormais mémoriser des informations entre les sessions via 4 fichiers locaux dans `Data/` :
  - `system.md` — prompt système personnalisable (remplace `AI_SYSTEM_PROMPT` dans `CONSTANTS.py`)
  - `memory.md` — notes personnelles de l'agent (max 2 200 chars)
  - `user.md` — profil utilisateur : préférences, habitudes, style (max 1 375 chars)
  - `skills.md` — procédures et techniques apprises (max 3 000 chars)  
  L'IA utilise l'outil `update_memory_file` pour ajouter, remplacer ou supprimer des entrées. Ces fichiers sont injectés automatiquement dans le system prompt à chaque démarrage avec un indicateur d'utilisation `[12% — 267/2200 chars]`.
- **Texte préliminaire conservé** : quand l'IA écrit du texte avant d'appeler un outil (ex. « Je vais lister le dossier… »), ce texte reste affiché plutôt que d'être supprimé.
- **Prise en charge du format `<tool_code>` de Gemma** : les appels d'outils au format Google/Gemma (`<tool_code>print(file_manager.create_file(...))</tool_code>`) sont désormais parsés et exécutés correctement, y compris la concaténation de chaînes Python dans les arguments.

### Dashboard (v2.5 + v2.6 antérieur)
- **Gemma comme agent — boucle agentique multi-tours** : l'IA peut enchaîner jusqu'à 6 tours d'outils automatiquement. Une seule question peut déclencher une recherche web, lire la page trouvée, lister le dossier ouvert, puis analyser les images — tout en continu, sans intervention.
- **Thinking natif streamé** : les modèles supportant le mode thinking Ollama affichent leur raisonnement intermédiaire en temps réel dans une bulle 💭 dédiée.
- **Outils dossier intégrés** : quand un dossier est ouvert, l'IA dispose de 4 outils supplémentaires :
  - `list_folder_contents` — liste les fichiers avec taille et date
  - `read_file_content` — lit le contenu d'un fichier texte
  - `organize_files` — propose et exécute une organisation par sous-dossiers (confirmation avant action)
  - `analyze_images` — analyse visuellement les images par lots avec une question libre
- **Sélection photo IA agentique** : nouveau mode de sélection avant développement RAW via l'outil `select_photos`. Analyse par lots de 5 images, critères professionnels de reportage (netteté, expression, exposition, cadrage), taux de sélection 30-60 % configurable.
- **Modèle par défaut mis à jour** : Gemma 4 E4B (~9.6 GB, texte + vision natif) remplace les anciens `llama3.2:3b` + `llava:7b`. Liste étendue incluant Gemma 4 26B, DeepSeek-R1 (8B/14B), Llama 3.2 Vision, etc.
- **Support documents et audio** : glisser-déposer ou joindre des fichiers texte, code, PDF, DOCX directement à l'IA ; support des fichiers audio (mp3, wav, m4a, flac…).
- **Outils web et dossier centralisés** : les définitions d'outils et le contexte système sont partagés entre Dashboard et SidePanel via `ai_tools.py` (pas de duplication).

### Dashboard (v2.4)
- **Assistant IA local** : conversation intégrée via [Ollama](https://ollama.com) — accessible avec `/ai` dans la barre de commande.
  - Sélection automatique du modèle : texte pur (`llama3.2:3b`) ou vision (`llava:7b`) selon qu'une image est jointe ou non.
  - **Envoi d'images** : bouton 📎 dans le panneau IA, ou clic-droit sur une image de la preview → *Envoyer à l'IA*.
  - Images redimensionnées automatiquement à 1024 px avant envoi (performance).
  - Auto-démarrage du serveur Ollama si absent ; téléchargement automatique du modèle à la première utilisation.
  - Bouton ⏹ pour libérer la RAM (`ollama stop`) quand l'analyse est terminée.
  - Mise à jour automatique des modèles lors du `git pull` intégré.
  - Ollama installé automatiquement par `install.sh` / `install.bat` si absent.
- **Visionneuse plein écran** : ouvrir n'importe quelle image en plein écran depuis le panneau de fichiers, avec navigation au clavier (flèches), possibilité de **sélectionner ou supprimer** le fichier affiché depuis la visionneuse.
- **Tri des dossiers** : tri alphabétique A → Z, Z → A ou par **Date** via les boutons dédiés dans la barre de contenu.
- **Bouton Mise à jour** intégré directement dans l'interface (équivalent de `update.bat` / `update.sh`).
- **Nettoyage des anciens fichiers** : suppression en un clic des fichiers de plus de 60 jours dans des dossiers cibles prédéfinis.
-**Bloc note** : intégré dane le terminal via la commande /note. Enregistré automatiquement à la fermeture (bouton croix ou avec la touche Echap) dans un fichier .note.txt$
-**Options** : intégré via la commande /option dans le terminal. Permet de voir (et modifier) le fichier CONSTANTS.py. 

### Augmentation IA (v2.0)
- **Sélection SAM2** : découpe interactive par clics positifs / négatifs en complément de rembg — modèles S, B+ et L téléchargeables à la demande.
- **Inpainting** : suppression d'éléments par inpainting avec choix du moteur :
  - **TELEA** (intégré, sans dépendance supplémentaire)
  - **LaMa** et **MAT** via [IOPaint](https://github.com/Sanster/IOPaint) (`pip install iopaint`)
- **Slider morphologique unifié** (−5 % … +5 %) : valeur négative = érosion du masque rembg, valeur positive = dilatation du masque SAM2 avant inpainting.

### Recadrage (v2.0)
- **Interface repensée** avec des sections colorées (Géométrie, Luminosité, Couleur, Netteté) pour une navigation plus lisible.
- **Balance des blancs** : curseur froid / chaud ajustable en temps réel.
- **Histogramme** : aperçu de la distribution des tons directement dans le panneau de droite.

### SidePanel (v2.1)
- **Onglet Fichiers** : prévisualisation d'un dossier source avec sélection par checkbox, filtres par type, tri et barre de recherche. Copie les fichiers sélectionnés vers un dossier de destination, avec création optionnelle d'un sous-dossier nommé.
- **Onglet Liste** : gestion d'une liste de noms / descriptions stockée en JSON — recherche, tri, ajout, édition et suppression d'entrées. Cliquer sur un nom ou une description le copie automatiquement dans le presse-papiers.
- **Lancement flexible** : utilisable indépendamment ou directement depuis le Dashboard.

---

## 🚀 Installation rapide

### Windows
```cmd
install.bat
```

### Linux / macOS
```bash
chmod +x install.sh run.sh update.sh
./install.sh
```

---

## ▶️ Lancement

### Méthode 1 : Lanceur automatique (recommandé)

**Windows :**
```cmd
run.bat
```

**Linux / macOS :**
```bash
./run.sh
```

### Méthode 2 : Python direct
```bash
python Dashboard.pyw
```
*ou*
```bash
python3 Dashboard.pyw
```

---

## 🔄 Mise à jour du projet (Git)

### Windows
```cmd
update.bat
```

### Linux / macOS
```bash
./update.sh
```

Ces scripts font `git pull` **uniquement si** :
- le dossier est un dépôt Git valide,
- le script est lancé depuis la racine du dépôt,
- le remote `origin` correspond à l'adresse attendue du projet.

Sinon, ils s'arrêtent avec un message d'erreur explicite.

---

## 📋 Prérequis

- **Python 3.8+** : [Télécharger Python](https://www.python.org/downloads/)
- **Ollama** *(installé automatiquement par `install.sh` / `install.bat`)* : [ollama.com](https://ollama.com/download)
  - Moteur d'IA local — fait tourner les modèles de langage sur la machine.
  - Modèle utilisé par défaut : `gemma4:e4b` (~9.6 GB, texte + vision natif).
  - Configurable dans `Data/CONSTANTS.py` (`AI_MODEL_TEXT` / `AI_MODEL_VISION`).
  - Autres modèles disponibles : Gemma 4 26B, DeepSeek-R1 (8B/14B), Llama 3.2 Vision, LLaVA, Mistral, etc.
- **ImageMagick** *(optionnel mais recommandé pour la conversion d'images)* :
  - **Windows** : [Télécharger ImageMagick](https://imagemagick.org/script/download.php#windows)
  - **macOS** : `brew install imagemagick`
  - **Linux** : `sudo apt install imagemagick` (Debian/Ubuntu) ou `sudo dnf install ImageMagick` (Fedora)

---

## 📦 Dépendances Python

Les dépendances sont installées automatiquement par `install.sh` ou `install.bat`.  
Pour une installation manuelle :

```bash
pip install -r requirements.txt
```

**Packages requis :**
- `flet` : Interface graphique
- `Pillow` : Traitement d'images
- `Wand` : Conversion d'images (requiert ImageMagick)
- `numpy` : Calculs vectoriels (exposition, ombres, hautes lumières)
- `PyMuPDF` : Conversion de PDF en images
- `rembg` *(optionnel)* : Suppression de fond par IA (requiert `onnxruntime`)
- `onnxruntime` *(optionnel)* : Moteur d'inférence pour rembg
- `spandrel` *(optionnel)* : Super-résolution ×2/×4 et restauration visage dans Augmentation IA.py (requiert `torch`)
- `torch` *(optionnel)* : Moteur d'inférence PyTorch requis par spandrel et SAM2
- `sam2` *(optionnel)* : Sélection interactive par clics (Segment Anything Model 2) dans Augmentation IA.py
- `opencv-python` *(optionnel)* : Inpainting TELEA dans Augmentation IA.py
- `iopaint` *(optionnel)* : Inpainting LaMa / MAT dans Augmentation IA.py (`pip install iopaint`)

---

## 📂 Structure du projet

```
Dashboard-Image-Manipulation/
├── Dashboard.pyw         # Application principale
├── run.py                # Lanceur universel Python
├── run.sh                # Lanceur Linux/macOS
├── run.bat               # Lanceur Windows
├── install.sh            # Installation Linux/macOS
├── install.bat           # Installation Windows
├── mount_kiosks.sh       # Montage des partages kiosques (macOS)
├── requirements.txt      # Dépendances Python
├── README.md             # Ce fichier
└── Data/                 # Applications et ressources
   ├── watermark.png     # Filigrane utilisé par certaines apps
   ├── 2 en 1.py
   ├── Ameliorer nettete.py
   ├── Augmentation IA.py
   ├── Changer version.py
   ├── Comparaison.pyw
   ├── Conversion JPG.py
   ├── Copier NEFs sélection.py
   ├── Copyright.py
   ├── Fichiers manquants.py
   ├── Fit 203.py
   ├── Format 13x15.py
   ├── Images en PDF.py
   ├── Kiosk droite.py
   ├── Kiosk gauche.py
   ├── kiosk_flet.pyw
   ├── N&B.py
   ├── Nettoyer anciens fichiers.py
   ├── Nettoyer metadonnees.py
   ├── Projet.py
   ├── Recadrage.pyw
   ├── Redimensionner filigrane.py
   ├── Redimensionner.py
   ├── Remerciements.py
   ├── Renommer sequence.py
   ├── Séparer RAW et JPG.py
   ├── SidePanel.pyw
   └── Transfert vers TEMP.py
```

---

## 🎯 Fonctionnalités

- **Assistant IA local** : conversation avec `/ai` dans la barre de commande, analyse d'images via Ollama (100 % local, aucune donnée envoyée sur Internet)
- **Interface graphique moderne** avec Flet
- **Navigation dans les dossiers** avec prévisualisation et **tri A-Z / Z-A / Date**
- **Visionneuse plein écran** : affichage plein écran avec navigation clavier, sélection et suppression depuis la visionneuse
- **Pagination** : affichage par tranches de 100 fichiers avec boutons Précédent / Suivant et indicateur de position (pour les dossiers volumineux)
- **Décompression ZIP** : cliquer sur un fichier `.zip` l'extrait automatiquement dans son dossier courant (détection de racine unique)
- **Lancement rapide d'applications** de traitement d'images
- **Gestion des fichiers** (sélection, suppression, ouverture, création de dossiers, copier/coller...)
- **Mise à jour Git intégrée** depuis le bouton de l'interface
- **Nettoyage automatique** des fichiers de plus de 60 jours dans des dossiers prédéfinis
- **Support multi-plateforme** (Windows, macOS, Linux)
- **Applications portables** : les apps sont lancées directement depuis le dossier du projet

---

## 🔧 Utilisation

1. Lancez le Dashboard avec `run.bat` (Windows) ou `./run.sh` (Linux/macOS)
2. Sélectionnez un dossier contenant vos images avec le bouton **Parcourir**
3. Vous pouvez soit selectionner les images a utiliser, soit ne rien selectionner, auquel cas, tous les fichiers image du dossiers seront utilisés
4. Cliquez sur une application dans la liste pour la lancer
5. L'application est lancée directement depuis le dossier du projet avec le dossier sélectionné comme contexte

---

## 📝 Applications disponibles

| Nom affiché (Dashboard) | Script | Description |
|-------------------------|--------|-------------|
| Augmentation IA | `Augmentation IA.py` | Super-résolution ×2/×4, restauration de visage par IA, **suppression de fond (rembg)**, **sélection interactive SAM2** (clics positifs/négatifs), **inpainting** (TELEA, LaMa, MAT via IOPaint), slider morphologique érosion/dilatation du masque |
| 2 en 1 | `2 en 1.py` | Assemble deux photos portrait côte à côte sur une seule image JPEG prête à imprimer |
| Améliorer la netteté | `Ameliorer nettete.py` | Améliore la netteté des images |
| Changer version | `Changer version.py` | Met à jour `__version__` dans Dashboard.pyw et tous les scripts de Data/ |
| Comparaison | `Comparaison.pyw` | Comparaison côte à côte de deux lots d'images avec visionneuses synchronisées |
| Conversion en JPG | `Conversion JPG.py` | Convertit les images (et les fichiers PDF !) en JPG |
| Copier NEFs sélection | `Copier NEFs sélection.py` | Trie les fichiers RAW : déplace ceux qui ne correspondent pas aux photos sélectionnées |
| Copyright | `Copyright.py` | Applique un filigrane de copyright (date et données EXIF) sur les images sélectionnées |
| Fichiers manquants | `Fichiers manquants.py` | Détecte les fichiers manquants |
| Fit 203 | `Fit 203.py` | Recadre et positionne des images au format portrait sur un canvas 13×20 cm |
| Format 13x15 | `Format 13x15.py` | Recadre en format 13x15 cm |
| Images en PDF | `Images en PDF.py` | Génère un PDF à partir d'images |
| Kiosk droite | `Kiosk droite.py` | Organise les fichiers kiosque droite |
| Kiosk gauche | `Kiosk gauche.py` | Organise les fichiers kiosque gauche |
| Kiosk Flet | `kiosk_flet.pyw` | Application kiosque de sélection d'impressions photo avec interface Flet plein écran |
| Noir et blanc | `N&B.py` | Conversion noir et blanc |
| Nettoyer anciens fichiers | `Nettoyer anciens fichiers.py` | Supprime les fichiers vieux de plus de 60 jours dans les dossiers KIOSK et TEMP |
| Nettoyer les métadonnées | `Nettoyer metadonnees.py` | Supprime les métadonnées EXIF |
| Projet | `Projet.py` | Génère des miniatures de projet avec filigrane semi-transparent |
| Recadrage | `Recadrage.pyw` | Recadrage interactif avec 16 formats d'impression (ID, 10x15, 13x18, 20x30…), mode batch, zoom/pan/rotation, 2 en 1, planches ID x2/x4, formats multiples par image, exemplaires, noir et blanc, netteté, grille des tiers, suppression de fond par IA (rembg) ; **interface repensée** avec sections colorées (Géométrie / Luminosité / Couleur / Netteté), **balance des blancs** et **histogramme** |
| Redimensionner | `Redimensionner.py` | Redimensionne les images (taille paramétrable) |
| Redimensionner + filigrane | `Redimensionner filigrane.py` | Redimensionne avec filigrane (taille paramétrable) |
| Remerciements | `Remerciements.py` | Génère des cartes de remerciement |
| Renommer en séquence | `Renommer sequence.py` | Renomme en séquence numérotée |
| Séparer RAW et JPG | `Séparer RAW et JPG.py` | Sépare les fichiers RAW et JPG d'un dossier dans des sous-dossiers dédiés |
| SidePanel | `SidePanel.pyw` | App compacte avec onglets pour gestion de fichiers, sélection et listes JSON |
| Transfert vers TEMP | `Transfert vers TEMP.py` | Envoie des fichiers vers un dossier TEMP prédéfini |

---

## 🛠️ Distribution portable

Pour distribuer l'application sur une autre machine :

1. **Compresser le dossier complet** en ZIP :
   ```
   Dashboard-Image-Manipulation.zip
   ```

2. **Décompresser sur la machine cible**

   ⚠️ Si vous voulez utiliser `update.bat` / `update.sh`, copiez aussi le dossier caché `.git`
   (ou faites un `git clone` sur la machine cible).

3. **Lancer l'installation** :
   - Windows : double-clic sur `install.bat`
   - Linux/macOS : `./install.sh` dans un terminal

4. **Lancer l'application** :
   - Windows : double-clic sur `run.bat`
   - Linux/macOS : `./run.sh`

---

## ⚠️ Dépannage

### "Python n'est pas reconnu..."
→ Python n'est pas installé ou pas dans le PATH  
→ Réinstallez Python en cochant "Add Python to PATH"

### "ImportError: No module named 'flet'"
→ Les dépendances ne sont pas installées  
→ Lancez `install.bat` (Windows) ou `./install.sh` (Linux/macOS)

### "ImageMagick introuvable"
→ ImageMagick n'est pas installé (optionnel)  
→ Les apps de conversion JPG peuvent ne pas fonctionner  
→ Installez ImageMagick depuis les liens ci-dessus

### Les scripts .sh ne se lancent pas (Linux/macOS)
→ Rendez-les exécutables :
```bash
chmod +x install.sh run.sh update.sh
```

### "[ERREUR] Mauvais depot distant configure" avec update
→ Le remote `origin` ne correspond pas au dépôt attendu
→ Vérifiez avec `git remote -v` puis corrigez si besoin

---

## 📄 Licence

Ce projet est sous licence libre. Vous pouvez l'utiliser, le modifier et le distribuer librement.

---

## 👤 Auteur

Créé avec ❤️ pour simplifier le traitement d'images en lots.
