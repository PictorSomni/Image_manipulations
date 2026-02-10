import flet as ft
import os
import subprocess
import sys
import platform
import shutil
import threading
import re
from queue import Queue

def main(page: ft.Page):
    # Colors
    DARK = "#23252a"
    BG = "#292c33"
    GREY = "#2f333c"
    LIGHT_GREY = "#62666f"
    BLUE = "#45B8F5"
    GREEN = "#49B76C"
    DARK_ORANGE = "#2A1D18"
    ORANGE = "#e06331"
    RED = "#e17080"
    WHITE = "#adb2be"

    page.title = "Dashboard de Projets"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG
    page.window.title_bar_hidden = True
    page.window.title_bar_buttons_hidden = True
    page.window.width = 1200
    page.window.height = 820

    
    selected_folder = {"path": None}
    current_browse_folder = {"path": None}
    cwd = os.path.dirname(os.path.abspath(__file__))
    
    # Configuration: nom du fichier -> True si l'app est locale (pas besoin de dossier sélectionné)
    apps = {
        "order_it gauche.py": True,
        "order_it droite.py": True,
        "Transfert vers TEMP.py": True,
        "Renommer sequence.py": False,
        "sharpen.py": False,
        "any to JPG.py": False,
        "Remerciements.py": False,
        "Clean.py": False,
        "Recadrage.pyw": False,
        "Renommer nombre photos.py": False,
        "Resize_watermark.py": False,
        "jpeg 2 jpg.py": False,
        "Resize.py": False,
        "FIT_PRINT_13x10.py": False,
        "2-in-1.py": False,
        "FIT_PRINT_13x15.py": False,
    }
    
    resize_size = {"value": "640"}  # Taille par défaut pour le redimensionnement
    resize_watermark_size = {"value": "640"}  # Taille par défaut pour le redimensionnement avec watermark
    
    folder_path = ft.TextField(
        label="Dossier sélectionné",
        hint_text="Cliquez sur Parcourir...",
        width=500,
        bgcolor=DARK,
        border_color=GREY,
        read_only=True
    )
    
    apps_list = ft.GridView(expand=True, max_extent=250, padding=8, spacing=8, run_spacing=8, child_aspect_ratio=2.0)
    preview_list = ft.ListView(expand=True, spacing=2, auto_scroll=False)
    terminal_output = ft.ListView(expand=True, spacing=2, auto_scroll=True)
    
    # Queue pour les messages du terminal (thread-safe)
    terminal_queue = Queue()
    
    def process_terminal_queue():
        """Traite les messages en attente dans la queue"""
        updated = False
        while not terminal_queue.empty():
            try:
                message, color = terminal_queue.get_nowait()
                terminal_output.controls.append(
                    ft.Text(message, size=11, color=color, font_family="monospace")
                )
                # Garder seulement les 200 dernières lignes
                if len(terminal_output.controls) > 200:
                    terminal_output.controls.pop(0)
                updated = True
            except:
                break
        if updated:
            page.update()
    
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
    
    def request_refresh():
        """Demande un rafraîchissement de la preview (thread-safe)"""
        page.pubsub.send_all_on_topic("refresh", None)
    
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
            page.snack_bar = ft.SnackBar(ft.Text("Le terminal est vide"), bgcolor=ORANGE)
            page.snack_bar.open = True
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
            
            # Afficher une confirmation
            page.snack_bar = ft.SnackBar(
                ft.Text(f"✓ {len(terminal_output.controls)} lignes copiées dans le presse-papiers"),
                bgcolor=GREEN
            )
            page.snack_bar.open = True
        except Exception as e:
            page.snack_bar = ft.SnackBar(
                ft.Text(f"✗ Erreur lors de la copie: {str(e)}"),
                bgcolor=RED
            )
            page.snack_bar.open = True
        
        page.update()
    
    def open_in_file_explorer(folder_path):
        """Ouvre le dossier dans l'explorateur de fichiers natif"""
        if not folder_path or not os.path.isdir(folder_path):
            return
        
        try:
            if platform.system() == "Windows":
                os.startfile(folder_path)
            elif platform.system() == "Darwin":  # macOS
                subprocess.Popen(["open", folder_path])
            else:  # Linux
                subprocess.Popen(["xdg-open", folder_path])
        except Exception as e:
            print(f"Erreur lors de l'ouverture de l'explorateur: {e}")
    
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
            print(f"Erreur lors de l'ouverture du fichier: {e}")
    
    def navigate_to_folder(new_path):
        """Navigue vers un dossier dans la preview"""
        if new_path and os.path.isdir(new_path):
            current_browse_folder["path"] = new_path
            selected_folder["path"] = new_path
            # Update the folder_path TextField label to the new path
            folder_path.value = new_path
            folder_path.update()
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
            except Exception as err:
                print(f"Erreur lors de la suppression: {err}")
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
    
    file_count_text = ft.Text("", size=12, color=ft.Colors.GREY_400)
    
    def refresh_preview():
        preview_list.controls.clear()
        folder_to_display = current_browse_folder["path"] or selected_folder["path"]
        
        if folder_to_display and os.path.isdir(folder_to_display):
            try:
                files = os.listdir(folder_to_display)
                file_count = sum(1 for f in files if not os.path.isdir(os.path.join(folder_to_display, f)))
                file_count_text.value = f"({file_count} fichier{'s' if file_count > 1 else ''})"
                if not files:
                    preview_list.controls.append(ft.Text("(dossier vide)", color=GREY))
                else:
                    for file in sorted(files, key=lambda x: (not os.path.isdir(os.path.join(folder_to_display, x)), x.lower())):
                        file_path = os.path.join(folder_to_display, file)
                        is_dir = os.path.isdir(file_path)
                        
                        # Détection des icônes selon le type de fichier
                        if is_dir:
                            icon = ft.Icons.FOLDER
                            icon_color = ft.Colors.AMBER_400
                        else:
                            # Détection du type d'image
                            ext = os.path.splitext(file)[1].lower()
                            if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.ico', '.tiff', '.tif']:
                                icon = ft.Icons.IMAGE
                                icon_color = ft.Colors.GREEN_400
                            elif ext in ['.pdf']:
                                icon = ft.Icons.PICTURE_AS_PDF
                                icon_color = ft.Colors.RED_400
                            elif ext in ['.txt', '.md', '.log']:
                                icon = ft.Icons.DESCRIPTION
                                icon_color = ft.Colors.BLUE_GREY_400
                            else:
                                icon = ft.Icons.INSERT_DRIVE_FILE
                                icon_color = ft.Colors.BLUE_GREY_400
                        
                        preview_list.controls.append(
                            ft.ListTile(
                                leading=ft.Icon(icon, color=icon_color, size=20),
                                title=ft.Text(file, size=12),
                                trailing=ft.IconButton(
                                    icon=ft.Icons.DELETE_OUTLINE,
                                    icon_size=16,
                                    icon_color=ft.Colors.RED_300,
                                    tooltip="Supprimer",
                                    on_click=lambda e, path=file_path: delete_item(path),
                                ),
                                on_click=lambda e, path=file_path, d=is_dir: on_file_click(path, d),
                                hover_color=GREY,
                                content_padding=ft.Padding(left=8, top=2, right=8, bottom=2),
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
    
    def launch_app(app_name, app_path, is_local):
        if not is_local and not selected_folder["path"]:
            return
        
        try:
            log_to_terminal(f"▶ Lancement de {app_name}...", BLUE)
            
            if is_local:
                # Préparer l'environnement pour les apps locales
                env = os.environ.copy()
                env["DATA_PATH"] = os.path.join(cwd, "Data")
                
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
                    log_to_terminal(f"✗ Erreur: Pas d'accès en écriture au dossier {selected_folder['path']}", RED)
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
                
                # Ajouter la taille de redimensionnement pour Resize.py
                if app_name == "Resize.py":
                    env["RESIZE_SIZE"] = resize_size["value"]
                
                # Ajouter la taille de redimensionnement avec watermark pour Resize_watermark.py
                if app_name == "Resize_watermark.py":
                    env["RESIZE_WATERMARK_SIZE"] = resize_watermark_size["value"]
                
                # Ajouter le dossier destination pour Transfert vers TEMP.py
                if app_name == "Transfert vers TEMP.py":
                    if platform.system() == "Windows":
                        env["DEST_FOLDER"] = "Z:/temp"
                    else:
                        env["DEST_FOLDER"] = "/Volumes/TRAVAUX EN COURS/Z2026/TEMP"
                
                if platform.system() == "Windows":
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
                else:
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
                            log_to_terminal(line.rstrip(), color)
                    pipe.close()
                
                threading.Thread(target=read_output, args=(process.stdout, WHITE), daemon=True).start()
                threading.Thread(target=read_output, args=(process.stderr, RED), daemon=True).start()
                
                # Supprimer le fichier en arrière-plan pour ne pas bloquer l'UI
                def cleanup():
                    process.wait()
                    try:
                        os.remove(dest_path)
                        log_to_terminal(f"✓ {app_name} terminé", GREEN)
                    except Exception as err:
                        log_to_terminal(f"✗ Erreur lors de la suppression du fichier: {err}", RED)
                    # Rafraîchir la preview pour afficher les nouveaux dossiers/fichiers créés
                    request_refresh()
                
                threading.Thread(target=cleanup, daemon=True).start()
        except Exception as err:
            print(f"Erreur lors du lancement: {err}")
    
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
        app_path = os.path.join(cwd, "Data", "Resize.py")
        if os.path.exists(app_path):
            launch_app("Resize.py", app_path, False)
    
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
        app_path = os.path.join(cwd, "Data", "Resize_watermark.py")
        if os.path.exists(app_path):
            launch_app("Resize_watermark.py", app_path, False)
    
    def refresh_apps():
        apps_list.controls.clear()
        
        for app_name, is_local in apps.items():
            app_path = os.path.join(cwd, "Data", app_name)
            if not os.path.exists(app_path):
                continue
            
            # Widget spécial pour Resize.py
            if app_name == "Resize.py":
                apps_list.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Redimensionnement", size=13, color=WHITE, weight=ft.FontWeight.W_500, text_align=ft.TextAlign.CENTER),
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
            # Widget spécial pour Resize_watermark.py
            elif app_name == "Resize_watermark.py":
                apps_list.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Projet", size=12, color=WHITE, weight=ft.FontWeight.W_500, text_align=ft.TextAlign.CENTER),
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
                            app_name,
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
            refresh_preview()
    
    refresh_apps()
    
    async def close_window(e):
        await page.window.close()
    
    refresh_apps()
    
    page.add(
        ft.WindowDragArea(
            ft.Row([
                ft.Container(
                    ft.Text("DASHBOARD", color=WHITE),
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
                ft.Container(expand=True),
                ft.IconButton(ft.Icons.CLOSE, on_click=close_window),
            ])
        ),
        ft.Column([
            ft.Divider(),
            ft.Row([
                ft.Column([
                    ft.Container(
                        content=ft.Text("Applications disponibles", weight=ft.FontWeight.BOLD, size=14, color=WHITE),
                        margin=ft.Margin.only(top=10, bottom=10, left=10),
                    ),
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
                            "Ouvrir l'explorateur",
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=lambda e: open_in_file_explorer(current_browse_folder["path"] or selected_folder["path"]),
                            bgcolor=GREY,
                            color=GREEN,
                            height=35,
                        ),
                        file_count_text,
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
            ft.Divider(height=1, color=GREY),
            ft.Container(
                content=ft.Column([
                    ft.Row([
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
                    ], spacing=5),
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

ft.run(main)
