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
import warnings
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

warnings.filterwarnings("ignore", category=DeprecationWarning)

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
LABEL = ft.TextStyle(color=DARK, weight=ft.FontWeight.W_600)


def _field(value, on_change, color=WHITE, border=GREY,
           text_size=CONSTANTS.TEXT_SM, **kw):
    return ft.TextField(
        value=str(value or ""), on_change=on_change, dense=True,
        color=color, border_color=border, focused_border_color=WHITE,
        text_size=text_size, **kw)


def main(page: ft.Page):
    page.title = "Fiche commande"
    page.bgcolor = BACKGROUND
    page.padding = 12
    page.theme_mode = ft.ThemeMode.DARK
    page.window.maximized = True

    photos = fc.photos_in(FOLDER) if os.path.isdir(FOLDER) else []
    st = {"name": fc.list_models()[0], "objects": fc.load_objects(),
          "photo": None, "renders": {}, "dirty": False, "gen": 0,
          "open": set()}
    st["model"] = fc.load_model(st["name"])
    if photos:
        st["photo"] = fc.open_photo(os.path.join(FOLDER, photos[0]))

    preview = ft.Image(src=_png_src(Image.new("RGB", (10, 7), "white")),
                       fit=ft.BoxFit.CONTAIN, expand=True)
    status = ft.Text("", color=LIGHT_GREY, size=CONSTANTS.TEXT_SM)
    progress = ft.ProgressBar(color=GREEN, visible=False, value=0)
    sections_col = ft.Column(spacing=10)

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

    def actions_menu(lst, i, color=LIGHT_GREY):
        """Monter / descendre / supprimer, toujours au même endroit."""
        def drop(e):
            lst.pop(i)
            changed(True)
        return ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT, icon_color=color,
            items=[ft.PopupMenuItem(content="Monter",
                                    icon=ft.Icons.ARROW_UPWARD,
                                    on_click=lambda e: move(lst, i, -1)),
                   ft.PopupMenuItem(content="Descendre",
                                    icon=ft.Icons.ARROW_DOWNWARD,
                                    on_click=lambda e: move(lst, i, 1)),
                   ft.PopupMenuItem(content="Supprimer",
                                    icon=ft.Icons.DELETE_OUTLINE,
                                    on_click=drop)])

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
        on = it.get("on", True)
        return ft.Container(ft.Row([
            ft.Checkbox(value=on, on_change=toggle, active_color=DARK,
                        check_color=tint, border_side=ft.BorderSide(
                            2, DARK)),
            ft.Column([
                _field(it["name"], set_("name"), color=DARK,
                       border=WHITE, filled=True, fill_color=WHITE,
                       cursor_color=DARK, text_style=ft.TextStyle(
                           weight=ft.FontWeight.W_600)),
                _field(it.get("sub", ""), set_("sub"), color=DARK,
                       border=DARK, hint_text="Détail", text_size=12,
                       cursor_color=DARK, hint_style=ft.TextStyle(
                           color=ft.Colors.with_opacity(0.5, DARK)))],
                spacing=6, expand=True),
            _field(it["price"], set_("price"), width=80, color=DARK,
                   border=GREEN, filled=True, fill_color=WHITE,
                   cursor_color=DARK, suffix=ft.Text("€", color=DARK),
                   tooltip="Prix",
                   text_style=ft.TextStyle(weight=ft.FontWeight.BOLD)),
            _field(it.get("price2", ""), set_("price2"), width=80,
                   color=DARK, border=YELLOW, filled=True,
                   fill_color=WHITE, cursor_color=DARK,
                   prefix=ft.Text("+", color=DARK),
                   suffix=ft.Text("€", color=DARK),
                   tooltip="Supplément",
                   text_style=ft.TextStyle(weight=ft.FontWeight.BOLD)),
            ft.Dropdown(value=it.get("object") or NO_OBJ,
                        options=obj_options(), on_select=set_obj,
                        dense=True, width=170, color=DARK,
                        border_color=VIOLET, filled=True, fill_color=WHITE,
                        text_style=ft.TextStyle(color=DARK),
                        text_size=CONSTANTS.TEXT_SM,
                        leading_icon=ft.Icon(ft.Icons.IMAGE_OUTLINED,
                                             color=VIOLET)),
            actions_menu(sec["items"], i, DARK)], spacing=10),
            opacity=1 if on else 0.45, padding=ft.Padding.symmetric(
                horizontal=10, vertical=8), border_radius=8,
            bgcolor=ft.Colors.with_opacity(0.45, WHITE),
            border=ft.Border.all(1, DARK))

    def section_box(i, sec):
        def rename(e):
            sec["name"] = e.control.value
            title.value = sec["name"]
            changed()

        def set_col(e):
            sec["col"] = int(e.control.value)
            changed(True)

        def add_item(e):
            sec["items"].append({"name": "Nouvel article", "sub": "",
                                 "price": "0", "price2": "",
                                 "object": None, "on": True})
            st["open"].add(id(sec))
            changed(True)

        def toggle(e):
            st["open"].symmetric_difference_update({id(sec)})
        tint = PALETTE[i % len(PALETTE)]
        n_on = sum(1 for it in sec["items"] if it.get("on", True))
        title = ft.Text(sec["name"], weight=ft.FontWeight.BOLD, size=17)
        return ft.ExpansionTile(
            title=title,
            subtitle=ft.Text(f"Colonne {sec.get('col', 0) + 1} · "
                             f"{n_on} / {len(sec['items'])} articles",
                             size=CONSTANTS.TEXT_SM),
            expanded=id(sec) in st["open"], on_change=toggle,
            maintain_state=True,
            collapsed_bgcolor=tint, collapsed_text_color=DARK,
            collapsed_icon_color=DARK,
            bgcolor=tint, text_color=DARK, icon_color=DARK,
            shape=ft.RoundedRectangleBorder(radius=10),
            collapsed_shape=ft.RoundedRectangleBorder(radius=10),
            controls_padding=ft.Padding.all(12),
            controls=[
                ft.Row([
                    _field(sec["name"], rename, expand=True, border=DARK,
                           label="Rubrique", color=DARK, filled=True,
                           fill_color=WHITE, cursor_color=DARK,
                           label_style=LABEL),
                    ft.Dropdown(value=str(sec.get("col", 0)), width=110,
                                label="Colonne", border_color=DARK,
                                label_style=LABEL,
                                filled=True, fill_color=WHITE,
                                dense=True, color=DARK,
                                on_select=set_col,
                                text_size=CONSTANTS.TEXT_SM,
                                options=[ft.DropdownOption(
                                    key=str(c), text=str(c + 1))
                                    for c in range(3)]),
                    actions_menu(st["model"]["sections"], i, DARK)],
                    spacing=10),
                ft.Container(height=4),
                ft.Column([item_row(sec, j, it, tint)
                           for j, it in enumerate(sec["items"])],
                          spacing=8),
                ft.Container(ft.Row([ft.FilledButton(
                    "Article", icon=ft.Icons.ADD, on_click=add_item,
                    style=ft.ButtonStyle(bgcolor=DARK, color=tint,
                                         icon_color=tint))],
                    alignment=ft.MainAxisAlignment.END),
                    padding=ft.Padding.only(top=6, bottom=6))])

    def draw_sections():
        m = st["model"]

        def set_m(key):
            def _h(e):
                m[key] = e.control.value
                changed()
            return _h
        sections_col.controls = [
            ft.ExpansionTile(
                title=ft.Text("Fiche", weight=ft.FontWeight.BOLD, size=17),
                subtitle=ft.Text(f"Pour le {m.get('deadline', '')}",
                                 size=CONSTANTS.TEXT_SM),
                expanded="fiche" in st["open"],
                on_change=lambda e: st["open"].symmetric_difference_update(
                    {"fiche"}),
                collapsed_bgcolor=LIGHT_GREY, collapsed_text_color=DARK,
                collapsed_icon_color=DARK, text_color=DARK,
                icon_color=DARK, bgcolor=LIGHT_GREY,
                shape=ft.RoundedRectangleBorder(radius=10),
                collapsed_shape=ft.RoundedRectangleBorder(radius=10),
                controls_padding=ft.Padding.only(left=12, right=12,
                                                 top=16, bottom=12),
                controls=[ft.Column([
                    ft.Row([
                        _field(m.get("deadline", ""), set_m("deadline"),
                               label="Date limite",
                               color=ft.Colors.DEEP_ORANGE_900,
                               border=DARK, width=200, filled=True,
                               fill_color=WHITE, cursor_color=DARK,
                               label_style=LABEL),
                        _field(m.get("note", ""), set_m("note"),
                               label="Note en rouge",
                               color=ft.Colors.RED_800,
                               border=DARK, expand=True, filled=True,
                               fill_color=WHITE, cursor_color=DARK,
                               label_style=LABEL)]),
                    _field(m.get("footer", ""), set_m("footer"),
                           label="Bas de fiche · {date}",
                           border=DARK, multiline=True, min_lines=2,
                           color=DARK, filled=True, fill_color=WHITE,
                           cursor_color=DARK, label_style=LABEL)],
                    spacing=18)]),
            *[section_box(i, s) for i, s in enumerate(m["sections"])],
            ft.Row([ft.FilledButton(
                "Rubrique", icon=ft.Icons.ADD, on_click=add_section,
                style=ft.ButtonStyle(bgcolor=BLUE, color=DARK,
                                     icon_color=DARK))],
                alignment=ft.MainAxisAlignment.END)]

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
                                  on_click=objects_dialog),
                    gen_btn]),
            ft.Container(ft.Column([sections_col],
                                   scroll=ft.ScrollMode.AUTO),
                         expand=True),
            status, progress], width=720),
        ft.Column([
            ft.Container(preview, expand=True, bgcolor="#8a8d93",
                         border_radius=6)], expand=True)], expand=True,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH))
    refresh(0)


ft.run(main)
