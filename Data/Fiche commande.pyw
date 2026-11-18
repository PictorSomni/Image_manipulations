# -*- coding: utf-8 -*-
"""
Fiche commande.pyw — fiches de commande des photos de classe (Flet)
===================================================================

Remplace COMMANDE/Order.pyw : la fiche (rubriques, articles, prix,
objets montrés avec la photo) se modifie ici, s'enregistre en modèles
réutilisables, puis une fiche JPEG est créée par photo du dossier dans
« Fiches ». La grande photo de chaque fiche est filigranée.

Variable d'environnement : FOLDER_PATH — dossier des photos.
Moteur : Data/fiche_commande.py.
"""
import asyncio
import base64
import io
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import CONSTANTS  # noqa: E402
import flet as ft  # noqa: E402
import fiche_commande as fc  # noqa: E402
from PIL import Image  # noqa: E402

DARK = CONSTANTS.COLOR_DARK
BACKGROUND = CONSTANTS.COLOR_BACKGROUND
GREY = CONSTANTS.COLOR_GREY
LIGHT_GREY = CONSTANTS.COLOR_LIGHT_GREY
WHITE = CONSTANTS.COLOR_WHITE
BLUE = CONSTANTS.COLOR_BLUE
GREEN = CONSTANTS.COLOR_GREEN
RED = CONSTANTS.COLOR_RED
YELLOW = CONSTANTS.COLOR_YELLOW
VIOLET = CONSTANTS.COLOR_VIOLET
ORANGE = CONSTANTS.COLOR_ORANGE

FOLDER = os.environ.get("FOLDER_PATH") or os.getcwd()
NO_OBJ = "—"


def _png_src(img, width=1400):
    img = img.copy()
    img.thumbnail((width, width), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(
        buf.getvalue()).decode()


def _btn(text, icon, color, on_click):
    return ft.FilledButton(
        text, icon=icon, on_click=on_click,
        style=ft.ButtonStyle(bgcolor=color, color=DARK, icon_color=DARK))


PALETTE = [BLUE, VIOLET, GREEN, ORANGE, YELLOW, RED]


def _field(value, on_change, color=WHITE, border=GREY, **kw):
    return ft.TextField(
        value=str(value or ""), on_change=on_change, dense=True,
        color=color, border_color=border, focused_border_color=WHITE,
        text_size=CONSTANTS.TEXT_SM, **kw)


def main(page: ft.Page):
    page.title = "Fiche commande"
    page.bgcolor = BACKGROUND
    page.padding = 12
    page.theme_mode = ft.ThemeMode.DARK

    photos = fc.photos_in(FOLDER) if os.path.isdir(FOLDER) else []
    st = {"name": fc.list_models()[0], "objects": fc.load_objects(),
          "photo": None, "renders": {}, "dirty": False, "gen": 0}
    st["model"] = fc.load_model(st["name"])
    if photos:
        st["photo"] = fc.open_photo(os.path.join(FOLDER, photos[0]))

    preview = ft.Image(src=_png_src(Image.new("RGB", (10, 7), "white")),
                       fit=ft.BoxFit.CONTAIN, expand=True)
    status = ft.Text("", color=LIGHT_GREY, size=CONSTANTS.TEXT_SM)
    progress = ft.ProgressBar(color=GREEN, visible=False, value=0)
    sections_col = ft.Column(spacing=16)

    # ── Aperçu (en tâche de fond, la dernière demande gagne) ────────────
    def refresh(delay=0.5):
        st["gen"] += 1
        page.run_task(_render, st["gen"], delay)

    async def _render(gen, delay):
        await asyncio.sleep(delay)
        if gen != st["gen"]:
            return
        label = os.path.splitext(photos[0])[0] if photos else ""
        try:
            img = await asyncio.to_thread(
                fc.render_sheet, st["model"], st["objects"], st["photo"],
                label, st["renders"])
            src = await asyncio.to_thread(_png_src, img)
        except Exception as exc:  # objet manquant, image illisible…
            status.value = f"Aperçu impossible : {exc}"
            page.update()
            return
        if gen == st["gen"]:
            preview.src = src
            page.update()

    def changed(redraw=False):
        st["dirty"] = True
        save_btn.style.bgcolor = ORANGE
        if redraw:
            draw_sections()
        page.update()
        refresh()

    # ── Éditeur des rubriques ───────────────────────────────────────────
    def obj_options():
        return [ft.DropdownOption(key=NO_OBJ, text=NO_OBJ)] + [
            ft.DropdownOption(key=k, text=o["name"])
            for k, o in sorted(st["objects"].items(),
                               key=lambda kv: kv[1]["name"].lower())]

    def move(lst, i, d):
        j = i + d
        if 0 <= j < len(lst):
            lst[i], lst[j] = lst[j], lst[i]
            changed(True)

    def item_row(sec, i, it, tint):
        def set_(key):
            def _h(e):
                it[key] = e.control.value
                changed()
            return _h

        def set_obj(e):
            it["object"] = (None if e.control.value == NO_OBJ
                            else e.control.value)
            changed()

        def toggle(e):
            it["on"] = e.control.value
            changed(True)

        def drop(e):
            sec["items"].pop(i)
            changed(True)
        on = it.get("on", True)
        return ft.Container(ft.Column([
            ft.Row([
                ft.Checkbox(value=on, on_change=toggle, active_color=GREEN),
                _field(it["name"], set_("name"), expand=True,
                       border=tint, text_style=ft.TextStyle(
                           weight=ft.FontWeight.W_600)),
                _field(it["price"], set_("price"), width=70,
                       color=GREEN, border=GREEN,
                       suffix="€", tooltip="Prix"),
                _field(it.get("price2", ""), set_("price2"), width=70,
                       color=YELLOW, border=YELLOW,
                       prefix="+", suffix="€", tooltip="Supplément"),
                ft.IconButton(ft.Icons.ARROW_UPWARD, icon_size=18,
                              icon_color=LIGHT_GREY,
                              on_click=lambda e: move(sec["items"], i, -1)),
                ft.IconButton(ft.Icons.ARROW_DOWNWARD, icon_size=18,
                              icon_color=LIGHT_GREY,
                              on_click=lambda e: move(sec["items"], i, 1)),
                ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_size=18,
                              icon_color=RED, on_click=drop)],
                spacing=4),
            ft.Row([
                ft.Container(width=40),
                _field(it.get("sub", ""), set_("sub"), expand=True,
                       color=LIGHT_GREY, hint_text="Détail"),
                ft.Dropdown(value=it.get("object") or NO_OBJ,
                            options=obj_options(), on_select=set_obj,
                            dense=True, width=210, color=WHITE,
                            text_size=CONSTANTS.TEXT_SM,
                            border_color=VIOLET,
                            leading_icon=ft.Icons.IMAGE_OUTLINED)],
                spacing=4)], spacing=4),
            opacity=1 if on else 0.4, padding=8, border_radius=8,
            bgcolor=ft.Colors.with_opacity(0.07 if i % 2 else 0.14, tint),
            border=ft.Border.only(left=ft.BorderSide(4, tint)))

    def section_box(i, sec):
        def rename(e):
            sec["name"] = e.control.value
            changed()

        def set_col(e):
            sec["col"] = int(e.control.value)
            changed()

        def add_item(e):
            sec["items"].append({"name": "Nouvel article", "sub": "",
                                 "price": "0", "price2": "",
                                 "object": None, "on": True})
            changed(True)

        def drop(e):
            st["model"]["sections"].pop(i)
            changed(True)
        secs = st["model"]["sections"]
        tint = PALETTE[i % len(PALETTE)]
        return ft.Container(ft.Column([
            ft.Container(ft.Row([
                _field(sec["name"], rename, expand=True, color=DARK,
                       border=DARK, text_style=ft.TextStyle(
                           weight=ft.FontWeight.BOLD, size=17)),
                ft.Dropdown(value=str(sec.get("col", 0)), width=96,
                            label="Colonne", border_color=DARK,
                            label_style=ft.TextStyle(color=DARK),
                            dense=True, color=DARK, on_select=set_col,
                            text_size=CONSTANTS.TEXT_SM,
                            options=[ft.DropdownOption(
                                key=str(c), text=str(c + 1))
                                for c in range(3)]),
                ft.IconButton(ft.Icons.ARROW_UPWARD, icon_color=DARK,
                              on_click=lambda e: move(secs, i, -1)),
                ft.IconButton(ft.Icons.ARROW_DOWNWARD, icon_color=DARK,
                              on_click=lambda e: move(secs, i, 1)),
                ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_color=DARK,
                              on_click=drop)]),
                bgcolor=tint, border_radius=8,
                padding=ft.Padding.only(left=8, top=10, bottom=6)),
            *[item_row(sec, j, it, tint)
              for j, it in enumerate(sec["items"])],
            ft.TextButton("Article", icon=ft.Icons.ADD, on_click=add_item,
                          style=ft.ButtonStyle(color=tint))],
            spacing=8), border_radius=10, padding=10,
            bgcolor=ft.Colors.with_opacity(0.06, tint),
            border=ft.Border.all(2, tint))

    def draw_sections():
        m = st["model"]
        sections_col.controls = [
            ft.Container(ft.Column([ft.Row([
                _field(m.get("deadline", ""),
                       lambda e: (m.__setitem__("deadline", e.control.value),
                                  changed()), label="Date limite",
                       color=ORANGE, border=ORANGE, width=200),
                _field(m.get("note", ""),
                       lambda e: (m.__setitem__("note", e.control.value),
                                  changed()), label="Note en rouge",
                       color=RED, border=RED, expand=True)]),
                _field(m.get("footer", ""),
                       lambda e: (m.__setitem__("footer", e.control.value),
                                  changed()), label="Bas de fiche · {date}",
                       border=LIGHT_GREY, multiline=True, min_lines=2)],
                spacing=16), padding=ft.Padding.only(top=14, bottom=6)),
            *[section_box(i, s) for i, s in enumerate(m["sections"])],
            ft.TextButton("Rubrique", icon=ft.Icons.ADD,
                          on_click=add_section,
                          style=ft.ButtonStyle(color=BLUE))]

    def add_section(e):
        st["model"]["sections"].append(
            {"name": "Nouvelle rubrique", "col": 2, "items": []})
        changed(True)

    # ── Modèles ─────────────────────────────────────────────────────────
    model_dd = ft.Dropdown(value=st["name"], width=260, dense=True,
                           color=WHITE,
                           options=[ft.DropdownOption(key=n, text=n)
                                    for n in fc.list_models()])

    def load(e=None):
        st["name"] = model_dd.value
        st["model"] = fc.load_model(st["name"])
        st["dirty"] = False
        save_btn.style.bgcolor = GREEN
        draw_sections()
        page.update()
        refresh(0)
    model_dd.on_select = load

    def save(e=None):
        fc.save_model(st["name"], st["model"])
        st["dirty"] = False
        save_btn.style.bgcolor = GREEN
        status.value = f"« {st['name']} » enregistré"
        page.update()

    def ask_name(title, on_ok, value=""):
        f = _field(value, None, autofocus=True)

        def ok(e):
            name = f.value.strip().replace("/", "-").replace("\\", "-")
            page.pop_dialog()
            if name:
                on_ok(name)
        f.on_submit = ok
        page.show_dialog(ft.AlertDialog(
            title=ft.Text(title), content=f,
            actions=[ft.TextButton("Annuler",
                                   on_click=lambda e: page.pop_dialog()),
                     _btn("OK", ft.Icons.CHECK, GREEN, ok)]))

    def save_as(e):
        def _do(name):
            st["name"] = name
            save()
            model_dd.options = [ft.DropdownOption(key=n, text=n)
                                for n in fc.list_models()]
            model_dd.value = name
            page.update()
        ask_name("Nom du modèle", _do, st["name"] + " copie")

    def delete(e):
        if len(fc.list_models()) <= 1:
            return

        def ok(e):
            page.pop_dialog()
            fc.delete_model(st["name"])
            names = fc.list_models()
            model_dd.options = [ft.DropdownOption(key=n, text=n)
                                for n in names]
            model_dd.value = names[0]
            load()
        page.show_dialog(ft.AlertDialog(
            title=ft.Text(f"Supprimer « {st['name']} » ?"),
            actions=[ft.TextButton("Annuler",
                                   on_click=lambda e: page.pop_dialog()),
                     _btn("Supprimer", ft.Icons.DELETE, RED, ok)]))

    save_btn = _btn("Enregistrer", ft.Icons.SAVE, GREEN, save)

    # ── Objets : photo de l'objet, masque, zone de la photo ─────────────
    def objects_dialog(e=None):
        rows = [ft.ListTile(
            title=ft.Text(o["name"], color=WHITE),
            leading=ft.Icon(ft.Icons.IMAGE_OUTLINED, color=BLUE),
            on_click=lambda e, k=k: (page.pop_dialog(), edit_object(k)))
            for k, o in sorted(st["objects"].items(),
                               key=lambda kv: kv[1]["name"].lower())]
        page.show_dialog(ft.AlertDialog(
            title=ft.Text("Objets"),
            content=ft.Column(rows, scroll=ft.ScrollMode.AUTO, width=360,
                              height=480),
            actions=[_btn("Nouvel objet", ft.Icons.ADD, GREEN,
                          lambda e: (page.pop_dialog(), edit_object(None))),
                     ft.TextButton("Fermer",
                                   on_click=lambda e: page.pop_dialog())]))

    def edit_object(key):
        obj = dict(st["objects"].get(key) or {
            "name": "Nouvel objet", "bg": "", "alpha": "",
            "box": [0, 0, 100, 100], "fit": False, "orient": False})
        view = 460
        img = ft.Image(src=_png_src(Image.new("RGB", (10, 10), "grey")),
                       width=view, height=view, fit=ft.BoxFit.CONTAIN)
        rect = ft.Container(border=ft.Border.all(3, RED), left=0, top=0,
                            width=0, height=0)
        sample = ft.Image(src=_png_src(Image.new("RGB", (10, 10), "grey")),
                          width=260, height=260, fit=ft.BoxFit.CONTAIN)
        geo = {"scale": 1, "ox": 0, "oy": 0, "start": None}
        name = _field(obj["name"], None, label="Nom")
        fit = ft.Checkbox(label="Photo entière, sans recadrer",
                          value=obj.get("fit", False))
        orient = ft.Checkbox(label="Tourner pour les photos en paysage",
                             value=obj.get("orient", False))

        def place():
            bg = fc._asset(obj["bg"]) if obj["bg"] else None
            if bg is None:
                return
            sc = min(view / bg.width, view / bg.height)
            geo.update(scale=sc, ox=(view - bg.width * sc) / 2,
                       oy=(view - bg.height * sc) / 2)
            img.src = _png_src(bg, 700)
            l, u, r, d = obj["box"]
            rect.left, rect.top = geo["ox"] + l * sc, geo["oy"] + u * sc
            rect.width, rect.height = (r - l) * sc, (d - u) * sc
            redo_sample()

        def redo_sample():
            if st["photo"] is None or not obj["bg"]:
                return
            obj["fit"], obj["orient"] = fit.value, orient.value
            sample.src = _png_src(fc.render_object(st["photo"], obj), 500)

        def to_px(p):
            sc = geo["scale"]
            bg = fc._asset(obj["bg"])
            return (min(bg.width, max(0, (p.x - geo["ox"]) / sc)),
                    min(bg.height, max(0, (p.y - geo["oy"]) / sc)))

        def pan_start(e):
            if obj["bg"]:
                geo["start"] = to_px(e.local_position)

        def pan_update(e):
            if not geo["start"]:
                return
            (x0, y0), (x1, y1) = geo["start"], to_px(e.local_position)
            obj["box"] = [round(min(x0, x1)), round(min(y0, y1)),
                          round(max(x0, x1)), round(max(y0, y1))]
            sc = geo["scale"]
            l, u, r, d = obj["box"]
            rect.left, rect.top = geo["ox"] + l * sc, geo["oy"] + u * sc
            rect.width, rect.height = (r - l) * sc, (d - u) * sc
            rect.update()

        def pan_end(e):
            geo["start"] = None
            redo_sample()
            page.update()

        async def pick(kind):
            files = await ft.FilePicker().pick_files(
                allowed_extensions=["png"])
            if not files or not files[0].path:
                return
            src = files[0].path
            dst = os.path.join(fc.ASSETS, os.path.basename(src))
            if os.path.abspath(src) != os.path.abspath(dst):
                shutil.copy2(src, dst)
            fc._img_cache.pop(os.path.basename(dst), None)
            obj[kind] = os.path.basename(dst)
            if kind == "bg" and obj["box"] == [0, 0, 100, 100]:
                bg = fc._asset(obj["bg"])
                obj["box"] = [0, 0, bg.width, bg.height]
            place()
            page.update()

        def ok(e):
            if not obj["bg"]:
                return
            obj["name"] = name.value.strip() or "Objet"
            obj["fit"], obj["orient"] = fit.value, orient.value
            k = key or "obj_%d" % int(time.time())
            st["objects"][k] = obj
            fc.save_objects(st["objects"])
            st["renders"].pop(k, None)
            page.pop_dialog()
            changed(True)

        fit.on_change = orient.on_change = lambda e: (redo_sample(),
                                                      page.update())
        place()
        page.show_dialog(ft.AlertDialog(
            title=ft.Text("Objet"),
            content=ft.Row([
                ft.GestureDetector(
                    content=ft.Stack([img, rect], width=view, height=view),
                    on_pan_start=pan_start, on_pan_update=pan_update,
                    on_pan_end=pan_end,
                    mouse_cursor=ft.MouseCursor.PRECISE),
                ft.Column([
                    name,
                    ft.Row([_btn("Objet", ft.Icons.IMAGE, BLUE,
                                 lambda e: page.run_task(pick, "bg")),
                            _btn("Masque", ft.Icons.GRADIENT, VIOLET,
                                 lambda e: page.run_task(pick, "alpha"))]),
                    fit, orient, sample], width=300)],
                vertical_alignment=ft.CrossAxisAlignment.START),
            actions=[ft.TextButton("Annuler",
                                   on_click=lambda e: page.pop_dialog()),
                     _btn("OK", ft.Icons.CHECK, GREEN, ok)]))

    # ── Création des fiches ─────────────────────────────────────────────
    def generate(e):
        if not photos:
            return
        if st["dirty"]:
            save()
        out = os.path.join(FOLDER, "Fiches")
        os.makedirs(out, exist_ok=True)
        gen_btn.disabled = True
        progress.visible = True
        page.update()

        async def _run():
            for n, f in enumerate(photos, 1):
                status.value = f"{n} / {len(photos)} · {f}"
                progress.value = (n - 1) / len(photos)
                page.update()
                await asyncio.to_thread(_one, f)
            status.value = f"{len(photos)} fiches dans « Fiches »"
            progress.visible = False
            gen_btn.disabled = False
            page.update()

        def _one(f):
            sheet = fc.make_sheet(st["model"], st["objects"],
                                  os.path.join(FOLDER, f))
            sheet.save(os.path.join(out, os.path.splitext(f)[0] + ".jpg"),
                       "JPEG", quality=95, subsampling=0, dpi=(300, 300))
        page.run_task(_run)

    gen_btn = _btn(f"Créer {len(photos)} fiches", ft.Icons.PRINT, BLUE,
                   generate)
    if not photos:
        gen_btn.disabled = True
        status.value = "Aucune photo dans le dossier"

    draw_sections()
    page.add(ft.Row([
        ft.Column([
            ft.Row([model_dd, save_btn,
                    ft.IconButton(ft.Icons.COPY_ALL, icon_color=BLUE,
                                  tooltip="Enregistrer sous",
                                  on_click=save_as),
                    ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_color=RED,
                                  tooltip="Supprimer le modèle",
                                  on_click=delete),
                    ft.IconButton(ft.Icons.CATEGORY_OUTLINED,
                                  icon_color=VIOLET, tooltip="Objets",
                                  on_click=objects_dialog)]),
            ft.Container(ft.Column([sections_col],
                                   scroll=ft.ScrollMode.AUTO),
                         expand=True)], width=640),
        ft.Column([
            ft.Container(preview, expand=True, bgcolor=WHITE,
                         border_radius=6),
            ft.Row([gen_btn, ft.Container(status, expand=True)]),
            progress], expand=True)], expand=True,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH))
    refresh(0)


ft.run(main)
