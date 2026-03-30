# -*- coding: utf-8 -*-
"""
Tableau de bord principal de l'application Image Manipulations.

Ce module fournit une interface graphique Flet permettant de :
  - Sélectionner un dossier de travail et parcourir son contenu
    dans un panneau de prévisualisation avec chargement paresseux des miniatures.
  - Lancer les scripts de traitement d'images du répertoire ``Data/``
    en tant que sous-processus Python isolés, avec injection automatique des
    variables d'environnement requises (``FOLDER_PATH``, ``DATA_PATH``, etc.).
  - Afficher la sortie standard / erreur de chaque script dans un terminal
    intégré mis à jour en temps réel.
  - Effectuer des opérations sur fichiers : sélection par checkbox, copier/
    coller, suppression avec confirmation, création de dossier.

Raccourcis clavier :
  Ctrl/Cmd+C  — copier les fichiers sélectionnés dans le presse-papiers interne.
  Ctrl/Cmd+V  — coller dans le dossier actuel.
  Ctrl/Cmd+N  — créer un nouveau dossier.

Dépendances :
  flet >= 0.80, modules standard (os, subprocess, sys, platform, shutil,
  threading, re, zipfile, time).
"""

__version__ = "1.9.4"

#############################################################
#                          IMPORTS                          #
#############################################################
import flet as ft
import os
import subprocess
import sys
import platform
import shutil
import threading
import re
import zipfile
import time
import json

#############################################################
#                           MAIN                            #
#############################################################
def main(page: ft.Page):
    """
    Point d'entrée Flet du Dashboard.

    Configure la fenêtre principale (titre, thème, dimensions, barre de titre
    personnalisée), initialise toutes les variables d'état, enregistre les
    canaux PubSub et construit l'interface avec trois zones :
      - Grille « Applications disponibles » (gauche).
      - Panneau de prévisualisation du contenu du dossier sélectionné (droite).
      - Terminal intégré affichant la sortie des scripts (bas).

    Parameters
    ----------
    page : ft.Page
        Objet page Flet injecté automatiquement par ``ft.run(main)``.

    ---
    PubSub (publish/subscribe) est un système de messagerie interne
    qui permet la communication thread-safe entre les threads de fond
    (scan, lecture de processus) et le thread UI de Flet :
    les threads publient des messages sur des "canaux" nommés
    (ex. "terminal", "refresh", "navigate"), et les callbacks abonnés les reçoivent
    et mettent à jour l'interface.
    ---
    """
# ===================== COLORS ===================== #
    DARK = "#222429"
    BG = "#373d4a"
    GREY = "#2C3038"
    LIGHT_GREY = "#9399A6"
    BLUE = "#45B8F5"
    VIOLET = "#B587FE"
    GREEN = "#49B76C"
    YELLOW = "#FBCD5F"
    HOVER_YELLOW = "#F9BA4E"
    ORANGE = "#FFA071"
    RED = "#F17171"
    WHITE = "#c7ccd8"

# ===================== PROPERTIES ===================== #
    page.title = "Dashboard de Projets"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG
    page.window.title_bar_hidden = True
    page.window.title_bar_buttons_hidden = True
    page.window.width = 1200
    page.window.height = 840
    # page.window.maximized = True
    
    selected_folder = {"path": None}
    current_browse_folder = {"path": None}
    cwd = os.path.dirname(os.path.abspath(__file__))
    selected_files = set()  # Ensemble des fichiers sélectionnés
    clipboard = {"files": []}  # Presse-papiers pour copier/coller des fichiers
    
    # Configuration: nom du fichier -> True si l'app est locale (pas besoin de dossier sélectionné)
    apps = {
        "N&B.py": [False, WHITE],
        "Fichiers manquants.py": [False, ORANGE],
        "Transfert vers TEMP.py": [True, BLUE],
        "Ameliorer nettete.py": [False, WHITE],
        "Renommer sequence.py": [False, BLUE],
        "Conversion JPG.py": [False, BLUE],
        "Nettoyer metadonnees.py": [False, RED],
        "Remerciements.py": [False, VIOLET],
        "Recadrage.pyw": [False, BLUE],
        "Redimensionner filigrane.py": [False, WHITE],
        "Images en PDF.py": [False, GREEN],
        "Redimensionner.py": [False, WHITE],
        "Format 13x10.py": [False, WHITE],
        "Augmentation IA.py": [False, GREEN],
        "Format 13x15.py": [False, WHITE],
    }
    
    resize_size = {"value": "640"}  # Taille par défaut pour le redimensionnement
    resize_watermark_size = {"value": "640"}  # Taille par défaut pour le redimensionnement avec watermark
    sort_by_date = {"value": False}  # False = alphabétique, True = par date de modification
    lazy_images = []  # [(list_index, file_path, image_ctrl)] pour le chargement paresseux
    PAGE_SIZE = 100             # Nb d'éléments max par page dans la prévisualisation
    preview_page = {"value": 0}  # Page courante (0-indexé)
    all_entries_data = {"list": [], "error": ""}  # Données brutes du dernier scan
    _pending_selection = {"names": None}  # Noms à sélectionner après le prochain scan
    
# ===================== UI ELEMENTS ===================== #
    folder_path = ft.TextField(
        label="Dossier sélectionné",
        hint_text="Cliquez sur Parcourir...",
        width=300,
        bgcolor=DARK,
        border_color=GREY,
        read_only=True
    )

    apps_list = ft.GridView(expand=True, runs_count=3, padding=8, spacing=8, run_spacing=8, child_aspect_ratio=1.97)
    preview_list = ft.ListView(expand=True, auto_scroll=False, spacing=4)
    preview_loading = ft.Container(
        content=ft.Row([
            ft.ProgressRing(width=16, height=16, stroke_width=2, color=BLUE),
            ft.Text("Chargement...", size=12, color=LIGHT_GREY),
        ], spacing=8, alignment=ft.MainAxisAlignment.CENTER),
        alignment=ft.Alignment(0, 0),
        expand=True,
        visible=False,
    )
    terminal_output = ft.ListView(expand=True, spacing=2, auto_scroll=True)
    file_count_text = ft.Text("", size=14, color=WHITE, text_align=ft.TextAlign.RIGHT)
    selection_count_text = ft.Text(f"", size=14, color=BLUE, text_align=ft.TextAlign.RIGHT)
    sort_switch = ft.Switch(
        label="Trier par date",
        value=False,
        label_position=ft.LabelPosition.LEFT,
        active_color=BLUE,
        tooltip="Basculer entre tri alphabétique et tri par date de modification",
    )
    prev_page_btn = ft.IconButton(
        icon=ft.Icons.CHEVRON_LEFT, icon_size=18, icon_color=DARK, bgcolor=YELLOW,
        tooltip="Page précédente", visible=False, hover_color=HOVER_YELLOW
    )
    next_page_btn = ft.IconButton(
        icon=ft.Icons.CHEVRON_RIGHT, icon_size=18, icon_color=DARK, bgcolor=YELLOW,
        tooltip="Page suivante", visible=False, hover_color=HOVER_YELLOW
    )
    page_indicator_text = ft.Text("", size=12, color=LIGHT_GREY)
    selected_files_prefix = "SELECTED_FILES:"

# ===================== METHODS ===================== #
    # ================================================================ #
    #                    PUBSUB & ÉVÉNEMENTS                           #
    # ================================================================ #
    def on_terminal_message(topic, message):
        """Callback pour les messages pubsub"""
        try:
            msg, color = message
            terminal_output.controls.append(
                ft.Text(msg, size=13, color=color, font_family="monospace")
            )
            if len(terminal_output.controls) > 200:
                terminal_output.controls.pop(0)
            page.update()
        except Exception:
            # Ignore errors if page is closing or already destroyed
            pass
    
    # S'abonner au canal terminal
    page.pubsub.subscribe_topic("terminal", on_terminal_message)
    
    def on_refresh_preview(topic, message):
        """Callback pour rafraîchir la preview depuis un thread"""
        refresh_preview(reset_page=False)
    
    # S'abonner au canal refresh
    page.pubsub.subscribe_topic("refresh", on_refresh_preview)
    
    def on_navigate_request(topic, folder_path):
        """Callback pour naviguer vers un dossier depuis un thread"""
        if folder_path and os.path.isdir(folder_path):
            navigate_to_folder(folder_path)
    
    # S'abonner au canal navigate
    page.pubsub.subscribe_topic("navigate", on_navigate_request)

    def on_select_files_request(topic, selected_names_str):
        """Callback pour sélectionner des fichiers depuis la sortie d'un script"""
        apply_selected_files_by_name(selected_names_str)

    # S'abonner au canal select-files
    page.pubsub.subscribe_topic("select_files", on_select_files_request)
    
    def request_refresh():
        """Demande un rafraîchissement de la preview (thread-safe)"""
        page.pubsub.send_all_on_topic("refresh", None)
    
    def on_keyboard_event(e: ft.KeyboardEvent):
        """Gestionnaire des événements clavier pour les raccourcis"""
        # Détection de Ctrl (Windows/Linux) ou Cmd (macOS)
        ctrl_pressed = e.ctrl or e.meta
        
        if ctrl_pressed:
            if e.key == "C":
                # Ctrl/Cmd + C : Copier les fichiers sélectionnés
                copy_selected_files(None)
            elif e.key == "V":
                # Ctrl/Cmd + V : Coller les fichiers
                paste_files(None)
            elif e.key == "N":
                # Ctrl/Cmd + N : Créer un nouveau dossier
                create_new_folder(None)
    
    # Activer la gestion des événements clavier
    page.on_keyboard_event = on_keyboard_event

    # ================================================================ #
    #                          TERMINAL                                #
    # ================================================================ #
    def log_to_terminal(message, color=WHITE):
        """Ajoute un message au terminal intégré"""
        # Supprimer les codes ANSI d'échappement (clear screen, colors, etc.)
        ansi_escape = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\[\?[0-9;]*[a-zA-Z]')
        clean_message = ansi_escape.sub('', message).strip()
        if clean_message:  # N'afficher que si le message n'est pas vide après nettoyage
            page.pubsub.send_all_on_topic("terminal", (clean_message, color))
    
    def clear_terminal(e):
        """Efface le contenu du terminal"""
        terminal_output.controls.clear()
        page.update()
    
    def copy_terminal_to_clipboard():
        """Copie tout le contenu du terminal dans le presse-papiers"""
        if not terminal_output.controls:
            page.update()
            return
        
        # Extraire le texte de chaque contrôle Text
        terminal_text = "\n".join([ctrl.value for ctrl in terminal_output.controls if hasattr(ctrl, 'value')])
        
        # Copier dans le presse-papiers en utilisant les commandes système
        try:
            if platform.system() == "Darwin":  # macOS
                process = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
                process.communicate(terminal_text.encode('utf-8'))
            elif platform.system() == "Windows":
                process = subprocess.Popen(['clip'], stdin=subprocess.PIPE)
                process.communicate(terminal_text.encode('utf-16'))
            else:  # Linux
                try:
                    process = subprocess.Popen(['xclip', '-selection', 'clipboard'], stdin=subprocess.PIPE)
                    process.communicate(terminal_text.encode('utf-8'))
                except FileNotFoundError:
                    process = subprocess.Popen(['xsel', '--clipboard', '--input'], stdin=subprocess.PIPE)
                    process.communicate(terminal_text.encode('utf-8'))
        except Exception as e:
            log_to_terminal(f"[ERREUR] Erreur lors de la copie dans le presse-papiers: {e}", RED)
        
        page.update()

    # ================================================================ #
    #                   NAVIGATION & FICHIERS                          #
    # ================================================================ #
    def open_in_file_explorer(folder_path):
        """Ouvre le dossier dans l'explorateur de fichiers natif"""
        if not folder_path or not os.path.isdir(folder_path):
            log_to_terminal("Aucun dossier sélectionné", RED)
            return
        
        try:
            if platform.system() == "Windows":
                subprocess.Popen(f'explorer "{folder_path}"')
            elif platform.system() == "Darwin":  # macOS
                subprocess.Popen(["open", folder_path])
            else:  # Linux
                subprocess.Popen(["xdg-open", folder_path])
            log_to_terminal(f"[OK] Ouverture du dossier: {os.path.basename(folder_path)}", GREEN)
        except Exception as e:
            log_to_terminal(f"[ERREUR] Erreur lors de l'ouverture de l'explorateur: {e}", RED)
    
    def open_file_with_default_app(file_path):
        """Ouvre un fichier avec l'application par défaut du système en premier plan"""
        if not file_path or not os.path.isfile(file_path):
            return
        
        try:
            if platform.system() == "Windows":
                # Utilise 'start' avec '' pour ouvrir en premier plan
                subprocess.Popen(f'start "" "{file_path}"', shell=True)
            elif platform.system() == "Darwin":  # macOS
                # -a pour activer l'application
                subprocess.Popen(["open", "-a", "Preview", file_path])
            else:  # Linux
                subprocess.Popen(["xdg-open", file_path])
        except Exception as e:
            log_to_terminal(f"[ERREUR] Erreur lors de l'ouverture du fichier: {e}", RED)
    
    def navigate_to_folder(new_path):
        """Navigue vers un dossier dans la preview"""
        if not new_path:
            return
        current_browse_folder["path"] = new_path
        selected_folder["path"] = new_path
        folder_path.value = new_path
        selected_files.clear()
        selection_count_text.value = ""
        preview_page["value"] = 0
        refresh_preview()
    
    def go_to_parent_folder(e):
        """Remonte au dossier parent"""
        if current_browse_folder["path"]:
            parent = os.path.dirname(current_browse_folder["path"])
            if parent and parent != current_browse_folder["path"]:
                navigate_to_folder(parent)
    
    def extract_zip(file_path):
        """Décompresse un .zip avec détection de dossier racine unique"""
        dest_dir = os.path.dirname(file_path)
        zip_name = os.path.splitext(os.path.basename(file_path))[0]
        
        try:
            with zipfile.ZipFile(file_path, 'r') as zf:
                names = zf.namelist()
                top_levels = {n.split('/')[0] for n in names if n}
                # Si tout le contenu est sous un seul dossier racine, extraire directement
                if len(top_levels) == 1 and any('/' in n for n in names):
                    extract_to = dest_dir
                else:
                    extract_to = os.path.join(dest_dir, zip_name)
                    os.makedirs(extract_to, exist_ok=True)

                zf.extractall(extract_to)
            log_to_terminal(f"[OK] Décompressé: {os.path.basename(file_path)}", GREEN)
            refresh_preview()
        except Exception as err:
            log_to_terminal(f"[ERREUR] Décompression: {err}", RED)

    def on_file_click(file_path, is_dir):
        """Gère le clic sur un fichier ou dossier dans la preview"""
        if is_dir:
            navigate_to_folder(file_path)
        elif os.path.splitext(file_path)[1].lower() == ".zip":
            log_to_terminal(f"Extraction: {os.path.splitext(os.path.basename(file_path))[0]}", BLUE)
            extract_zip(file_path)
        else:
            open_file_with_default_app(file_path)

    # ================================================================ #
    #                  OPÉRATIONS SUR FICHIERS                         #
    # ================================================================ #
    def delete_item(file_path):
        """Supprime un fichier ou dossier avec confirmation"""
        def confirm_delete(e):
            """
            Exécute la suppression confirmée du fichier ou dossier.

            Appelée par le bouton « Supprimer » de la boîte de dialogue
            de confirmation. Ferme la dialog et rafraîchit la preview.
            """
            try:
                if os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                else:
                    os.remove(file_path)
                dialog.open = False
                page.update()
                refresh_preview()
                log_to_terminal(f"[OK] Supprimé: {os.path.basename(file_path)}", GREEN)
            except Exception as err:
                log_to_terminal(f"[ERREUR] Erreur lors de la suppression: {err}", RED)
                dialog.open = False
                page.update()
        
        def cancel_delete(e):
            """Annule la suppression et ferme la boîte de dialogue."""
            dialog.open = False
            page.update()
        
        item_type = "dossier" if os.path.isdir(file_path) else "fichier"
        item_name = os.path.basename(file_path)
        
        dialog = ft.AlertDialog(
            title=ft.Text(f"Supprimer {item_type}?"),
            content=ft.Text(f"Voulez-vous vraiment supprimer '{item_name}'?"),
            actions=[
                ft.TextButton("Annuler", on_click=cancel_delete),
                ft.TextButton("Supprimer", on_click=confirm_delete, style=ft.ButtonStyle(color=ft.Colors.RED)),
            ],
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()
        
    def create_new_folder(e):
        """Crée un nouveau dossier dans le dossier actuel"""
        target_folder = current_browse_folder["path"] or selected_folder["path"]
        if not target_folder:
            log_to_terminal("[ERREUR] Aucun dossier sélectionné", RED)
            return
        
        def confirm_create(e):
            """
            Valide la création du nouveau dossier.

            Lit le nom saisi, crée le dossier via ``os.makedirs``,
            ferme la dialog et rafraîchit la preview.
            """
            folder_name = folder_name_input.value.strip()
            if not folder_name:
                log_to_terminal("[ERREUR] Le nom du dossier ne peut pas être vide", RED)
                return
            
            new_folder_path = os.path.join(target_folder, folder_name)
            try:
                if os.path.exists(new_folder_path):
                    log_to_terminal(f"[ERREUR] Le dossier '{folder_name}' existe déjà", RED)
                else:
                    os.makedirs(new_folder_path)
                    log_to_terminal(f"[OK] Dossier créé: {folder_name}", BLUE)
                    dialog.open = False
                    page.update()
                    refresh_preview()
            except Exception as err:
                log_to_terminal(f"[ERREUR] Erreur lors de la création du dossier: {err}", RED)
                dialog.open = False
                page.update()
        
        def cancel_create(e):
            """Annule la création du dossier et ferme la boîte de dialogue."""
            dialog.open = False
            page.update()
        
        folder_name_input = ft.TextField(
            label="Nom du dossier",
            autofocus=True,
            on_submit=confirm_create,
        )
        
        dialog = ft.AlertDialog(
            title=ft.Text("Créer un nouveau dossier"),
            content=folder_name_input,
            actions=[
                ft.TextButton("Annuler", on_click=cancel_create),
                ft.TextButton("Créer", on_click=confirm_create),
            ],
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()
    
    def copy_selected_files(e):
        """Copie les fichiers sélectionnés dans le presse-papiers"""
        if not selected_files:
            log_to_terminal("[ATTENTION] Aucun fichier sélectionné", ORANGE)
            return
        
        clipboard["files"] = list(selected_files)
        count = len(clipboard["files"])
        log_to_terminal(f"[OK] {count} élément(s) copié(s)", BLUE)
    
    def paste_files(e):
        """Colle les fichiers du presse-papiers dans le dossier actuel"""
        target_folder = current_browse_folder["path"] or selected_folder["path"]
        if not target_folder:
            log_to_terminal("[ERREUR] Aucun dossier de destination sélectionné", RED)
            return
        
        if not clipboard["files"]:
            log_to_terminal("[ATTENTION] Presse-papiers vide", ORANGE)
            return
        
        copied_count = 0
        errors = []
        
        for source_path in clipboard["files"]:
            if not os.path.exists(source_path):
                errors.append(f"{os.path.basename(source_path)}: fichier source introuvable")
                continue
            
            dest_path = os.path.join(target_folder, os.path.basename(source_path))
            
            # Si le fichier existe déjà, ajouter un suffixe
            if os.path.exists(dest_path):
                base_name = os.path.basename(source_path)
                name, ext = os.path.splitext(base_name)
                counter = 1
                while os.path.exists(dest_path):
                    new_name = f"{name} ({counter}){ext}"
                    dest_path = os.path.join(target_folder, new_name)
                    counter += 1
            
            try:
                if os.path.isdir(source_path):
                    shutil.copytree(source_path, dest_path)
                else:
                    shutil.copy2(source_path, dest_path)
                copied_count += 1
            except Exception as err:
                errors.append(f"{os.path.basename(source_path)}: {err}")
        
        if copied_count > 0:
            log_to_terminal(f"[OK] {copied_count} élément(s) collé(s)", BLUE)
        
        if errors:
            for error in errors:
                log_to_terminal(f"[ERREUR] {error}", RED)
        
        refresh_preview()

    # ================================================================ #
    #                          SÉLECTION                               #
    # ================================================================ #
    def on_checkbox_change(e, file_path):
        """Gère le changement d'état d'une checkbox"""
        if e.control.value:
            selected_files.add(file_path)
        else:
            selected_files.discard(file_path)
        selection_count_text.value = f"{len(selected_files)} fichier{'s' if len(selected_files) > 1 else ''} sélectionné{'s' if len(selected_files) > 1 else ''}" if len(selected_files) > 0 else ""
        page.update()
    
    def clear_selection(e):
        """Désélectionne tous les fichiers et dossiers"""
        selected_files.clear()
        refresh_preview()
        selection_count_text.value = f"{len(selected_files)} fichier{'s' if len(selected_files) > 1 else ''} sélectionné{'s' if len(selected_files) > 1 else ''}" if len(selected_files) > 0 else ""
        page.update()
        log_to_terminal("[OK] Sélection effacée", GREEN)
    
    def delete_selected_files(e):
        """Supprime tous les fichiers et dossiers sélectionnés avec confirmation"""
        if not selected_files:
            log_to_terminal("[ATTENTION] Aucun élément sélectionné", ORANGE)
            return
        
        def confirm_delete_multiple(e):
            """
            Supprime tous les éléments sélectionnés après confirmation.

            Itère sur ``selected_files``, supprime fichiers et dossiers,
            reporte le nombre de suppressions réussies dans le terminal.
            """
            deleted_files = 0
            deleted_folders = 0
            errors = []
            for item_path in list(selected_files):
                try:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                        deleted_folders += 1
                    elif os.path.isfile(item_path):
                        os.remove(item_path)
                        deleted_files += 1
                except Exception as err:
                    errors.append(f"{os.path.basename(item_path)}: {err}")
            
            selected_files.clear()
            dialog.open = False
            page.update()
            refresh_preview()
            
            if deleted_files > 0 or deleted_folders > 0:
                msg_parts = []
                if deleted_files > 0:
                    msg_parts.append(f"{deleted_files} fichier(s)")
                if deleted_folders > 0:
                    msg_parts.append(f"{deleted_folders} dossier(s)")
                log_to_terminal(f"[OK] Supprimé: {' et '.join(msg_parts)}", GREEN)
            if errors:
                for error in errors:
                    log_to_terminal(f"[ERREUR] {error}", RED)
        
        def cancel_delete_multiple(e):
            """Annule la suppression multiple et ferme la boîte de dialogue."""
            dialog.open = False
            page.update()
        
        item_count = len(selected_files)
        
        dialog = ft.AlertDialog(
            title=ft.Text(f"Supprimer {item_count} élément(s)?"),
            content=ft.Text(f"Voulez-vous vraiment supprimer les {item_count} élément(s) sélectionné(s)?"),
            actions=[
                ft.TextButton("Annuler", on_click=cancel_delete_multiple),
                ft.TextButton("Supprimer", on_click=confirm_delete_multiple, style=ft.ButtonStyle(color=ft.Colors.RED)),
            ],
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def apply_selected_files_by_name(selected_names_str):
        """Sélectionne dans la preview les éléments correspondant aux noms fournis"""
        folder_to_display = current_browse_folder["path"] or selected_folder["path"]
        if not folder_to_display or not os.path.isdir(folder_to_display):
            return

        names = [name for name in selected_names_str.split("|") if name]
        names_set = set(names)

        selected_files.clear()
        # Utilise all_entries_data pour garantir que les chemins dans selected_files
        # sont identiques (même objet str) à ceux utilisés par _render_current_page(),
        # évitant toute divergence de normalisation Unicode NFD/NFC sur macOS.
        entries = all_entries_data["list"]
        if names_set and entries:
            for file_name, file_path, is_dir, is_image, ext in entries:
                if file_name in names_set:
                    selected_files.add(file_path)
        elif names_set:
            # Fallback si entries pas encore peuplées
            for item_name in os.listdir(folder_to_display):
                if item_name in names_set:
                    selected_files.add(os.path.join(folder_to_display, item_name))

        selection_count_text.value = f"{len(selected_files)} fichier{'s' if len(selected_files) > 1 else ''} sélectionné{'s' if len(selected_files) > 1 else ''}" if len(selected_files) > 0 else ""

        # Naviguer vers la première page contenant au moins un fichier sélectionné
        # (évite que les fichiers au-delà de PAGE_SIZE soient invisibles)
        if selected_files and entries:
            for idx, (file, file_path, is_dir, is_image, ext) in enumerate(entries):
                if file_path in selected_files:
                    preview_page["value"] = idx // PAGE_SIZE
                    break

        # Re-rendu immédiat sans nouveau scan (le script ne modifie aucun fichier)
        _render_current_page()

        if names_set and not selected_files:
            log_to_terminal("[ATTENTION] Aucun fichier correspondant trouvé dans la preview", ORANGE)

    # ================================================================ #
    #                           PREVIEW                                #
    # ================================================================ #
    ITEM_HEIGHT = 44  # hauteur approx. d'un ListTile dense avec thumbnail 40px
    _refresh_token = {"v": 0}  # incrémenté à chaque refresh pour annuler les anciens threads

    def _set_visible_images(scroll_pixels, viewport_height, do_update=True):
        """Applique src aux images dans la zone visible + buffer."""
        buffer_px = 3 * ITEM_HEIGHT
        for (list_idx, file_path, image_ctrl) in lazy_images:
            item_top = list_idx * ITEM_HEIGHT
            if item_top < scroll_pixels + viewport_height + buffer_px and (item_top + ITEM_HEIGHT) > scroll_pixels - buffer_px:
                if image_ctrl.src is None:
                    image_ctrl.src = file_path
                    if do_update:
                        image_ctrl.update()

    def on_preview_scroll(e):
        """Déclenche le chargement paresseux des miniatures lors du défilement de la liste."""
        _set_visible_images(e.pixels, e.viewport_dimension)

    def _render_current_page():
        """
        Construit et affiche les contrôles ListView pour la page courante.
        Appelée depuis on_preview_ready et go_to_page (thread UI uniquement).
        Toutes les miniatures de la page sont chargées immédiatement (pas de lazy loading).
        """
        try:
            entries = all_entries_data["list"]
            total = len(entries)
            total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            current_pg = min(preview_page["value"], total_pages - 1)
            preview_page["value"] = current_pg

            new_controls = []

            if all_entries_data["error"]:
                new_controls.append(ft.Text(all_entries_data["error"], color="red"))
            elif not entries:
                folder_to_display = current_browse_folder["path"] or selected_folder["path"]
                if folder_to_display:
                    new_controls.append(ft.Text("(dossier vide)", color=GREY))
            else:
                start = current_pg * PAGE_SIZE
                end = min(start + PAGE_SIZE, total)
                for list_idx, (file, file_path, is_dir, is_image, ext) in enumerate(entries[start:end]):
                    if is_dir:
                        icon = ft.Icons.FOLDER
                        icon_color = ft.Colors.AMBER_400
                    elif is_image:
                        icon = ft.Icons.IMAGE
                        icon_color = ft.Colors.GREEN_400
                    elif ext in [".pdf"]:
                        icon = ft.Icons.PICTURE_AS_PDF
                        icon_color = ft.Colors.RED_400
                    elif ext == ".zip":
                        icon = ft.Icons.FOLDER_ZIP
                        icon_color = ORANGE
                    elif ext in [".txt", ".md", ".log"]:
                        icon = ft.Icons.DESCRIPTION
                        icon_color = ft.Colors.BLUE_GREY_400
                    elif ext in [".af", ".afphoto", ".afdesign", ".afpub", ".psd", ".psb", ".svg", ".eps", ".ai"]:
                        icon = ft.Icons.ADOBE
                        icon_color = GREEN
                    else:
                        icon = ft.Icons.INSERT_DRIVE_FILE
                        icon_color = ft.Colors.BLUE_GREY_400

                    checkbox = ft.Checkbox(
                        border_side=ft.BorderSide(color=BLUE),
                        value=file_path in selected_files,
                        on_change=lambda e, path=file_path: on_checkbox_change(e, path),
                    )

                    if is_image:
                        visual = ft.Container(
                            content=ft.Image(src=file_path, fit=ft.BoxFit.COVER, error_content=ft.Icon(icon, color=icon_color, size=18)),
                            width=40, height=40,
                            border_radius=4, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                        )
                    else:
                        visual = ft.Icon(icon, color=icon_color, size=18)

                    new_controls.append(
                        ft.ListTile(
                            leading=ft.Row([checkbox, visual], spacing=8, tight=True),
                            title=ft.Text(file, size=12, color=WHITE),
                            trailing=ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE, icon_size=16,
                                icon_color=ft.Colors.RED_300, tooltip="Supprimer",
                                on_click=lambda e, path=file_path: delete_item(path),
                            ),
                            on_click=lambda e, path=file_path, d=is_dir: on_file_click(path, d),
                            hover_color=GREY, dense=True,
                            content_padding=ft.Padding(left=5, top=0, right=5, bottom=0),
                        )
                    )

            preview_list.controls.clear()
            preview_list.controls.extend(new_controls)
            preview_list.on_scroll = None
            preview_loading.visible = False

            # Contrôles de pagination
            if total > PAGE_SIZE:
                prev_page_btn.visible = current_pg > 0
                next_page_btn.visible = current_pg < total_pages - 1
                page_indicator_text.value = f"{current_pg * PAGE_SIZE + 1}-{min((current_pg + 1) * PAGE_SIZE, total)}/{total}"
            else:
                prev_page_btn.visible = False
                next_page_btn.visible = False
                page_indicator_text.value = ""

            page.update()
        except Exception as ex:
            log_to_terminal(f"[ERREUR] Rendu preview: {ex}", RED)

    def on_preview_ready(topic, payload):
        """Reçoit les données brutes du thread bg et déclenche le rendu de la page courante."""
        token, entries_data, new_file_count_text, error_text = payload
        if _refresh_token["v"] != token:
            return
        all_entries_data["list"] = entries_data
        all_entries_data["error"] = error_text
        file_count_text.value = new_file_count_text
        # Appliquer la sélection en attente si un script l'a demandé
        # (ex: Fichiers manquants). On le fait ICI avec les données fraîches
        # pour éviter tout race condition entre threads.
        if _pending_selection["names"] is not None:
            names_to_apply = _pending_selection["names"]
            _pending_selection["names"] = None
            apply_selected_files_by_name(names_to_apply)
        else:
            _render_current_page()

    page.pubsub.subscribe_topic("preview_ready", on_preview_ready)
    def refresh_preview(reset_page=True):
        """
        Déclenche un rafraîchissement asynchrone du panneau de prévisualisation.

        Incrémente le jeton de rafraîchissement (annulant tout rafraîchissement
        précédent en cours), vide la liste courante, affiche un indicateur de
        chargement, puis lance un thread de fond ``_bg()`` qui scanne le dossier
        courant et envoie les nouveaux contrôles via PubSub.

        Parameters
        ----------
        reset_page : bool
            Si True (défaut), revient à la page 0. Si False, conserve la page courante.
        """
        if reset_page:
            preview_page["value"] = 0
        _refresh_token["v"] += 1
        my_token = _refresh_token["v"]
        preview_list.on_scroll = None
        preview_list.controls.clear()
        lazy_images.clear()
        file_count_text.value = ""
        folder_to_display = current_browse_folder["path"] or selected_folder["path"]
        preview_loading.visible = bool(folder_to_display)
        page.update()

        def _bg():
            """
            Thread de fond : scanne le dossier et stocke des tuples de données brutes.

            Ne crée aucun widget Flet — la construction des contrôles est déléguée
            à _render_current_page() (thread UI), ce qui évite de sérialiser des
            centaines de widgets en un seul page.update().
            """
            entries_data = []
            new_file_count_text = ""
            error_text = ""

            # Fichiers système à ignorer (macOS, Windows, Linux)
            OS_JUNK = {
                ".ds_store", "thumbs.db", "thumbs.db:encryptable",
                "ehthumbs.db", "ehthumbs_vista.db", "desktop.ini",
                ".directory", ".spotlight-v100", ".trashes",
            }

            def _is_os_junk(entry):
                name_lower = entry.name.lower()
                return (
                    name_lower in OS_JUNK
                    or name_lower.startswith("._")
                    or entry.name == "$RECYCLE.BIN"
                    or (entry.name.startswith(".Trash-") and entry.is_dir())
                )

            if folder_to_display:
                try:
                    with os.scandir(folder_to_display) as it:
                        raw = [e for e in it if not _is_os_junk(e)]

                    file_count = sum(1 for e in raw if not e.name.startswith(".") and not e.is_dir())
                    new_file_count_text = f"({file_count} fichier{'s' if file_count > 1 else ''})"

                    if raw:
                        if sort_by_date["value"]:
                            sorted_entries = sorted(raw, key=lambda e: (not e.is_dir(), -e.stat().st_mtime))
                        else:
                            sorted_entries = sorted(raw, key=lambda e: (not e.is_dir(), e.name.lower()))

                        for entry in sorted_entries:
                            name = entry.name
                            path = entry.path
                            is_dir = entry.is_dir()
                            ext = os.path.splitext(name)[1].lower()
                            is_image = ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ico", ".tiff", ".tif"]
                            entries_data.append((name, path, is_dir, is_image, ext))

                except PermissionError:
                    error_text = "⚠️ Accès refusé à ce dossier"
                except Exception as ex:
                    error_text = f"⚠️ Erreur: {str(ex)}"

            # Envoyer tuples de données brutes — le rendu des widgets se fait sur le thread UI
            page.pubsub.send_all_on_topic("preview_ready", (my_token, entries_data, new_file_count_text, error_text))

        threading.Thread(target=_bg, daemon=True).start()
    
    def on_sort_change(e):
        """Change le mode de tri et rafraîchit la preview"""
        sort_by_date["value"] = e.control.value
        refresh_preview()
    
    # Attacher le callback au switch
    sort_switch.on_change = on_sort_change

    def go_to_page(delta):
        """Navigue de ±1 page sans rescanner le dossier."""
        entries = all_entries_data["list"]
        total_pages = max(1, (len(entries) + PAGE_SIZE - 1) // PAGE_SIZE)
        new_pg = max(0, min(preview_page["value"] + delta, total_pages - 1))
        if new_pg == preview_page["value"]:
            return
        preview_page["value"] = new_pg
        _render_current_page()

    prev_page_btn.on_click = lambda e: go_to_page(-1)
    next_page_btn.on_click = lambda e: go_to_page(+1)

    # ================================================================ #
    #                LANCEMENT D'APPLICATIONS                          #
    # ================================================================ #
    def launch_app(app_name, app_path, is_local, series_name=None):
        """
        Lance un script Data/ en tant que sous-processus Python avec les variables
        d'environnement appropriées.

        Pour certains scripts (``Renommer sequence.py``, ``Images en PDF.py``),
        affiche d'abord une boîte de dialogue pour recueillir un paramètre
        (nom de série / nom du PDF) avant de relancer la fonction.

        Pour les scripts « locaux » (is_local=True, ex. Kiosk, Transfert),
        lit stdout/stderr en temps réel, interprète les commandes spéciales
        ``NAVIGATE_TO:<path>`` et filtre les messages de fermeture Flet.
        Pour les scripts « dossier » (is_local=False), injecte ``FOLDER_PATH``,
        ``SELECTED_FILES``, ``RESIZE_SIZE``, etc. et rafraîchit la preview
        à la fin du processus.

        Parameters
        ----------
        app_name : str
            Nom du fichier script (ex. ``"Recadrage.pyw"``).
        app_path : str
            Chemin absolu vers le script.
        is_local : bool
            ``True`` si le script fonctionne sans dossier utilisateur sélectionné
            (ex. Kiosk, Transfert vers TEMP).
        series_name : str or None, optional
            Paramètre textuel à transmettre via ``SERIES_NAME`` ou ``PDF_NAME``
            (renseigné par le dialog affiché au premier appel).
        """
        # Pour Renommer sequence.py, demander le nom de la série avant de lancer
        if app_name == "Images en PDF.py" and series_name is None:
            pdf_name_input = ft.TextField(
                label="Nom du PDF",
                hint_text="Ex: Album_Mariage",
                autofocus=True,
                width=320,
                bgcolor=DARK,
                border_color=GREY,
            )

            def on_confirm_pdf(e):
                """Valide le nom du PDF et relance launch_app avec series_name renseigné."""
                name = pdf_name_input.value.strip() if pdf_name_input.value else ""
                pdf_dialog.open = False
                page.update()
                if name:
                    launch_app(app_name, app_path, is_local, series_name=name)

            def on_cancel_pdf(e):
                """Annule la saisie du nom du PDF et ferme la boîte de dialogue."""
                pdf_dialog.open = False
                page.update()

            pdf_name_input.on_submit = on_confirm_pdf

            pdf_dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text("Nom du PDF"),
                content=pdf_name_input,
                actions=[
                    ft.TextButton("Annuler", on_click=on_cancel_pdf),
                    ft.TextButton("OK", on_click=on_confirm_pdf),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.overlay.append(pdf_dialog)
            pdf_dialog.open = True
            page.update()
            return

        if app_name == "Renommer sequence.py" and series_name is None:
            series_input = ft.TextField(
                label="Nom de la série",
                hint_text="Ex: Mariage_Martin",
                autofocus=True,
                width=320,
                bgcolor=DARK,
                border_color=GREY,
            )

            def on_confirm_series(e):
                """Valide le nom de la série et relance launch_app avec series_name renseigné."""
                name = series_input.value.strip() if series_input.value else ""
                series_dialog.open = False
                page.update()
                launch_app(app_name, app_path, is_local, series_name=name)

            def on_cancel_series(e):
                """Annule la saisie du nom de la série et ferme la boîte de dialogue."""
                series_dialog.open = False
                page.update()

            series_input.on_submit = on_confirm_series

            series_dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text("Renommer la série"),
                content=series_input,
                actions=[
                    ft.TextButton("Annuler", on_click=on_cancel_series),
                    ft.TextButton("OK", on_click=on_confirm_series),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.overlay.append(series_dialog)
            series_dialog.open = True
            page.update()
            return

        if not is_local and not selected_folder["path"]:
            log_to_terminal("[ERREUR] Veuillez sélectionner un dossier avant de lancer cette application", RED)
            return

        try:
            display_name = app_name[:-4] if app_name.endswith(".pyw") else app_name[:-3]
            log_to_terminal(f"▶ Lancement de {display_name}...", BLUE)
            
            if is_local:
                # Préparer l'environnement pour les apps locales
                env = os.environ.copy()
                env["DATA_PATH"] = os.path.join(cwd, "Data")
                
                # Naviguer vers le PATH pour order_it gauche/droite
                if app_name == "Kiosk gauche.py":
                    if platform.system() == "Windows":
                        order_path = "\\\\Diskstation\\travaux en cours\\z2026\\kiosk\\KIOSK GAUCHE"
                    else:
                        order_path = "/Volumes/TRAVAUX EN COURS/Z2026/KIOSK/KIOSK GAUCHE"
                    if os.path.isdir(order_path):
                        navigate_to_folder(order_path)
                    else:
                        log_to_terminal(f"[AVERTISSEMENT] Le dossier {order_path} n'est pas accessible", ORANGE)
                
                elif app_name == "Kiosk droite.py":
                    if platform.system() == "Windows":
                        order_path = "\\\\Diskstation\\travaux en cours\\z2026\\kiosk\\KIOSK DROITE"
                    else:
                        order_path = "/Volumes/TRAVAUX EN COURS/Z2026/KIOSK/KIOSK DROITE"
                    if os.path.isdir(order_path):
                        navigate_to_folder(order_path)
                    else:
                        log_to_terminal(f"[AVERTISSEMENT] Le dossier {order_path} n'est pas accessible", ORANGE)
                
                # Ajouter le dossier destination pour Transfert vers TEMP.py
                if app_name == "Transfert vers TEMP.py":
                    if platform.system() == "Windows":
                        env["DEST_FOLDER"] = "\\\\diskstation\\travaux en cours\\Z2026\\TEMP"
                    else:
                        env["DEST_FOLDER"] = "/Volumes/TRAVAUX EN COURS/Z2026/TEMP"
                    env["LAUNCHED_FROM_DASHBOARD"] = "1"
                
                process = subprocess.Popen(
                    [sys.executable, "-u", app_path],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                if platform.system() == "Windows":
                    try:
                        import ctypes
                        ctypes.windll.user32.AllowSetForegroundWindow(process.pid)
                    except Exception:
                        pass
                
                # Lire la sortie en temps réel
                def read_output(pipe, color):
                    """
                    Lit en temps réel une pipe stdout ou stderr du sous-processus
                    local (Flet) et envoie chaque ligne non vide au terminal.

                    Filtre les messages de fermeture de session Flet et interprète
                    les commandes ``NAVIGATE_TO:<path>`` pour naviguer dans la preview.

                    Parameters
                    ----------
                    pipe : IO
                        Pipe stdout ou stderr du subprocess.
                    color : str
                        Couleur hexadécimale pour l'affichage dans le terminal.
                    """
                    try:
                        for line in iter(pipe.readline, ''):
                            if line:
                                line_stripped = line.rstrip()
                                # Ignorer les messages de fermeture de session Flet
                                if "Session closed" in line_stripped or "session" in line_stripped.lower() and "closed" in line_stripped.lower():
                                    continue
                                # Détecter la commande de navigation
                                if line_stripped.startswith("NAVIGATE_TO:"):
                                    folder_to_navigate = line_stripped[12:]  # Enlever "NAVIGATE_TO:"
                                    if os.path.isdir(folder_to_navigate):
                                        # Utiliser pubsub pour mettre à jour l'UI depuis un thread
                                        page.pubsub.send_all_on_topic("navigate", folder_to_navigate)
                                else:
                                    log_to_terminal(line_stripped, color)
                    except:
                        pass
                    finally:
                        pipe.close()
                
                threading.Thread(target=read_output, args=(process.stdout, WHITE), daemon=True).start()
                threading.Thread(target=read_output, args=(process.stderr, RED), daemon=True).start()
                
            else:
                # Préparer l'environnement avec le chemin du dossier Data
                env = os.environ.copy()
                env["DATA_PATH"] = os.path.join(cwd, "Data")
                env["FOLDER_PATH"] = selected_folder["path"]
                
                # Ajouter les chemins ImageMagick pour Wand (Homebrew sur macOS)
                if platform.system() == "Darwin":
                    # Chemins Homebrew pour Apple Silicon et Intel
                    homebrew_paths = ["/opt/homebrew", "/usr/local"]
                    for brew_path in homebrew_paths:
                        magick_lib = os.path.join(brew_path, "lib")
                        if os.path.exists(magick_lib):
                            env["MAGICK_HOME"] = brew_path
                            env["DYLD_LIBRARY_PATH"] = magick_lib + ":" + env.get("DYLD_LIBRARY_PATH", "")
                            env["PATH"] = os.path.join(brew_path, "bin") + ":" + env.get("PATH", "")
                            break
                
                # Ajouter la taille de redimensionnement pour Redimensionner.py
                if app_name == "Redimensionner.py":
                    env["RESIZE_SIZE"] = resize_size["value"]
                
                # Ajouter la taille de redimensionnement avec watermark pour Redimensionner filigrane.py
                if app_name == "Redimensionner filigrane.py":
                    env["RESIZE_WATERMARK_SIZE"] = resize_watermark_size["value"]
                
                # Ajouter le dossier destination pour Transfert vers TEMP.py
                if app_name == "Transfert vers TEMP.py":
                    if platform.system() == "Windows":
                        env["DEST_FOLDER"] = "Z:/temp"
                    else:
                        env["DEST_FOLDER"] = "/Volumes/TRAVAUX EN COURS/Z2026/TEMP"
                
                # Ajouter le nom de la série pour Renommer sequence.py
                if app_name == "Renommer sequence.py" and series_name:
                    env["SERIES_NAME"] = series_name

                # Ajouter le nom du PDF pour Images en PDF.py
                if app_name == "Images en PDF.py" and series_name:
                    env["PDF_NAME"] = series_name

                # Ajouter les fichiers sélectionnés (si aucun n'est sélectionné, la variable sera vide)
                if selected_files:
                    env["SELECTED_FILES"] = "|".join(os.path.basename(f) for f in selected_files)
                
                process = subprocess.Popen(
                    [sys.executable, "-u", app_path],
                    cwd=os.path.join(cwd, "Data"),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
                if platform.system() == "Windows":
                    try:
                        import ctypes
                        ctypes.windll.user32.AllowSetForegroundWindow(process.pid)
                    except Exception:
                        pass

                
                # Lire la sortie en temps réel
                def read_output(pipe, color):
                    """
                    Lit en temps réel une pipe stdout ou stderr du sous-processus
                    et envoie chaque ligne au terminal.

                    Détecte les lignes préfixées par ``SELECTED_FILES:`` pour
                    resélectionner des fichiers dans la preview après exécution
                    du script.

                    Parameters
                    ----------
                    pipe : IO
                        Pipe stdout ou stderr du subprocess.
                    color : str
                        Couleur hexadécimale pour l'affichage dans le terminal.
                    """
                    try:
                        for line in iter(pipe.readline, ''):
                            if line:
                                line_stripped = line.rstrip()
                                if line_stripped.startswith(selected_files_prefix):
                                    selected_names = line_stripped[len(selected_files_prefix):]
                                    # Stocker pour que on_preview_ready l'applique
                                    # avec les données fraîches du prochain scan.
                                    _pending_selection["names"] = selected_names
                                else:
                                    log_to_terminal(line_stripped, color)
                    except Exception as read_err:
                        log_to_terminal(f"[ERREUR] Lecture sortie script: {read_err}", RED)
                    finally:
                        pipe.close()
                
                t_stdout = threading.Thread(target=read_output, args=(process.stdout, WHITE), daemon=True)
                t_stderr = threading.Thread(target=read_output, args=(process.stderr, RED), daemon=True)
                t_stdout.start()
                t_stderr.start()
                
                # Attendre la fin et rafraîchir la preview
                def done():
                    """
                    Attend la fin du sous-processus ET la lecture complète des pipes,
                    puis journalise le résultat et demande un rafraîchissement de la preview.
                    On attend les threads de lecture pour s'assurer que SELECTED_FILES:
                    a bien été traité avant de déclencher le refresh.
                    """
                    t_stdout.join()
                    t_stderr.join()
                    process.wait()
                    log_to_terminal(f"[OK] {display_name} terminé", GREEN)
                    # Rafraîchir la preview pour afficher les nouveaux dossiers/fichiers créés
                    request_refresh()
                
                threading.Thread(target=done, daemon=True).start()
        except Exception as err:
            log_to_terminal(f"[ERREUR] Erreur lors du lancement: {err}", RED)

    # Widget personnalisé pour Resize
    resize_input = ft.TextField(
        value="640",
        width=80,
        height=35,
        text_size=13,
        text_align=ft.TextAlign.CENTER,
        keyboard_type=ft.KeyboardType.NUMBER,
        border_color=BLUE,
        content_padding=ft.Padding(5, 5, 5, 5),
    )
    
    def on_resize_input_change(e):
        """Met à jour la taille de redimensionnement cible en pixels."""
        resize_size["value"] = e.control.value
    
    resize_input.on_change = on_resize_input_change
    
    def launch_resize(e):
        """Lance Redimensionner.py avec la taille saisie dans resize_input."""
        app_path = os.path.join(cwd, "Data", "Redimensionner.py")
        if os.path.exists(app_path):
            launch_app("Redimensionner.py", app_path, False)
    
    # Widget personnalisé pour Resize_watermark
    resize_watermark_input = ft.TextField(
        value="640",
        width=80,
        height=35,
        text_size=13,
        text_align=ft.TextAlign.CENTER,
        keyboard_type=ft.KeyboardType.NUMBER,
        border_color=ORANGE,
        content_padding=ft.Padding(5, 5, 5, 5),
    )
    
    def on_resize_watermark_input_change(e):
        """Met à jour la taille de redimensionnement+filigrane cible en pixels."""
        resize_watermark_size["value"] = e.control.value
    
    resize_watermark_input.on_change = on_resize_watermark_input_change
    
    def launch_resize_watermark(e):
        """Lance Redimensionner filigrane.py avec la taille saisie dans resize_watermark_input."""
        app_path = os.path.join(cwd, "Data", "Redimensionner filigrane.py")
        if os.path.exists(app_path):
            launch_app("Redimensionner filigrane.py", app_path, False)
    
    def refresh_apps():
        """
        Reconstruit la grille des applications disponibles.

        Filtre les scripts présents sur disque, crée des widgets spéciaux
        (champ numérique + bouton) pour ``Redimensionner.py`` et
        ``Redimensionner filigrane.py``, et des boutons simples pour les autres.
        """
        apps_list.controls.clear()
        
        for app_name, app_config in apps.items():
            is_local = app_config[0]
            app_color = app_config[1]
            app_path = os.path.join(cwd, "Data", app_name)
            if not os.path.exists(app_path):
                continue
            
            # Widget spécial pour Redimensionner.py
            if app_name == "Redimensionner.py":
                apps_list.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Redimensionner", size=13, color=app_color, weight=ft.FontWeight.W_500, text_align=ft.TextAlign.CENTER),
                            resize_input,
                            ft.Text("px", size=11, color=LIGHT_GREY, text_align=ft.TextAlign.CENTER),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=3),
                        bgcolor=GREY,
                        border=ft.Border.all(1, app_color),
                        padding=ft.Padding(5, 8, 5, 8),
                        border_radius=4,
                        on_click=launch_resize,
                        ink=True,
                    )
                )
            # Widget spécial pour Redimensionner filigrane.py
            elif app_name == "Redimensionner filigrane.py":
                apps_list.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Redimensionner + filigrane", size=12, color=app_color, weight=ft.FontWeight.W_500, text_align=ft.TextAlign.CENTER),
                            resize_watermark_input,
                            ft.Text("px", size=11, color=LIGHT_GREY, text_align=ft.TextAlign.CENTER),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=3),
                        bgcolor=GREY,
                        border=ft.Border.all(1, app_color),
                        padding=ft.Padding(5, 8, 5, 8),
                        border_radius=4,
                        on_click=launch_resize_watermark,
                        ink=True,
                    )
                )
            else:
                apps_list.controls.append(
                    ft.Container(
                        content=ft.Text(
                            app_name[:-4] if app_name.endswith(".pyw") else app_name[:-3],
                            size=14,
                            color=app_color,
                            text_align=ft.TextAlign.CENTER,
                            weight=ft.FontWeight.W_500,
                            max_lines=3,
                        ),
                        alignment=ft.alignment.Alignment(0, 0),
                        on_click=lambda e, name=app_name, path=app_path, local=is_local: launch_app(name, path, local),
                        bgcolor=GREY,
                        border=ft.Border.all(1, app_color),
                        padding=ft.Padding(10, 10, 10, 10),
                        border_radius=4,
                        ink=True,
                    )
                )
        page.update()

    # ================================================================ #
    #                       ACTIONS FENÊTRE                            #
    # ================================================================ #
    async def pick_folder(e):
        """
        Ouvre le sélecteur de dossier natif et navigue vers le dossier choisi.

        Appelle ``ft.FilePicker.get_directory_path`` de façon asynchrone,
        normalise le chemin résultant et déclenche un rafraîchissement de la preview.
        """
        folder = await ft.FilePicker().get_directory_path(dialog_title="Sélectionner un dossier contenant des images")
        if folder:
            selected_folder["path"] = os.path.normpath(folder)
            current_browse_folder["path"] = selected_folder["path"]
            folder_path.value = selected_folder["path"]
            folder_path.update()
            selected_files.clear()
            preview_page["value"] = 0
            refresh_preview()
    
    async def close_window(e):
        """Ferme la fenêtre principale de l'application de façon asynchrone."""
        await page.window.close()

    def minimize_window(e):
        """Réduit la fenêtre dans la barre des tâches."""
        page.window.minimized = True
    
    refresh_apps()


# ===================== FLET UI ===================== #
    page.add(
        ft.WindowDragArea(
            ft.Row([
                ft.Container(
                    ft.Text(f"DASHBOARD {__version__}", size=24, color=WHITE),
                    bgcolor=BG,
                    padding=10,
                ),
                ft.Container(expand=True),
                folder_path,
                ft.Button(
                    "Parcourir",
                    icon=ft.Icons.FOLDER_OPEN,
                    bgcolor=GREY,
                    color=RED,
                    on_click=pick_folder,
                ),
                ft.Button(
                    "Rafraîchir",
                    icon=ft.Icons.REFRESH,
                    bgcolor=GREY,
                    color=BLUE,
                    on_click=lambda e: refresh_preview(),
                ),
                ft.Button(
                    "Ouvrir l'explorateur",
                    icon=ft.Icons.FOLDER_OPEN,
                    on_click=lambda e: open_in_file_explorer(current_browse_folder["path"] or selected_folder["path"]),
                    bgcolor=GREY,
                    color=GREEN,
                    height=35,
                ),
                ft.Container(expand=True),
                ft.IconButton(
                    icon=ft.Icons.MINIMIZE, on_click=minimize_window,),
                ft.IconButton(ft.Icons.CLOSE, on_click=close_window),
            ])
        ),
        ft.Column([
            ft.Divider(),
            ft.Row([
                ft.Column([
                    ft.Row([
                        ft.Container(
                            content=ft.Text("Applications disponibles", weight=ft.FontWeight.BOLD, size=14, color=WHITE),
                            margin=ft.Margin.only(top=10, bottom=10, left=10),
                        ),
                        ft.Container(width=48),  # Espacement entre le titre et les boutons
                        ft.IconButton(
                            icon=ft.Icons.KEYBOARD_DOUBLE_ARROW_LEFT_SHARP,
                            tooltip="Kiosk gauche",
                            on_click=lambda e: launch_app("Kiosk gauche.py", os.path.join(cwd, "Data", "Kiosk gauche.py"), True),
                            icon_color=VIOLET,
                            bgcolor=DARK,
                            icon_size=18,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.KEYBOARD_DOUBLE_ARROW_RIGHT_SHARP,
                            tooltip="Kiosk droite",
                            on_click=lambda e: launch_app("Kiosk droite.py", os.path.join(cwd, "Data", "Kiosk droite.py"), True),
                            icon_color=VIOLET,
                            bgcolor=DARK,
                            icon_size=18,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.AUTO_DELETE,
                            tooltip="Nettoyer anciens fichiers (> 60 jours)",
                            on_click=lambda e: launch_app("Nettoyer anciens fichiers.py", os.path.join(cwd, "Data", "Nettoyer anciens fichiers.py"), True),
                            icon_color=ORANGE,
                            bgcolor=GREY,
                            icon_size=18,
                        ),
                    ]),
                    ft.Container(
                        content=apps_list,
                        expand=True,
                        border=ft.Border.all(1, GREY),
                        border_radius=8,
                        bgcolor=DARK,
                    )
                ], expand=True, width=350),
                ft.Column([
                    ft.Row([
                        ft.Text("Contenu du dossier", weight=ft.FontWeight.BOLD, size=14, color=WHITE, margin=ft.Margin.only(left=10)),
                        ft.IconButton(
                            icon=ft.Icons.ARROW_UPWARD,
                            tooltip="Dossier parent",
                            on_click=go_to_parent_folder,
                            icon_color=BLUE,
                            icon_size=20,
                        ),
                        ft.Button(
                            "Désélectionner",
                            icon=ft.Icons.DESELECT,
                            on_click=clear_selection,
                            bgcolor=GREY,
                            color=ORANGE,
                            height=35,
                        ),
                        ft.Button(
                            "Supprimer",
                            icon=ft.Icons.DELETE_SWEEP,
                            on_click=delete_selected_files,
                            bgcolor=GREY,
                            color=RED,
                            height=35,
                        ),
                    ]),
                    ft.Container(
                        content=ft.Stack([
                            preview_list,
                            preview_loading,
                        ]),
                        expand=True,
                        border=ft.Border.all(1, GREY),
                        border_radius=8,
                        bgcolor=DARK,
                    )
                ], expand=True)
            ], expand=True, height=400),
            ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Container(width=8),  # Espacement à gauche du titre
                        ft.Text("Terminal", weight=ft.FontWeight.BOLD, size=14, color=WHITE),
                        ft.IconButton(
                            icon=ft.Icons.COPY_ALL,
                            tooltip="Copier le terminal",
                            on_click=lambda e: copy_terminal_to_clipboard(),
                            icon_color=BLUE,
                            icon_size=18,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CLEAR_ALL,
                            tooltip="Effacer le terminal",
                            on_click=clear_terminal,
                            icon_color=RED,
                            icon_size=18,
                        ),
                        ft.Container(expand=True),
                        selection_count_text,
                        ft.Container(width=10),
                        file_count_text,
                        ft.Container(width=4),
                        prev_page_btn,
                        page_indicator_text,
                        next_page_btn,
                        ft.Container(width=4),
                        sort_switch,
                        ft.IconButton(
                            icon=ft.Icons.CREATE_NEW_FOLDER,
                            tooltip="Créer un nouveau dossier",
                            on_click=create_new_folder,
                            icon_color=GREEN,
                            icon_size=18,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CONTENT_COPY,
                            tooltip="Copier les fichiers sélectionnés",
                            on_click=copy_selected_files,
                            icon_color=BLUE,
                            icon_size=18,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CONTENT_PASTE,
                            tooltip="Coller les fichiers",
                            on_click=paste_files,
                            icon_color=ORANGE,
                            icon_size=18,
                        ),
                    ], spacing=5, alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Container(
                        content=terminal_output,
                        expand=True,
                        border=ft.Border.all(1, GREY),
                        border_radius=8,
                        bgcolor=DARK,
                        padding=5,
                    )
                ], spacing=5),
                height=160,
            ),
        ], expand=True, spacing=5)
    )

#############################################################
#                            RUN                            #
#############################################################
import asyncio
import sys

# Neutralise l'erreur asyncio Windows "ConnectionResetError: [WinError 10054]"
# qui apparaît lors de la fermeture des pipes des sous-processus.
# C'est un bug connu de la boucle ProactorEventLoop sous Windows — sans impact fonctionnel.
if sys.platform == "win32":
    _original_exception_handler = None

    def _silence_proactor_pipe_errors(loop, context):
        exc = context.get("exception")
        if isinstance(exc, (ConnectionResetError, BrokenPipeError)):
            return
        if _original_exception_handler:
            _original_exception_handler(loop, context)
        else:
            loop.default_exception_handler(context)

    import asyncio
    _loop = asyncio.new_event_loop()
    _original_exception_handler = _loop.get_exception_handler()
    _loop.set_exception_handler(_silence_proactor_pipe_errors)
    asyncio.set_event_loop(_loop)

ft.run(main)
