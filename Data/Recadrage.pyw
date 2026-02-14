# -*- coding: utf-8 -*-

__version__ = "1.6.3"

#############################################################
#                          IMPORTS                          #
#############################################################
import flet as ft
import os
from PIL import Image, ImageOps
import asyncio

# ===================== Configuration ===================== #
MAX_CANVAS_SIZE = 1200  # Taille max du canvas
CONTROLS_WIDTH = 270    # Largeur de la colonne de contrôles
ZOOM_SENSIBILITY = 5000   # Sensibilité du zoom
DPI = 300  # Résolution d'export

# Formats d'impression (largeur_mm, hauteur_mm) - en portrait
FORMATS = {
    "ID (36x46mm)": (36, 46),
    "10x10 (102x102mm)": (102, 102),
    "10x15 (102x152mm)": (102, 152),
    "13x18 (127x178mm)": (127, 178),
    "15x20 (152x203mm)": (152, 203),
    "15x15 (152x152mm)": (152, 152),
    "18x24 (178x240mm)": (178, 240),
    "20x30 (203x305mm)": (203, 305),
    "30x40 (305x405mm)": (305, 405),
    "30x45 (305x455mm)": (305, 455),
    "40x50 (405x505mm)": (405, 505),
    "40x60 (405x605mm)": (405, 605),
    "50x70 (505x705mm)": (505, 705),
    "60x80 (605x805mm)": (605, 805),
    "60x90 (605x905mm)": (605, 905),
    "70x100 (705x1005mm)": (705, 1005)
}

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
        self.border_20x24 = False
        self.border_13x10 = False
        self.border_polaroid = False
        self.border_id2 = False
        self.border_id4 = False
        self.canvas_w = 800  # Valeur initiale, ajustée au chargement
        self.canvas_h = self.canvas_w * self.current_format[1] / self.current_format[0]

        # Gestion du zoom et transformation (contrôlées manuellement)
        self.scale = 1.0          # Scale actuel
        self.offset_x = 0.0       # Offset X en pixels
        self.offset_y = 0.0       # Offset Y en pixels
        self.base_scale = 1.0
        self.pinch_start_scale = 1.0  # Scale au début du pinch

        # Option noir et blanc
        self.is_bw = False

        # Image principale
        self.image_display = ft.Image(
            src="",
            fit=ft.BoxFit.COVER,
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
            on_pan_update=self.on_pan_update,
            on_scroll=self.on_scroll,
            on_scale_start=self.on_scale_start,
            on_scale_update=self.on_scale_update,
            drag_interval=10,
        )

        # visible status fallback when SnackBar is not shown
        self.status_text = ft.Text("")
        # action buttons (created here so main can reference them)
        self.validate_button = ft.Button(
            "Valider & Suivant",
            icon=ft.icons.Icons.CHECK,
            bgcolor=GREEN,
            color=DARK,
            on_click=self.validate_and_next,
        )

        # Ignore button to skip current image
        self.ignore_button = ft.Button(
            "Ignorer Image",
            icon=ft.icons.Icons.BLOCK,
            bgcolor=RED,
            color=DARK,
            on_click=self.ignore_image,
        )

        self.border_switch_13x15 = ft.Switch(label="13x15", active_color=ORANGE, value=False, visible=True if "10x15" in self.current_format_label else False, on_change=self.on_border_toggle_13x15)
        self.border_switch_20x24 = ft.Switch(label="20x24", active_color=ORANGE, value=False, visible=True if "18x24" in self.current_format_label else False, on_change=self.on_border_toggle_20x24)
        self.border_switch_13x10 = ft.Switch(label="13x10", active_color=ORANGE, value=False, visible=True if "10x10" in self.current_format_label else False, on_change=self.on_border_toggle_13x10)
        self.border_switch_polaroid = ft.Switch(label="Polaroid", active_color=ORANGE, value=False, visible=True if "10x10" in self.current_format_label else False, on_change=self.on_border_toggle_polaroid)
        self.border_switch_ID2 = ft.Switch(label="ID X2", active_color=ORANGE, value=False, visible=True if "ID" in self.current_format_label else False, on_change=self.on_border_toggle_id2)
        self.border_switch_ID4 = ft.Switch(label="ID X4", active_color=ORANGE, value=False, visible=True if "ID" in self.current_format_label else False, on_change=self.on_border_toggle_id4)
        self.bw_switch = ft.Switch(label="Noir et blanc", active_color=ORANGE, value=False, on_change=self.on_bw_toggle)

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

        path = self.image_paths[self.current_index]
        
        # Vérifier que le fichier existe et est accessible
        if not os.path.isfile(path) or not os.access(path, os.R_OK):
            self.status_text.value = f"Fichier inaccessible: {os.path.basename(path)}"
            self.page.update()
            # Passer à l'image suivante automatiquement
            self.current_index += 1
            if self.current_index < len(self.image_paths):
                self.load_image(preserve_orientation)
            return
        
        try:
            pil_img = Image.open(path)
            # Appliquer la rotation EXIF pour corriger l'orientation
            pil_img = ImageOps.exif_transpose(pil_img)
            pil_img = pil_img.convert("RGBA")
            self.current_pil_image = pil_img
            self.orig_w, self.orig_h = pil_img.size
        except Exception as e:
            self.status_text.value = f"Erreur lors du chargement: {os.path.basename(path)} - {str(e)}"
            self.page.update()
            # Passer à l'image suivante automatiquement
            self.current_index += 1
            if self.current_index < len(self.image_paths):
                self.load_image(preserve_orientation)
            return

        if not preserve_orientation:
            self.canvas_is_portrait = True if self.orig_h >= self.orig_w else False

        self.update_canvas_size()
        
        # Calculer la taille de base pour que l'image COUVRE le canvas (cover)
        scale_w = self.canvas_w / self.orig_w
        scale_h = self.canvas_h / self.orig_h
        self.base_scale = max(scale_w, scale_h)
        
        # S'assurer que le canvas est entièrement couvert même après l'arrondi
        self.display_w = max(int(round(self.orig_w * self.base_scale)), int(self.canvas_w))
        self.display_h = max(int(round(self.orig_h * self.base_scale)), int(self.canvas_h))

        self.image_display.src = path
        self.image_display.width = self.display_w
        self.image_display.height = self.display_h
        
        # Réinitialiser le scale du container
        self.image_container.scale = 1.0

        # Appliquer la transformation initiale en forçant l'image à couvrir le canevas
        self._clamp_offsets()
        self._update_transform()

        if "10x15" in self.current_format_label:
            self.border_switch_13x15.visible = True
            self.border_switch_13x15.value = self.border_13x15
        else:
            self.border_switch_13x15.visible = False

        if "18x24" in self.current_format_label:
            self.border_switch_20x24.visible = True
            self.border_switch_20x24.value = self.border_20x24
        else:
            self.border_switch_20x24.visible = False

        if "10x10" in self.current_format_label:
            self.border_switch_13x10.visible = True
            self.border_switch_13x10.value = self.border_13x10
            self.border_switch_polaroid.visible = True
            self.border_switch_polaroid.value = self.border_polaroid
        else:
            self.border_switch_13x10.visible = False
            self.border_switch_polaroid.visible = False

        if "ID" in self.current_format_label:
            self.border_switch_ID2.visible = True
            self.border_switch_ID2.value = self.border_id2
            self.border_switch_ID4.visible = True
            self.border_switch_ID4.value = self.border_id4
        else:
            self.border_switch_ID2.visible = False
            self.border_switch_ID4.visible = False

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

    def _clamp_offsets(self):
        """Contraint les offsets pour empêcher l'image de sortir du canevas"""
        zoomed_w = self.display_w * self.scale
        zoomed_h = self.display_h * self.scale

        if zoomed_w <= self.canvas_w:
            self.offset_x = 0
        else:
            max_offset_x = (zoomed_w - self.canvas_w) / 2
            self.offset_x = min(max_offset_x, max(-max_offset_x, self.offset_x))

        if zoomed_h <= self.canvas_h:
            self.offset_y = 0
        else:
            max_offset_y = (zoomed_h - self.canvas_h) / 2
            self.offset_y = min(max_offset_y, max(-max_offset_y, self.offset_y))

    def on_pan_update(self, e: ft.DragUpdateEvent):
        """Pendant le pan - déplacer l'image avec limites aux bords du canvas"""
        # Calculer la nouvelle position
        new_offset_x = self.offset_x + e.local_delta.x
        new_offset_y = self.offset_y + e.local_delta.y
        
        # Dimensions zoomées de l'image
        zoomed_w = self.display_w * self.scale
        zoomed_h = self.display_h * self.scale
        
        # Position théorique (centrée + offset)
        left = (self.canvas_w - zoomed_w) / 2 + new_offset_x
        top = (self.canvas_h - zoomed_h) / 2 + new_offset_y
        
        # Limiter le déplacement pour que l'image reste dans le canvas
        # L'image ne doit pas laisser de blanc
        if zoomed_w > self.canvas_w:
            # L'image est plus large que le canvas
            # left doit être <= 0 et left + zoomed_w >= canvas_w
            max_left = 0
            min_left = self.canvas_w - zoomed_w
            left = max(min_left, min(max_left, left))
            new_offset_x = left - (self.canvas_w - zoomed_w) / 2
        else:
            # L'image est plus petite que le canvas - la centrer
            new_offset_x = 0
        
        if zoomed_h > self.canvas_h:
            # L'image est plus haute que le canvas
            max_top = 0
            min_top = self.canvas_h - zoomed_h
            top = max(min_top, min(max_top, top))
            new_offset_y = top - (self.canvas_h - zoomed_h) / 2
        else:
            # L'image est plus petite que le canvas - la centrer
            new_offset_y = 0
        
        self.offset_x = new_offset_x
        self.offset_y = new_offset_y
        self._clamp_offsets()
        self._update_transform()
        self.page.update()

    def on_scroll(self, e: ft.ScrollEvent):
        """Zoom avec la molette (centré sur le canvas) avec limites"""
        # Récupérer le delta de scroll
        delta = e.scroll_delta.y
        
        # Calculer le nouveau scale
        zoom_factor = 1 - delta / ZOOM_SENSIBILITY
        old_scale = self.scale
        # Scale minimum = 1.0 pour que l'image couvre toujours le canvas
        self.scale = max(1.0, min(10, self.scale * zoom_factor))
        
        # Ajuster l'offset pour zoomer vers le centre du canvas
        if old_scale != self.scale:
            ratio = self.scale / old_scale
            self.offset_x *= ratio
            self.offset_y *= ratio
        
        # Appliquer les limites après le zoom
        zoomed_w = self.display_w * self.scale
        zoomed_h = self.display_h * self.scale
        
        # Calculer la position
        left = (self.canvas_w - zoomed_w) / 2 + self.offset_x
        top = (self.canvas_h - zoomed_h) / 2 + self.offset_y
        
        # Limiter le déplacement
        if zoomed_w > self.canvas_w:
            max_left = 0
            min_left = self.canvas_w - zoomed_w
            left = max(min_left, min(max_left, left))
            self.offset_x = left - (self.canvas_w - zoomed_w) / 2
        else:
            self.offset_x = 0
        
        if zoomed_h > self.canvas_h:
            max_top = 0
            min_top = self.canvas_h - zoomed_h
            top = max(min_top, min(max_top, top))
            self.offset_y = top - (self.canvas_h - zoomed_h) / 2
        else:
            self.offset_y = 0

        self._clamp_offsets()
        self._update_transform()
        self.page.update()

    def on_scale_start(self, e: ft.ScaleStartEvent):
        """Début du pinch-to-zoom (trackpad)"""
        self.pinch_start_scale = self.scale

    def on_scale_update(self, e: ft.ScaleUpdateEvent):
        """Pendant le pinch-to-zoom (trackpad)"""
        old_scale = self.scale
        # Scale minimum = 1.0 pour que l'image couvre toujours le canvas
        self.scale = max(1.0, min(10, self.pinch_start_scale * e.scale))
        
        # Ajuster l'offset pour zoomer vers le centre du canvas
        if old_scale != self.scale:
            ratio = self.scale / old_scale
            self.offset_x *= ratio
            self.offset_y *= ratio
        
        # Appliquer les limites après le zoom
        zoomed_w = self.display_w * self.scale
        zoomed_h = self.display_h * self.scale
        
        # Calculer la position
        left = (self.canvas_w - zoomed_w) / 2 + self.offset_x
        top = (self.canvas_h - zoomed_h) / 2 + self.offset_y
        
        # Limiter le déplacement
        if zoomed_w > self.canvas_w:
            max_left = 0
            min_left = self.canvas_w - zoomed_w
            left = max(min_left, min(max_left, left))
            self.offset_x = left - (self.canvas_w - zoomed_w) / 2
        else:
            self.offset_x = 0
        
        if zoomed_h > self.canvas_h:
            max_top = 0
            min_top = self.canvas_h - zoomed_h
            top = max(min_top, min(max_top, top))
            self.offset_y = top - (self.canvas_h - zoomed_h) / 2
        else:
            self.offset_y = 0

        self._clamp_offsets()
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
        # Force immediate UI update to show "Enregistrement..." message
        self.page.update()

        # ========== CALCUL PRÉCIS DU RECADRAGE ==========
        zoomed_w = self.display_w * self.scale
        zoomed_h = self.display_h * self.scale
        
        img_left = (self.canvas_w - zoomed_w) / 2 + self.offset_x
        img_top = (self.canvas_h - zoomed_h) / 2 + self.offset_y
        
        px_to_orig = self.orig_w / zoomed_w
        
        crop_x = -img_left * px_to_orig
        crop_y = -img_top * px_to_orig
        crop_w = self.canvas_w * px_to_orig
        crop_h = self.canvas_h * px_to_orig
        
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
        
        pil_crop = pil_crop.resize((target_w_px, target_h_px), Image.Resampling.LANCZOS)
        
        if self.is_bw:
            pil_crop = pil_crop.convert("L")
        
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

        if self.border_20x24 and "18x24" in fmt_short:
            ratio_20_24 = 203 / 240
            
            if self.canvas_is_portrait:
                target_w = int(pil_crop.height * ratio_20_24)
                framed = Image.new("RGB", (target_w, pil_crop.height), "white")
                framed.paste(pil_crop, (0, 0))
            else:
                target_h = int(pil_crop.width * ratio_20_24)
                framed = Image.new("RGB", (pil_crop.width, target_h), "white")
                framed.paste(pil_crop, (0, 0))
            pil_crop = framed
            fmt_short = "20x24"

        if self.border_13x10 and "10x10" in fmt_short:
            ratio_13_10 = 127 / 102
            
            if self.canvas_is_portrait:
                target_w = int(pil_crop.height * ratio_13_10)
                framed = Image.new("RGB", (target_w, pil_crop.height), "white")
                framed.paste(pil_crop, (0, 0))
            else:
                target_h = int(pil_crop.width * ratio_13_10)
                framed = Image.new("RGB", (pil_crop.width, target_h), "white")
                framed.paste(pil_crop, (0, 0))
            pil_crop = framed
            fmt_short = "13x10"

        if self.border_polaroid and "10x10" in fmt_short:
            # Image 102x102mm dans un format 127x152mm (polaroid)
            POLAROID_WIDTH_PX = mm_to_pixels(127)
            POLAROID_HEIGHT_PX = mm_to_pixels(152)
            
            framed = Image.new("RGB", (POLAROID_WIDTH_PX, POLAROID_HEIGHT_PX), "white")
            # Centrer l'image 102x102 dans le cadre 127x152
            x_offset = (POLAROID_WIDTH_PX - pil_crop.width) // 2
            y_offset = x_offset  # Même espace en haut que sur les côtés
            framed.paste(pil_crop, (x_offset, y_offset))
            pil_crop = framed
            fmt_short = "Polaroid"

        # Gestion des layouts ID : ID X4 prioritaire sur ID X2
        if self.border_id4 and "ID" in self.current_format_label:
            # 4 images ID (36x46mm chacune) sur un canvas de 127x102mm
            # Layout: grille 2x2
            CANVA_WIDTH_PX = mm_to_pixels(127)
            CANVA_HEIGHT_PX = mm_to_pixels(102)
            SPACE_PX = mm_to_pixels(5)
            
            framed = Image.new("RGB", (CANVA_WIDTH_PX, CANVA_HEIGHT_PX), "white")
            
            # Rotation si nécessaire pour que l'image soit en portrait
            img = pil_crop
            if img.height > img.width:
                img = img.rotate(90, expand=True)
            
            # Calculer les positions pour centrer le bloc de 4 images
            total_width = img.width * 2 + SPACE_PX
            total_height = img.height * 2 + SPACE_PX
            start_x = (CANVA_WIDTH_PX - total_width) // 2
            start_y = (CANVA_HEIGHT_PX - total_height) // 2
            
            # Placer les 4 images en grille 2x2
            for row in range(2):
                for col in range(2):
                    x_pos = start_x + col * (img.width + SPACE_PX)
                    y_pos = start_y + row * (img.height + SPACE_PX)
                    framed.paste(img, (x_pos, y_pos))
            
            pil_crop = framed
            fmt_short = "ID_X4"

        elif self.border_id2 and "ID" in self.current_format_label:
            # 2 images ID (36x46mm chacune) sur un canvas de 102x102mm
            # Layout: 2 lignes, 1 colonne
            CANVA_WIDTH_PX = mm_to_pixels(102)
            CANVA_HEIGHT_PX = mm_to_pixels(102)
            SPACE_PX = mm_to_pixels(5)
            
            framed = Image.new("RGB", (CANVA_WIDTH_PX, CANVA_HEIGHT_PX), "white")
            
            # Rotation si nécessaire pour que l'image soit en portrait
            img = pil_crop
            if img.width > img.height:
                img = img.rotate(90, expand=True)
            
            # Position centrée horizontalement
            x_offset = (CANVA_WIDTH_PX - img.width) // 2
            
            # Première image en haut
            y_offset_1 = SPACE_PX
            framed.paste(img, (x_offset, y_offset_1))
            
            # Deuxième image en bas
            y_offset_2 = CANVA_HEIGHT_PX - img.height - SPACE_PX
            framed.paste(img, (x_offset, y_offset_2))
            
            pil_crop = framed
            fmt_short = "ID_X2"

        os.makedirs(fmt_short, exist_ok=True)
        jpg = name + ".jpg"
        out_path = os.path.join(fmt_short, jpg)
        pil_crop.save(out_path, quality=100, format="JPEG", dpi=(DPI, DPI))
        
        self.status_text.value = f"[OK] {os.path.basename(out_path)}"
        self.page.update()

        if self.batch_mode:
            self.current_index += 1
            if self.current_index < len(self.image_paths):
                self.load_image(preserve_orientation=False)
                return
            else:
                self.batch_mode = False
                self.canvas_container.visible = False
                self.validate_button.visible = False
                self.status_text.value = "[OK] Toutes les images sont traitées !"
                self.page.update()
                asyncio.create_task(self.close_window())
                return

    def change_ratio(self, e=None):
        self.current_format = FORMATS[e.control.value]
        try:
            self.current_format_label = e.control.value
        except Exception:
            pass
        if "10x15" in self.current_format_label:
            self.border_switch_13x15.visible = True
            self.border_switch_20x24.visible = False
            self.border_switch_20x24.value = False
            self.border_20x24 = False
            self.border_switch_13x10.visible = False
            self.border_switch_13x10.value = False
            self.border_13x10 = False
            self.border_switch_ID2.visible = False
            self.border_switch_ID2.value = False
            self.border_switch_ID4.visible = False
            self.border_switch_ID4.value = False

        elif "18x24" in self.current_format_label:
            self.border_switch_20x24.visible = True
            self.border_switch_13x15.visible = False
            self.border_switch_13x15.value = False
            self.border_13x15 = False
            self.border_switch_13x10.visible = False
            self.border_switch_13x10.value = False
            self.border_13x10 = False
            self.border_switch_ID2.visible = False
            self.border_switch_ID2.value = False
            self.border_switch_ID4.visible = False
            self.border_switch_ID4.value = False
            self.border_switch_polaroid.visible = False
            self.border_switch_polaroid.value = False
            self.border_polaroid = False

        elif "10x10" in self.current_format_label:
            self.border_switch_13x10.visible = True
            self.border_switch_polaroid.visible = True
            self.border_switch_13x15.visible = False
            self.border_switch_13x15.value = False
            self.border_13x15 = False
            self.border_switch_ID2.visible = False
            self.border_switch_ID2.value = False
            self.border_switch_ID4.visible = False
            self.border_switch_ID4.value = False
        elif "ID" in self.current_format_label:
            self.border_switch_ID2.visible = True
            self.border_switch_ID4.visible = True
            self.border_switch_13x15.visible = False
            self.border_switch_13x15.value = False
            self.border_13x15 = False
            self.border_switch_13x10.visible = False
            self.border_switch_13x10.value = False
            self.border_13x10 = False
            self.border_switch_polaroid.visible = False
            self.border_switch_polaroid.value = False
            self.border_polaroid = False
        else:
            self.border_switch_13x15.visible = False
            self.border_switch_13x15.value = False
            self.border_13x15 = False
            self.border_switch_20x24.visible = False
            self.border_switch_20x24.value = False
            self.border_20x24 = False
            self.border_switch_13x10.visible = False
            self.border_switch_13x10.value = False
            self.border_13x10 = False
            self.border_switch_ID2.visible = False
            self.border_switch_ID2.value = False
            self.border_switch_ID4.visible = False
            self.border_switch_ID4.value = False
            self.border_switch_polaroid.visible = False
            self.border_switch_polaroid.value = False
            self.border_polaroid = False
        self.update_canvas_size()
        if self.image_paths:
            self.load_image(preserve_orientation=True)

    def on_border_toggle_13x15(self, e):
        self.border_13x15 = bool(e.control.value)

    def on_border_toggle_20x24(self, e):
        self.border_20x24 = bool(e.control.value)

    def on_border_toggle_13x10(self, e):
        self.border_13x10 = bool(e.control.value)
        # Désactiver Polaroid si 13x10 est activé
        if self.border_13x10:
            self.border_polaroid = False
            self.border_switch_polaroid.value = False
            self.page.update()
    
    def on_border_toggle_polaroid(self, e):
        self.border_polaroid = bool(e.control.value)
        # Désactiver 13x10 si Polaroid est activé
        if self.border_polaroid:
            self.border_13x10 = False
            self.border_switch_13x10.value = False
            self.page.update()

    def on_border_toggle_id2(self, e):
        self.border_id2 = bool(e.control.value)
        # Désactiver ID X4 si ID X2 est activé
        if self.border_id2:
            self.border_id4 = False
            self.border_switch_ID4.value = False
            self.page.update()

    def on_border_toggle_id4(self, e):
        self.border_id4 = bool(e.control.value)
        # Désactiver ID X2 si ID X4 est activé
        if self.border_id4:
            self.border_id2 = False
            self.border_switch_ID2.value = False
            self.page.update()

    def batch_process_interactive(self, e):
        import time
        
        folder = os.getcwd()
        
        # Délai plus long pour s'assurer que tous les fichiers sont complètement copiés
        # (évite les problèmes de timing si on lance juste après un copier/coller)
        time.sleep(0.3)
        
        # Récupérer les fichiers sélectionnés depuis le Dashboard (si applicable)
        selected_files_str = os.environ.get("SELECTED_FILES", "")
        selected_files_set = set(selected_files_str.split("|")) if selected_files_str else None
        
        # Lister tous les fichiers du dossier
        try:
            all_files = os.listdir(folder)
        except Exception as e:
            self.status_text.value = f"Erreur lors de la lecture du dossier: {e}"
            self.page.update()
            return
        
        # Filtrer pour ne garder que les images
        imgs = [f for f in all_files if f.lower().endswith(('.png', '.jpg', '.jpeg', '.jpe', '.tif', '.tiff', '.bmp', '.dib', '.gif', '.webp', '.ico', '.pcx', '.tga', '.ppm', '.pgm', '.pbm', '.pnm')) and not f == "watermark.png"]
        
        # Message de diagnostic
        total_images_found = len(imgs)
        
        # Filtrer par les fichiers sélectionnés si applicable
        if selected_files_set:
            imgs = [f for f in imgs if f in selected_files_set]
            # Message d'erreur détaillé si rien ne correspond
            if not imgs and total_images_found > 0:
                self.status_text.value = f"{total_images_found} image(s) trouvée(s) mais aucune ne correspond aux fichiers sélectionnés"
                self.page.update()
                return
        
        if not imgs:
            # Message d'erreur détaillé selon le contexte
            if len(all_files) == 0:
                self.status_text.value = "Le dossier est vide"
            else:
                self.status_text.value = f"Aucune image valide trouvée dans le dossier ({len(all_files)} fichier(s) présent(s))"
            self.page.update()
            return

        # Vérifier que les fichiers sont accessibles et valides
        valid_paths = []
        for img_file in imgs:
            img_path = os.path.join(folder, img_file)
            # Vérifier que le fichier existe et est accessible
            if os.path.isfile(img_path) and os.access(img_path, os.R_OK):
                try:
                    # Essayer d'ouvrir l'image pour vérifier qu'elle est valide
                    with Image.open(img_path) as test_img:
                        test_img.verify()
                    valid_paths.append(img_path)
                except Exception:
                    # Fichier corrompu ou inaccessible, ignorer
                    pass
        
        if not valid_paths:
            self.status_text.value = f"{len(imgs)} image(s) trouvée(s) mais aucune n'est accessible ou valide"
            self.page.update()
            return

        self.image_paths = valid_paths
        self.current_index = 0
        self.batch_mode = True
        self.load_image()

    def toggle_orientation(self, e):
        self.canvas_is_portrait = not self.canvas_is_portrait
        self.update_canvas_size()
        if self.image_paths:
            self.load_image(preserve_orientation=True)

        self.border_switch_13x15.visible = True if "10x15" in self.current_format_label else False

        self.border_switch_13x10.visible = True if "10x10" in self.current_format_label else False

        self.border_switch_polaroid.visible = True if "10x10" in self.current_format_label else False

        self.border_switch_ID2.visible = True if "ID" in self.current_format_label else False

        self.border_switch_ID4.visible = True if "ID" in self.current_format_label else False

    def ignore_image(self, e):
        if not self.image_paths or self.current_index >= len(self.image_paths):
            self.status_text.value = "Toutes les images ont été traitées."
            self.page.update()
            asyncio.create_task(self.close_window())
            return
        
        self.current_index += 1
        
        # Vérifier si on a atteint la fin après l'incrémentation
        if self.current_index >= len(self.image_paths):
            self.status_text.value = "Toutes les images ont été traitées."
            self.page.update()
            asyncio.create_task(self.close_window())
            return
            
        self.status_text.value = "Image ignorée."
        self.load_image(preserve_orientation=False)
        self.page.update()

    async def close_window(self, e=None):
        await self.page.window.close()

#############################################################
#                           MAIN                            #
#############################################################
def main(page: ft.Page):
    page.title = "Recadrage Photo"
    page.theme_mode = ft.ThemeMode.DARK
    page.window.maximized = True
    page.bgcolor = BG

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
        ft.Container(
            content=ft.RadioGroup(
                content=ft.Column(
                    [ft.Radio(value=fmt, label=fmt, fill_color=BLUE) for fmt in FORMATS.keys()],
                    scroll=ft.ScrollMode.AUTO,
                ),
                value="10x15 (102x152mm)",
                on_change=app.change_ratio
            ),
            height=500,
            border=ft.Border.all(1, LIGHT_GREY),
            border_radius=8,
            padding=5,
        ),
        app.border_switch_13x15,
        app.border_switch_20x24,
        app.border_switch_13x10,
        app.border_switch_polaroid,
        app.border_switch_ID2,
        app.border_switch_ID4,
        ft.Divider(),
        ft.Button("Orientation",
            icon=ft.icons.Icons.SWAP_HORIZ,
            color=BLUE,
            bgcolor=DARK,
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
                bgcolor=DARK,
                padding=10,
                border_radius=8,
                right=20,
                bottom=20,
            ),
        ], expand=True)
    )

    # Gestionnaire de redimensionnement de la fenêtre
    def on_window_resize(e):
        app.update_canvas_size()
        if app.image_paths:
            app._update_transform()
    
    page.on_resize = on_window_resize

    # Start directly in interactive batch mode on launch (avec délai pour s'assurer que la fenêtre est initialisée)
    async def delayed_start():
        await asyncio.sleep(0.3)  # Attendre que la fenêtre soit maximisée
        try:
            app.batch_process_interactive(None)
            # Forcer un recalcul après le premier chargement pour s'assurer des bonnes dimensions
            await asyncio.sleep(0.1)
            if app.image_paths:
                app.update_canvas_size()
                app.load_image(preserve_orientation=True)
        except Exception:
            pass
    
    asyncio.create_task(delayed_start())

# Utilisation de la syntaxe recommandée pour éviter le DeprecationWarning
if __name__ == "__main__":
    ft.run(main)