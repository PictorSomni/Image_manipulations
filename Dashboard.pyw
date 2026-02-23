# -*- coding: utf-8 -*-

__version__ = "1.6.8"

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
from time import sleep

#############################################################
#                           MAIN                            #
#############################################################
def main(page: ft.Page):
# ===================== COLORS ===================== #
    DARK = "#23252a"
    BG = "#292c33"
    GREY = "#2f333c"
    LIGHT_GREY = "#62666f"
    BLUE = "#45B8F5"
    GREEN = "#49B76C"
    ORANGE = "#e06331"
    RED = "#e17080"
    WHITE = "#adb2be"

# ===================== PROPERTIES ===================== #
    page.title = "Dashboard de Projets"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG
    page.window.title_bar_hidden = True
    page.window.title_bar_buttons_hidden = True
    page.window.width = 1200
    page.window.height = 796

    
    selected_folder = {"path": None}
    current_browse_folder = {"path": None}
    cwd = os.path.dirname(os.path.abspath(__file__))
    selected_files = set()  # Ensemble des fichiers sélectionnés
    clipboard = {"files": []}  # Presse-papiers pour copier/coller des fichiers
    
    # Configuration: nom du fichier -> True si l'app est locale (pas besoin de dossier sélectionné)
    apps = {
        "Fichiers manquants.py": False,
        "N&B.py": False,
        "Transfert vers TEMP.py": True,
        "Renommer sequence.py": False,
        "Ameliorer nettete.py": False,
        "Conversion JPG.py": False,
        "Remerciements.py": False,
        "Nettoyer metadonnees.py": False,
        "Recadrage.pyw": False,
        "Redimensionner filigrane.py": False,
        "Images en PDF.py": False,
        "Redimensionner.py": False,
        "Format 13x10.py": False,
        "2 en 1.py": False,
        "Format 13x15.py": False,
    }
    
    resize_size = {"value": "640"}  # Taille par défaut pour le redimensionnement
    resize_watermark_size = {"value": "640"}  # Taille par défaut pour le redimensionnement avec watermark
    sort_by_date = {"value": False}  # False = alphabétique, True = par date de modification
    
# ===================== UI ELEMENTS ===================== #
    folder_path = ft.TextField(
        label="Dossier sélectionné",
        hint_text="Cliquez sur Parcourir...",
        width=300,
        bgcolor=DARK,
        border_color=GREY,
        read_only=True
    )

    apps_list = ft.GridView(expand=True, runs_count=3, padding=8, spacing=8, run_spacing=8, child_aspect_ratio=2.1)
    preview_list = ft.ListView(expand=True, auto_scroll=False, spacing=4)
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
    selected_files_prefix = "SELECTED_FILES:"

# ===================== METHODS ===================== #
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
        refresh_preview()
    
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
        if new_path and os.path.isdir(new_path):
            current_browse_folder["path"] = new_path
            selected_folder["path"] = new_path
            # Update the folder_path TextField label to the new path
            folder_path.value = new_path
            folder_path.update()
            selected_files.clear()
            selection_count_text.value = ""
            refresh_preview()
    
    def go_to_parent_folder(e):
        """Remonte au dossier parent"""
        if current_browse_folder["path"]:
            parent = os.path.dirname(current_browse_folder["path"])
            if parent and parent != current_browse_folder["path"]:
                navigate_to_folder(parent)
    
    def on_file_click(file_path, is_dir):
        """Gère le clic sur un fichier ou dossier dans la preview"""
        if is_dir:
            navigate_to_folder(file_path)
        else:
            # Ouvre le fichier avec l'application par défaut
            open_file_with_default_app(file_path)
    
    def delete_item(file_path):
        """Supprime un fichier ou dossier avec confirmation"""
        def confirm_delete(e):
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
        if names_set:
            for item_name in os.listdir(folder_to_display):
                if item_name in names_set:
                    selected_files.add(os.path.join(folder_to_display, item_name))

        selection_count_text.value = f"{len(selected_files)} fichier{'s' if len(selected_files) > 1 else ''} sélectionné{'s' if len(selected_files) > 1 else ''}" if len(selected_files) > 0 else ""
        sleep(0.2)
        refresh_preview()

        if names_set and not selected_files:
            log_to_terminal("[ATTENTION] Aucun fichier correspondant trouvé dans la preview", ORANGE)
    
    def refresh_preview():
        preview_list.controls.clear()
        folder_to_display = current_browse_folder["path"] or selected_folder["path"]
        
        if folder_to_display and os.path.isdir(folder_to_display):
            try:
                files = os.listdir(folder_to_display)
                file_count = sum(1 for f in files if not f.startswith(".") and not os.path.isdir(os.path.join(folder_to_display, f)))
                file_count_text.value = f"({file_count} fichier{'s' if file_count > 1 else ''})"
                if not files:
                    preview_list.controls.append(ft.Text("(dossier vide)", color=GREY))
                else:
                    # Tri des fichiers selon le mode sélectionné
                    if sort_by_date["value"]:
                        # Tri par date de modification (plus récent en haut), dossiers d'abord
                        sorted_files = sorted(files, key=lambda x: (
                            not os.path.isdir(os.path.join(folder_to_display, x)),
                            -os.path.getmtime(os.path.join(folder_to_display, x))
                        ))
                    else:
                        # Tri alphabétique, dossiers d'abord
                        sorted_files = sorted(files, key=lambda x: (
                            not os.path.isdir(os.path.join(folder_to_display, x)),
                            x.lower()
                        ))
                    
                    for file in sorted_files:
                        file_path = os.path.join(folder_to_display, file)
                        is_dir = os.path.isdir(file_path)
                        
                        # Détection des icônes selon le type de fichier
                        ext = os.path.splitext(file)[1].lower()
                        is_image = ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.ico', '.tiff', '.tif']
                        
                        if is_dir:
                            icon = ft.Icons.FOLDER
                            icon_color = ft.Colors.AMBER_400
                        elif is_image:
                            icon = ft.Icons.IMAGE
                            icon_color = ft.Colors.GREEN_400
                        elif ext in ['.pdf']:
                            icon = ft.Icons.PICTURE_AS_PDF
                            icon_color = ft.Colors.RED_400
                        elif ext in ['.txt', '.md', '.log']:
                            icon = ft.Icons.DESCRIPTION
                            icon_color = ft.Colors.BLUE_GREY_400
                        elif ext in [".af", ".afphoto", ".afdesign", ".afpub", ".psd", ".psb", ".svg", ".eps", ".ai"]:
                            icon = ft.Icons.ADOBE
                            icon_color = GREEN
                        else:
                            icon = ft.Icons.INSERT_DRIVE_FILE
                            icon_color = ft.Colors.BLUE_GREY_400
                        
                        # Ajouter une checkbox pour tous les éléments (fichiers et dossiers)
                        checkbox = ft.Checkbox(
                            border_side = ft.BorderSide(color=BLUE),
                            value=file_path in selected_files,
                            on_change=lambda e, path=file_path: on_checkbox_change(e, path),
                        )
                        
                        # Créer le visuel (thumbnail pour images, icône pour le reste)
                        if is_image:
                            visual = ft.Container(
                                content=ft.Image(src=file_path, fit=ft.BoxFit.COVER, error_content=ft.Icon(icon, color=icon_color, size=18)),
                                width=40,
                                height=40,
                                border_radius=4,
                                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                            )
                        else:
                            visual = ft.Icon(icon, color=icon_color, size=18)
                        
                        preview_list.controls.append(
                            ft.ListTile(
                                leading=ft.Row([
                                    checkbox,
                                    visual,
                                ], spacing=8, tight=True),
                                title=ft.Text(file, size=12, color=WHITE),
                                trailing=ft.IconButton(
                                    icon=ft.Icons.DELETE_OUTLINE,
                                    icon_size=16,
                                    icon_color=ft.Colors.RED_300,
                                    tooltip="Supprimer",
                                    on_click=lambda e, path=file_path: delete_item(path),
                                ),
                                on_click=lambda e, path=file_path, d=is_dir: on_file_click(path, d),
                                hover_color=GREY,
                                dense=True,
                                content_padding=ft.Padding(left=5, top=0, right=5, bottom=0),
                            )
                        )
            except PermissionError:
                preview_list.controls.append(ft.Text("⚠️ Accès refusé à ce dossier", color="red"))
                file_count_text.value = ""
            except Exception as e:
                preview_list.controls.append(ft.Text(f"⚠️ Erreur: {str(e)}", color="red"))
                file_count_text.value = ""
        else:
            file_count_text.value = ""
        page.update()
    
    def on_sort_change(e):
        """Change le mode de tri et rafraîchit la preview"""
        sort_by_date["value"] = e.control.value
        refresh_preview()
    
    # Attacher le callback au switch
    sort_switch.on_change = on_sort_change
    
    def launch_app(app_name, app_path, is_local):
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
                
                if platform.system() == "Windows":
                    process = subprocess.Popen(
                        [sys.executable, "-u", app_path],
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        bufsize=1,
                        universal_newlines=True
                    )
                else:
                    process = subprocess.Popen(
                        [sys.executable, "-u", app_path],
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        bufsize=1,
                        universal_newlines=True
                    )
                
                # Lire la sortie en temps réel
                def read_output(pipe, color):
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
                if not os.access(selected_folder["path"], os.W_OK):
                    log_to_terminal(f"[ERREUR] Erreur: Pas d'accès en écriture au dossier {selected_folder['path']}", RED)
                    return
                
                dest_path = os.path.join(selected_folder["path"], app_name)
                shutil.copy(app_path, dest_path)
                
                # Préparer l'environnement avec le chemin du dossier Data
                env = os.environ.copy()
                env["DATA_PATH"] = os.path.join(cwd, "Data")
                
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
                
                # Ajouter les fichiers sélectionnés (si aucun n'est sélectionné, la variable sera vide)
                if selected_files:
                    env["SELECTED_FILES"] = "|".join(os.path.basename(f) for f in selected_files)
                
                process = subprocess.Popen(
                    [sys.executable, "-u", app_name],
                    cwd=selected_folder["path"],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )

                
                # Lire la sortie en temps réel
                def read_output(pipe, color):
                    for line in iter(pipe.readline, ''):
                        if line:
                            line_stripped = line.rstrip()
                            if line_stripped.startswith(selected_files_prefix):
                                selected_names = line_stripped[len(selected_files_prefix):]
                                page.pubsub.send_all_on_topic("select_files", selected_names)
                            else:
                                log_to_terminal(line_stripped, color)
                    pipe.close()
                
                threading.Thread(target=read_output, args=(process.stdout, WHITE), daemon=True).start()
                threading.Thread(target=read_output, args=(process.stderr, RED), daemon=True).start()
                
                # Supprimer le fichier en arrière-plan pour ne pas bloquer l'UI
                def cleanup():
                    process.wait()
                    try:
                        os.remove(dest_path)
                        log_to_terminal(f"[OK] {app_name} terminé", GREEN)
                    except Exception as err:
                        log_to_terminal(f"[ERREUR] Erreur lors de la suppression du fichier: {err}", RED)
                    # Rafraîchir la preview pour afficher les nouveaux dossiers/fichiers créés
                    request_refresh()
                
                threading.Thread(target=cleanup, daemon=True).start()
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
        resize_size["value"] = e.control.value
    
    resize_input.on_change = on_resize_input_change
    
    def launch_resize(e):
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
        resize_watermark_size["value"] = e.control.value
    
    resize_watermark_input.on_change = on_resize_watermark_input_change
    
    def launch_resize_watermark(e):
        app_path = os.path.join(cwd, "Data", "Redimensionner filigrane.py")
        if os.path.exists(app_path):
            launch_app("Redimensionner filigrane.py", app_path, False)
    
    def refresh_apps():
        apps_list.controls.clear()
        
        for app_name, is_local in apps.items():
            app_path = os.path.join(cwd, "Data", app_name)
            if not os.path.exists(app_path):
                continue
            
            # Widget spécial pour Redimensionner.py
            if app_name == "Redimensionner.py":
                apps_list.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Redimensionner", size=13, color=WHITE, weight=ft.FontWeight.W_500, text_align=ft.TextAlign.CENTER),
                            resize_input,
                            ft.Text("px", size=11, color=LIGHT_GREY, text_align=ft.TextAlign.CENTER),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=3),
                        bgcolor=GREY,
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
                            ft.Text("Redimensionner + filigrane", size=12, color=WHITE, weight=ft.FontWeight.W_500, text_align=ft.TextAlign.CENTER),
                            resize_watermark_input,
                            ft.Text("px", size=11, color=LIGHT_GREY, text_align=ft.TextAlign.CENTER),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=3),
                        bgcolor=GREY,
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
                            color=WHITE,
                            text_align=ft.TextAlign.CENTER,
                            weight=ft.FontWeight.W_500,
                            max_lines=3,
                        ),
                        alignment=ft.alignment.Alignment(0, 0),
                        on_click=lambda e, name=app_name, path=app_path, local=is_local: launch_app(name, path, local),
                        bgcolor=GREY,
                        padding=ft.Padding(10, 10, 10, 10),
                        border_radius=4,
                        ink=True,
                    )
                )
        page.update()
    
    async def pick_folder(e):
        folder = await ft.FilePicker().get_directory_path(dialog_title="Sélectionner un dossier contenant des images")
        if folder:
            selected_folder["path"] = os.path.normpath(folder)
            current_browse_folder["path"] = selected_folder["path"]
            folder_path.value = selected_folder["path"]
            folder_path.update()
            selected_files.clear()
            refresh_preview()
    
    async def close_window(e):
        await page.window.close()

    def minimize_window(e):
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
                    color=RED,
                    on_click=pick_folder,
                ),
                ft.Button(
                    "Rafraîchir",
                    icon=ft.Icons.REFRESH,
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
                            icon=ft.Icons.ARROW_LEFT,
                            tooltip="Kiosk gauche",
                            on_click=lambda e: launch_app("Kiosk gauche.py", os.path.join(cwd, "Data", "Kiosk gauche.py"), True),
                            icon_color=BLUE,
                            bgcolor=GREY,
                            icon_size=18,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.ARROW_RIGHT,
                            tooltip="Kiosk droite",
                            on_click=lambda e: launch_app("Kiosk droite.py", os.path.join(cwd, "Data", "Kiosk droite.py"), True),
                            icon_color=BLUE,
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
                        content=preview_list,
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
                        ft.Container(width=10),
                        sort_switch,
                        ft.Container(width=10),
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
                height=120,
            ),
        ], expand=True, spacing=5)
    )

#############################################################
#                            RUN                            #
#############################################################
ft.run(main)
