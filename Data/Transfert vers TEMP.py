# -*- coding: utf-8 -*-

__version__ = "1.6.4"

#############################################################
#                          IMPORTS                          #
#############################################################
from pathlib import Path
from shutil import copy2
from datetime import datetime
import subprocess
import platform
import sys
import os
import flet as ft

#############################################################
#                         CONSTANTS                         #
#############################################################
DEFAULT_SOURCE = Path.home() / "Downloads"
DEFAULT_DEST = Path(os.environ.get("DEST_FOLDER", "Z:/temp"))
LAUNCHED_FROM_DASHBOARD = os.environ.get("LAUNCHED_FROM_DASHBOARD") == "1"

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

#############################################################
#                           MAIN                            #
#############################################################
def main(page: ft.Page):
    page.title = "Copy remaining files"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG
    page.window.title_bar_hidden = True
    page.window.title_bar_buttons_hidden = True
    page.window.width = 640
    page.window.height = 360
    page.window.resizable = False
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.START
    
    # Initialiser avec les chemins par défaut
    from_folder_path = DEFAULT_SOURCE if DEFAULT_SOURCE.exists() else ""
    to_folder_path = DEFAULT_DEST if DEFAULT_DEST.exists() else ""
    
    from_folder_text = ft.Text(
        f"Source: {from_folder_path}" if from_folder_path else "Aucun dossier sélectionné",
        color=GREEN if from_folder_path else LIGHT_GREY,
        size=12
    )
    to_folder_text = ft.Text(
        f"Destination: {to_folder_path}" if to_folder_path else "Aucun dossier sélectionné",
        color=GREEN if to_folder_path else LIGHT_GREY,
        size=12
    )
    status_text = ft.Text(
        "Copie en cours..." if LAUNCHED_FROM_DASHBOARD else "",
        color=BLUE if LAUNCHED_FROM_DASHBOARD else WHITE,
        size=14
    )
    progress_bar = ft.ProgressBar(width=400, color=ORANGE, bgcolor=LIGHT_GREY, visible=LAUNCHED_FROM_DASHBOARD)
    copy_button = ft.Button(
        "Lancer la copie",
        icon=ft.Icons.COPY,
        color=DARK,
        bgcolor=BLUE,
        style=ft.ButtonStyle(
            padding=20,
            text_style=ft.TextStyle(size=18, weight=ft.FontWeight.BOLD),
        ),
        height=60,
        width=250,
        disabled=not (from_folder_path and to_folder_path),
        visible=not LAUNCHED_FROM_DASHBOARD  # Cacher si lancé depuis Dashboard
    )
    
    def open_dest_folder(e):
        """Ouvre le dossier destination dans l'explorateur de fichiers"""
        if to_folder_path:
            folder_to_open = str(to_folder_path)
            if platform.system() == "Darwin":  # macOS
                subprocess.Popen(["open", folder_to_open])
            elif platform.system() == "Windows":
                subprocess.Popen(f'explorer "{folder_to_open}"', shell=True)
            else:  # Linux
                subprocess.Popen(["xdg-open", folder_to_open])
    
    open_folder_button = ft.Button(
        "Ouvrir destination",
        icon=ft.Icons.FOLDER,
        color= ORANGE,
        on_click=open_dest_folder,
        disabled=not to_folder_path,
        visible=not LAUNCHED_FROM_DASHBOARD  # Cacher si lancé depuis Dashboard
    )
    
    async def pick_from_folder(e):
        folder = await ft.FilePicker().get_directory_path(dialog_title="Sélectionner un dossier source")
        if folder:
            nonlocal from_folder_path
            from_folder_path = Path(folder)
            from_folder_text.value = f"Source: {from_folder_path}"
            from_folder_text.color = GREEN
            from_folder_text.update()
            update_copy_button_state()
            status_text.value = ""
            status_text.update()
    
    async def pick_to_folder(e):
        folder = await ft.FilePicker().get_directory_path(dialog_title="Sélectionner un dossier destination")
        if folder:
            nonlocal to_folder_path
            to_folder_path = Path(folder)
            to_folder_text.value = f"Destination: {to_folder_path}"
            to_folder_text.color = GREEN
            to_folder_text.update()
            update_copy_button_state()
            status_text.value = ""
            status_text.update()
    
    def update_copy_button_state():
        copy_button.disabled = not (from_folder_path and to_folder_path)
        copy_button.update()
        open_folder_button.disabled = not to_folder_path
        open_folder_button.update()
    
    def get_files_list(folder_path):
        """Retourne la liste de tous les fichiers dans un dossier (non récursif)"""
        files_list = []
        folder_path = Path(folder_path)
        for file_path in folder_path.iterdir():
            if file_path.is_file():
                files_list.append(file_path)
        return files_list
    
    def get_next_sequence_folder(base_path):
        """Retourne le prochain dossier séquentiel dans le dossier de la date du jour"""
        today = datetime.now().strftime("%Y-%m-%d")
        date_folder = Path(base_path) / today
        date_folder.mkdir(parents=True, exist_ok=True)
        
        # Trouver le prochain numéro de séquence
        seq_num = 1
        while True:
            seq_folder = date_folder / f"{seq_num:02d}"
            if not seq_folder.exists():
                seq_folder.mkdir(parents=True, exist_ok=True)
                return seq_folder
            seq_num += 1

    async def copy_missing_files(e):
        nonlocal from_folder_path, to_folder_path
        if not from_folder_path or not to_folder_path:
            status_text.value = "Veuillez sélectionner les deux dossiers"
            status_text.color = ft.Colors.RED
            status_text.update()
            return
        
        try:
            copy_button.disabled = True
            copy_button.update()
            
            print("Analyse du dossier source...", flush=True)
            status_text.value = "Analyse du dossier source..."
            status_text.color = ft.Colors.BLUE
            status_text.update()
            
            # Obtenir la liste des fichiers dans le dossier source
            source_files = get_files_list(from_folder_path)
            
            if not source_files:
                print("Aucun fichier à copier dans le dossier source", flush=True)
                status_text.value = "Aucun fichier à copier dans le dossier source"
                status_text.color = ft.Colors.ORANGE
                status_text.update()
                copy_button.disabled = False
                copy_button.update()
                return
            
            # Créer le dossier de destination séquentiel
            dest_folder = get_next_sequence_folder(to_folder_path)
            
            print(f"Copie de {len(source_files)} fichier(s) vers {dest_folder}...", flush=True)
            status_text.value = f"Copie de {len(source_files)} fichier(s) vers {dest_folder.name}..."
            status_text.color = ft.Colors.BLUE
            status_text.update()
            
            progress_bar.visible = True
            progress_bar.value = 0
            progress_bar.update()
            
            # Copier tous les fichiers
            copied_count = 0
            for i, source_file in enumerate(source_files):
                dest_file = dest_folder / source_file.name
                
                # Copier le fichier
                copy2(source_file, dest_file)
                copied_count += 1
                
                # Mettre à jour la barre de progression
                progress_bar.value = (i + 1) / len(source_files)
                status_text.value = f"Copie: {copied_count}/{len(source_files)} - {source_file.name}"
                progress_bar.update()
                status_text.update()
            
            progress_bar.visible = False
            progress_bar.update()
            
            # Supprimer les fichiers sources après copie réussie
            print("Suppression des fichiers sources...", flush=True)
            status_text.value = "Suppression des fichiers sources..."
            status_text.color = ft.Colors.BLUE
            status_text.update()
            
            for source_file in source_files:
                source_file.unlink()
            
            print(f"[ok] Terminé! {copied_count} fichier(s) copié(s) dans {dest_folder} et supprimé(s) de la source", flush=True)
            # Envoyer le chemin du dossier créé au Dashboard
            print(f"NAVIGATE_TO:{dest_folder}", flush=True)
            status_text.value = f"Terminé! {copied_count} fichier(s) copié(s) dans {dest_folder} et supprimé(s) de la source"
            status_text.color = ft.Colors.GREEN
            status_text.update()
            
            # Fermer automatiquement si lancé depuis Dashboard
            if LAUNCHED_FROM_DASHBOARD:
                await page.window.close()
            
        except Exception as ex:
            progress_bar.visible = False
            progress_bar.update()
            print(f"[x] Erreur: {str(ex)}", flush=True)
            status_text.value = f"Erreur: {str(ex)}"
            status_text.color = ft.Colors.RED
            status_text.update()
        
        finally:
            copy_button.disabled = False
            copy_button.update()
    
    copy_button.on_click = copy_missing_files
    
    async def close_window(e):
        await page.window.close()

    # Lancer automatiquement la copie si lancé depuis Dashboard
    if LAUNCHED_FROM_DASHBOARD and from_folder_path and to_folder_path:
        page.run_task(copy_missing_files, None)


    page.add(
        ft.WindowDragArea(
            ft.Row([
                ft.Container(
                    ft.Text("Copier fichiers", color=WHITE),
                    bgcolor=BG,
                    padding=10,
                ),
                ft.Container(expand=True),
                ft.IconButton(ft.Icons.CLOSE, on_click=close_window),
            ])
        ),
        ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Row([
                        ft.Column([
                            ft.Button(
                                "Dossier source",
                                icon=ft.Icons.FOLDER_OPEN,
                                color=RED,
                                on_click=pick_from_folder,
                            ),
                            from_folder_text,
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Column([
                            ft.Button(
                                "Dossier destination",
                                icon=ft.Icons.FOLDER_OPEN,
                                color=GREEN,
                                on_click=pick_to_folder,
                            ),
                            to_folder_text,
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    ], alignment=ft.MainAxisAlignment.SPACE_AROUND),
                    padding=10
                ),
                
                ft.Container(
                    content=ft.Row([
                        copy_button,
                        open_folder_button,
                    ], alignment=ft.MainAxisAlignment.CENTER, spacing=20),
                    alignment=ft.Alignment.CENTER,
                    padding=10
                ),
                
                ft.Container(
                    content=progress_bar,
                    alignment=ft.Alignment.CENTER,
                    padding=10
                ),
                
                ft.Container(
                    content=status_text,
                    alignment=ft.Alignment.CENTER,
                    padding=10
                ),
            ], spacing=10),
            padding=20
        )
    )

ft.run(main)

