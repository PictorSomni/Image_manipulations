# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
import flet as ft
import os
from PIL import Image, ImageOps

# === Configuration ===
MAX_CANVAS_SIZE = 1200  # Taille max du canvas
CONTROLS_WIDTH = 270    # Largeur de la colonne de contrôles

# Formats d'impression (ratio largeur/hauteur)
FORMATS = {
    "10x15 (102x152mm)": 102 / 152,
    "13x18 (127x178mm)": 127 / 178,
    "15x20 (152x203mm)": 152 / 203,
    "20x30 (203x305mm)": 203 / 305,
}

#############################################################
#                         CONTENT                           #
#############################################################
class PhotoCropper:
    def __init__(self, page: ft.Page):
        self.page = page
        # État du batch
        self.image_paths = []
        self.current_index = 0
        self.batch_mode = False
        
        # Configuration du canvas (calculé dynamiquement)
        self.canvas_is_portrait = True
        self.current_ratio = FORMATS["10x15 (102x152mm)"]
        self.current_format_label = "10x15 (102x152mm)"
        self.canvas_w = 800  # Valeur initiale, ajustée au chargement
        self.canvas_h = self.canvas_w / self.current_ratio

        # Gestion du zoom
        self.zoom_factor = 1.0
        self.base_scale = 1.0

        # Image principale
        self.image_display = ft.Image(
            src="",
            fit="contain",
            width=500,
            height=500,
            top=0,
            left=0,
        )

        # On place l'image dans un Stack pour pouvoir la déplacer
        self.image_stack = ft.Stack(
            [self.image_display],
            width=self.canvas_w,
            height=self.canvas_h,
        )

        self.gesture_detector = ft.GestureDetector(
            content=self.image_stack,
            on_pan_update=self.on_pan_update,
            drag_interval=10,
        )

        # small label to show zoom percent
        self.zoom_label = ft.Text("100%")
        # visible status fallback when SnackBar is not shown
        self.status_text = ft.Text("")
        # action buttons (created here so main can reference them)
        self.validate_button = ft.Button(
            "Valider & Suivant",
            icon=ft.icons.Icons.CHECK,
            bgcolor=ft.Colors.GREEN_700,
            color=ft.Colors.WHITE,
            on_click=self.validate_and_next,
        )
        self.close_button = ft.Button(
            "Fermer",
            icon=ft.icons.Icons.CLOSE,
            bgcolor=ft.Colors.RED_700,
            color=ft.Colors.WHITE,
            on_click=self.close_app,
        )
        # hide close until needed
        try:
            self.close_button.visible = False
        except Exception:
            pass

        self.canvas_container = ft.Container(
            content=self.gesture_detector,
            bgcolor=ft.Colors.BLACK,
            clip_behavior=ft.ClipBehavior.HARD_EDGE, # Important pour le recadrage visuel
            width=self.canvas_w,
            height=self.canvas_h,
            border=ft.Border.all(1, ft.Colors.WHITE24),
        )

    def update_canvas_size(self):
        """Calcule la taille optimale du canvas en fonction de l'espace disponible"""
        # Espace disponible (fenêtre - contrôles - marges)
        available_width = min(self.page.window.width - CONTROLS_WIDTH - 80, MAX_CANVAS_SIZE) if self.page.window.width else 800
        available_height = min(self.page.window.height - 80, MAX_CANVAS_SIZE) if self.page.window.height else 600
        
        # Calcul selon l'orientation
        if self.canvas_is_portrait:
            # Portrait : plus haut que large (ratio < 1)
            # hauteur = largeur / ratio
            self.canvas_w = available_width
            self.canvas_h = self.canvas_w / self.current_ratio
            # Si trop haut, réduire
            if self.canvas_h > available_height:
                self.canvas_h = available_height
                self.canvas_w = self.canvas_h * self.current_ratio
        else:
            # Paysage : plus large que haut (on inverse le ratio)
            # hauteur = largeur * ratio (ou largeur = hauteur / ratio)
            self.canvas_h = available_height
            self.canvas_w = self.canvas_h / self.current_ratio
            # Si trop large, réduire
            if self.canvas_w > available_width:
                self.canvas_w = available_width
                self.canvas_h = self.canvas_w * self.current_ratio
            
        self.canvas_container.width = self.canvas_w
        self.canvas_container.height = self.canvas_h
        self.image_stack.width = self.canvas_w
        self.image_stack.height = self.canvas_h
        self.page.update()

    def load_image(self, preserve_orientation=False):
        if not self.image_paths:
            return
        # reset zoom to 100% for each new image
        self.zoom_factor = 1.0
        try:
            self.zoom_label.value = "100%"
        except Exception:
            pass
        try:
            self.zoom_slider.value = 1.0
        except Exception:
            pass
        
        path = self.image_paths[self.current_index]
        # Load original image with Pillow to compute precise crop mapping
        pil_img = Image.open(path)
        # Apply EXIF orientation if present so width/height reflect display
        try:
            pil_img = ImageOps.exif_transpose(pil_img)
        except Exception:
            pass
        pil_img = pil_img.convert("RGBA")
        self.current_pil_image = pil_img
        self.orig_w, self.orig_h = pil_img.size

        # Auto-orient canvas selon l'image, sauf si on veut préserver l'orientation utilisateur
        if not preserve_orientation:
            self.canvas_is_portrait = True if self.orig_h >= self.orig_w else False

        # Compute canvas size (may have changed due to ratio / orientation)
        self.update_canvas_size()
        # Compute base_scale to behave like CSS 'cover' (fill canvas)
        scale = max(self.canvas_w / self.orig_w, self.canvas_h / self.orig_h)
        self.base_scale = scale
        # apply zoom factor
        self.current_scale = self.base_scale * self.zoom_factor
        self.display_w = int(self.orig_w * self.current_scale)
        self.display_h = int(self.orig_h * self.current_scale)

        # Initial position: center the image inside the canvas
        self.image_display.src = path
        self.image_display.width = self.display_w
        self.image_display.height = self.display_h
        self.image_display.left = int((self.canvas_w - self.display_w) / 2)
        self.image_display.top = int((self.canvas_h - self.display_h) / 2)

        # record for crop calculations (already set above)

        self.page.title = f"Recadrage : {os.path.basename(path)} ({self.current_index + 1}/{len(self.image_paths)})"
        self.page.update()

    def on_pan_update(self, e: ft.DragUpdateEvent):
        """Gestion du déplacement de l'image par drag"""
        # Extraction du delta (compatible avec différentes versions de Flet)
        ld = getattr(e, 'local_delta', None)
        if not ld:
            return
            
        dx = ld[0] if isinstance(ld, (list, tuple)) else getattr(ld, 'x', 0)
        dy = ld[1] if isinstance(ld, (list, tuple)) and len(ld) > 1 else getattr(ld, 'y', 0)

        # Calcul des nouvelles positions
        new_left = (self.image_display.left or 0) + dx
        new_top = (self.image_display.top or 0) + dy
        dw = self.display_w
        dh = self.display_h

        # Contraintes : centrer si trop petit, sinon limiter pour couvrir le canvas
        if dw <= self.canvas_w:
            new_left = int((self.canvas_w - dw) / 2)
        else:
            new_left = max(self.canvas_w - dw, min(0, new_left))

        if dh <= self.canvas_h:
            new_top = int((self.canvas_h - dh) / 2)
        else:
            new_top = max(self.canvas_h - dh, min(0, new_top))

        self.image_display.left = new_left
        self.image_display.top = new_top
        self.page.update()

    def validate_and_next(self, e):
        # Guard against invalid index / no images to avoid IndexError
        if not self.image_paths or self.current_index >= len(self.image_paths):
            self.status_text.value = "Aucune image à traiter"
            self.page.update()
            return

        try:
            left_on_display = self.image_display.left or 0
            top_on_display = self.image_display.top or 0
            crop_x = int(max(0, -left_on_display) / self.current_scale)
            crop_y = int(max(0, -top_on_display) / self.current_scale)
            crop_w = int(self.canvas_w / self.current_scale)
            crop_h = int(self.canvas_h / self.current_scale)
            self.status_text.value = "Enregistrement en cours..."
            self.page.update()
        except Exception:
            pass

        # Calcul de la zone visible dans les coordonnées de l'image originale
        left = self.image_display.left or 0
        top = self.image_display.top or 0
        crop_x = int(max(0, -left) / self.current_scale)
        crop_y = int(max(0, -top) / self.current_scale)
        crop_w = int(self.canvas_w / self.current_scale)
        crop_h = int(self.canvas_h / self.current_scale)

        # Limitation aux dimensions de l'image
        crop_x = max(0, min(self.orig_w - 1, crop_x))
        crop_y = max(0, min(self.orig_h - 1, crop_y))
        crop_w = max(1, min(self.orig_w - crop_x, crop_w))
        crop_h = max(1, min(self.orig_h - crop_y, crop_h))

        # Recadrage et sauvegarde
        pil_crop = self.current_pil_image.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))
        base = os.path.basename(self.image_paths[self.current_index])
        name, ext = os.path.splitext(base)
        fmt_short = self.current_format_label.split()[0]
        out_path = f"{fmt_short}_{name}_crop_{self.current_index + 1}{ext}"
        pil_crop.convert('RGB').save(out_path)
        self.status_text.value = f"✓ {os.path.basename(out_path)}"
        self.page.update()

        # If in batch interactive mode, advance to next image instead of closing
        if self.batch_mode:
            self.current_index += 1
            if self.current_index < len(self.image_paths):
                self.load_image()
                return
            else:
                # finished batch interactive: clear image visual completely
                self.batch_mode = False
                self.image_display.src = ""
                self.image_display.width = 0
                self.image_display.height = 0
                self.image_display.visible = False
                self.image_stack.controls = []
                self.canvas_container.visible = False
                self.validate_button.visible = False
                self.status_text.value = "✓ Toutes les images traitées !"
                self.page.update()
                return
                

        # Close the window after saving the current crop (single image mode)
        try:
            self.page.window_close()
        except Exception:
            # fallback: force terminate the process if window_close unavailable
            try:
                import os as _os
                _os._exit(0)
            except Exception:
                pass

    def change_ratio(self, e):
        self.current_ratio = FORMATS[e.control.value]
        # remember the human-readable format label for naming
        try:
            self.current_format_label = e.control.value
        except Exception:
            pass
        self.update_canvas_size()
        # If an image is loaded, reload it to recompute display scale and clamp
        if self.image_paths:
            self.load_image()

    def close_app(self, e=None):
        # attempt graceful window close then schedule external kill to force termination
        try:
            self.page.window_close()
        except Exception:
            pass

    def on_zoom_change(self, e):
        # slider value is the zoom multiplier (1.0 = base scale)
        try:
            val = float(e.control.value)
        except Exception:
            return
        # ensure zoom not below 1.0 (image must cover canvas)
        if val < 1.0:
            val = 1.0
        self.zoom_factor = val
        # if an image is loaded, recompute display sizes and preserve focal point (canvas center)
        if getattr(self, 'orig_w', None) is not None:
            old_scale = getattr(self, 'current_scale', self.base_scale)
            old_left = getattr(self.image_display, 'left', 0) or 0
            old_top = getattr(self.image_display, 'top', 0) or 0
            # canvas center coordinates
            cx = self.canvas_w / 2
            cy = self.canvas_h / 2
            # image coordinate (in original image space) under canvas center
            img_x = (cx - old_left) / old_scale
            img_y = (cy - old_top) / old_scale

            # new scale and display sizes
            self.current_scale = self.base_scale * self.zoom_factor
            self.display_w = int(self.orig_w * self.current_scale)
            self.display_h = int(self.orig_h * self.current_scale)

            # compute new left/top so the same image coord stays under canvas center
            new_left = int(cx - img_x * self.current_scale)
            new_top = int(cy - img_y * self.current_scale)

            # clamp so image still covers canvas
            if self.display_w <= self.canvas_w:
                new_left = int((self.canvas_w - self.display_w) / 2)
            else:
                min_left = int(self.canvas_w - self.display_w)
                new_left = max(min_left, min(0, new_left))

            if self.display_h <= self.canvas_h:
                new_top = int((self.canvas_h - self.display_h) / 2)
            else:
                min_top = int(self.canvas_h - self.display_h)
                new_top = max(min_top, min(0, new_top))

            self.image_display.width = self.display_w
            self.image_display.height = self.display_h
            self.image_display.left = new_left
            self.image_display.top = new_top
            self.page.update()
        # update zoom label
        try:
            self.zoom_label.value = f"{int(self.zoom_factor * 100)}%"
            self.page.update()
        except Exception:
            pass

    def batch_process_interactive(self, e):
        # Load all images from current folder and allow manual validation per image
        folder = os.getcwd()
        imgs = [f for f in os.listdir(folder) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        if not imgs:
            self.status_text.value = "Aucune image trouvée"
            self.page.update()
            return

        # Prepare full paths and enter batch interactive mode
        self.image_paths = [os.path.join(folder, f) for f in imgs]
        self.current_index = 0
        self.batch_mode = True
        self.load_image()

    def toggle_orientation(self, e):
        # Toggle between portrait and landscape canvas
        self.canvas_is_portrait = not self.canvas_is_portrait
        self.update_canvas_size()
        if self.image_paths:
            self.load_image(preserve_orientation=True)

#############################################################
#                           MAIN                            #
#############################################################
def main(page: ft.Page):
    page.title = "Photo Cropper"
    page.theme_mode = ft.ThemeMode.DARK
    page.window.maximized = True

    app = PhotoCropper(page)
    # create zoom slider control instance so PhotoCropper can reset it
    app.zoom_slider = ft.Slider(value=1.0, min=1.0, max=3.0, divisions=40, on_change=app.on_zoom_change)

    controls = ft.Column([
        ft.Text("Formats Photos", size=20, weight="bold"),
        ft.RadioGroup(
            content=ft.Column([
                ft.Radio(value=fmt, label=fmt) for fmt in FORMATS.keys()
            ]),
            value="10x15 (102x152mm)",
            on_change=app.change_ratio
        ),
        ft.Divider(),
          ft.Text("Zoom", size=14),
          ft.Row([app.zoom_label, ft.Container(width=8)]),
          app.zoom_slider,
        # Buttons for manual file/folder selection removed; app auto-starts batch
          ft.Button("Orientation",
              icon=ft.icons.Icons.SWAP_HORIZ,
              on_click=app.toggle_orientation),
          ft.Row([app.validate_button, app.close_button]),
    ], width=250) # pyright: ignore[reportArgumentType]

    page.add(
        ft.Stack([
            ft.Row([
                ft.Container(
                    content=app.canvas_container,
                    expand=True,
                    alignment=ft.Alignment.CENTER,
                ),
                ft.VerticalDivider(width=1),
                controls
            ], expand=True),
            ft.Container(
                content=app.status_text,
                bgcolor=ft.Colors.with_opacity(0.8, ft.Colors.BLUE_GREY_900),
                padding=10,
                border_radius=8,
                right=20,
                bottom=20,
            ),
        ], expand=True)
    )

    # Start directly in interactive batch mode on launch
    try:
        app.batch_process_interactive(None)
    except Exception:
        pass

# Utilisation de la syntaxe recommandée pour éviter le DeprecationWarning
if __name__ == "__main__":
    ft.run(main)