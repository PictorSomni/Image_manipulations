# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
import os
from shutil import copy2
import flet as ft

#############################################################
#                           MAIN                            #
#############################################################
def main(page: ft.Page):
    page.title = "Copy remaining files"
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 700
    page.window.height = 400
    page.window.resizable = False
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.START
    
    from_folder_text = ft.Text("Aucun dossier sélectionné", color=ft.Colors.GREY_400, size=12)
    to_folder_text = ft.Text("Aucun dossier sélectionné", color=ft.Colors.GREY_400, size=12)
    status_text = ft.Text("", color=ft.Colors.WHITE, size=14)
    progress_bar = ft.ProgressBar(width=400, color="amber", bgcolor="#eeeeee", visible=False)
    copy_button = ft.Button("Lancer la copie", color=ft.Colors.LIGHT_BLUE, disabled=True)
    
    from_folder_path = ""
    to_folder_path = ""
    
    async def pick_from_folder(e):
        folder = await ft.FilePicker().get_directory_path(dialog_title="Sélectionner un dossier source")
        if folder:
            nonlocal from_folder_path
            from_folder_path = os.path.normpath(folder)
            from_folder_text.value = f"Source: {from_folder_path}"
            from_folder_text.color = ft.Colors.GREEN_400
            from_folder_text.update()
            update_copy_button_state()
            status_text.value = ""
            status_text.update()
    
    async def pick_to_folder(e):
        folder = await ft.FilePicker().get_directory_path(dialog_title="Sélectionner un dossier destination")
        if folder:
            nonlocal to_folder_path
            to_folder_path = os.path.normpath(folder)
            to_folder_text.value = f"Destination: {to_folder_path}"
            to_folder_text.color = ft.Colors.GREEN_400
            to_folder_text.update()
            update_copy_button_state()
            status_text.value = ""
            status_text.update()
    
    def update_copy_button_state():
        copy_button.disabled = not (from_folder_path and to_folder_path)
        copy_button.update()
    
    def get_files_list(folder_path):
        """Retourne la liste de tous les fichiers dans un dossier et ses sous-dossiers"""
        files_set = set()
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                # Chemin relatif par rapport au dossier de base
                rel_path = os.path.relpath(os.path.join(root, file), folder_path)
                files_set.add(rel_path)
        return files_set
    
    def copy_missing_files(e):
        if not from_folder_path or not to_folder_path:
            status_text.value = "Veuillez sélectionner les deux dossiers"
            status_text.color = ft.Colors.RED
            status_text.update()
            return
        
        try:
            copy_button.disabled = True
            copy_button.update()
            
            status_text.value = "Analyse des dossiers..."
            status_text.color = ft.Colors.BLUE
            status_text.update()
            
            # Obtenir la liste des fichiers dans les deux dossiers
            source_files = get_files_list(from_folder_path)
            dest_files = get_files_list(to_folder_path)
            
            # Trouver les fichiers manquants
            missing_files = source_files - dest_files
            
            if not missing_files:
                status_text.value = "Aucun fichier à copier - tous les fichiers sont déjà présents"
                status_text.color = ft.Colors.GREEN
                status_text.update()
                copy_button.disabled = False
                copy_button.update()
                return
            
            status_text.value = f"Copie de {len(missing_files)} fichier(s)..."
            status_text.color = ft.Colors.BLUE
            status_text.update()
            
            progress_bar.visible = True
            progress_bar.value = 0
            progress_bar.update()
            
            # Copier les fichiers manquants
            copied_count = 0
            for i, file_rel_path in enumerate(missing_files):
                source_file = os.path.join(from_folder_path, file_rel_path)
                dest_file = os.path.join(to_folder_path, file_rel_path)
                
                # Créer le dossier de destination si nécessaire
                dest_dir = os.path.dirname(dest_file)
                if not os.path.exists(dest_dir):
                    os.makedirs(dest_dir)
                
                # Copier le fichier
                copy2(source_file, dest_file)
                copied_count += 1
                
                # Mettre à jour la barre de progression
                progress_bar.value = (i + 1) / len(missing_files)
                status_text.value = f"Copie: {copied_count}/{len(missing_files)} - {os.path.basename(file_rel_path)}"
                progress_bar.update()
                status_text.update()
            
            progress_bar.visible = False
            progress_bar.update()
            
            status_text.value = f"Copie terminée! {copied_count} fichier(s) copié(s)"
            status_text.color = ft.Colors.GREEN
            status_text.update()
            
        except Exception as ex:
            progress_bar.visible = False
            progress_bar.update()
            status_text.value = f"Erreur: {str(ex)}"
            status_text.color = ft.Colors.RED
            status_text.update()
        
        finally:
            copy_button.disabled = False
            copy_button.update()
    
    copy_button.on_click = copy_missing_files


    page.add(
        ft.AppBar(
            title=ft.Text("Copier fichiers manquants", color=ft.Colors.LIGHT_BLUE),
            bgcolor=ft.Colors.GREY_900,
            center_title=True,
        ),
        ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Row([
                        ft.Column([
                            ft.Button(
                                "Dossier source",
                                icon=ft.Icons.FOLDER_OPEN,
                                color=ft.Colors.RED,
                                on_click=pick_from_folder,
                            ),
                            from_folder_text,
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Column([
                            ft.Button(
                                "Dossier destination",
                                icon=ft.Icons.FOLDER_OPEN,
                                color=ft.Colors.GREEN,
                                on_click=pick_to_folder,
                            ),
                            to_folder_text,
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    ], alignment=ft.MainAxisAlignment.SPACE_AROUND),
                    padding=10
                ),
                
                ft.Container(
                    content=copy_button,
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

