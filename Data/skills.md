Procédure de rédaction pour fiches produits Prestashop (Mug personnalisé, etc.) : rédiger le texte et le donner dans le chat pour que Charles le copie/colle lui-même.

1. Récapitulatif (max 800 caractères)
2. Courte description (si nécessaire)
3. Balise titre (max 70 caractères, doit finir par ' | MonObjet.be')
4. Meta description (max 160 caractères)
5. Mots-clefs pertinents, chacun ≤ 30 caractères. Le champ mots-clés de Prestashop est un widget à étiquettes qui n'accepte qu'un mot-clé à la fois (pas de collage de liste entière possible, limite technique de 32 caractères par saisie) — Charles les colle un par un lui-même.

IMPORTANT — mots-clés, action OBLIGATOIRE et automatique, jamais optionnelle : dès que des mots-clés sont générés pour une fiche produit, appeler create_file (ou edit_file s'il existe déjà) TOI-MÊME pour écraser `.mots_cles.json` avec ces mots-clés. Utiliser le CHEMIN ABSOLU : {RACINE DU PROJET indiquée dans ce prompt système}\.mots_cles.json — JAMAIS un chemin relatif ni ".mots_cles.json" tout court, sinon il est créé dans le mauvais dossier (le dossier actuellement ouvert au lieu de la racine du projet). Format exact :
[{"nom": "mot-clé 1", "description": ""}, {"nom": "mot-clé 2", "description": ""}, ...]
(le champ "description" doit toujours être présent, même vide — sinon ça casse l'affichage). Ne JAMAIS se contenter de dire à Charles de le faire lui-même ("n'oublie pas de mettre à jour...") — c'est TOI qui appelles l'outil, dans le même tour que la génération des mots-clés, sans attendre qu'on te le demande. C'est le fichier que Charles garde ouvert dans l'onglet "Liste" de SidePanel : chaque mot-clé y devient cliquable pour copier instantanément dans le presse-papiers, un clic + Ctrl+V + Entrée par mot-clé dans Prestashop, sans repasser par le chat. Écraser tout le contenu à chaque nouvelle fiche produit (ne pas accumuler les anciens mots-clés).

§

CATALOGUE DES SCRIPTS DE TRAITEMENT (Data/*.py) — les utiliser AVANT de réécrire du Pillow/OpenCV à la main. Ce sont les mêmes traitements que les boutons du Dashboard. Chacun est un script headless : il lit son dossier et ses paramètres dans des variables d'ENVIRONNEMENT, traite, puis quitte. Invocation via run_terminal_command (chemin absolu obligatoire — {RACINE DU PROJET indiquée dans ce prompt système}/Data/) :

  FOLDER_PATH="/chemin/dossier" SELECTED_FILES="a.jpg|b.jpg" python3 "{RACINE}/Data/Redimensionner.py"

Contrat commun à presque tous :
- FOLDER_PATH : dossier à traiter (obligatoire). Par défaut, prends le DOSSIER ACTUELLEMENT OUVERT.
- SELECTED_FILES : basenames séparés par '|' (ex. "img1.jpg|img2.jpg"). Absent ou vide = tout le dossier. Si des FICHIERS SÉLECTIONNÉS DANS L'INTERFACE existent, les passer ici.

Scripts sans paramètre supplémentaire (juste FOLDER_PATH + SELECTED_FILES) :
- N&B.py — conversion noir et blanc en lot.
- Débruiter.py — réduction de bruit (OpenCV NLM).
- Améliorer netteté.py — accentuation de la netteté.
- Images en PDF.py — assemble les images en un seul PDF.
- Nettoyer metadonnées.py — supprime les EXIF.

Scripts avec paramètres (env vars en plus) :
- Conversion JPG.py — convertit PNG/TIFF/BMP… vers JPG ou PNG ; CONVERT_FORMAT=jpg|png (défaut jpg).
- Redimensionner.py — RESIZE_SIZE=<px> (dimension max, défaut 640) ; RESIZE_QUALITY=<0-100> (qualité JPEG, défaut 100).
- Renommer séquence.py — SERIES_NAME="<préfixe>" (renommage numéroté en séquence).
- 2 en 1.py — TWO_IN_ONE_WIDTH=<mm> TWO_IN_ONE_HEIGHT=<mm> (défaut 76×102 mm ; la largeur est doublée pour poser 2 tirages côte à côte).
- Recadrage automatique.py — FORCE_CROP_SIZE="LxH" (mm) OU FORCE_CROP_WIDTH/FORCE_CROP_HEIGHT ; FORCE_CROP_FIT=1 (fit, bords blancs) ou 0 (crop) ; FORCE_CROP_SCOPE="selected"|"folder" ; FORCE_CROP_WHITE_BORDER=1/0.

GUI à interaction (NE PAS tenter de piloter en headless — les lancer ouvre une fenêtre que Charles utilise lui-même) : Séparer RAW et JPG.py, Fichiers identiques.py, Fichiers manquants.py, Augmentation IA.py, Transfert vers TEMP.py.

Après lancement d'un script, vérifier son code de sortie et son stdout/stderr pour confirmer le succès avant d'annoncer à Charles que c'est fait.
