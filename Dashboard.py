import flet as ft
import os
import subprocess
import sys
import platform
import shutil
import threading

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

    
    selected_folder = {"path": None}
    current_browse_folder = {"path": None}
    cwd = os.path.dirname(os.path.abspath(__file__))
    
    # Configuration: nom du fichier -> True si l'app est locale (pas besoin de dossier sélectionné)
    apps = {
        "order_it gauche.py": True,
        "Recadrage.pyw": False,
        "order_it droite.py": True,
        "any to JPG.py": False,
        "Renommer sequence.py": False,
        "Projet.py": False,
        "sharpen.py": False,
        "Clean.py": False,
        "Renommer nombre photos.py": False,
        "Copy remaining files.py": True,
        "Remerciements.py": False,
        "jpeg 2 jpg.py": False,
        "Polaroid.py": False,
        "FIT_PRINT_13x10.py": False,
        "2-in-1.py": False,
        "FIT_PRINT_13x15.py": False,
    }
    
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
            if is_local:
                if platform.system() == "Windows":
                    subprocess.Popen(
                        [sys.executable, app_path],
                        # creationflags=subprocess.CREATE_NEW_CONSOLE
                    )
                else:
                    subprocess.Popen([sys.executable, app_path])
            else:
                if not os.access(selected_folder["path"], os.W_OK):
                    print(f"Erreur: Pas d'accès en écriture au dossier {selected_folder['path']}")
                    return
                
                dest_path = os.path.join(selected_folder["path"], app_name)
                shutil.copy(app_path, dest_path)
                
                # Préparer l'environnement avec le chemin du dossier Data
                env = os.environ.copy()
                env["DATA_PATH"] = os.path.join(cwd, "Data")
                
                if platform.system() == "Windows":
                    process = subprocess.Popen(
                        [sys.executable, app_name],
                        cwd=selected_folder["path"],
                        env=env,
                        creationflags=subprocess.CREATE_NEW_CONSOLE
                    )
                else:
                    process = subprocess.Popen(
                        [sys.executable, app_name],
                        cwd=selected_folder["path"],
                        env=env
                    )
                
                # Supprimer le fichier en arrière-plan pour ne pas bloquer l'UI
                def cleanup():
                    process.wait()
                    try:
                        os.remove(dest_path)
                        print(f"Fichier supprimé: {dest_path}")
                    except Exception as err:
                        print(f"Erreur lors de la suppression du fichier: {err}")
                
                threading.Thread(target=cleanup, daemon=True).start()
        except Exception as err:
            print(f"Erreur lors du lancement: {err}")
    
    def refresh_apps():
        apps_list.controls.clear()
        for app_name, is_local in apps.items():
            app_path = os.path.join(cwd, "Data", app_name)
            if not os.path.exists(app_path):
                continue
            
            apps_list.controls.append(
                ft.ListTile(
                    title=ft.Text(
                        app_name,
                        size=14,
                        color=WHITE,
                        text_align=ft.TextAlign.CENTER,
                        weight=ft.FontWeight.W_500,
                        max_lines=3,
                        margin=ft.Margin.all(3),
                    ),
                    on_click=lambda e, name=app_name, path=app_path, local=is_local: launch_app(name, path, local),
                    on_long_press=lambda e, name=app_name, path=app_path: launch_app(name, path, True),
                    bgcolor=GREY,
                    hover_color=LIGHT_GREY,
                    content_padding=ft.Padding(left=5, top=10, right=5, bottom=10),
                    shape=ft.RoundedRectangleBorder(radius=4),
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
                        ft.IconButton(
                            icon=ft.Icons.FOLDER_OPEN,
                            tooltip="Ouvrir dans l'explorateur",
                            on_click=lambda e: open_in_file_explorer(current_browse_folder["path"] or selected_folder["path"]),
                            icon_color=GREEN,
                            icon_size=20,
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
            ], expand=True),
        ], expand=True, spacing=10)
    )

ft.run(main)
