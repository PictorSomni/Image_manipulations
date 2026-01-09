# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
import flet as ft
import os
from PIL import Image

# ===================== Configuration ===================== #
MAX_CANVAS_SIZE = 1200  # Taille max du canvas
CONTROLS_WIDTH = 270    # Largeur de la colonne de contrôles
ZOOM_SENSIBILITY = 5000   # Sensibilité du zoom
DPI = 300  # Résolution d'export

# Formats d'impression (largeur_mm, hauteur_mm) - en portrait
FORMATS = {
    "10x15 (102x152mm)": (102, 152),
    "13x18 (127x178mm)": (127, 178),
    "15x20 (152x203mm)": (152, 203),
    "20x30 (203x305mm)": (203, 305),
}

def mm_to_pixels(mm, dpi=DPI):
    """Convertit des millimètres en pixels à la résolution donnée"""
    return int(mm / 25.4 * dpi)

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
        self.current_format = FORMATS["10x15 (102x152mm)"]
        self.current_format_label = "10x15 (102x152mm)"
        self.border_13x15 = False
        self.canvas_w = 800  # Valeur initiale, ajustée au chargement
        self.canvas_h = self.canvas_w * self.current_format[1] / self.current_format[0]

        # Gestion du zoom et transformation (contrôlées manuellement)
        self.scale = 1.0          # Scale actuel
        self.offset_x = 0.0       # Offset X en pixels
        self.offset_y = 0.0       # Offset Y en pixels
        self.base_scale = 1.0
        self.drag_start_x = 0.0
        self.drag_start_y = 0.0

        # Option noir et blanc
        self.is_bw = False

        # Image principale
        self.image_display = ft.Image(
            src="",
        )
        
        # Container positionné dans un Stack avec scale pour le zoom
        self.image_container = ft.Container(
            content=self.image_display,
            left=0,
            top=0,
        )
        
        # Stack pour positionner l'image
        self.image_stack = ft.Stack(
            controls=[self.image_container],
            width=self.canvas_w,
            height=self.canvas_h,
        )

        # GestureDetector pour gérer le pan et zoom manuellement
        self.gesture_detector = ft.GestureDetector(
            content=self.image_stack,
            on_pan_start=self.on_pan_start,
            on_pan_update=self.on_pan_update,
            on_scroll=self.on_scroll,
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

        # Ignore button to skip current image
        self.ignore_button = ft.Button(
            "Ignorer Image",
            icon=ft.icons.Icons.BLOCK,
            bgcolor=ft.Colors.RED_700,
            color=ft.Colors.WHITE,
            on_click=self.ignore_image,
        )

        self.border_switch = ft.Switch(label="13x15", value=False, visible=True if "10x15" in self.current_format_label else False, on_change=self.on_border_toggle)
        self.bw_switch = ft.Switch(label="Noir et blanc", value=False, on_change=self.on_bw_toggle)

        self.canvas_container = ft.Container(
            content=self.gesture_detector,
            bgcolor=ft.Colors.WHITE,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            width=self.canvas_w,
            height=self.canvas_h,
            border=ft.Border.all(1, ft.Colors.WHITE24),
        )

    def update_canvas_size(self):
        """Compute optimal canvas size based on available space"""
        available_width = min(self.page.window.width - CONTROLS_WIDTH - 80, MAX_CANVAS_SIZE) if self.page.window.width else 800
        available_height = min(self.page.window.height - 80, MAX_CANVAS_SIZE) if self.page.window.height else 600

        # Calculer le ratio du format choisi
        fmt_w, fmt_h = self.current_format
        if self.canvas_is_portrait:
            target_ratio = fmt_w / fmt_h  # portrait: largeur < hauteur
        else:
            target_ratio = fmt_h / fmt_w  # paysage: largeur > hauteur

        self.canvas_w = available_width
        self.canvas_h = self.canvas_w / target_ratio
        if self.canvas_h > available_height:
            self.canvas_h = available_height
            self.canvas_w = self.canvas_h * target_ratio

        self.canvas_container.width = self.canvas_w
        self.canvas_container.height = self.canvas_h
        self.image_stack.width = self.canvas_w
        self.image_stack.height = self.canvas_h
        self.page.update()

    def load_image(self, preserve_orientation=False):
        if not self.image_paths:
            return
        # Réinitialiser les valeurs de transformation
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.zoom_label.value = "100%"

        path = self.image_paths[self.current_index]
        pil_img = Image.open(path)
        pil_img = pil_img.convert("RGBA")
        self.current_pil_image = pil_img
        self.orig_w, self.orig_h = pil_img.size

        if not preserve_orientation:
            self.canvas_is_portrait = True if self.orig_h >= self.orig_w else False

        self.update_canvas_size()
        
        # Calculer la taille de base pour que l'image COUVRE le canvas (cover)
        scale_w = self.canvas_w / self.orig_w
        scale_h = self.canvas_h / self.orig_h
        self.base_scale = max(scale_w, scale_h)
        
        self.display_w = int(self.orig_w * self.base_scale)
        self.display_h = int(self.orig_h * self.base_scale)

        self.image_display.src = path
        self.image_display.width = self.display_w
        self.image_display.height = self.display_h
        
        # Réinitialiser le scale du container
        self.image_container.scale = 1.0
        
        # Appliquer la transformation initiale
        self._update_transform()

        if "10x15" in self.current_format_label:
            self.border_switch.visible = True
            self.border_switch.value = self.border_13x15
        else:
            self.border_switch.visible = False

        self.page.title = f"Crop: {os.path.basename(path)} ({self.current_index + 1}/{len(self.image_paths)})"
        self.page.update()
    
    def _update_transform(self):
        """Applique scale et offset au container de l'image"""
        # Dimensions zoomées
        zoomed_w = self.display_w * self.scale
        zoomed_h = self.display_h * self.scale
        
        # Position pour centrer l'image + offset utilisateur
        left = (self.canvas_w - zoomed_w) / 2 + self.offset_x
        top = (self.canvas_h - zoomed_h) / 2 + self.offset_y
        
        # Appliquer le scale via la propriété scale du container
        # Le scale s'applique depuis le centre, donc on ajuste la position
        self.image_container.scale = self.scale
        
        # Position du centre du container (avant scale)
        # Avec scale depuis le centre, on doit positionner le coin supérieur gauche
        # tel que le centre de l'image scalée soit au bon endroit
        center_x = left + zoomed_w / 2
        center_y = top + zoomed_h / 2
        
        # left/top sont pour le coin supérieur gauche du container AVANT scale
        # Le container a les dimensions display_w x display_h
        self.image_container.left = center_x - self.display_w / 2
        self.image_container.top = center_y - self.display_h / 2
        
        self.zoom_label.value = f"{int(self.scale * 100)}%"

    def on_pan_start(self, e: ft.DragStartEvent):
        """Début du pan"""
        self.drag_start_x = self.offset_x
        self.drag_start_y = self.offset_y

    def on_pan_update(self, e: ft.DragUpdateEvent):
        """Pendant le pan - déplacer l'image"""
        self.offset_x += e.local_delta.x
        self.offset_y += e.local_delta.y
        self._update_transform()
        self.page.update()

    def on_scroll(self, e: ft.ScrollEvent):
        """Zoom avec la molette (centré sur le canvas)"""
        # Récupérer le delta de scroll
        delta = e.scroll_delta.y
        
        # Calculer le nouveau scale
        zoom_factor = 1 - delta / ZOOM_SENSIBILITY
        old_scale = self.scale
        self.scale = max(0.5, min(10, self.scale * zoom_factor))
        
        # Ajuster l'offset pour zoomer vers le centre du canvas
        if old_scale != self.scale:
            ratio = self.scale / old_scale
            self.offset_x *= ratio
            self.offset_y *= ratio
        
        self._update_transform()
        self.page.update()

    def on_bw_toggle(self, e):
        """Active/désactive le noir et blanc"""
        self.is_bw = e.control.value

    def validate_and_next(self, e):
        if not self.image_paths or self.current_index >= len(self.image_paths):
            self.status_text.value = "Toutes les images ont été traitées."
            self.page.update()
            return

        self.status_text.value = "Enregistrement..."
        self.page.update()

        # ========== DEBUG ==========
        # print(f"=== DEBUG CROP ===")
        # print(f"orig_w={self.orig_w}, orig_h={self.orig_h}")
        # print(f"canvas_w={self.canvas_w}, canvas_h={self.canvas_h}")
        # print(f"display_w={self.display_w}, display_h={self.display_h}")
        # print(f"scale={self.scale}")
        # print(f"offset_x={self.offset_x}, offset_y={self.offset_y}")

        # ========== CALCUL PRÉCIS DU RECADRAGE ==========
        # L'image est affichée à display_w * scale x display_h * scale pixels
        # Elle est positionnée au centre du canvas + offset
        
        zoomed_w = self.display_w * self.scale
        zoomed_h = self.display_h * self.scale
        
        # Position du coin supérieur gauche de l'image dans le canvas
        img_left = (self.canvas_w - zoomed_w) / 2 + self.offset_x
        img_top = (self.canvas_h - zoomed_h) / 2 + self.offset_y
        
        # print(f"zoomed_w={zoomed_w}, zoomed_h={zoomed_h}")
        # print(f"img_left={img_left}, img_top={img_top}")
        
        # Ratio pour convertir pixels affichés -> pixels originaux
        # zoomed_w pixels affichés = orig_w pixels originaux
        px_to_orig = self.orig_w / zoomed_w
        
        # Le canvas montre une fenêtre de (0,0) à (canvas_w, canvas_h)
        # On calcule quel rectangle de l'image originale est visible
        # Si img_left > 0, il y a du blanc à gauche, donc crop_x = 0
        # Si img_left < 0, l'image dépasse à gauche, crop_x = -img_left converti en pixels originaux
        crop_x = -img_left * px_to_orig
        crop_y = -img_top * px_to_orig
        crop_w = self.canvas_w * px_to_orig
        crop_h = self.canvas_h * px_to_orig
        
        # print(f"px_to_orig={px_to_orig}")
        # print(f"crop AVANT clamp: x={crop_x}, y={crop_y}, w={crop_w}, h={crop_h}")
        
        # S'assurer qu'on reste dans les limites de l'image
        crop_x = max(0, crop_x)
        crop_y = max(0, crop_y)
        crop_w = min(self.orig_w - crop_x, crop_w)
        crop_h = min(self.orig_h - crop_y, crop_h)
        
        crop_x = int(crop_x)
        crop_y = int(crop_y)
        crop_w = int(max(1, crop_w))
        crop_h = int(max(1, crop_h))

        pil_crop = self.current_pil_image.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))
        
        # ========== DIMENSIONS FINALES EN MM À 300 DPI ==========
        fmt_w_mm, fmt_h_mm = self.current_format
        if self.canvas_is_portrait:
            target_w_px = mm_to_pixels(fmt_w_mm)
            target_h_px = mm_to_pixels(fmt_h_mm)
        else:
            target_w_px = mm_to_pixels(fmt_h_mm)
            target_h_px = mm_to_pixels(fmt_w_mm)
        
        # Redimensionner pour obtenir les dimensions exactes en pixels à 300 DPI
        pil_crop = pil_crop.resize((target_w_px, target_h_px), Image.Resampling.LANCZOS)
        
        # Appliquer le noir et blanc si activé
        if self.is_bw:
            pil_crop = pil_crop.convert("L")
        
        # Créer un fond blanc et coller l'image transparente dessus
        if pil_crop.mode == "RGBA":
            white_bg = Image.new("RGBA", pil_crop.size, (255, 255, 255, 255))
            pil_crop = Image.alpha_composite(white_bg, pil_crop)
            pil_crop = pil_crop.convert("RGB")
        else:
            pil_crop = pil_crop.convert("RGB")
        
        base = os.path.basename(self.image_paths[self.current_index])
        name, ext = os.path.splitext(base)
        fmt_short = self.current_format_label.split()[0]

        if self.border_13x15 and "10x15" in fmt_short:
            # Le format 13x15 utilise 127mm x 152mm (comme le 13x18 en largeur)
            ratio_13_15 = 127 / 152
            
            if self.canvas_is_portrait:
                target_w = int(pil_crop.height * ratio_13_15)
                framed = Image.new("RGB", (target_w, pil_crop.height), "white")
                framed.paste(pil_crop, (0, 0))
            else:
                target_h = int(pil_crop.width * ratio_13_15)
                framed = Image.new("RGB", (pil_crop.width, target_h), "white")
                framed.paste(pil_crop, (0, 0))
            pil_crop = framed
            fmt_short = "13x15"

        os.makedirs(fmt_short, exist_ok=True)
        out_path = os.path.join(fmt_short, base)
        pil_crop.save(out_path)
        self.status_text.value = f"✓ {os.path.basename(out_path)}"
        self.page.update()

        if self.batch_mode:
            self.current_index += 1
            if self.current_index < len(self.image_paths):
                self.load_image(preserve_orientation=True)
                return
            else:
                self.batch_mode = False
                self.canvas_container.visible = False
                self.validate_button.visible = False
                self.status_text.value = "✓ All images processed!"
                self.page.update()
                return

    def change_ratio(self, e):
        self.current_format = FORMATS[e.control.value]
        try:
            self.current_format_label = e.control.value
        except Exception:
            pass
        if "10x15" in self.current_format_label:
            self.border_switch.visible = True
        else:
            self.border_switch.visible = False
            self.border_switch.value = False
            self.border_13x15 = False
        self.update_canvas_size()
        if self.image_paths:
            self.load_image(preserve_orientation=True)

    def on_border_toggle(self, e):
        self.border_13x15 = bool(e.control.value)

    def batch_process_interactive(self, e):
        folder = os.getcwd()
        imgs = [f for f in os.listdir(folder) if f.lower().endswith(('.png', '.jpg', '.jpeg')) and not f == "watermark.png"]
        if not imgs:
            self.status_text.value = "Aucune image trouvée"
            self.page.update()
            return

        self.image_paths = [os.path.join(folder, f) for f in imgs]
        self.current_index = 0
        self.batch_mode = True
        self.load_image()

    def toggle_orientation(self, e):
        self.canvas_is_portrait = not self.canvas_is_portrait
        self.update_canvas_size()
        if self.image_paths:
            self.load_image(preserve_orientation=True)
        try:
            self.border_switch.visible = True if "10x15" in self.current_format_label else False
        except Exception:
            pass

    def ignore_image(self, e):
        if not self.image_paths or self.current_index >= len(self.image_paths):
            self.status_text.value = "Toutes les images ont été traitées."
            self.page.update()
            return
        
        self.current_index += 1
        self.status_text.value = "Image ignorée."
        self.load_image(preserve_orientation=True)
        self.page.update()

#############################################################
#                           MAIN                            #
#############################################################
def main(page: ft.Page):
    page.title = "Recadrage Photo"
    page.theme_mode = ft.ThemeMode.DARK
    page.window.maximized = True

    app = PhotoCropper(page)

    def on_key(event: ft.KeyboardEvent):
        if event.key == "Enter":
            app.validate_and_next(event)
        elif event.key == "Backspace":
            app.toggle_orientation(event)
        elif event.key == " ":
            app.ignore_image(event)
    page.on_keyboard_event = on_key

    controls = ft.Column([
        ft.Text("Formats Photos", size=20, weight=ft.FontWeight.BOLD),
        ft.RadioGroup(
            content=ft.Column([
                ft.Radio(value=fmt, label=fmt) for fmt in FORMATS.keys()
            ]),
            value="10x15 (102x152mm)",
            on_change=app.change_ratio
        ),
        app.border_switch,
        ft.Divider(),
        ft.Button("Orientation",
            icon=ft.icons.Icons.SWAP_HORIZ,
            on_click=app.toggle_orientation),
        app.bw_switch,
        app.validate_button,
        app.ignore_button
    ], width=250)

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