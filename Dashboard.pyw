import flet as ft
import os
import subprocess
import sys
import platform
from tkinter import filedialog
import tkinter as tk
import shutil

def main(page: ft.Page):
    page.title = "Dashboard de Projets"
    page.theme_mode = ft.ThemeMode.DARK
    
    selected_folder = {"path": None}
    current_browse_folder = {"path": None}
    cwd = os.path.dirname(os.path.abspath(__file__))
    
    # Configuration: nom du fichier -> True si l'app est locale (pas besoin de dossier sélectionné)
    apps = {
        "order_it gauche.py": True,
        "any to JPG.py": False,
        "order_it droite.py": True,
        "1024.py": False,
        "Clean.py": False,
        "Renommer sequence.py": False,
        "FIT_PRINT_13x15.py": False,
        "FIT_PRINT_13x10.py": False,
        "Projet.py": False,
        "Recadrage.py": False,
        "Copy remaining files.py": True,
        
    }
    
    folder_path = ft.TextField(
        label="Dossier sélectionné",
        hint_text="Cliquez sur Parcourir...",
        width=500,
        border_color=ft.Colors.OUTLINE_VARIANT,
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
    
    def navigate_to_folder(folder_path):
        """Navigue vers un dossier dans la preview"""
        if folder_path and os.path.isdir(folder_path):
            current_browse_folder["path"] = folder_path
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
                    preview_list.controls.append(ft.Text("(dossier vide)", color="grey"))
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
                                on_click=lambda e, path=file_path, d=is_dir: on_file_click(path, d),
                                hover_color=ft.Colors.BLUE_GREY_800,
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
                        creationflags=subprocess.CREATE_NEW_CONSOLE
                    )
                else:
                    subprocess.Popen([sys.executable, app_path])
            else:
                if not os.access(selected_folder["path"], os.W_OK):
                    print(f"Erreur: Pas d'accès en écriture au dossier {selected_folder['path']}")
                    return
                
                dest_path = os.path.join(selected_folder["path"], app_name)
                shutil.copy(app_path, dest_path)
                
                if platform.system() == "Windows":
                    process = subprocess.Popen(
                        [sys.executable, app_name],
                        cwd=selected_folder["path"],
                        creationflags=subprocess.CREATE_NEW_CONSOLE
                    )
                else:
                    process = subprocess.Popen(
                        [sys.executable, app_name],
                        cwd=selected_folder["path"]
                    )
                
                # Attendre la fin du processus et supprimer le fichier
                process.wait()
                try:
                    os.remove(dest_path)
                    print(f"Fichier supprimé: {dest_path}")
                except Exception as err:
                    print(f"Erreur lors de la suppression du fichier: {err}")
        except Exception as err:
            print(f"Erreur lors du lancement: {err}")
    
    def refresh_apps():
        apps_list.controls.clear()
        for app_name, is_local in apps.items():
            app_path = os.path.join(cwd, app_name)
            if not os.path.exists(app_path):
                continue
            
            apps_list.controls.append(
                ft.ListTile(
                    title=ft.Text(
                        app_name,
                        size=14,
                        color=ft.Colors.BLUE_GREY_100,
                        text_align=ft.TextAlign.CENTER,
                        weight=ft.FontWeight.W_500,
                        max_lines=3,
                        margin=ft.Margin.all(3),
                    ),
                    on_click=lambda e, name=app_name, path=app_path, local=is_local: launch_app(name, path, local),
                    on_long_press=lambda e, name=app_name, path=app_path: launch_app(name, path, True),
                    bgcolor=ft.Colors.LIGHT_BLUE_900,
                    hover_color=ft.Colors.LIGHT_BLUE_700,
                    content_padding=ft.Padding(left=5, top=10, right=5, bottom=10),
                    shape=ft.RoundedRectangleBorder(radius=4),
                )
            )
        page.update()
    
    def pick_folder(e):
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes('-topmost', 1)
        folder = filedialog.askdirectory(master=root, title="Sélectionner un dossier contenant des images")
        root.destroy()
        if folder:
            selected_folder["path"] = os.path.normpath(folder)
            current_browse_folder["path"] = selected_folder["path"]  # Sync le dossier de navigation
            folder_path.value = selected_folder["path"]
            folder_path.update()
            refresh_preview()
    
    refresh_apps()
    
    page.add(
        ft.AppBar(
            title=ft.Text("DASHBOARD", color=ft.Colors.LIGHT_BLUE),
            bgcolor=ft.Colors.GREY_900,
            center_title=True,
        ),
        ft.Column([
            ft.Row([
                folder_path,
                ft.Button(
                    "Parcourir",
                    icon=ft.Icons.FOLDER_OPEN,
                    color=ft.Colors.WHITE_70,
                    on_click=pick_folder,
                ),
                ft.Button(
                    "Rafraîchir",
                    icon=ft.Icons.REFRESH,
                    color=ft.Colors.LIGHT_BLUE,
                    on_click=lambda e: refresh_preview(),
                ),
            ]),
            ft.Divider(),
            
            ft.Row([
                ft.Column([
                    ft.Container(
                        content=ft.Text("Applications disponibles", weight=ft.FontWeight.BOLD, size=14),
                        height=40,  # Hauteur pour s'aligner avec le Row contenant les IconButtons
                    ),
                    ft.Container(
                        content=apps_list,
                        expand=True,
                        border=ft.Border.all(1, ft.Colors.OUTLINE),
                        border_radius=8,
                        bgcolor=ft.Colors.BLACK_12,
                    )
                ], expand=True, width=350),
                
                ft.Column([
                    ft.Row([
                        ft.Text("Contenu du dossier", weight=ft.FontWeight.BOLD, size=14),
                        ft.IconButton(
                            icon=ft.Icons.ARROW_UPWARD,
                            tooltip="Dossier parent",
                            on_click=go_to_parent_folder,
                            icon_color=ft.Colors.LIGHT_BLUE,
                            icon_size=20,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.FOLDER_OPEN,
                            tooltip="Ouvrir dans l'explorateur",
                            on_click=lambda e: open_in_file_explorer(current_browse_folder["path"] or selected_folder["path"]),
                            icon_color=ft.Colors.AMBER_400,
                            icon_size=20,
                        ),
                        file_count_text,
                    ]),
                    ft.Container(
                        content=preview_list,
                        expand=True,
                        border=ft.Border.all(1, ft.Colors.OUTLINE),
                        border_radius=8,
                        bgcolor=ft.Colors.BLACK_12,
                    )
                ], expand=True)
            ], expand=True),
        ], expand=True, spacing=10,)
    )

ft.run(main)
