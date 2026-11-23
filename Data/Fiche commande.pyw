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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import CONSTANTS  # noqa: E402
import flet as ft  # noqa: E402
import fiche_commande as fc  # noqa: E402
import ui_helpers  # noqa: E402
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
LAST_MODEL = CONSTANTS.state_file(".fiche_commande_modele.txt")
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


def _drawer(title, subtitle, color, is_open, on_toggle, controls):
    """Tiroir au style de Retouche photo : filet de couleur, en-tête
    GREY (teinté quand ouvert), corps sur fond BACKGROUND."""
    accent = color if is_open else LIGHT_GREY
    title = ft.Text(title, color=accent, weight=ft.FontWeight.W_600,
                    size=CONSTANTS.TEXT_SM)
    header = ft.Container(
        ft.Row([
            ft.Icon(ft.Icons.EXPAND_MORE if is_open
                    else ft.Icons.CHEVRON_RIGHT, color=accent,
                    size=CONSTANTS.ICON_SM),
            ft.Column([
                title,
                ft.Text(subtitle, color=LIGHT_GREY,
                        size=CONSTANTS.TEXT_SM - 2)], spacing=0)],
            spacing=CONSTANTS.SPACE_SM),
        on_click=on_toggle, border_radius=6,
        bgcolor=(ft.Colors.with_opacity(0.15, color) if is_open
                 else GREY),
        padding=ft.Padding(CONSTANTS.SPACE_SM, CONSTANTS.SPACE_SM,
                           CONSTANTS.SPACE_SM, CONSTANTS.SPACE_SM))
    body = ft.Container(
        ft.Column(controls, spacing=CONSTANTS.SPACE_SM), visible=is_open,
        bgcolor=BACKGROUND, border_radius=6,
        padding=ft.Padding(CONSTANTS.SPACE_LG, CONSTANTS.SPACE_MD,
                           CONSTANTS.SPACE_LG, CONSTANTS.SPACE_MD))
    return ft.Container(
        ft.Column([header, body], spacing=CONSTANTS.SPACE_XS),
        border=ft.Border(left=ft.BorderSide(3, color)),
        padding=ft.Padding(CONSTANTS.SPACE_SM, 0, 0, 0))


def _field(value, on_change, color=WHITE, border=GREY,
           text_size=CONSTANTS.TEXT_SM, **kw):
    return ft.TextField(
        value=str(value or ""), on_change=on_change, dense=True,
        color=color, border_color=border, focused_border_color=WHITE,
        text_size=text_size, **kw)


def main(page: ft.Page):
    page.title = "Fiche commande"
    page.bgcolor = BACKGROUND
    page.padding = 0
    page.theme_mode = ft.ThemeMode.DARK
    page.window.maximized = True

    photos = fc.photos_in(FOLDER) if os.path.isdir(FOLDER) else []
    wanted = set(filter(None, os.environ.get("SELECTED_FILES",
                                             "").split("|")))
    if wanted:
        photos = [f for f in photos if f in wanted] or photos
    models = fc.list_models()
    try:
        last = Path(LAST_MODEL).read_text(encoding="utf-8").strip()
    except OSError:
        last = ""
    st = {"name": last if last in models else models[0], "objects": fc.load_objects(),
          "photo": None, "renders": {}, "dirty": False, "gen": 0,
          "open": set()}
    st["model"] = fc.load_model(st["name"])
    if photos:
        st["photo"] = fc.open_photo(os.path.join(FOLDER, photos[0]))

    preview = ft.Image(src=_png_src(Image.new("RGB", (10, 7), "white")),
                       fit=ft.BoxFit.CONTAIN, expand=True)
    status = ft.Text("", color=LIGHT_GREY, size=CONSTANTS.TEXT_SM)
    progress = ft.ProgressBar(color=GREEN, visible=False, value=0)
    sections_col = ft.ReorderableListView(
        expand=True, spacing=10,
        mouse_cursor=ft.MouseCursor.GRAB)

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
            _boot_done()
            page.update()
            return
        if gen == st["gen"]:
            preview.src = src
            _boot_done()
            page.update()

    def _boot_done():
        if st.pop("boot", False):
            ui_helpers.set_busy_veil(boot_veil, False)

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
        bold = ft.TextStyle(weight=ft.FontWeight.BOLD)
        return ft.Container(ft.Row([
            ft.Checkbox(value=on, on_change=toggle, active_color=tint,
                        check_color=DARK, border_side=ft.BorderSide(
                            2, tint)),
            ft.Column([
                _field(it["name"], set_("name"), border=tint,
                       text_style=ft.TextStyle(
                           weight=ft.FontWeight.W_600)),
                _field(it.get("sub", ""), set_("sub"), color=LIGHT_GREY,
                       hint_text="Détail", text_size=12)],
                spacing=6, expand=True),
            ft.Column([
                _field(it["price"], set_("price"), width=96, color=GREEN,
                       border=GREEN, suffix=ft.Text("€", color=GREEN),
                       tooltip="Prix", text_style=bold),
                _field(it.get("price2", ""), set_("price2"), width=96,
                       color=YELLOW, border=YELLOW,
                       prefix=ft.Text("+", color=YELLOW),
                       suffix=ft.Text("€", color=YELLOW),
                       tooltip="Supplément", text_style=bold)],
                spacing=6),
            ft.Dropdown(value=it.get("object") or NO_OBJ,
                        options=obj_options(), on_select=set_obj,
                        dense=True, width=170, color=WHITE,
                        border_color=VIOLET, filled=True, fill_color=DARK,
                        bgcolor=DARK,
                        text_size=CONSTANTS.TEXT_SM,
                        leading_icon=ft.Icon(ft.Icons.IMAGE_OUTLINED,
                                             color=VIOLET)),
            actions_menu(sec["items"], i)], spacing=10),
            opacity=1 if on else 0.45, padding=ft.Padding.symmetric(
                horizontal=10, vertical=8), border_radius=6,
            bgcolor=GREY)

    def section_box(i, sec):
        def rename(e):
            sec["name"] = e.control.value
            title.value = sec["name"]
            changed()

        def add_item(e):
            sec["items"].append({"name": "Nouvel article", "sub": "",
                                 "price": "0", "price2": "",
                                 "object": None, "on": True})
            st["open"].add(id(sec))
            changed(True)

        def toggle(e):
            st["open"].symmetric_difference_update({id(sec)})
            draw_sections()
            page.update()
        si = st["model"]["sections"].index(sec)
        tint = PALETTE[si % len(PALETTE)]
        n_on = sum(1 for it in sec["items"] if it.get("on", True))
        drawer = _drawer(
            sec["name"],
            f"{n_on} / {len(sec['items'])} articles",
            tint, id(sec) in st["open"], toggle, [
                ft.Row([
                    _field(sec["name"], rename, expand=True, border=tint,
                           label="Rubrique"),
                    sec_menu(i, si)],
                    spacing=10),
                ft.Container(height=4),
                ft.Column([item_row(sec, j, it, tint)
                           for j, it in enumerate(sec["items"])],
                          spacing=8),
                ft.Container(ft.Row([ft.FilledButton(
                    "Article", icon=ft.Icons.ADD, on_click=add_item,
                    style=ft.ButtonStyle(bgcolor=tint, color=DARK,
                                         icon_color=DARK))],
                    alignment=ft.MainAxisAlignment.END),
                    padding=ft.Padding.only(top=6, bottom=6))])
        title = drawer.content.controls[0].content.controls[1].controls[0]
        drawer.key = str(id(sec))
        return drawer

    def toggle_fiche(e):
        st["open"].symmetric_difference_update({"fiche"})
        draw_sections()
        page.update()

    def draw_sections():
        m = st["model"]

        def set_m(key):
            def _h(e):
                m[key] = e.control.value
                changed()
            return _h
        sections_col.header = ft.Container(_drawer(
                "Fiche", f"Pour le {m.get('deadline', '')}", LIGHT_GREY,
                "fiche" in st["open"], toggle_fiche, [ft.Column([
                    _field(m.get("note", ""), set_m("note"),
                           label="Note en rouge",
                           color=RED, border=RED),
                    _field(m.get("footer", ""), set_m("footer"),
                           label="Message · {date} · {compte}",
                           border=LIGHT_GREY, multiline=True,
                           min_lines=2),
                    ft.Row([
                        _field(m.get("deadline", ""), set_m("deadline"),
                               label="Date limite",
                               color=ORANGE, border=ORANGE,
                               width=200),
                        _field(m.get("compte", ""), set_m("compte"),
                               label="Compte", border=LIGHT_GREY,
                               expand=True)])],
                    spacing=18)]), padding=ft.Padding.only(bottom=10))
        sections_col.header = ft.Column(
            [sections_col.header,
             ft.Text("Colonne 1", color=LIGHT_GREY,
                     weight=ft.FontWeight.W_600, size=CONSTANTS.TEXT_SM)],
            spacing=0)
        seq = []
        for c in range(3):
            if c:
                seq.append(c)
            seq += [s for s in m["sections"] if s.get("col", 0) == c]
        st["seq"] = seq
        sections_col.controls = [
            col_sep(x, n) if isinstance(x, int) else section_box(n, x)
            for n, x in enumerate(seq)]
        sections_col.footer = ft.Container(ft.Row([ft.FilledButton(
                "Rubrique", icon=ft.Icons.ADD, on_click=add_section,
                style=ft.ButtonStyle(bgcolor=BLUE, color=DARK,
                                     icon_color=DARK))],
                alignment=ft.MainAxisAlignment.END),
            padding=ft.Padding.only(top=10))

    def col_sep(c, n):
        return ft.Container(
            ft.Row([ft.Text(f"Colonne {c + 1}", color=LIGHT_GREY,
                            weight=ft.FontWeight.W_600,
                            size=CONSTANTS.TEXT_SM),
                    ft.Container(height=1, bgcolor=GREY, expand=True)]),
            padding=ft.Padding.only(top=6), key=f"col{c}")

    def sec_menu(n, si):
        def go(d):
            if 0 <= n + d < len(st["seq"]):
                apply_order(n, n + d)

        def drop(e):
            st["model"]["sections"].pop(si)
            changed(True)
        return ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT, icon_color=LIGHT_GREY,
            items=[ft.PopupMenuItem(content="Monter",
                                    icon=ft.Icons.ARROW_UPWARD,
                                    on_click=lambda e: go(-1)),
                   ft.PopupMenuItem(content="Descendre",
                                    icon=ft.Icons.ARROW_DOWNWARD,
                                    on_click=lambda e: go(1)),
                   ft.PopupMenuItem(content="Supprimer",
                                    icon=ft.Icons.DELETE_OUTLINE,
                                    on_click=drop)])

    def reorder(e):
        apply_order(e.old_index, e.new_index)

    def apply_order(old, new):
        seq = st["seq"]
        seq.insert(new, seq.pop(old))
        col, secs = 0, []
        for x in seq:
            if isinstance(x, int):
                col += 1
            else:
                x["col"] = min(col, 2)
                secs.append(x)
        st["model"]["sections"] = secs
        changed(True)

    sections_col.on_reorder = reorder


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
        if st["dirty"] and e is not None:
            new = model_dd.value
            model_dd.value = st["name"]

            def _go(e2):
                page.pop_dialog()
                st["dirty"] = False
                model_dd.value = new
                load()
            page.show_dialog(ft.AlertDialog(
                title=ft.Text(f"Abandonner les changements de "
                              f"« {st['name']} » ?"),
                actions=[ft.TextButton(
                    "Annuler", on_click=lambda e2: page.pop_dialog()),
                    _btn("Abandonner", ft.Icons.CLOSE, RED, _go)]))
            page.update()
            return
        st["name"] = model_dd.value
        try:
            Path(LAST_MODEL).write_text(st["name"], encoding="utf-8")
        except OSError:
            pass
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
        ask_name("Nouveau modèle", _do, "")

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

    save_btn = ft.IconButton(ft.Icons.SAVE, icon_color=DARK,
                             tooltip="Enregistrer", on_click=save,
                             style=ft.ButtonStyle(bgcolor=GREEN))

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
        static = ft.Checkbox(label="Image fixe, sans la photo",
                             value=obj.get("static", False))
        persp = ft.Slider(min=-300, max=300, divisions=60,
                          value=int(obj.get("persp", 0) or 0),
                          label="Perspective {value}", active_color=ORANGE)

        def read_opts():
            obj["fit"], obj["orient"] = fit.value, orient.value
            obj["static"] = static.value
            obj["persp"] = int(persp.value)

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
            read_opts()
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
            read_opts()
            k = key or "obj_%d" % int(time.time())
            st["objects"][k] = obj
            fc.save_objects(st["objects"])
            st["renders"].pop(k, None)
            page.pop_dialog()
            changed(True)

        fit.on_change = orient.on_change = static.on_change = (
            lambda e: (redo_sample(), page.update()))
        persp.on_change_end = lambda e: (redo_sample(), page.update())
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
                    fit, orient, static, persp, sample], width=300)],
                vertical_alignment=ft.CrossAxisAlignment.START),
            actions=[ft.TextButton("Annuler",
                                   on_click=lambda e: page.pop_dialog()),
                     _btn("OK", ft.Icons.CHECK, GREEN, ok)]))

    # ── Création des fiches ─────────────────────────────────────────────
    def generate(e):
        if not photos:
            return
        out = os.path.join(FOLDER, "Fiches")
        os.makedirs(out, exist_ok=True)
        gen_btn.disabled = True
        progress.visible = True
        veil_text.value = f"Création des fiches… 0 / {len(photos)}"
        ui_helpers.set_busy_veil(veil, True)
        page.update()

        async def _run():
            loop = asyncio.get_running_loop()
            workers = max(1, min(4, os.cpu_count() or 1))
            with ThreadPoolExecutor(workers) as pool:
                jobs = [loop.run_in_executor(pool, _one, f)
                        for f in photos]
                for n, job in enumerate(asyncio.as_completed(jobs), 1):
                    await job
                    status.value = f"{n} / {len(photos)}"
                    progress.value = n / len(photos)
                    veil_text.value = (f"Création des fiches… "
                                       f"{n} / {len(photos)}")
                    page.update()
            status.value = f"{len(photos)} fiches dans « Fiches »"
            progress.visible = False
            gen_btn.disabled = False
            ui_helpers.set_busy_veil(veil, False)
            page.update()

        def _one(f):
            sheet = fc.make_sheet(st["model"], st["objects"],
                                  os.path.join(FOLDER, f))
            sheet.save(os.path.join(out, os.path.splitext(f)[0] + ".jpg"),
                       "JPEG", quality=95, subsampling=0, dpi=(300, 300))
        page.run_task(_run)

    veil = ui_helpers.busy_veil("Création des fiches…", BLUE)
    veil_text = veil.content.controls[1]
    ui_helpers.set_busy_veil(veil, False)
    page.overlay.append(veil)
    boot_veil = ui_helpers.busy_veil("Préparation de l'aperçu…", BLUE)

    gen_btn = _btn(f"Créer {len(photos)} fiches", ft.Icons.PRINT, BLUE,
                   generate)
    if not photos:
        gen_btn.disabled = True
        status.value = "Aucune photo dans le dossier"

    def on_key(e):
        if e.key.upper() == "S" and (e.ctrl or e.meta):
            save()
    page.on_keyboard_event = on_key

    draw_sections()
    page.add(ft.Row([
        ft.Container(ft.Stack([preview, boot_veil], expand=True,
                              alignment=ft.Alignment.CENTER),
                     expand=True, padding=CONSTANTS.SPACE_MD),
        ft.Container(ft.Column([
            ft.Row([model_dd, save_btn,
                    ft.IconButton(ft.Icons.ADD, icon_color=DARK,
                                  tooltip="Nouveau modèle",
                                  on_click=save_as,
                                  style=ft.ButtonStyle(bgcolor=BLUE)),
                    ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_color=RED,
                                  tooltip="Supprimer le modèle",
                                  on_click=delete),
                    ft.IconButton(ft.Icons.CATEGORY_OUTLINED,
                                  icon_color=VIOLET, tooltip="Objets",
                                  on_click=objects_dialog),
                    gen_btn], wrap=True, run_spacing=8),
            sections_col,
            status, progress], spacing=CONSTANTS.SPACE_MD),
            width=740, bgcolor=DARK, padding=CONSTANTS.SPACE_MD,
            border=ft.Border(left=ft.BorderSide(1, GREY)))],
        expand=True, spacing=0,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH))
    st["boot"] = True
    ui_helpers.set_busy_veil(boot_veil, True)
    page.update()
    refresh(0)


ft.run(main)
