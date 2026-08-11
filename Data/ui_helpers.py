"""
Widgets d'interface partagés entre les apps Flet du dossier Data/ (Hub,
Recadrage manuel, etc.) — pour l'instant juste le pavé numérique
tactile, extrait de Hub.pyw (_set_print_count) pour que les autres
outils puissent le réutiliser sans dupliquer le code.
"""
import flet as ft


def numeric_keypad(page, fields, colors, on_confirm=None,
                    allow_decimal=False):
    """Pavé numérique tactile réutilisable, attaché à un ou plusieurs
    champs texte (retour user : le clavier virtuel de l'OS n'apparaît
    pas toujours de façon fiable sur un poste tactile).

    - page : l'objet ft.Page de l'app appelante (pour .update()).
    - fields : un ft.TextField, ou une liste de plusieurs — avec
      plusieurs champs, le pavé agit sur celui qui a le focus (premier
      champ par défaut).
    - colors : dict avec les clés "dark", "red", "grey", "green",
      "white" — chaque app définit ses propres couleurs depuis
      CONSTANTS, on les reçoit ici plutôt que de les importer en dur
      (les valeurs diffèrent d'un thème d'app à l'autre).
    - on_confirm : callback optionnel, ajoute un bouton ✓ au pavé.
    - allow_decimal : ajoute une touche "." — utile pour des
      dimensions en mm/px qui acceptent les décimales, pas pour un
      compteur entier (ex. nombre d'impressions).
    """
    field_list = ([fields] if isinstance(fields, ft.TextField)
                  else list(fields))
    active = {"field": field_list[0]}

    def _track_focus(target_field):
        previous = target_field.on_focus

        def _on_focus(event, _prev=previous, _f=target_field):
            active["field"] = _f
            if _prev:
                _prev(event)
        target_field.on_focus = _on_focus

    for f in field_list:
        _track_focus(f)

    def _append(text):
        def _on_click(event):
            fld = active["field"]
            current = "" if fld.value in (None, "0") else fld.value
            if text == "." and "." in (current or ""):
                return  # un seul point décimal par nombre
            fld.value = (current or "") + text
            page.update()
        return _on_click

    def _backspace(event):
        fld = active["field"]
        fld.value = (fld.value or "")[:-1]
        page.update()

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
    if on_confirm is not None:
        last_row.append(ft.IconButton(
            ft.Icons.CHECK_CIRCLE_OUTLINE, icon_color=colors["green"],
            icon_size=24,
            style=ft.ButtonStyle(bgcolor=colors["grey"],
                                 padding=ft.Padding.all(16)),
            on_click=on_confirm))

    return ft.Column([
        ft.Row([_key_btn("7"), _key_btn("8"), _key_btn("9")], spacing=8),
        ft.Row([_key_btn("4"), _key_btn("5"), _key_btn("6")], spacing=8),
        ft.Row([_key_btn("1"), _key_btn("2"), _key_btn("3")], spacing=8),
        ft.Row(last_row, spacing=8),
    ], spacing=8, tight=True)
