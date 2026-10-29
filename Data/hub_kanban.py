# -*- coding: utf-8 -*-
"""Hub — surface Tâches (Kanban Notion « Tâches »).

Section extraite de Hub.pyw (main) : build(ui) reçoit l'espace de
noms de main (ui) et renvoie les noms utilisés ailleurs dans Hub."""


import CONSTANTS
import datetime
import flet as ft
import hub_sync
import json
import os
import re
import tempfile
import threading
import ui_helpers


def build(ui):
    BACKGROUND = ui.BACKGROUND
    DARK = ui.DARK
    GREY = ui.GREY
    KANBAN_DATA_SOURCE = ui.KANBAN_DATA_SOURCE
    KANBAN_ETATS = ui.KANBAN_ETATS
    KANBAN_ETAT_COLORS = ui.KANBAN_ETAT_COLORS
    KANBAN_PAYE_COLORS = ui.KANBAN_PAYE_COLORS
    KANBAN_PAYE_OPTIONS = ui.KANBAN_PAYE_OPTIONS
    KANBAN_PREVENU_COLORS = ui.KANBAN_PREVENU_COLORS
    KANBAN_PREVENU_OPTIONS = ui.KANBAN_PREVENU_OPTIONS
    KANBAN_PROJET_COLORS = ui.KANBAN_PROJET_COLORS
    KANBAN_PROJET_OPTIONS = ui.KANBAN_PROJET_OPTIONS
    LIGHT_GREY = ui.LIGHT_GREY
    MINT = ui.MINT
    RED = ui.RED
    SQUARE_BTN = ui.SQUARE_BTN
    SURFACE_ACCENT = ui.SURFACE_ACCENT
    TOOLBAR_H = ui.TOOLBAR_H
    VIOLET = ui.VIOLET
    WHITE = ui.WHITE
    _KANBAN_CACHE_FILE = ui._KANBAN_CACHE_FILE
    _KANBAN_ORDER_FILE = ui._KANBAN_ORDER_FILE
    _KANBAN_SETTINGS_FILE = ui._KANBAN_SETTINGS_FILE
    _KANBAN_TRASH_DAYS = ui._KANBAN_TRASH_DAYS
    _KANBAN_TRASH_FILE = ui._KANBAN_TRASH_FILE
    _dialog = ui._dialog
    _dlg_btn = ui._dlg_btn
    _hub_sync_pull_all = ui._hub_sync_pull_all
    _log_to_terminal = ui.late__log_to_terminal
    _open_file_default = ui._open_file_default
    _liste_add_task = ui._liste_add_task
    _liste_has_task = ui._liste_has_task
    _load_json = ui._load_json
    _run_task = ui._run_task
    IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
    _save_json = ui._save_json
    _surface_title = ui._surface_title
    page = ui.page
    _mails = ui._mails
    _agenda_rebuild = ui.late__agenda_rebuild
    # ═════════════════════════════════════════════════════════════════════
    #  Surface Tâches — stockées sur le Pi (hub-sync, Pi/tasks.py), que
    #  le Pi recopie dans la base Notion "Tâches". Pas de rafraîchissement
    #  en fond (retour user : peu de changements par heure) : le panneau
    #  se recharge à chaque fois qu'on revient dessus, plus un bouton
    #  "Actualiser" manuel.
    # ═════════════════════════════════════════════════════════════════════
    # Mêmes appels qu'à l'époque de Notion (noms d'outils gardés).
    _notion_call = hub_sync.tasks_call
    kanban_status = ft.Text("", size=CONSTANTS.TEXT_SM, color=LIGHT_GREY)
    kanban_columns = {etat: ft.ListView(expand=True, spacing=8,
                                        padding=ft.Padding(6, 4, 6, 8))
                      for etat, _color in KANBAN_ETATS}
    # Cache local (.kanban_cache.json) : évite un tableau vide le temps du
    # premier appel réseau à chaque passage sur l'onglet — comme Notion,
    # qui affiche l'état connu avant de resynchroniser (retour user).
    _hub_sync_pull_all()
    kanban_state = {"loading": False, "search": "",
                    "order": _load_json(_KANBAN_ORDER_FILE, []),
                    "rows": _load_json(_KANBAN_CACHE_FILE, []),
                    # Auto-synchronisation : re-télécharge tout le tableau
                    # depuis Notion après chaque modification (retour user)
                    # au lieu d'attendre un clic sur "Actualiser". Persisté
                    # (fichier séparé, pas le cache lui-même) pour retenir
                    # le choix d'une session à l'autre.
                    "auto_sync": _load_json(
                        _KANBAN_SETTINGS_FILE, {}).get("auto_sync", False)}

    # (propriété Notion, clé du dict `row`, options disponibles)
    KANBAN_EDITABLE_PROPS = [
        ("Etat", "etat", [e for e, _c in KANBAN_ETATS], {}),
        ("Projet ?", "projet", KANBAN_PROJET_OPTIONS, KANBAN_PROJET_COLORS),
        ("Payé ?", "paye", KANBAN_PAYE_OPTIONS, KANBAN_PAYE_COLORS),
        ("Prévenir ?", "prevenu", KANBAN_PREVENU_OPTIONS,
         KANBAN_PREVENU_COLORS),
    ]

    def _kanban_change_property(row, notion_prop, state_key, new_value):
        old_value = row.get(state_key, "")
        if old_value == new_value:
            return
        row[state_key] = new_value
        if state_key == "etat" and new_value == "Terminé":
            _notify(row)
        _kanban_rebuild_columns()
        _save_json(_KANBAN_CACHE_FILE, kanban_state["rows"])
        _kanban_busy(1)
        page.update()

        def _work():
            # Notion attend `null` (pas une chaîne vide) pour vider un
            # select/status — cf. "(vide)" dans _kanban_prop_menu.
            api_value = new_value if new_value else None
            result = _notion_call(
                "mcp__notion__notion-update-page",
                {"page_id": row["page_id"], "command": "update_properties",
                 "properties": {notion_prop: api_value}})
            failed = result.startswith("Erreur")

            async def _apply():
                _kanban_busy(-1)
                if failed:
                    row[state_key] = old_value
                    _kanban_rebuild_columns()
                    _save_json(_KANBAN_CACHE_FILE, kanban_state["rows"])
                    kanban_status.value = f"Échec de la mise à jour : {result}"
                    page.update()
                elif kanban_state["auto_sync"]:
                    # Switch "Auto-sync" (retour user) : re-télécharge tout
                    # le tableau depuis Notion après chaque modification
                    # réussie, sans clic sur "Actualiser".
                    _kanban_refresh()
                page.update()

            _run_task(_apply)

        threading.Thread(target=_work, daemon=True).start()

    def _notify(row):
        """Propose le mail « commande prête » ; envoyé → « Prévenu »."""
        _mails["notify_client"](row, on_sent=lambda: _kanban_change_property(
            row, "Prévenir ?", "prevenu", "Prévenu"))

    def _kanban_chip(text, color):
        # Fond quasi plein (0.85) + texte NOIR en gras (retour user :
        # blanc devient illisible une fois le fond presque opaque, comme
        # les pastilles de Notion qui utilisent aussi du texte sombre).
        return ft.Container(
            content=ft.Text(text, size=11, color=ft.Colors.BLACK,
                            weight=ft.FontWeight.W_600),
            bgcolor=ft.Colors.with_opacity(0.85, color),
            border_radius=4, padding=ft.Padding(6, 2, 6, 2))

    def _kanban_prop_menu(row, notion_prop, state_key, options, colors):
        # Plus d'option "(vide)" : chaque propriété a désormais un état par
        # défaut côté Notion (retour user). Couleur par valeur (comme dans
        # Notion), via `colors` — valeur sans couleur définie -> VIOLET.
        current = row.get(state_key, "")
        items = [
            ft.PopupMenuItem(
                content=ft.Text(opt, color=colors.get(opt, VIOLET)),
                on_click=(lambda e, o=opt: _kanban_change_property(
                    row, notion_prop, state_key, o)))
            for opt in options
        ]
        # Projet ? a désormais un état par défaut explicite "Pas de
        # projet" côté Notion (retour user) : affiché tel quel plutôt que
        # le "—" générique quand la valeur est encore vide (anciennes
        # tâches créées avant ce défaut).
        empty_label = "Pas de projet" if notion_prop == "Projet ?" else "—"
        return ft.PopupMenuButton(
            content=_kanban_chip(
                f"{current or empty_label}  ▾",
                colors.get(current, VIOLET) if current
                else colors.get(empty_label, LIGHT_GREY)),
            items=items,
        )

    def _kanban_extract_page_content(raw_json_str):
        """notion-fetch renvoie un JSON dont le champ "text" contient un
        gros bloc XML-ish (<page><properties>...</properties><content>
        ...</content></page>) — seul le <content> nous intéresse ici, le
        reste (properties, ancestor-path) est déjà affiché via les champs
        du formulaire ou redondant."""
        try:
            text = json.loads(raw_json_str).get("text", "")
        except (json.JSONDecodeError, AttributeError):
            return None
        match = re.search(r"<content>\n?(.*?)\n?</content>", text, re.S)
        return match.group(1).strip() if match else None

    def _kanban_notion_to_plain(text):
        """<br> (saut de ligne Notion, dans un même bloc) -> vrai saut de
        ligne, plus lisible pour un collègue non-technique. <empty-block/>
        (marqueur technique Notion pour une ligne vide) masqué entièrement
        — regex plutôt qu'un match ligne entière, pour couvrir aussi un
        <empty-block/> qui ne serait pas seul sur sa ligne."""
        text = text.replace("<br>", "\n")
        text = re.sub(r"[ \t]*<empty-block/>[ \t]*\n?", "", text)
        return text

    def _kanban_plain_to_notion(text):
        """Inverse partiel de _kanban_notion_to_plain : une ligne vide doit
        redevenir <empty-block/> pour Notion. On ne réintroduit PAS de
        <br> (un ex-saut de ligne "<br>" redevient un bloc/paragraphe à
        part entière, à peine plus espacé visuellement) — plus simple et
        sans risque de casser une liste à puces/checklist en fusionnant
        des lignes qui doivent rester des blocs séparés."""
        lines = ["<empty-block/>" if not line.strip() else line
                 for line in text.split("\n")]
        return "\n".join(lines)

    def _kanban_deadline_field(value, label="Deadline"):
        """Champ Deadline : calendrier (DatePicker) plutôt que saisie
        libre (retour user). Valeur texte AAAA-MM-JJ, lue comme avant."""
        field = ft.TextField(
            label=label, value=(value or "")[:10], width=560,
            read_only=True, bgcolor=DARK,
            border=CONSTANTS.input_border(GREY), color=WHITE)

        def _picked(e):
            v = e.control.value
            if v is None:
                return
            # Datetime éventuellement en UTC : ramené en heure locale
            # pour ne pas afficher la veille.
            d = v.astimezone().date() if v.tzinfo else v.date()
            field.value = d.isoformat()
            field.update()

        def _open(e):
            try:
                current = datetime.date.fromisoformat(field.value)
            except ValueError:
                current = datetime.date.today()
            page.show_dialog(ft.DatePicker(
                value=datetime.datetime.combine(current, datetime.time()),
                first_date=datetime.datetime(2020, 1, 1),
                last_date=datetime.datetime(2040, 12, 31),
                locale=ft.Locale("fr", "BE"),
                on_change=_picked))

        def _clear(e):
            field.value = ""
            field.update()

        field.on_click = _open
        field.suffix = ft.Row([
            ft.IconButton(ft.Icons.CALENDAR_MONTH, on_click=_open,
                          icon_color=MINT),
            ft.IconButton(ft.Icons.CLOSE, on_click=_clear,
                          icon_color=LIGHT_GREY),
        ], tight=True, spacing=0)
        return field

    def _kanban_open_details(row, trash=None):
        """trash = (entrée, dialogue corbeille) : lecture seule + Restaurer."""
        demande_field = ft.TextField(
            label="Demande", value=row["demande"], width=560,
            bgcolor=DARK, border=CONSTANTS.input_border(GREY), color=WHITE)
        deadline_field = _kanban_deadline_field(row["deadline"])
        telephone_field = ft.TextField(
            label="Téléphone", value=row["telephone"], width=560,
            bgcolor=DARK, border=CONSTANTS.input_border(GREY), color=WHITE)
        email_field = ft.TextField(
            label="E-mail", value=row["email"], width=560,
            bgcolor=DARK, border=CONSTANTS.input_border(GREY), color=WHITE)
        prix_field = ft.TextField(
            label="Prix", value=(f"{row['prix']:g}"
                                 if row["prix"] not in (None, "") else ""),
            width=560, bgcolor=DARK,
            border=CONSTANTS.input_border(GREY), color=WHITE)

        # Etat + Payé ? + Projet ? directement dans l'overlay (retour
        # user) : en CupertinoSlidingSegmentedButton plutôt qu'un
        # dropdown, pour pouvoir changer le prix ET ces statuts en une
        # seule sauvegarde, sans repasser par le menu déroulant de la
        # tuile juste après.
        def _style_segments(btn, texts):
            for i, t in enumerate(texts):
                t.color = DARK if i == btn.selected_index else WHITE

        # Payé ?/Projet ? peuvent légitimement rester vides (jamais
        # renseignés, cf. "(vide)" dans _kanban_prop_menu) — un segment
        # est TOUJOURS sélectionné visuellement (pas d'état "vide"
        # possible sur ce contrôle), donc on ne les envoie à Notion que si
        # l'utilisateur y a vraiment touché (seg_touched), pour ne jamais
        # écraser silencieusement un champ vide resté tel quel.
        seg_touched = {"etat": False, "paye": False, "projet": False,
                       "prevenu": False}

        etat_names = [e for e, _c in KANBAN_ETATS]
        etat_index = (etat_names.index(row["etat"])
                     if row["etat"] in etat_names else 0)
        # Libellé raccourci pour le segment (retour user) : la valeur
        # Notion complète ("En cours / en attente") reste utilisée pour
        # etat_names/etat_index/l'écriture — seul l'affichage change.
        ETAT_SEG_LABELS = {"En cours / en attente": "En cours"}
        etat_texts = [ft.Text(ETAT_SEG_LABELS.get(e, e), size=11)
                     for e in etat_names]

        def _on_etat_seg_change(event):
            seg_touched["etat"] = True
            _style_segments(etat_seg, etat_texts)
            etat_seg.thumb_color = KANBAN_ETAT_COLORS.get(
                etat_names[etat_seg.selected_index], MINT)
            for t in etat_texts:
                t.update()
            etat_seg.update()

        etat_seg = ft.CupertinoSlidingSegmentedButton(
            selected_index=etat_index, controls=etat_texts,
            thumb_color=KANBAN_ETAT_COLORS.get(row["etat"], MINT),
            on_change=_on_etat_seg_change, width=560)
        _style_segments(etat_seg, etat_texts)

        paye_index = (KANBAN_PAYE_OPTIONS.index(row["paye"])
                     if row.get("paye") in KANBAN_PAYE_OPTIONS else 0)
        paye_texts = [ft.Text(o, size=11) for o in KANBAN_PAYE_OPTIONS]

        def _on_paye_seg_change(event):
            seg_touched["paye"] = True
            _style_segments(paye_seg, paye_texts)
            paye_seg.thumb_color = KANBAN_PAYE_COLORS.get(
                KANBAN_PAYE_OPTIONS[paye_seg.selected_index], VIOLET)
            for t in paye_texts:
                t.update()
            paye_seg.update()

        paye_seg = ft.CupertinoSlidingSegmentedButton(
            selected_index=paye_index, controls=paye_texts,
            thumb_color=KANBAN_PAYE_COLORS.get(
                KANBAN_PAYE_OPTIONS[paye_index], VIOLET),
            on_change=_on_paye_seg_change, width=560)
        _style_segments(paye_seg, paye_texts)

        projet_index = (KANBAN_PROJET_OPTIONS.index(row["projet"])
                       if row.get("projet") in KANBAN_PROJET_OPTIONS else 0)
        projet_texts = [ft.Text(o, size=11) for o in KANBAN_PROJET_OPTIONS]

        def _on_projet_seg_change(event):
            seg_touched["projet"] = True
            _style_segments(projet_seg, projet_texts)
            projet_seg.thumb_color = KANBAN_PROJET_COLORS.get(
                KANBAN_PROJET_OPTIONS[projet_seg.selected_index], VIOLET)
            for t in projet_texts:
                t.update()
            projet_seg.update()

        projet_seg = ft.CupertinoSlidingSegmentedButton(
            selected_index=projet_index, controls=projet_texts,
            thumb_color=KANBAN_PROJET_COLORS.get(
                KANBAN_PROJET_OPTIONS[projet_index], VIOLET),
            on_change=_on_projet_seg_change, width=560)
        _style_segments(projet_seg, projet_texts)

        prevenu_index = (
            KANBAN_PREVENU_OPTIONS.index(row["prevenu"])
            if row.get("prevenu") in KANBAN_PREVENU_OPTIONS
            else KANBAN_PREVENU_OPTIONS.index("Viendra d'office"))
        prevenu_texts = [ft.Text(o, size=11) for o in KANBAN_PREVENU_OPTIONS]

        def _on_prevenu_seg_change(event):
            seg_touched["prevenu"] = True
            _style_segments(prevenu_seg, prevenu_texts)
            prevenu_seg.thumb_color = KANBAN_PREVENU_COLORS.get(
                KANBAN_PREVENU_OPTIONS[prevenu_seg.selected_index], VIOLET)
            for t in prevenu_texts:
                t.update()
            prevenu_seg.update()

        prevenu_seg = ft.CupertinoSlidingSegmentedButton(
            selected_index=prevenu_index, controls=prevenu_texts,
            thumb_color=KANBAN_PREVENU_COLORS.get(
                KANBAN_PREVENU_OPTIONS[prevenu_index], VIOLET),
            on_change=_on_prevenu_seg_change, width=560)
        _style_segments(prevenu_seg, prevenu_texts)

        # Contenu de la page (texte libre, sous-tâches, check-listes) : pas
        # une propriété de la base, donc absent de notion-query-data-sources
        # — récupéré à part via notion-fetch, affiché/éditable tel quel
        # (syntaxe Markdown Notion brute, ex. <br> pour un saut de ligne —
        # pas "nettoyé" pour l'affichage, pour un aller-retour sans risque
        # de casser un tableau/toggle/colonne imbriqué).
        # Mis en cache dès la première ouverture (row["notes"], voir plus
        # bas) : les ouvertures suivantes affichent la valeur en cache
        # tout de suite, sans nouvel appel réseau ni délai (retour user).
        cached_notes = row.get("notes")
        content_field = ft.TextField(
            value=cached_notes if cached_notes is not None else "Chargement…",
            multiline=True, min_lines=8, max_lines=20,
            width=560, bgcolor=DARK, border=CONSTANTS.input_border(GREY),
            color=WHITE, disabled=cached_notes is None)
        content_loaded = {"original": cached_notes}
        files_row = _kanban_files_row(row["page_id"], read_only=bool(trash))

        def _cancel(event):
            dlg.open = False
            page.update()

        def _delete(event):
            # Corbeille Notion (récupérable 30 jours) : pas de
            # confirmation. Retrait local immédiat, remis si échec.
            dlg.open = False
            kanban_state["rows"].remove(row)
            _kanban_rebuild_columns()
            _save_json(_KANBAN_CACHE_FILE, kanban_state["rows"])
            page.update()

            def _work():
                _kanban_to_trash([row])
                result = _notion_call("mcp__notion__notion-trash-page",
                                      {"page_id": row["page_id"]})

                async def _apply():
                    if result.startswith("Erreur"):
                        kanban_state["rows"].append(row)
                        _kanban_rebuild_columns()
                        _save_json(_KANBAN_CACHE_FILE, kanban_state["rows"])
                        kanban_status.value = (
                            f"Échec de la suppression : {result}")
                        page.update()

                _run_task(_apply)

            threading.Thread(target=_work, daemon=True).start()

        def _confirm(event):
            props = {}
            new_demande = (demande_field.value or "").strip()
            if new_demande and new_demande != row["demande"]:
                props["Demande"] = new_demande
            new_deadline = (deadline_field.value or "").strip()
            if new_deadline != (row["deadline"] or "")[:10]:
                props["Deadline"] = new_deadline or None
            new_tel = (telephone_field.value or "").strip()
            if new_tel != (row["telephone"] or ""):
                props["Téléphone"] = new_tel or None
            new_email = (email_field.value or "").strip()
            if new_email != (row["email"] or ""):
                props["E-mail"] = new_email or None
            new_prix_raw = (prix_field.value or "").strip()
            try:
                new_prix = float(new_prix_raw.replace(",", ".")) \
                    if new_prix_raw else None
            except ValueError:
                new_prix = row["prix"]
            if new_prix != row["prix"]:
                props["Prix"] = new_prix
            if seg_touched["etat"]:
                new_etat = etat_names[etat_seg.selected_index]
                if new_etat != row["etat"]:
                    props["Etat"] = new_etat
                    if new_etat == "Terminé":
                        _notify(row)
            if seg_touched["paye"]:
                new_paye = KANBAN_PAYE_OPTIONS[paye_seg.selected_index]
                if new_paye != (row["paye"] or ""):
                    props["Payé ?"] = new_paye
            if seg_touched["projet"]:
                new_projet = KANBAN_PROJET_OPTIONS[projet_seg.selected_index]
                if new_projet != (row["projet"] or ""):
                    props["Projet ?"] = new_projet
            if seg_touched["prevenu"]:
                new_prevenu = KANBAN_PREVENU_OPTIONS[
                    prevenu_seg.selected_index]
                if new_prevenu != (row["prevenu"] or ""):
                    props["Prévenir ?"] = new_prevenu
            new_content = content_field.value
            content_changed = (content_loaded["original"] is not None and
                              new_content != content_loaded["original"])
            dlg.open = False
            page.update()
            if not props and not content_changed:
                return

            def _work():
                errors = []
                if props:
                    result = _notion_call(
                        "mcp__notion__notion-update-page",
                        {"page_id": row["page_id"],
                         "command": "update_properties",
                         "properties": props})
                    if result.startswith("Erreur"):
                        errors.append(result)
                if content_changed:
                    result = _notion_call(
                        "mcp__notion__notion-update-page",
                        {"page_id": row["page_id"],
                         "command": "replace_content",
                         "new_str": _kanban_plain_to_notion(new_content)})
                    if result.startswith("Erreur"):
                        errors.append(result)

                async def _apply():
                    if errors:
                        kanban_status.value = ("Échec de la mise à jour : "
                                               + " / ".join(errors))
                        page.update()
                    else:
                        if content_changed:
                            # Reporté dans le cache directement (pas
                            # besoin d'attendre le refresh, qui de toute
                            # façon reporte cette même valeur — voir
                            # _kanban_refresh).
                            row["notes"] = new_content
                            _save_json(_KANBAN_CACHE_FILE,
                                      kanban_state["rows"])
                        _kanban_refresh()

                _run_task(_apply)

            threading.Thread(target=_work, daemon=True).start()

        dlg = _dialog(
            title=ft.Text("Détails de la tâche", size=CONSTANTS.TEXT_SM,
                          color=WHITE),
            content=ft.Column([
                # Espace avant le 1er champ : sans lui, le libellé flottant
                # de demande_field (collé au bord haut de la zone
                # défilante) se fait rogner (retour user, screenshots).
                ft.Container(height=10),
                demande_field, deadline_field, telephone_field, email_field,
                prix_field,
                ft.Text("Etat", size=11, color=LIGHT_GREY),
                etat_seg,
                ft.Text("Projet ?", size=11, color=LIGHT_GREY),
                projet_seg,
                ft.Text("Payé ?", size=11, color=LIGHT_GREY),
                paye_seg,
                ft.Text("Prévenir ?", size=11, color=LIGHT_GREY),
                prevenu_seg,
                ft.Text(f"Créé le : {row['cree_le'] or '?'}", size=11,
                       color=LIGHT_GREY),
                files_row,
                ft.Divider(height=1, color=GREY),
                content_field,
            # Hauteur plafonnée à la fenêtre dispo (retour user : sur une
            # fenêtre courte, une hauteur fixe faisait déborder le dialogue
            # centré hors écran par le haut, cachant le champ Demande).
            # Marge de 220 (pas juste 100) : le titre, les boutons et les
            # espacements internes du dialogue ne sont pas comptés dans
            # cette hauteur de contenu, sous peine de continuer à déborder.
            ], tight=True, spacing=8, scroll=ft.ScrollMode.AUTO,
               width=600,
               height=max(300, min(680, (page.height or 900) - 220))),
            actions=[_dlg_btn("Fermer", "cancel", on_click=_cancel),
                     _dlg_btn("Restaurer", color=SURFACE_ACCENT["kanban"],
                              on_click=lambda e: (
                                  _cancel(e), _kanban_restore(*trash)))]
            if trash else
                    [_dlg_btn("Supprimer", "danger", on_click=_delete),
                     _dlg_btn("Déjà dans la Liste" if _liste_has_task(row)
                              else "Ajouter à la Liste",
                              color=SURFACE_ACCENT["liste"],
                              disabled=_liste_has_task(row),
                              on_click=lambda e: _liste_add_task(
                                  row, e.control)),
                     *([_dlg_btn("Prévenir", color=ui.YELLOW,
                                 on_click=lambda e: _notify(row))]
                       if row.get("email") else []),
                     _dlg_btn("Annuler", "cancel", on_click=_cancel),
                     _dlg_btn("Enregistrer", "primary", on_click=_confirm)],
            # Marge mini garantie avec le haut/bas de l'écran (retour
            # user : "rajouter une marge au dessus") — évite que le
            # dialogue vienne toucher le bord de la fenêtre.
            inset_padding=ft.Padding(20, 40, 20, 40),
        )
        if trash:
            for c in dlg.content.controls:
                if isinstance(c, ft.TextField):
                    c.read_only = True
                elif isinstance(c, ft.CupertinoSlidingSegmentedButton):
                    c.disabled = True
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

        def _load_content():
            raw = _notion_call(
                "mcp__notion__notion-fetch", {"id": row["page_id"]})
            body = None if raw.startswith("Erreur") else \
                _kanban_extract_page_content(raw)

            async def _apply():
                plain = _kanban_notion_to_plain(body or "")
                content_loaded["original"] = plain
                content_field.value = plain
                content_field.disabled = False
                # Mis en cache : les prochaines ouvertures de cette tâche
                # afficheront cette valeur tout de suite (retour user).
                row["notes"] = plain
                _save_json(_KANBAN_CACHE_FILE, kanban_state["rows"])
                page.update()

            _run_task(_apply)

        # Seulement si pas déjà en cache (retour user : ne plus attendre à
        # chaque ouverture).
        if cached_notes is None:
            threading.Thread(target=_load_content, daemon=True).start()

    def _kanban_item_card(row):
        # Couleur de fond de la tuile (cf. plus bas) calculée en amont :
        # le bouton Détails reprend cette même teinte en pleine opacité
        # (retour user : un fond blanc pur était trop flashy).
        etat_color = KANBAN_ETAT_COLORS.get(row["etat"], GREY)
        rows = [
            ft.Row([
                ft.Text(row["demande"], size=CONSTANTS.TEXT_SM, color=WHITE,
                        weight=ft.FontWeight.W_600, max_lines=3,
                        overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                *([ft.Icon(ft.Icons.ATTACH_FILE, color=LIGHT_GREY,
                           size=14)] if row.get("files") else []),
                ft.IconButton(
                    ft.Icons.OPEN_IN_FULL, icon_color=DARK, icon_size=14,
                    tooltip="Détails / modifier",
                    style=ft.ButtonStyle(
                        bgcolor=etat_color,
                        padding=4),
                    on_click=(lambda e, r=row:
                              _kanban_open_details(r))),
            ], spacing=0),
        ]
        # Deadline en rouge (attire l'œil), téléphone/e-mail en blanc
        # (coordonnées à contacter, lisibilité), prix en gras + coloré
        # (retour user : trop discret en gris, doit se voir au premier
        # coup d'œil).
        info_bits = []
        if row["deadline"]:
            info_bits.append(ft.Text(row["deadline"], size=11, color=RED))
        if row["telephone"]:
            info_bits.append(ft.Text(row["telephone"], size=11, color=WHITE))
        if row["email"]:
            info_bits.append(ft.Text(row["email"], size=11, color=WHITE))
        if row["prix"] not in (None, ""):
            info_bits.append(ft.Text(f"{row['prix']:g} €", size=12,
                                     color=MINT, weight=ft.FontWeight.W_700))
        if info_bits:
            spans = []
            for i, bit in enumerate(info_bits):
                if i:
                    spans.append(ft.Text("  •  ", size=11, color=LIGHT_GREY))
                spans.append(bit)
            rows.append(ft.Row(spans, spacing=0, wrap=True))
        if row["cree_le"]:
            rows.append(ft.Text(f"Créé le {row['cree_le'][:10]}", size=10,
                                color=LIGHT_GREY))
        # Pas de badge Etat ici : la colonne le représente déjà — on
        # change l'Etat en glissant la carte vers une autre colonne.
        badges = [_kanban_prop_menu(row, notion_prop, state_key,
                                    options, colors)
                 for notion_prop, state_key, options, colors
                 in KANBAN_EDITABLE_PROPS[1:]]
        rows.append(ft.Row(badges, spacing=4, wrap=True))
        # Fond de la tuile teinté selon l'Etat (retour user) — en plus de
        # la couleur de colonne, pour repérer le statut même une fois les
        # colonnes défilées hors champ horizontalement.
        card = ft.Container(
            content=ft.Column(rows, spacing=4, tight=True),
            bgcolor=ft.Colors.with_opacity(0.18, etat_color),
            border_radius=8, padding=10)
        # Chaque carte est aussi une cible : un trait apparaît au-dessus
        # pendant le survol pour montrer où la carte glissée sera posée
        # (retour user, comme la démo Flet « Trolli »).
        marker = _kanban_drop_marker(row["etat"])
        return ft.DragTarget(
            group="kanban_card",
            content=ft.Column([marker, ft.Draggable(
                group="kanban_card", data=row["page_id"], content=card)],
                spacing=2, tight=True),
            on_will_accept=lambda e, m=marker: _kanban_mark(m, True),
            on_leave=lambda e, m=marker: _kanban_mark(m, False),
            on_accept=lambda e, m=marker, pid=row["page_id"],
            et=row["etat"]: (_kanban_mark(m, False),
                             _kanban_drop(e, et, before=pid)))

    def _kanban_drop_marker(etat):
        return ft.Container(
            height=3, border_radius=2, opacity=0,
            bgcolor=KANBAN_ETAT_COLORS.get(etat, WHITE))

    def _kanban_mark(marker, on):
        marker.opacity = 1 if on else 0
        marker.update()

    def _kanban_ordered(rows):
        """Ordre manuel ; les cartes jamais placées (nouvelles) en haut,
        les plus récentes d'abord."""
        order = kanban_state["order"]
        known = set(order)
        new = sorted((r for r in rows if r["page_id"] not in known),
                     key=lambda r: r["cree_le"], reverse=True)
        if new:
            order[:0] = [r["page_id"] for r in new]
            _save_json(_KANBAN_ORDER_FILE, order)
        pos = {pid: i for i, pid in enumerate(order)}
        return sorted(rows, key=lambda r: pos[r["page_id"]])

    def _kanban_move(page_id, etat, before=None):
        """Place `page_id` avant `before`, ou en fin de colonne `etat`."""
        order = kanban_state["order"]
        if page_id == before:
            return
        if page_id in order:
            order.remove(page_id)
        if before in order:
            order.insert(order.index(before), page_id)
        else:
            etats = {r["page_id"]: r["etat"] for r in kanban_state["rows"]}
            last = max((i for i, pid in enumerate(order)
                        if etats.get(pid) == etat), default=len(order) - 1)
            order.insert(last + 1, page_id)
        _save_json(_KANBAN_ORDER_FILE, order)

    def _kanban_rebuild_columns():
        for etat, _color in KANBAN_ETATS:
            kanban_columns[etat].controls.clear()
        rows_sorted = _kanban_ordered(kanban_state["rows"])
        needle = kanban_state["search"].strip().lower()
        if needle:
            rows_sorted = [
                r for r in rows_sorted
                if needle in (r["demande"] or "").lower()
                or needle in (r["telephone"] or "").lower()
                or needle in (r["email"] or "").lower()]
        for row in rows_sorted:
            column = kanban_columns.get(row["etat"])
            if column is not None:
                column.controls.append(_kanban_item_card(row))
        # Cible de fin de colonne, avec son trait (dépôt tout en bas).
        for etat, _color in KANBAN_ETATS:
            marker = _kanban_drop_marker(etat)
            kanban_columns[etat].controls.append(ft.DragTarget(
                group="kanban_card",
                content=ft.Container(marker, height=60,
                                     alignment=ft.Alignment(0, -1)),
                on_will_accept=lambda e, m=marker: _kanban_mark(m, True),
                on_leave=lambda e, m=marker: _kanban_mark(m, False),
                on_accept=lambda e, m=marker, t=etat: (
                    _kanban_mark(m, False), _kanban_drop(e, t))))

    def _kanban_parse_rows(raw_json_str):
        data = json.loads(raw_json_str)
        try:  # cartes qui ont des fichiers sur le Pi (trombone)
            with_files = set(json.loads(hub_sync.file_req("GET", "",
                                                          timeout=5)))
        except Exception:
            with_files = set()
        rows = []
        for r in data.get("results", []):
            url = r.get("url", "")
            page_id = url.rsplit("/", 1)[-1].split("?")[0] if url else ""
            rows.append({
                "page_id": page_id,
                "demande": r.get("Demande") or "(sans titre)",
                "files": page_id.replace("-", "") in with_files,
                "etat": r.get("Etat") or "À faire",
                "deadline": r.get("date:Deadline:start", ""),
                "telephone": r.get("Téléphone", ""),
                "email": r.get("E-mail", ""),
                "prix": r.get("Prix"),
                "projet": r.get("Projet ?", ""),
                "paye": r.get("Payé ?", ""),
                "prevenu": r.get("Prévenir ?", ""),
                "cree_le": r.get("Créé le", ""),
                "edited": r.get("last_edited", ""),
                # Contenu de la page (Notes) : absent de cette requête
                # (propriétés seulement) — None = "jamais chargé", distinct
                # d'une chaîne vide ("chargé, page vide"). Rempli à la
                # première ouverture des détails puis mis en cache (voir
                # _kanban_open_details) et reporté ici lors des refresh
                # suivants (voir _kanban_refresh).
                "notes": None,
            })
        return rows

    def _kanban_new_task(event=None, prefill=None):
        # Overlay complet dès la création (retour user : dans Notion, la
        # nouvelle page s'ouvre avec toutes les propriétés éditables tout
        # de suite — remplir en un seul passage plutôt que de créer avec
        # juste un titre puis rouvrir le détail pour compléter).
        # prefill : tâche créée depuis un rendez-vous de l'Agenda.
        prefill = prefill or {}
        title_field = ft.TextField(
            label="Demande", autofocus=True, width=560, bgcolor=DARK,
            value=prefill.get("demande", ""),
            border=CONSTANTS.input_border(GREY), color=WHITE)
        deadline_field = _kanban_deadline_field(prefill.get("deadline", ""))
        telephone_field = ft.TextField(
            label="Téléphone", width=560, bgcolor=DARK,
            value=prefill.get("telephone", ""),
            border=CONSTANTS.input_border(GREY), color=WHITE)
        email_field = ft.TextField(
            label="E-mail", width=560, bgcolor=DARK,
            value=prefill.get("email", ""),
            border=CONSTANTS.input_border(GREY), color=WHITE)
        prix_field = ft.TextField(
            label="Prix", width=560, bgcolor=DARK,
            border=CONSTANTS.input_border(GREY), color=WHITE)
        # Notes envoyées directement dans le contenu de la page Notion
        # (notion-create-pages accepte "content" dès la création) — pas
        # besoin d'un aller-retour create-puis-replace_content, donc rien
        # ne se perd si l'appel MCP échoue en cours de route.
        notes_field = ft.TextField(
            label="Notes (contenu de la page)", multiline=True,
            value=prefill.get("notes", ""),
            min_lines=4, max_lines=10, width=560, bgcolor=DARK,
            border=CONSTANTS.input_border(GREY), color=WHITE)
        # Mêmes boutons glissants que la fiche détaillée (retour user :
        # interfaces identiques). Défauts : À faire / Pas de projet /
        # Non payé / Viendra d'office.
        ETAT_SEG_LABELS = {"En cours / en attente": "En cours"}
        seg_specs = [
            ("Etat", [e for e, _c in KANBAN_ETATS], KANBAN_ETAT_COLORS,
             "À faire"),
            ("Projet ?", KANBAN_PROJET_OPTIONS, KANBAN_PROJET_COLORS,
             "Pas de projet"),
            ("Payé ?", KANBAN_PAYE_OPTIONS, KANBAN_PAYE_COLORS, "Non payé"),
            ("Prévenir ?", KANBAN_PREVENU_OPTIONS, KANBAN_PREVENU_COLORS,
             prefill.get("prevenir", "Viendra d'office")),
        ]
        prop_segs = {}
        seg_rows = []

        def _make_seg(options, colors, default):
            texts = [ft.Text(ETAT_SEG_LABELS.get(o, o), size=11)
                     for o in options]
            index = options.index(default) if default in options else 0

            def _restyle():
                for k, t in enumerate(texts):
                    t.color = DARK if k == seg.selected_index else WHITE
                seg.thumb_color = colors.get(
                    options[seg.selected_index], VIOLET)

            def _on_change(event):
                _restyle()
                seg.update()

            seg = ft.CupertinoSlidingSegmentedButton(
                selected_index=index, controls=texts,
                on_change=_on_change, width=560)
            _restyle()
            return seg

        for notion_prop, options, colors, default in seg_specs:
            seg = _make_seg(options, colors, default)
            prop_segs[notion_prop] = (seg, options)
            seg_rows += [ft.Text(notion_prop, size=11, color=LIGHT_GREY),
                         seg]

        def _cancel(event):
            dlg.open = False
            page.update()

        def _confirm(event):
            title = (title_field.value or "").strip()
            if not title:
                return
            properties = {"Demande": title}
            for notion_prop, (seg, options) in prop_segs.items():
                properties[notion_prop] = options[seg.selected_index]
            deadline = (deadline_field.value or "").strip()
            if deadline:
                properties["Deadline"] = deadline
            telephone = (telephone_field.value or "").strip()
            if telephone:
                properties["Téléphone"] = telephone
            email = (email_field.value or "").strip()
            if email:
                properties["E-mail"] = email
            prix_raw = (prix_field.value or "").strip()
            if prix_raw:
                try:
                    properties["Prix"] = float(prix_raw.replace(",", "."))
                except ValueError:
                    pass
            notes = (notes_field.value or "").strip()
            content = _kanban_plain_to_notion(notes) if notes else None
            dlg.open = False
            kanban_status.value = "Création…"
            page.update()

            def _work():
                data_source_id = KANBAN_DATA_SOURCE.split("://", 1)[-1]
                page_data = {"properties": properties}
                if content:
                    page_data["content"] = content
                result = _notion_call(
                    "mcp__notion__notion-create-pages",
                    {"parent": {"type": "data_source_id",
                                "data_source_id": data_source_id},
                     "pages": [page_data]})
                failed = result.startswith("Erreur")

                async def _apply():
                    if failed:
                        kanban_status.value = f"Échec de création : {result}"
                        page.update()
                    else:
                        _kanban_refresh()

                _run_task(_apply)

            threading.Thread(target=_work, daemon=True).start()

        dlg = _dialog(
            title=ft.Text("Nouvelle tâche", size=CONSTANTS.TEXT_SM,
                          color=WHITE),
            content=ft.Column([
                ft.Container(height=10),
                title_field,
                deadline_field, telephone_field, email_field, prix_field,
                *seg_rows,
                ft.Divider(height=1, color=GREY),
                notes_field,
            ], tight=True, spacing=8, scroll=ft.ScrollMode.AUTO,
               width=600,
               height=max(300, min(640, (page.height or 900) - 220))),
            actions=[_dlg_btn("Annuler", "cancel", on_click=_cancel),
                     _dlg_btn("Créer", "primary", on_click=_confirm)],
            inset_padding=ft.Padding(20, 40, 20, 40),
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    # Voile par-dessus le tableau pendant une synchro Notion (retour
    # user) : bloque le glisser-déposer et les clics, message clair.
    kanban_sync_veil = ui_helpers.busy_veil(
        "Synchronisation…", SURFACE_ACCENT["kanban"])
    # Même voile dans l'Agenda pendant une synchro Notion (retour user).
    agenda_sync_veil = ui_helpers.busy_veil(
        "Synchronisation avec Notion…", SURFACE_ACCENT["agenda"])

    def _kanban_busy(delta):
        kanban_state["busy"] = max(0, kanban_state.get("busy", 0) + delta)
        # Les deux voiles suivent le même compteur : les tâches sont aussi
        # dans l'Agenda.
        for veil in (kanban_sync_veil, agenda_sync_veil):
            ui_helpers.set_busy_veil(veil, kanban_state["busy"] > 0)

    def _kanban_files_row(page_id, read_only=False):
        """Fichiers joints à la carte, stockés sur le Pi (hub_sync) :
        clic = ouvrir, ✕ = retirer, Joindre = un ou plusieurs fichiers."""
        files_row = ft.Row(wrap=True, spacing=4, run_spacing=4)
        if not hub_sync.available():
            return files_row
        local_dir = os.path.join(tempfile.gettempdir(), "hub_task_files",
                                 page_id.replace("-", ""))

        def _bg(work):
            def _run():
                try:
                    work()
                except Exception as exc:
                    _log_to_terminal(f"[Fichiers] {exc}", RED)
                _refresh()
            threading.Thread(target=_run, daemon=True).start()

        def _viewer(name, data, path):
            """Image vue dans Hub : Enregistrer (où on veut, ex. dossier
            du projet) ou Ouvrir avec l'appli par défaut."""
            async def _save(e):
                await ft.FilePicker().save_file(
                    dialog_title="Enregistrer", file_name=name,
                    src_bytes=data)

            def _close(e=None):
                dlg.open = False
                page.update()
            dlg = _dialog(
                title=ft.Text(name), content=ft.Image(
                    src=data, fit=ft.BoxFit.CONTAIN,
                    width=min(1100, (page.width or 1200) - 120),
                    height=max(300, (page.height or 900) - 260)),
                actions=[
                    _dlg_btn("Ouvrir", "cancel", on_click=lambda e: (
                        _close(), _open_file_default(path))),
                    _dlg_btn("Enregistrer", "primary", on_click=_save),
                    _dlg_btn("Fermer", "cancel", on_click=_close)],
                inset_padding=ft.Padding(20, 30, 20, 30))
            page.overlay.append(dlg)
            dlg.open = True
            page.update()

        def _open(name):
            def work():
                os.makedirs(local_dir, exist_ok=True)
                path = os.path.join(local_dir, name)
                data = hub_sync.file_req("GET", page_id, name)
                with open(path, "wb") as f:
                    f.write(data)
                if os.path.splitext(name)[1].lower() not in IMAGE_EXTS:
                    _open_file_default(path)
                    return

                async def _show():
                    _viewer(name, data, path)
                _run_task(_show)
            _bg(work)

        async def _attach(e):
            picked = await ft.FilePicker().pick_files(
                dialog_title="Joindre des fichiers", allow_multiple=True)
            paths = [f.path for f in picked or [] if f.path]

            def work():
                for p in paths:
                    with open(p, "rb") as f:
                        hub_sync.file_req("PUT", page_id,
                                          os.path.basename(p), f.read(),
                                          timeout=300)
            if paths:
                _bg(work)

        def _chip(name):
            return ft.Container(ft.Row([c for c in [
                ft.TextButton(content=ft.Row([
                    ft.Icon(ft.Icons.ATTACH_FILE, color=LIGHT_GREY,
                            size=CONSTANTS.ICON_SM),
                    ft.Text(name, size=CONSTANTS.TEXT_SM, color=WHITE)],
                    spacing=4, tight=True),
                    on_click=lambda e: _open(name)),
                None if read_only else ft.IconButton(
                    ft.Icons.CLOSE, icon_size=14, icon_color=LIGHT_GREY,
                    tooltip="Retirer", on_click=lambda e: _bg(
                        lambda: hub_sync.file_req("DELETE", page_id,
                                                  name)))] if c],
                spacing=0, tight=True),
                bgcolor=GREY, border_radius=8)

        def _refresh():
            try:
                names = hub_sync.list_files(page_id)
            except Exception:
                names = []
            files_row.controls = [_chip(n) for n in names]
            if not read_only:
                files_row.controls.append(ft.TextButton(
                    content=ft.Row([
                        ft.Icon(ft.Icons.ADD, color=MINT,
                                size=CONSTANTS.ICON_SM),
                        ft.Text("Joindre", size=CONSTANTS.TEXT_SM,
                                color=WHITE)], spacing=4, tight=True),
                    on_click=_attach))
            try:
                files_row.update()
            except Exception:
                pass  # dialogue déjà fermé

        threading.Thread(target=_refresh, daemon=True).start()
        return files_row

    def _kanban_to_trash(rows):
        """Copie locale des tâches supprimées (thread de travail : va
        chercher les Notes pas encore en cache)."""
        if not rows:
            return
        trash = _load_json(_KANBAN_TRASH_FILE, [])
        known = {t["row"]["page_id"] for t in trash}
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        for r in rows:
            if r["page_id"] in known:
                continue
            r = dict(r)
            if r.get("notes") is None:
                raw = _notion_call("mcp__notion__notion-fetch",
                                   {"id": r["page_id"]})
                if not raw.startswith("Erreur"):
                    r["notes"] = _kanban_notion_to_plain(
                        _kanban_extract_page_content(raw) or "")
            trash.insert(0, {"deleted_at": now, "row": r})
        _save_json(_KANBAN_TRASH_FILE, trash)

    def _kanban_restore(entry, dlg):
        """Sortie de la corbeille Notion si encore possible (30 j), sinon
        recréée à partir de la copie locale."""
        row = entry["row"]
        dlg.open = False
        kanban_status.value = "Restauration…"
        page.update()

        def _work():
            result = _notion_call("mcp__notion__notion-restore-page",
                                  {"page_id": row["page_id"]})
            if result.startswith("Erreur"):
                props = {"Demande": row["demande"], "Etat": row["etat"],
                         "Deadline": row.get("deadline"),
                         "Téléphone": row.get("telephone"),
                         "E-mail": row.get("email"), "Prix": row.get("prix"),
                         "Projet ?": row.get("projet"),
                         "Payé ?": row.get("paye"),
                         "Prévenir ?": row.get("prevenu")}
                page_data = {"properties": {k: v for k, v in props.items()
                                            if v not in (None, "")}}
                if row.get("notes"):
                    page_data["content"] = _kanban_plain_to_notion(
                        row["notes"])
                result = _notion_call(
                    "mcp__notion__notion-create-pages",
                    {"parent": {"type": "data_source_id",
                                "data_source_id":
                                    KANBAN_DATA_SOURCE.split("://", 1)[-1]},
                     "pages": [page_data]})
            failed = result.startswith("Erreur")
            if not failed:
                _save_json(_KANBAN_TRASH_FILE, [
                    t for t in _load_json(_KANBAN_TRASH_FILE, [])
                    if t["row"]["page_id"] != row["page_id"]])

            async def _apply():
                if failed:
                    kanban_status.value = f"Échec de la restauration : {result}"
                    page.update()
                else:
                    _kanban_refresh()

            _run_task(_apply)

        threading.Thread(target=_work, daemon=True).start()

    def _kanban_show_trash(e=None):
        limit = (datetime.datetime.now() - datetime.timedelta(
            days=_KANBAN_TRASH_DAYS)).strftime("%Y-%m-%d %H:%M")
        trash = [t for t in _load_json(_KANBAN_TRASH_FILE, [])
                 if t["deleted_at"] >= limit]
        _save_json(_KANBAN_TRASH_FILE, trash)
        items = ft.ListView(spacing=4, height=460, width=560)
        dlg = None

        def _fill(query=""):
            q = query.lower().strip()
            items.controls = [
                ft.Container(
                    ft.Row([
                        ft.Column([
                            ft.Text(t["row"]["demande"], color=WHITE,
                                    size=CONSTANTS.TEXT_SM, no_wrap=False),
                            ft.Text(f"Supprimée le {t['deleted_at']} — "
                                    f"{t['row'].get('etat', '')}",
                                    size=11, color=LIGHT_GREY),
                        ], spacing=2, expand=True),
                        _dlg_btn("Restaurer", color=SURFACE_ACCENT["kanban"],
                                 on_click=lambda e, t=t: _kanban_restore(
                                     t, dlg)),
                        ft.IconButton(ft.Icons.DELETE_FOREVER_OUTLINED,
                                      icon_color=RED,
                                      tooltip="Supprimer définitivement",
                                      on_click=lambda e, t=t: _forget(t)),
                    ]),
                    padding=8, border_radius=8, bgcolor=BACKGROUND,
                    on_click=lambda e, t=t: _kanban_open_details(
                        dict(t["row"]), trash=(t, dlg)))
                for t in trash
                if not q or q in json.dumps(t, ensure_ascii=False).lower()]

        def _forget(t):
            trash.remove(t)
            _save_json(_KANBAN_TRASH_FILE, trash)
            _fill(search.value or "")
            items.update()

        def _on_search(e):
            _fill(e.control.value or "")
            items.update()

        _fill()
        dlg = _dialog(
            title=ft.Text("Corbeille des tâches", size=CONSTANTS.TEXT_SM,
                          color=WHITE),
            content=ft.Column([
                search := ft.TextField(
                             hint_text="Rechercher…", on_change=_on_search,
                             width=560,
                             border=CONSTANTS.input_border(
                                 SURFACE_ACCENT["kanban"]),
                             color=WHITE, bgcolor=DARK, autofocus=True),
                items], tight=True, spacing=8),
            actions=[_dlg_btn("Fermer", "cancel",
                              on_click=lambda e: (setattr(dlg, "open", False),
                                                  page.update()))])
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _sync_label(cache_file=None):
        """« Synchro 14:05 » (aujourd'hui) ou « Synchro 26/09 14:05 » ;
        au démarrage, date du fichier cache."""
        # ponytail: mtime du cache — une modif locale le réécrit aussi.
        try:
            t = (datetime.datetime.fromtimestamp(os.path.getmtime(cache_file))
                 if cache_file else datetime.datetime.now())
        except OSError:
            return "Pas encore synchronisé"
        fmt = "%H:%M" if t.date() == datetime.date.today() else "%d/%m %H:%M"
        return f"Synchro {t.strftime(fmt)}"

    def _kanban_refresh(event=None):
        if kanban_state["loading"]:
            return
        kanban_state["loading"] = True
        _kanban_busy(1)
        kanban_status.value = "Chargement…"
        page.update()

        def _work():
            try:
                raw = _notion_call(
                    "mcp__notion__notion-query-data-sources",
                    {"data": {"mode": "rows",
                              "data_source_url": KANBAN_DATA_SOURCE,
                              "limit": 100}})
                error = raw if raw.startswith("Erreur") else None
                rows = [] if error else _kanban_parse_rows(raw)
                if not error:
                    # Reporte les Notes déjà en cache (page_id -> texte) :
                    # un refresh ne les récupère pas (pas une propriété),
                    # sans ça chaque refresh effacerait le cache constitué
                    # au fil des ouvertures de détails.
                    # Page modifiée ailleurs (autre machine) : notes en
                    # cache périmées, rechargées à l'ouverture (retour user).
                    cached_notes = {
                        r["page_id"]: (r["notes"], r.get("edited", ""))
                        for r in kanban_state["rows"]
                        if r.get("notes") is not None}
                    for r in rows:
                        notes, edited = cached_notes.get(
                            r["page_id"], (None, None))
                        if notes is not None and edited == r["edited"]:
                            r["notes"] = notes
                    # Supprimées dans Notion depuis la dernière synchro
                    # (requête paginée complète : absence = suppression).
                    ids = {r["page_id"] for r in rows}
                    _kanban_to_trash([r for r in kanban_state["rows"]
                                      if r["page_id"] not in ids])
            except Exception as exc:
                rows, error = [], str(exc)
            pi_pb = hub_sync.pi_problems() if hub_sync.available() else []

            async def _apply():
                kanban_state["loading"] = False
                _kanban_busy(-1)
                if error:
                    kanban_status.value = f"Erreur de chargement : {error}"
                else:
                    kanban_state["rows"] = rows
                    _save_json(_KANBAN_CACHE_FILE, rows)
                    kanban_status.value = (
                        f"{len(rows)} tâches — {_sync_label()}")
                    kanban_status.color = LIGHT_GREY
                    if pi_pb:
                        kanban_status.value = "Pi : " + " · ".join(pi_pb)
                        kanban_status.color = RED
                    _kanban_rebuild_columns()
                    _agenda_rebuild()
                page.update()

            _run_task(_apply)

        threading.Thread(target=_work, daemon=True).start()

    def _kanban_drop(e, new_etat, before=None):
        # e.src None : la carte glissée a été reconstruite entre-temps (le
        # changement précédent redessine les colonnes) — drop ignoré au
        # lieu de planter (retour user : glisser trop vite).
        if e.src is None:
            return
        page_id = e.src.data
        row = next((r for r in kanban_state["rows"]
                    if r["page_id"] == page_id), None)
        if row is None:
            return
        _kanban_move(page_id, new_etat, before)
        if row["etat"] != new_etat:
            _kanban_change_property(row, "Etat", "etat", new_etat)
        else:
            _kanban_rebuild_columns()
            page.update()

    # Largeur de colonne calculée dynamiquement (voir _kanban_col_width) :
    # plein écran → les 5 colonnes se répartissent toute la largeur ; en
    # dessous de la largeur mini, elles gardent cette largeur mini et la
    # Row défile horizontalement (comme Notion) plutôt que de se replier
    # sur plusieurs lignes — le repli en lignes (essayé via ResponsiveRow)
    # cassait le défilement vertical propre à chaque colonne (retour user).
    KANBAN_COL_MIN_WIDTH = 260
    KANBAN_COL_SPACING = 8
    kanban_column_targets = {}

    def _kanban_col_width():
        n = len(KANBAN_ETATS)
        # Marge 64 (pas 32) : sous Windows, la barre de défilement et le
        # cadre de fenêtre rognaient la dernière colonne (retour user).
        avail = (page.width or 1200) - 64 - KANBAN_COL_SPACING * (n - 1)
        return max(KANBAN_COL_MIN_WIDTH, avail / n)

    def _kanban_column(etat, color):
        # La largeur est portée par ce Container (le contenu du
        # DragTarget), pas par le DragTarget lui-même — `width` n'existe
        # pas dans son constructeur (seulement `expand`/`col`).
        column_body = ft.Container(
            content=ft.Column([
                ft.Container(
                    # Même style que les pastilles (_kanban_chip) :
                    # fond quasi plein + texte noir (retour user).
                    content=ft.Text(etat, size=14, color=ft.Colors.BLACK,
                                    weight=ft.FontWeight.W_700,
                                    text_align=ft.TextAlign.CENTER),
                    bgcolor=ft.Colors.with_opacity(0.85, color),
                    border_radius=6, padding=ft.Padding(8, 4, 8, 4),
                    # Aère sous la barre de recherche (retour user).
                    margin=ft.Margin(0, 12, 0, 0)),
                kanban_columns[etat],
            ], spacing=6, expand=True, tight=True,
               # En-têtes pleine largeur de colonne, donc alignés entre
               # eux (retour user) — START les réduisait à leur texte.
               horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            width=_kanban_col_width(), padding=ft.Padding(4, 0, 4, 0))
        kanban_column_targets[etat] = column_body
        return ft.DragTarget(
            group="kanban_card", content=column_body,
            on_accept=(lambda e, t=etat: _kanban_drop(e, t)))

    def _kanban_on_resize(event=None):
        new_width = _kanban_col_width()
        changed = False
        for container in kanban_column_targets.values():
            if container.width != new_width:
                container.width = new_width
                changed = True
        if changed:
            page.update()

    def _kanban_search_change(event):
        kanban_state["search"] = kanban_search_field.value or ""
        _kanban_rebuild_columns()
        page.update()

    def _kanban_search_clear(event=None):
        kanban_search_field.value = ""
        kanban_state["search"] = ""
        _kanban_rebuild_columns()
        page.update()

    # Filtre local sur les tâches déjà chargées (titre/téléphone/e-mail) —
    # pas un nouvel appel MCP à chaque frappe (retour user : limiter les
    # appels réseau). Bouton d'effacement séparé (IconButton à côté, PAS
    # `suffix=` sur le TextField) — cf. l'exact même piège déjà documenté
    # pour search_field (recherche Fichiers, plus haut dans ce fichier) :
    # `suffix=` plaque le hint_text vers le bas.
    kanban_search_field = ft.TextField(
        hint_text="Rechercher…", height=36, dense=True, expand=True,
        bgcolor=DARK, border=CONSTANTS.input_border(SURFACE_ACCENT["kanban"]),
        color=WHITE, prefix_icon=ft.Icons.SEARCH,
        on_change=_kanban_search_change, on_submit=_kanban_search_clear)
    kanban_search_clear_btn = ft.IconButton(
        ft.Icons.CLOSE, **SQUARE_BTN, icon_size=CONSTANTS.ICON_SM,
        icon_color=LIGHT_GREY, tooltip="Effacer la recherche",
        on_click=_kanban_search_clear)
    kanban_search_wrap = ft.Row(
        [kanban_search_field, kanban_search_clear_btn], spacing=4,
        expand=True, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _kanban_toggle_auto_sync(event):
        kanban_state["auto_sync"] = event.control.value
        _save_json(_KANBAN_SETTINGS_FILE,
                  {"auto_sync": kanban_state["auto_sync"]})

    kanban_auto_sync_switch = ft.Switch(
        label="Auto-sync", value=kanban_state["auto_sync"],
        active_color=SURFACE_ACCENT["kanban"],
        tooltip="Resynchronise automatiquement tout le tableau après "
                "chaque modification (Etat, badges…) — sans clic sur "
                "\"Actualiser\"",
        on_change=_kanban_toggle_auto_sync)

    kanban_surface = ft.Column([
        ft.Container(
            # Recherche d'abord (extensible), les 2 boutons tout à droite
            # (retour user — même agencement que la barre Liste).
            content=ft.Row([
                _surface_title("Tâches", "kanban"),
                kanban_search_wrap,
                kanban_auto_sync_switch,
                kanban_status,
                ft.IconButton(ft.Icons.DELETE_OUTLINE, **SQUARE_BTN,
                             icon_color=SURFACE_ACCENT["kanban"],
                             icon_size=CONSTANTS.ICON_SM,
                             tooltip="Corbeille",
                             on_click=_kanban_show_trash),
                ft.IconButton(ft.Icons.ADD, **SQUARE_BTN,
                             icon_color=SURFACE_ACCENT["kanban"],
                             icon_size=CONSTANTS.ICON_SM,
                             tooltip="Nouvelle tâche",
                             on_click=_kanban_new_task),
                ft.IconButton(ft.Icons.REFRESH, **SQUARE_BTN,
                             icon_color=SURFACE_ACCENT["kanban"],
                             icon_size=CONSTANTS.ICON_SM,
                             tooltip="Actualiser",
                             on_click=_kanban_refresh),
            ], spacing=8),
            height=TOOLBAR_H, padding=ft.Padding(12, 0, 12, 0),
            alignment=ft.Alignment(-1, 0), bgcolor=BACKGROUND),
        ft.Divider(height=1, color=GREY),
        # Colonnes à largeur calculée (cf. _kanban_col_width) : se
        # répartissent toute la largeur en plein écran, gardent leur
        # largeur mini en fenêtre étroite avec défilement horizontal pour
        # atteindre les autres — chaque colonne garde ainsi son propre
        # défilement vertical (ListView expand=True), contrairement au
        # repli multi-lignes ResponsiveRow essayé avant (retour user).
        ft.Stack([ft.Row(
            [_kanban_column(etat, color) for etat, color in KANBAN_ETATS],
            expand=True, spacing=KANBAN_COL_SPACING,
            # Centrées : marge gauche = marge droite (retour user).
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            scroll=ft.ScrollMode.AUTO), kanban_sync_veil], expand=True),
    ], expand=True, spacing=0,
       # Sans ça, une Column ne force pas ses enfants à sa pleine largeur
       # (horizontal_alignment=START par défaut) : la Row des colonnes se
       # réduisait alors à la largeur intrinsèque de son contenu, laissant
       # les colonnes "expand" sans largeur bornée à se répartir (retour
       # user : rien d'autre que "À faire" ne s'affichait toujours).
       horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    if kanban_state["rows"]:
        # Affiche tout de suite le cache (rempli au run précédent) — plus
        # de rechargement auto (retour user), actualisation via le bouton.
        _kanban_rebuild_columns()
        kanban_status.value = (f"{len(kanban_state['rows'])} tâches — "
                               f"{_sync_label(_KANBAN_CACHE_FILE)}")

    # Recalcule la largeur des colonnes à chaque redimensionnement de la
    # fenêtre (mode plein écran / demi-écran...) — cf. _kanban_col_width.
    _existing_on_resize = page.on_resize

    def _on_page_resize(event):
        if _existing_on_resize:
            _existing_on_resize(event)
        _kanban_on_resize(event)

    page.on_resize = _on_page_resize

    return {
        "_kanban_busy": _kanban_busy,
        "_kanban_change_property": _kanban_change_property,
        "_kanban_deadline_field": _kanban_deadline_field,
        "_kanban_extract_page_content": _kanban_extract_page_content,
        "_kanban_new_task": _kanban_new_task,
        "_kanban_notion_to_plain": _kanban_notion_to_plain,
        "_kanban_open_details": _kanban_open_details,
        "_kanban_plain_to_notion": _kanban_plain_to_notion,
        "_kanban_refresh": _kanban_refresh,
        "_sync_label": _sync_label,
        "agenda_sync_veil": agenda_sync_veil,
        "kanban_state": kanban_state,
        "kanban_status": kanban_status,
        "kanban_surface": kanban_surface,
    }
