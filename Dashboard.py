from turtle import bgcolor, color
import flet as ft
import os
import subprocess
import sys
import platform
from tkinter import filedialog
import tkinter as tk
import shutil
from PIL import Image

def main(page: ft.Page):
    page.title = "Dashboard de Projets"
    page.theme_mode = ft.ThemeMode.DARK
    
    selected_folder = {"path": None}
    local_apps = set()
    
    cwd = os.path.dirname(os.path.abspath(__file__))
    py_files = [f.upper() for f in sorted(os.listdir(cwd)) if f.endswith(".py") and f != "Dashboard_clean.py"]
    
    folder_path = ft.TextField(
        label="Dossier sélectionné",
        hint_text="Cliquez sur Parcourir...",
        width=500,
        border_color=ft.Colors.OUTLINE_VARIANT,
        read_only=True
    )
    
    apps_list = ft.GridView(expand=True, max_extent=250, spacing=8, run_spacing=8, child_aspect_ratio=3.0)
    preview_list = ft.ListView(expand=True, spacing=2, auto_scroll=True)
    
    def refresh_preview():
        preview_list.controls.clear()
        if selected_folder["path"] and os.path.isdir(selected_folder["path"]):
            files = os.listdir(selected_folder["path"])
            if not files:
                preview_list.controls.append(ft.Text("(dossier vide)", color="grey"))
            else:
                for file in sorted(files):
                    file_path = os.path.join(selected_folder["path"], file)
                    if os.path.isdir(file_path):
                        preview_list.controls.append(ft.Text(f"📁 {file}", size=12))
                    else:
                        preview_list.controls.append(ft.Text(f"📄 {file}", size=12))
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
        for app_name in sorted(py_files):
            app_path = os.path.join(cwd, app_name)
            is_local = app_name in local_apps
            
            def on_app_click(e, name=app_name, path=app_path, local=is_local):
                launch_app(name, path, local)
            
            def toggle_local(e, name=app_name):
                if name in local_apps:
                    local_apps.remove(name)
                else:
                    local_apps.add(name)
            
            def on_long_press(e, name=app_name, path=app_path):
                # Marquer en local et lancer immédiatement en mode local
                local_apps.add(name)
                launch_app(name, path, True)

            apps_list.controls.append(
                ft.ListTile(
                    title=ft.Text(
                        app_name,
                        size=14,
                        color=ft.Colors.BLUE_GREY_200,
                        text_align=ft.TextAlign.CENTER,
                        weight=ft.FontWeight.W_500,
                        max_lines=3,
                    ),
                    on_click=on_app_click,
                    on_long_press=on_long_press,
                    bgcolor=ft.Colors.GREY_900,
                    content_padding=ft.Padding(left=5, top=10, right=5, bottom=10),
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
            folder_path.value = selected_folder["path"]
            folder_path.update()
            refresh_preview()
    
    refresh_apps()
    
    page.add(
        ft.AppBar(
            title=ft.Text("Dashboard", color=ft.Colors.LIGHT_BLUE_ACCENT),
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
                    color=ft.Colors.LIGHT_BLUE_ACCENT,
                    on_click=lambda e: refresh_preview(),
                ),
            ]),
            ft.Divider(),
            
            ft.Row([
                ft.Column([
                    ft.Text("Applications disponibles", weight=ft.FontWeight.BOLD, size=14),
                    ft.Container(
                        content=apps_list,
                        expand=True,
                        border=ft.Border.all(1, ft.Colors.OUTLINE),
                        border_radius=8,
                        bgcolor=ft.Colors.BLACK_12,
                    )
                ], expand=True, width=350),
                
                ft.Column([
                    ft.Text("Contenu du dossier", weight=ft.FontWeight.BOLD, size=14),
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
