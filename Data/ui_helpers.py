"""
Widgets d'interface partagés entre les apps Flet du dossier Data/ (Hub,
Recadrage manuel, etc.), extraits de Hub.pyw où ces motifs étaient
répétés dans plusieurs dialogues quasi identiques, pour que les autres
outils puissent les réutiliser sans dupliquer le code : pavé numérique
tactile, dialogue "un champ texte", dialogue de confirmation à deux
boutons.

Convention commune à toutes les fonctions de ce module : `colors` est
un dict {"dark", "red", "grey", "green", "white"} — chaque app définit
ses propres couleurs depuis CONSTANTS et les passe ici plutôt que ce
module les importe en dur (les valeurs diffèrent d'un thème d'app à
l'autre).
"""
import asyncio

import flet as ft

TEXT_SIZE_DEFAULT = 13  # = CONSTANTS.TEXT_SM au moment de l'écriture


def numeric_keypad(page, fields, colors, on_confirm=None,
                    allow_decimal=False, staged=False):
    """Pavé numérique tactile réutilisable, attaché à un ou plusieurs
    champs texte (retour user : le clavier virtuel de l'OS n'apparaît
    pas toujours de façon fiable sur un poste tactile).

    - page : l'objet ft.Page de l'app appelante (pour .update()).
    - fields : un ft.TextField, ou une liste de plusieurs — avec
      plusieurs champs, le pavé agit sur celui qui a le focus (premier
      champ par défaut).
    - colors : dict avec les clés "dark", "red", "grey", "green",
      "white" — chaque app définit ses propres couleurs depuis
      CONSTANTS, on les reçoit ici plutôt que ce module les importe en
      dur (les valeurs diffèrent d'un thème d'app à l'autre).
    - on_confirm : callback optionnel, appelé en plus de la validation
      elle-même (ex. fermer un dialogue).
    - allow_decimal : ajoute une touche "." — utile pour des
      dimensions en mm/px qui acceptent les décimales, pas pour un
      compteur entier (ex. nombre d'impressions).
    - staged : si True, les chiffres tapés s'accumulent dans un champ
      d'affichage propre au pavé, PAS dans le champ visé — qui n'est
      mis à jour qu'au clic sur ✓ (Valider), désormais toujours
      présent dans ce mode. Sert quand le pavé peut apparaître/
      disparaître selon le focus du champ (ex. overlay Montage) : taper
      un chiffre déclenche le blur natif du champ, donc écrire
      directement dedans dépend d'un focus qui vient de sauter (retour
      user : "je clique sur un chiffre et il disparait sans que rien
      ne se passe"). Par défaut (False) : comportement historique,
      écriture directe dans le champ actif — inchangé pour les
      dialogues où le pavé reste affiché en permanence (pas de
      show/hide sur focus), qui n'ont jamais eu ce problème.
    """
    field_list = ([fields] if isinstance(fields, ft.TextField)
                  else list(fields))
    active = {"field": field_list[0]}
    display = ft.TextField(
        value=field_list[0].value or "", width=56 * 3 + 16,
        text_align=ft.TextAlign.CENTER, bgcolor=colors["dark"],
        border_color=colors["grey"], color=colors["white"]) if staged else None
    # Un champ pré-rempli (valeur par défaut, ex. "100") doit s'effacer
    # au premier chiffre tapé plutôt que de s'y voir accolé ("1001") —
    # retour user. On ne vide pas .value dès le départ pour autant : du
    # code ailleurs (ex. Recadrage manuel.pyw) lit cette valeur par
    # défaut avant que l'utilisateur n'ait rien tapé. "fresh" ne marque
    # donc que l'INTENTION de tout effacer au prochain chiffre — remis à
    # True à chaque focus.
    fresh = {id(f): True for f in field_list}

    def _track_focus(target_field):
        previous = target_field.on_focus

        def _on_focus(event, _prev=previous, _f=target_field):
            active["field"] = _f
            fresh[id(_f)] = True
            if staged:
                display.value = _f.value or ""
                display.update()
            if _prev:
                _prev(event)
        target_field.on_focus = _on_focus

    for f in field_list:
        _track_focus(f)

    def _append(text):
        def _on_click(event):
            fld = display if staged else active["field"]
            if fresh[id(active["field"])]:
                current = ""
                fresh[id(active["field"])] = False
            else:
                current = "" if fld.value in (None, "0") else fld.value
            if text == "." and "." in (current or ""):
                return  # un seul point décimal par nombre
            fld.value = (current or "") + text
            fld.update() if staged else page.update()
        return _on_click

    def _backspace(event):
        fld = display if staged else active["field"]
        fresh[id(active["field"])] = False
        fld.value = (fld.value or "")[:-1]
        fld.update() if staged else page.update()

    def _validate(event):
        active["field"].value = display.value
        active["field"].update()
        if on_confirm is not None:
            on_confirm(event)

    def _key_btn(label):
        return ft.Button(
            label, width=56, height=56, on_click=_append(label),
            style=ft.ButtonStyle(bgcolor=colors["dark"],
                                 color=colors["white"]))

    last_row = [
        ft.IconButton(
            ft.Icons.BACKSPACE_OUTLINED, icon_color=colors["red"],
            icon_size=24,
            style=ft.ButtonStyle(bgcolor=colors["grey"],
                                 padding=ft.Padding.all(16)),
            on_click=_backspace),
    ]
    if allow_decimal:
        last_row.append(_key_btn("."))
    last_row.append(_key_btn("0"))
    if staged or on_confirm is not None:
        last_row.append(ft.IconButton(
            ft.Icons.CHECK_CIRCLE_OUTLINE, icon_color=colors["green"],
            icon_size=24,
            style=ft.ButtonStyle(bgcolor=colors["grey"],
                                 padding=ft.Padding.all(16)),
            on_click=_validate if staged else on_confirm))

    rows = [
        ft.Row([_key_btn("7"), _key_btn("8"), _key_btn("9")], spacing=8),
        ft.Row([_key_btn("4"), _key_btn("5"), _key_btn("6")], spacing=8),
        ft.Row([_key_btn("1"), _key_btn("2"), _key_btn("3")], spacing=8),
        ft.Row(last_row, spacing=8),
    ]
    if staged:
        rows.insert(0, ft.Row([display], alignment=ft.MainAxisAlignment.CENTER))
    return ft.Column(rows, spacing=8, tight=True)


async def _focus_soon(field):
    # autofocus=True sur un TextField de dialogue ne marche pas de façon
    # fiable (le contrôle n'est pas encore monté côté client quand
    # page.update() rend la main) — délai court avant .focus() en
    # remède, comme Hub.pyw:_focus_dialog_field.
    try:
        await asyncio.sleep(0.15)
        await field.focus()
    except Exception:
        pass


def text_prompt_dialog(page, title, on_confirm, colors, label=None,
                       hint_text=None, value="", confirm_label="Confirmer",
                       cancel_label="Annuler", text_size=TEXT_SIZE_DEFAULT,
                       width=280):
    """Dialogue générique "un champ texte + Annuler/Confirmer" — ex.
    demander un nom de dossier/fichier, ou une valeur à passer à un
    outil externe.

    - on_confirm(value) : appelé avec le texte saisi (déjà .strip()) à
      la confirmation — que la chaîne soit vide ou non, c'est à
      l'appelant de décider quoi en faire (valeur par défaut, refus...).
    - label / hint_text : label flottant et texte d'exemple grisé,
      indépendants (les deux peuvent être fournis, ou aucun des deux).
    - value : texte pré-rempli (vide par défaut).

    Retourne le ft.AlertDialog (rarement utile à l'appelant, mais
    cohérent avec confirm_dialog).
    """
    field = ft.TextField(
        label=label, hint_text=hint_text, value=value, autofocus=True,
        width=width, bgcolor=colors["dark"], border_color=colors["grey"],
        color=colors["white"])

    fired = {"done": False}

    def _cancel(event):
        dlg.open = False
        page.update()

    def _confirm(event):
        if fired["done"]:
            return
        fired["done"] = True
        value_out = (field.value or "").strip()
        dlg.open = False
        page.update()
        on_confirm(value_out)

    field.on_submit = _confirm
    dlg = ft.AlertDialog(
        title=ft.Text(title, size=text_size, color=colors["white"]),
        content=field,
        actions=[ft.TextButton(cancel_label, on_click=_cancel),
                 ft.TextButton(confirm_label, on_click=_confirm)],
    )
    page.overlay.append(dlg)
    dlg.open = True
    page.update()
    page.run_task(_focus_soon, field)
    return dlg


def confirm_dialog(page, title, on_confirm, colors, message=None,
                   confirm_label="Confirmer", cancel_label="Annuler",
                   confirm_color=None, on_cancel=None,
                   text_size=TEXT_SIZE_DEFAULT):
    """Dialogue générique de confirmation à deux boutons — pas de champ
    de saisie. Couvre aussi bien "Annuler/Supprimer" (on_cancel omis,
    ne fait que fermer) que "Conserver/Supprimer" où les deux boutons
    déclenchent une vraie action (on_cancel fourni).

    - on_confirm() : appelé sans argument au clic sur confirm_label.
    - on_cancel() : optionnel, appelé sans argument au clic sur
      cancel_label (sinon ce bouton ne fait que fermer le dialogue).
    - message : texte optionnel sous le titre (ex. liste de fichiers
      concernés) ; omis, le dialogue n'a qu'un titre.
    - confirm_color : couleur du bouton de confirmation (ex. RED pour
      une suppression) — None garde la couleur par défaut du thème.
    """
    fired = {"done": False}

    def _make_handler(callback):
        def _handler(event):
            if fired["done"]:
                return
            fired["done"] = True
            dlg.open = False
            page.update()
            if callback:
                callback()
        return _handler

    dlg = ft.AlertDialog(
        title=ft.Text(title, size=text_size, color=colors["white"]),
        content=(ft.Text(message, size=text_size, color=colors["white"])
                 if message else None),
        actions=[
            ft.TextButton(cancel_label, on_click=_make_handler(on_cancel)),
            ft.TextButton(
                confirm_label, on_click=_make_handler(on_confirm),
                style=(ft.ButtonStyle(color=confirm_color)
                      if confirm_color else None)),
        ],
    )
    page.overlay.append(dlg)
    dlg.open = True
    page.update()
    return dlg
