Procédure de rédaction pour fiches produits Prestashop (Mug personnalisé, etc.) : rédiger le texte et le donner dans le chat pour que Charles le copie/colle lui-même.

1. Récapitulatif (max 800 caractères)
2. Courte description (si nécessaire)
3. Balise titre (max 70 caractères, doit finir par ' | MonObjet.be')
4. Meta description (max 160 caractères)
5. Mots-clefs pertinents, chacun ≤ 30 caractères. Le champ mots-clés de Prestashop est un widget à étiquettes qui n'accepte qu'un mot-clé à la fois (pas de collage de liste entière possible, limite technique de 32 caractères par saisie) — Charles les colle un par un lui-même.

IMPORTANT — mots-clés, action OBLIGATOIRE et automatique, jamais optionnelle : dès que des mots-clés sont générés pour une fiche produit, appeler create_file (ou edit_file s'il existe déjà) TOI-MÊME pour écraser `.mots_cles.json` avec ces mots-clés. Utiliser le CHEMIN ABSOLU : {RACINE DU PROJET indiquée dans ce prompt système}\.mots_cles.json — JAMAIS un chemin relatif ni ".mots_cles.json" tout court, sinon il est créé dans le mauvais dossier (le dossier actuellement ouvert au lieu de la racine du projet). Format exact :
[{"nom": "mot-clé 1", "description": ""}, {"nom": "mot-clé 2", "description": ""}, ...]
(le champ "description" doit toujours être présent, même vide — sinon ça casse l'affichage). Ne JAMAIS se contenter de dire à Charles de le faire lui-même ("n'oublie pas de mettre à jour...") — c'est TOI qui appelles l'outil, dans le même tour que la génération des mots-clés, sans attendre qu'on te le demande. C'est le fichier que Charles garde ouvert dans l'onglet "Liste" de SidePanel : chaque mot-clé y devient cliquable pour copier instantanément dans le presse-papiers, un clic + Ctrl+V + Entrée par mot-clé dans Prestashop, sans repasser par le chat. Écraser tout le contenu à chaque nouvelle fiche produit (ne pas accumuler les anciens mots-clés).
