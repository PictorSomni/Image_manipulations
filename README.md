# 📸 Dashboard Image Manipulation

Application de gestion et manipulation d'images avec interface graphique.  
Compatible **Windows**, **macOS** et **Linux**.

![Dashboard](screenshots/dashboard01.jpg)
![Recadrage](screenshots/dashboard02.jpg)
![Selecteur](screenshots/dashboard03.jpg)
![Augmentation IA](screenshots/dashboard04.jpg)
![Kiosk](screenshots/dashboard05.jpg)

---

## ✨ Résumé utilisateur

Dashboard est un poste de travail tout-en-un pour trier, préparer, retoucher et exporter des photos en série, sans quitter la même interface.

### Ce que vous pouvez faire au quotidien

- **Parcourir et trier rapidement vos dossiers** : navigation, recherche, tri A→Z / Z→A / date, pagination des gros volumes, zipper/dézipper une sélection de fichiers.
- **Prévisualiser et sélectionner vos images** : sélection multiple, inversion, filtrage sur la sélection, suppression, création de dossiers, copier/couper/coller.
- **Ouvrir les images en plein écran** : navigation clavier, rotation, suppression directe depuis la visionneuse.
- **Lancer les outils de production en un clic** : recadrage, redimensionnement, conversion JPG, 2-en-1, PDF, noir et blanc, netteté, métadonnées, tri RAW/JPG, etc.
- **Utiliser des apps connexes intégrées** : Side Panel (utilitaires de fichiers/listes), Comparaison (deux dossiers côte à côte), Kiosk (flux d'impression).
- **Utiliser l'IA locale pour accélérer le tri et l'analyse** : chat, analyse d'images, sélection assistée, organisation de fichiers, lecture de documents.
- **Prendre des notes et ajuster les options sans sortir de l'app** : bloc-notes intégré, édition rapide options de l'app via la commande "/option", terminal intégré.

### Points forts

- **Pensé pour le volume** : traitement par lots, automatisations et scripts spécialisés photo.
- **Confort d'utilisation** : raccourcis clavier, actions contextuelles, interface unique pour éviter les allers-retours.
- **Multi-plateforme** : Windows, macOS et Linux.
- **Local-first** : vos images restent sur votre machine. Possibilité d'utiliser une IA locale comme Gemma via Ollama.

### Exemples de flux simples

1. Ouvrir un dossier client → sélectionner les meilleures images → lancer Recadrage ou Redimensionner.
2. Séparer RAW/JPG → copier les NEF liés à la sélection → exporter en JPG/PDF.
3. Ouvrir Comparaison pour deux dossiers → valider → finaliser dans Kiosk.

#### Dashboard (global)

- Ctrl/Cmd + Up : agrandir ou reduire la zone basse.
- Ctrl/Cmd + Down : basculer entre Terminal et IA + Notes.
- Esc : revenir au mode Terminal depuis IA/Notes.

#### Gestion de fichiers

- Ctrl/Cmd + A : selectionner/deselectionner tout.
- Ctrl/Cmd + I : inverser la selection.
- Ctrl/Cmd + C : copier la selection.
- Ctrl/Cmd + X : couper la selection.
- Ctrl/Cmd + V : coller dans le dossier courant.
- Ctrl/Cmd + N : creer un nouveau dossier.
- Ctrl/Cmd + R : rafraichir la previsualisation.
- Ctrl/Cmd + D : selectionner tous les fichiers de la meme date que le fichier de reference selectionne.
- Delete / Backspace : supprimer la selection.

#### IA et Notes

- Ctrl/Cmd + flèche de gauche : IA seule en mode colonne (preview a droite, quand IA/Notes est ouvert).
- Ctrl/Cmd + flèche de droite : bloc-notes seul en mode colonne (preview a droite, quand IA/Notes est ouvert).
- Ctrl/Cmd + Shift + flèche de gauche : IA en plein ecran reel (moins la barre du haut).
- Ctrl/Cmd + Shift + flèche de droite : bloc-notes en plein ecran reel (moins la barre du haut).

#### Visionneuse plein ecran

- flèche de gauche / flèche de droite : image precedente/suivante.
- [ / ] : rotation gauche/droite.
- Delete / Backspace : supprimer l'image courante.
- Esc : fermer la visionneuse.

## Installation rapide

### Windows

1. Installer Python 3.12+ : https://www.python.org/downloads/
2. Ouvrir le dossier du projet.
3. Double-cliquer sur `install.bat`.
4. Quand l'installation est terminee, lancer `run.bat`.

### macOS / Linux

1. Installer Python 3.12+ : https://www.python.org/downloads/
2. Ouvrir un terminal a la racine du projet.
3. Rendre les scripts executables (une seule fois) :

```bash
chmod +x install.sh run.sh
```

4. Lancer l'installation :

```bash
./install.sh
```

5. Quand l'installation est terminee, lancer :

```bash
./run.sh
```

## Important

- Les scripts `install.bat` et `install.sh` installent automatiquement les dependances Python.
- Les scripts verifient aussi ImageMagick et Ollama, puis affichent quoi faire si besoin.
- Suivre les messages affiches pendant l'installation suffit dans la grande majorite des cas.

## Utilisation de base

1. Ouvrir Dashboard.
2. Choisir un dossier avec `Parcourir`.
3. Selectionner les images a traiter.
4. Lancer l'application voulue depuis la grille (ou outils rapides).
5. Suivre les logs dans le terminal integre.

## Mise a jour

### Windows

```cmd
update.bat
```

### macOS / Linux

```bash
./update.sh
```

## Depannage rapide

### Python non detecte

Reinstaller Python depuis https://www.python.org/downloads/ et verifier l'ajout au PATH.

### Erreur module manquant

Relancer simplement le script d'installation (`install.bat` ou `./install.sh`).

Si le script affiche une action manuelle (ex: ImageMagick ou Ollama), suivre exactement l'instruction proposee, puis relancer le script.
