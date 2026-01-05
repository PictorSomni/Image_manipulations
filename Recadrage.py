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
        self.border_13x15 = False
        self.canvas_w = 800  # Valeur initiale, ajustée au chargement
        self.canvas_h = self.canvas_w / self.current_ratio

        # Gestion du zoom
        self.zoom_factor = 1.0
        self.base_scale = 1.0

        # Option noir et blanc
        self.is_bw = False

        # Image principale
        self.image_display = ft.Image(
            src="",
            fit="contain",
            width=500,
            height=500,
        )

        # InteractiveViewer pour gérer le zoom et le déplacement naturellement
        self.interactive_viewer = ft.InteractiveViewer(
            min_scale=0.1,
            max_scale=15,
            scale_factor=ZOOM_SENSIBILITY,
            boundary_margin=ft.Margin.all(0),
            on_interaction_start=self.on_interaction_start,
            on_interaction_update=self.on_interaction_update,
            on_interaction_end=self.on_interaction_end,
            content=self.image_display,
        )

        # small label to show zoom percent
        self.zoom_label = ft.Text("100%")
        # visible status fallback when SnackBar is not shown
        self.status_text = ft.Text("")
        # action buttons (created here so main can reference them)
        self.validate_button = ft.Button(
            "Validate & Next",
            icon=ft.icons.Icons.CHECK,
            bgcolor=ft.Colors.GREEN_700,
            color=ft.Colors.WHITE,
            on_click=self.validate_and_next,
        )
        self.border_switch = ft.Switch(label="13x15", value=False, visible=True if "10x15" in self.current_format_label else False, on_change=self.on_border_toggle)
        self.bw_switch = ft.Switch(label="Noir et blanc", value=False, on_change=self.on_bw_toggle)
        self.close_button = ft.Button(
            "Close",
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
            content=self.interactive_viewer,
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

        if self.canvas_is_portrait:
            target_ratio = self.current_ratio
        else:
            target_ratio = 1 / self.current_ratio

        self.canvas_w = available_width
        self.canvas_h = self.canvas_w / target_ratio
        if self.canvas_h > available_height:
            self.canvas_h = available_height
            self.canvas_w = self.canvas_h * target_ratio

        self.canvas_container.width = self.canvas_w
        self.canvas_container.height = self.canvas_h
        self.page.update()

    def load_image(self, preserve_orientation=False):
        if not self.image_paths:
            return
        self.zoom_factor = 1.0
        self.zoom_label.value = "100%"

        path = self.image_paths[self.current_index]
        pil_img = Image.open(path)
        pil_img = pil_img.convert("RGBA")
        self.current_pil_image = pil_img
        self.orig_w, self.orig_h = pil_img.size

        if not preserve_orientation:
            self.canvas_is_portrait = True if self.orig_h >= self.orig_w else False

        self.update_canvas_size()
        scale = min(self.canvas_w / self.orig_w, self.canvas_h / self.orig_h)
        self.base_scale = scale
        self.current_scale = self.base_scale * self.zoom_factor
        self.display_w = int(self.orig_w * self.current_scale)
        self.display_h = int(self.orig_h * self.current_scale)

        self.image_display.src = path
        self.image_display.width = self.display_w
        self.image_display.height = self.display_h

        if "10x15" in self.current_format_label:
            self.border_switch.visible = True
            self.border_switch.value = self.border_13x15
        else:
            self.border_switch.visible = False

        self.page.title = f"Crop: {os.path.basename(path)} ({self.current_index + 1}/{len(self.image_paths)})"
        self.page.update()

    def on_interaction_start(self, e):
        pass

    def on_interaction_update(self, e):
        pass

    def on_interaction_end(self, e):
        pass

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

        crop_x = 0
        crop_y = 0
        crop_w = int(self.orig_w * self.canvas_w / self.display_w) if self.display_w > 0 else self.orig_w
        crop_h = int(self.orig_h * self.canvas_h / self.display_h) if self.display_h > 0 else self.orig_h
        
        crop_x = max(0, min(self.orig_w - 1, crop_x))
        crop_y = max(0, min(self.orig_h - 1, crop_y))
        crop_w = max(1, min(self.orig_w - crop_x, crop_w))
        crop_h = max(1, min(self.orig_h - crop_y, crop_h))

        pil_crop = self.current_pil_image.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))
        
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
            ratio_13_15 = 13 / 15
            
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

        try:
            import asyncio
            asyncio.run(self.page.window.close())
        except Exception:
            pass

    def change_ratio(self, e):
        self.current_ratio = FORMATS[e.control.value]
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

    def close_app(self, e=None):
        try:
            import asyncio
            asyncio.run(self.page.window.close())
        except Exception:
            pass

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
        ft.Row([app.validate_button, app.close_button]),
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