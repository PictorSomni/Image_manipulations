# -*- coding: utf-8 -*-
"""Hub — surface IA (chat + outils, Data/ai_tools.py).

Section extraite de Hub.pyw (main) : build(ui) reçoit l'espace de
noms de main (ui) et renvoie les noms utilisés ailleurs dans Hub."""


from PIL import Image as PILImage
from ai_tools import _MicRecorder
from ai_tools import _format_ai_conversation
from ai_tools import _gemini_live_tts_stream
from ai_tools import _gemini_transcribe_audio
from ai_tools import _gemini_tts_stream
from ai_tools import _md_dark
import CONSTANTS
import asyncio
import base64
import credentials
import flet as ft
import io
import os
import threading


def build(ui):
    BLUE = ui.BLUE
    DARK = ui.DARK
    GREEN = ui.GREEN
    GREY = ui.GREY
    LIGHT_GREY = ui.LIGHT_GREY
    ORANGE = ui.ORANGE
    RED = ui.RED
    SQUARE_BTN = ui.SQUARE_BTN
    VIOLET = ui.VIOLET
    WHITE = ui.WHITE
    YELLOW = ui.YELLOW
    _dialog = ui._dialog
    _dlg_btn = ui._dlg_btn
    _focus_dialog_field = ui._focus_dialog_field
    _focused_input = ui._focused_input
    _history_add = ui._history_add
    _history_idx = ui._history_idx
    _load_json = ui._load_json
    _navigate = ui._navigate
    _notes_save = ui._notes_save
    _run_task = ui._run_task
    _show_notes_panel = ui._show_notes_panel
    ai_text_refs = ui.ai_text_refs
    notes_field = ui.notes_field
    notes_is_preview = ui.notes_is_preview
    notes_preview = ui.notes_preview
    page = ui.page
    state = ui.state
    _ai_generate = ui.late__ai_generate
    _busy_end = ui.late__busy_end
    _busy_start = ui.late__busy_start
    _liste_reload = ui.late__liste_reload
    _log_to_terminal = ui.late__log_to_terminal
    _select_surface = ui.late__select_surface
    # ═════════════════════════════════════════════════════════════════════
    #  Surface IA — chat + outils (cerveau mutualisé Data/ai_tools.py)
    #  v1 : modèles cloud uniquement (Gemini/Claude) — Ollama nécessite une
    #  gestion de process (_ensure_ollama_ready) hors scope pour l'instant.
    # ═════════════════════════════════════════════════════════════════════
    ai_conversation = []
    ai_streaming = {"value": False}
    ai_pending_images = []   # [{"path": str, "b64": str}, ...] — en attente d'envoi
    ai_pending_files = []    # [str, ...] chemins de documents en attente
    # Dernières images jointes au chat (b64) : source de repli pour
    # edit_image quand le modèle l'appelle sur une image collée/uploadée
    # dans la conversation plutôt que sur un fichier du dossier ouvert — le
    # modèle ne connaît alors aucun nom de fichier réel (les bytes envoyés
    # via user_message["images"] ne portent aucune métadonnée de nom) et en
    # invente un plausible (ex. "input_file_1.png"), qui ne correspond à
    # rien sur disque : sans ce repli, edit_image tombait silencieusement
    # en génération pure (aucune image source), produisant un résultat sans
    # rapport avec la photo jointe (retour user).
    ai_send_original_images = {"value": CONSTANTS.AI_IMAGE_ATTACH_DEFAULT_ORIGINAL}
    ai_tts_enabled = {"value": CONSTANTS.AI_VOICE_TTS_ENABLED}
    ai_tts_stop_event = {"event": None}
    _ai_history_file = CONSTANTS.state_file(".ai_conversation_hub.json")

    ai_chat_view = ft.ListView(expand=True, spacing=4, auto_scroll=True)
    ai_attach_row = ft.Row([], spacing=6, wrap=True, visible=False)
    def _ai_input_on_focus(event=None):
        _focused_input["name"] = "ai"

    def _ai_input_on_blur(event=None):
        if _focused_input["name"] == "ai":
            _focused_input["name"] = None
        _history_idx["ai"] = None

    ai_input_field = ft.TextField(
        hint_text="Décris l'image à générer ou la retouche… (Entrée pour envoyer)",
        border=CONSTANTS.input_border(BLUE),
        text_style=ft.TextStyle(font_family="monospace", size=CONSTANTS.TERMINAL_FONT_SIZE),
        dense=True, expand=True, color=WHITE, bgcolor=DARK, shift_enter=True,
        on_focus=_ai_input_on_focus, on_blur=_ai_input_on_blur)
    ai_model_dropdown = ft.Dropdown(
        value=(CONSTANTS.AI_MODEL_TEXT
               if CONSTANTS.AI_MODEL_TEXT in CONSTANTS.AI_DROPDOWN_MODELS
               else CONSTANTS.AI_DROPDOWN_MODELS[0]),
        options=[ft.dropdown.Option(m) for m in CONSTANTS.AI_DROPDOWN_MODELS
                 if m.startswith(("gemini", "claude", "muse"))],
        text_size=CONSTANTS.TEXT_SM, dense=True, color=WHITE, bgcolor=DARK,
        border=CONSTANTS.input_border(GREY),
        content_padding=ft.Padding.symmetric(horizontal=6, vertical=0), width=180)
    # Qualité des images générées/éditées via generate_image/edit_image —
    # 1K par défaut (coût/temps), à monter à 4K pour une image destinée à
    # l'impression (cf. Data/ai_ops.py::run_outpaint pour le même principe).
    ai_image_quality_dropdown = ft.Dropdown(
        value="1K",
        options=[ft.dropdown.Option(q) for q in ("1K", "2K", "4K")],
        tooltip="Qualité des images générées/éditées par l'IA (1K/2K/4K)",
        text_size=CONSTANTS.TEXT_SM, dense=True, color=WHITE, bgcolor=DARK,
        border=CONSTANTS.input_border(GREY),
        content_padding=ft.Padding.symmetric(horizontal=6, vertical=0), width=90)
    # Qualité seulement pour NB2 (Gemini) : Muse est limité à ~1K
    # (retour user).
    ai_image_quality_dropdown.visible = not ai_model_dropdown.value.startswith("muse")

    def _on_ai_model_select(e):
        ai_image_quality_dropdown.visible = not ai_model_dropdown.value.startswith("muse")
        ai_image_quality_dropdown.update()

    ai_model_dropdown.on_select = _on_ai_model_select
    ai_status_text = ft.Text("", color=LIGHT_GREY, size=CONSTANTS.TEXT_SM, italic=True, max_lines=1,
                             overflow=ft.TextOverflow.ELLIPSIS, expand=True)
    ai_progress_bar = ft.ProgressBar(value=None, visible=False, color=BLUE, height=2)

    # Contrôles réellement touchés par un tour de réponse IA. page.update()
    # SANS argument repousse tout l'arbre de la page (les 4 surfaces, la
    # grille de fichiers et ses centaines de vignettes, le terminal) — or
    # _ai_refresh est appelé plusieurs fois par seconde pendant un
    # streaming. On ne pousse donc que ces contrôles-là, comme
    # _clear_selection_visuals le fait déjà avec page.update(*touched).
    # Complété plus bas avec les boutons d'envoi (créés après) ; tant que
    # la liste est vide, page.update(*[]) retombe sur la mise à jour
    # complète, ce qui reste correct au démarrage.
    _ai_refresh_targets = [ai_chat_view, ai_status_text, ai_progress_bar]

    async def _ai_update_and_scroll():
        # Onglet IA démonté (autre onglet actif) : patcher/scroller ses
        # contrôles faisait redémarrer le client Flet (retour user, réponse
        # Muse arrivée sur un autre onglet). Rattrapé au retour sur l'IA.
        if state["surface"] != "ia":
            return
        try:
            page.update(*_ai_refresh_targets)
            await asyncio.sleep(0)
            await ai_chat_view.scroll_to(offset=-1)
        except Exception:
            pass

    def _ai_append_bubble_row(row):
        """Empile une bulle en bornant l'historique affiché.

        Sans plafond, une journée de travail accumule des centaines de
        ft.Markdown et de ft.Image gardés en mémoire, tous réévalués à
        chaque rafraîchissement. Même principe que le terminal intégré
        (HUB_TERMINAL_MAX_LINES) : seules les dernières bulles servent, la
        conversation complète reste dans ai_conversation et dans le
        fichier d'historique.
        """
        ai_chat_view.controls.append(row)
        while len(ai_chat_view.controls) > CONSTANTS.HUB_AI_MAX_BUBBLES:
            ai_chat_view.controls.pop(0)
        # ai_text_refs (utilisé par le réglage de taille de police) pointe
        # sur les Text/Markdown des bulles : le borner aussi, sinon il
        # garde des références sur des contrôles retirés de l'affichage.
        while len(ai_text_refs) > CONSTANTS.HUB_AI_MAX_BUBBLES:
            ai_text_refs.pop(0)

    def _ai_refresh():
        # Depuis un thread (streaming IA en arrière-plan), page.update() direct
        # ne se propage pas de façon fiable en Flet 0.85 — il faut repasser par
        # la boucle asyncio de la page via page.run_task (idiome SidePanel).
        # Si la fenêtre se ferme pendant qu'une réponse tourne encore en
        # arrière-plan, page.run_task lève RuntimeError("session détruite")
        # de façon SYNCHRONE ici (avant même que _ai_update_and_scroll ne
        # démarre, donc son propre try/except ne l'attrape jamais) — sans ce
        # garde, l'exception remonte dans le handler d'erreur ET le finally
        # de _run, qui appellent tous les deux _ai_refresh(), et fait planter
        # le thread IA (retour user : crash à la fermeture de l'app).
        try:
            _run_task(_ai_update_and_scroll)
        except Exception:
            pass

    async def _ai_navigate_async(folder):
        # _navigate()/_render() appellent page.update() en interne : les lancer
        # via page.run_task (plutôt que depuis le thread IA directement) place
        # cet appel sur la boucle asyncio de la page, même contrainte que ci-dessus.
        if folder:
            try:
                _navigate(folder)
            except Exception as exc:
                # _navigate() gère déjà OSError en interne (dossier
                # disparu...) — si une exception remonte quand même
                # jusqu'ici, ce n'est probablement pas ce cas bénin :
                # la logguer plutôt que l'avaler en silence, sinon un
                # vrai bug ailleurs (ex. KeyError sur `state`) passerait
                # pour un simple souci de navigation (retour audit).
                _log_to_terminal(f"[ERREUR] Navigation IA : {exc}", RED)
        # Comme le pubsub "refresh" de SidePanel : l'IA peut avoir écrit dans
        # le fichier .json actuellement ouvert dans la surface Liste (create_
        # file/edit_file, aucun outil dédié) — la recharger à chaque refresh.
        try:
            _liste_reload()
        except Exception:
            pass

    def _speak_bubble(text, force_chunked=False):
        """Lit un texte via Gemini TTS.

        force_chunked=True force la lecture fidèle du texte affiché (sans mode Live).
        """
        def _set_tts_feedback(status_text, show_progress):
            ai_status_text.value = status_text
            ai_progress_bar.visible = show_progress

            async def _apply_ui_update():
                try:
                    page.update()
                except Exception:
                    try:
                        ai_status_text.update()
                        ai_progress_bar.update()
                    except Exception:
                        pass

            try:
                _run_task(_apply_ui_update)
            except Exception:
                try:
                    page.update()
                except Exception:
                    pass

        # Arrêter le TTS précédent s'il tourne encore
        if ai_tts_stop_event["event"] is not None:
            ai_tts_stop_event["event"].set()
        stop_event = threading.Event()
        ai_tts_stop_event["event"] = stop_event
        selected_tts_mode = "chunked" if force_chunked else CONSTANTS.AI_VOICE_TTS_MODE
        if selected_tts_mode == "live":
            _set_tts_feedback(f"🔊 Live — {CONSTANTS.AI_VOICE_TTS_VOICE}…", True)
        else:
            _set_tts_feedback(f"🔊 Préparation de la voix — {CONSTANTS.AI_VOICE_TTS_VOICE}…", True)
        try:
            if selected_tts_mode == "live":
                _gemini_live_tts_stream(
                    text,
                    model=CONSTANTS.AI_VOICE_LIVE_MODEL,
                    voice_name=CONSTANTS.AI_VOICE_TTS_VOICE,
                    sample_rate=CONSTANTS.AI_VOICE_TTS_SAMPLE_RATE,
                    language_code=CONSTANTS.AI_VOICE_TTS_LANGUAGE,
                    stop_event=stop_event,
                    preroll_ms=CONSTANTS.AI_VOICE_TTS_PREROLL_MS,
                )
            else:
                # Streaming audio réel (une seule requête, lecture dès le
                # premier chunk) : plus rapide qu'un appel bloquant pour
                # toutes les longueurs de texte, donc plus besoin de
                # distinguer "court" (one-shot) et "long" (pipeline).
                _gemini_tts_stream(
                    text,
                    voice_name=CONSTANTS.AI_VOICE_TTS_VOICE,
                    tts_model=CONSTANTS.AI_VOICE_TTS_MODEL,
                    sample_rate=CONSTANTS.AI_VOICE_TTS_SAMPLE_RATE,
                    language_code=CONSTANTS.AI_VOICE_TTS_LANGUAGE,
                    stop_event=stop_event,
                    preroll_ms=CONSTANTS.AI_VOICE_TTS_PREROLL_MS,
                )
        except Exception as tts_exc:
            _set_tts_feedback(f"[❌ TTS] {tts_exc}", False)
            return
        finally:
            is_current_tts = ai_tts_stop_event["event"] is stop_event
            if is_current_tts:
                ai_tts_stop_event["event"] = None
                _set_tts_feedback("", False)
            # Referme toujours l'étape "lecture vocale" démarrée par
            # l'appelant (_busy_start appelé avant de lancer le thread qui
            # exécute cette fonction — jamais ici, pour éviter une fenêtre
            # où le compteur retombe à 0 entre le lancement du thread et
            # son premier tour de boucle).
            _busy_end()

    def _toggle_tts(event=None):
        """Active ou désactive la lecture vocale des réponses IA."""
        ai_tts_enabled["value"] = not ai_tts_enabled["value"]
        enabled = ai_tts_enabled["value"]
        ai_speaker_button.icon = ft.Icons.VOLUME_UP if enabled else ft.Icons.VOLUME_OFF
        ai_speaker_button.icon_color = BLUE if enabled else LIGHT_GREY
        ai_speaker_button.tooltip = ("Désactiver la lecture vocale" if enabled
                                     else "Activer la lecture vocale")
        try:
            ai_speaker_button.update()
        except Exception:
            pass

    def _ai_add_bubble(role, text):
        # Forme de bulle de chat façon artefact (.bub.u / .bub.a) : alignée à
        # droite (utilisateur, accent) ou à gauche (assistant, neutre), coin
        # arrondi asymétrique côté « pointe ». expand=8/2 sur la Row imite la
        # largeur max ~82% de l'artefact tout en restant responsive (utile en
        # mode compagnon demi-écran, cf. HUB_SPEC §3).
        is_user = role == "user"
        is_think = role == "think"
        if is_user:
            bubble_text = ft.Text(text, size=state["font_size"], color=DARK,
                                  font_family="monospace", selectable=True)
            bubble = ft.Container(
                content=bubble_text, bgcolor=BLUE, padding=ft.Padding(9, 7, 9, 7),
                border_radius=ft.BorderRadius(top_left=13, top_right=13,
                                              bottom_left=13, bottom_right=4),
                expand=8)
            row = ft.Row([ft.Container(expand=2), bubble],
                        alignment=ft.MainAxisAlignment.END)
        elif is_think:
            bubble_text = ft.Text(f"💭 {text}", size=state["font_size"] - 1,
                                  color=LIGHT_GREY, italic=True, selectable=True)
            bubble = ft.Container(
                content=bubble_text, bgcolor=DARK, border=ft.Border.all(1, LIGHT_GREY),
                padding=ft.Padding(9, 7, 9, 7),
                border_radius=ft.BorderRadius(top_left=13, top_right=13,
                                              bottom_left=4, bottom_right=13),
                expand=8)
            row = ft.Row([bubble, ft.Container(expand=2)],
                        alignment=ft.MainAxisAlignment.START)
        else:
            bubble_text = ft.Markdown(
                _md_dark(text), selectable=True,
                extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK, expand=True,
                auto_follow_links=True,
                md_style_sheet=ft.MarkdownStyleSheet(
                    p_text_style=ft.TextStyle(size=state["font_size"])))
            bubble = ft.Container(
                content=bubble_text, bgcolor=GREY, padding=ft.Padding(9, 7, 9, 7),
                border_radius=ft.BorderRadius(top_left=13, top_right=13,
                                              bottom_left=4, bottom_right=13),
                expand=8)
            raw_text = text

            def _speak_current_bubble_text(text_control, fallback_text):
                current_text = getattr(text_control, "value", "")
                if not isinstance(current_text, str) or not current_text.strip():
                    current_text = fallback_text
                _speak_bubble(current_text, force_chunked=True)

            def _on_speak_click(e, text_control=bubble_text, fallback_text=raw_text):
                # Incrémenté ici (thread UI, synchrone au clic), pas dans
                # _speak_bubble : même raison que pour la lecture auto —
                # garantir que le compteur est déjà à jour avant que le
                # thread spawné n'ait eu la main.
                _busy_start()
                threading.Thread(target=_speak_current_bubble_text,
                                 args=(text_control, fallback_text),
                                 daemon=True).start()

            speak_btn = ft.IconButton(
                icon=ft.Icons.VOLUME_UP, icon_color=LIGHT_GREY, icon_size=14,
                tooltip="Lire cette réponse (lecture fidèle)",
                on_click=_on_speak_click,
            )
            row = ft.Row([bubble, speak_btn, ft.Container(expand=2)],
                        alignment=ft.MainAxisAlignment.START)
        ai_text_refs.append((bubble_text, -1 if is_think else 0))
        _ai_append_bubble_row(row)
        _ai_refresh()
        return bubble_text

    def _ai_stop(event=None):
        ai_streaming["value"] = False




    def _ai_get_credential(service, username, timeout=300):
        # Coffre natif de l'OS (Data/credentials.py, keyring) — jamais en
        # clair sur disque. Bloque le thread IA (appelé depuis _run(), pas
        # le thread principal) le temps que l'utilisateur saisisse le mot
        # de passe, comme Dashboard.pyw:1355-1421.
        existing = credentials.get_credential(service, username)
        if existing is not None:
            return existing

        cred_event = threading.Event()
        cred_result = {"value": None}
        password_field = ft.TextField(
            label=f"Mot de passe pour {username}@{service}",
            password=True, can_reveal_password=True, autofocus=True, width=360,
            bgcolor=DARK, border=CONSTANTS.input_border(GREY), color=WHITE)

        fired = {"done": False}

        def _confirm(e=None):
            if fired["done"]:
                return
            fired["done"] = True
            value = password_field.value or ""
            if value:
                credentials.set_credential(service, username, value)
                cred_result["value"] = value
            dlg.open = False
            page.update()
            cred_event.set()

        def _cancel(e=None):
            dlg.open = False
            page.update()
            cred_event.set()

        password_field.on_submit = _confirm
        dlg = _dialog(
            modal=True,
            title=ft.Text(f"🔐 Identifiant requis : {service}", size=CONSTANTS.TEXT_SM, color=WHITE),
            content=ft.Column([
                ft.Text(f"Aucun mot de passe enregistré pour {username}@{service}.",
                       size=CONSTANTS.TEXT_SM, color=WHITE),
                password_field,
            ], tight=True, width=360),
            actions=[_dlg_btn("Annuler", "cancel", on_click=_cancel),
                     _dlg_btn("Enregistrer", "primary",
                              on_click=_confirm)],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        async def _open_dlg():
            page.overlay.append(dlg)
            dlg.open = True
            page.update()
            try:
                await page.window.to_front()
            except Exception:
                pass
            await _focus_dialog_field(password_field)
        _run_task(_open_dlg)
        cred_event.wait(timeout=timeout)
        return cred_result["value"]





    # Copie de Dashboard.pyw:3665-3744 : confirmation avant toute commande
    # (si CONSTANTS.AI_TERMINAL_CONFIRM) et systématiquement si `admin`
    # (élévation sudo/UAC/Touch ID via _run_elevated dans ai_tools.py) —
    # sans quoi l'IA pouvait exécuter des commandes admin sans validation
    # utilisateur. Même pattern threading.Event() que _ai_tool_organize_files
    # juste au-dessus (dialogue ouvert sur le thread UI, attente bloquante
    # sur le thread worker qui exécute l'outil).

    # Copie de Dashboard.pyw:3881-3961 : CONSTANTS.AI_DELETE_CONFIRM (True
    # par défaut) doit toujours faire confirmer une suppression déclenchée
    # par l'IA - sans ça (lambda direct vers _folder_delete_files) l'IA
    # pouvait supprimer des fichiers sans validation utilisateur, même
    # défaut de configuration que run_terminal_command/admin plus haut.

    # Copie de Dashboard.pyw:3139-3202 : `analyze_images` est annoncé à l'IA
    # via le schéma partagé (Data/ai_tools.py:1289) mais n'avait aucun
    # handler côté Hub -> l'IA pouvait l'appeler et recevait juste
    # « Outil indisponible ». Même structure que _ai_tool_score_photos
    # juste en dessous (bulle de progression par lot).













    # Résumés emoji des outils du fallback (dispatch_folder_tool en émet déjà
    # via ui.bubble() pour ses branches "pures" — move_file, copy_file,
    # create_folder, edit_file, zip/unzip, git_command, ask_subagent, etc. —
    # mais PAS pour ceux ci-dessous, gérés localement par app comme dans
    # Dashboard.pyw (l.3007-3033) : sans ça, l'appel disparaît une fois le
    # texte de statut effacé, aucune trace dans l'historique du chat.



    def _ai_load_history():
        saved = _load_json(_ai_history_file, None)
        if saved is None:
            return
        messages = saved.get("messages", []) if isinstance(saved, dict) else saved
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if role not in ("user", "assistant") or not content:
                continue
            ai_conversation.append({"role": role, "content": content})
            _ai_add_bubble(role, content)

    def _ai_clear_conversation(event=None):
        ai_conversation.clear()
        ai_chat_view.controls.clear()
        ai_text_refs.clear()
        ai_status_text.value = ""
        # Renommé en .bak plutôt que supprimé : ce bouton est une corbeille
        # rouge posée à quelques pixels de « transférer vers le bloc-notes »,
        # et l'effacement était instantané et définitif. Le renommage rend
        # le geste rattrapable sans ajouter un dialogue de confirmation sur
        # une action par ailleurs fréquente et volontaire.
        try:
            if os.path.isfile(_ai_history_file):
                os.replace(_ai_history_file, _ai_history_file + ".bak")
                _log_to_terminal(
                    "[OK] Conversation effacée — récupérable dans "
                    f"{os.path.basename(_ai_history_file)}.bak", GREEN)
        except OSError as exc:
            _log_to_terminal(f"[ERREUR] Effacement conversation : {exc}", RED)
        page.update()

    def _export_ai_conversation(to_notepad=False, event=None):
        if not ai_conversation:
            ai_status_text.value = "Aucune conversation à exporter"
            page.update()
            return
        text = _format_ai_conversation(ai_conversation, CONSTANTS.AI_USER_NAME,
                                       CONSTANTS.AI_SEPARATOR_WIDTH)

        async def _copy():
            try:
                await ft.Clipboard().set(text)
                ai_status_text.value = "Conversation copiée dans le presse-papiers"
            except Exception:
                ai_status_text.value = "Erreur lors de la copie"
            page.update()
        _run_task(_copy)

        if to_notepad:
            current = notes_field.value or ""
            sep = ("\n\n" + "#" * CONSTANTS.AI_SEPARATOR_WIDTH + "\n\n"
                  if current.strip() else "")
            notes_field.value = current + sep + text
            _notes_save()
            if notes_is_preview["value"]:
                notes_preview.value = notes_field.value or ""
            _show_notes_panel()

    def _ai_refresh_attach_row():
        ai_attach_row.controls.clear()
        for entry in ai_pending_images:
            ai_attach_row.controls.append(ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.IMAGE_OUTLINED, size=CONSTANTS.ICON_SM, color=ORANGE),
                    ft.Text(os.path.basename(entry["path"]), size=CONSTANTS.TEXT_SM,
                           color=WHITE),
                    ft.IconButton(ft.Icons.CLOSE, icon_size=CONSTANTS.ICON_SM, icon_color=RED,
                                 on_click=lambda e, en=entry: _ai_remove_image(en)),
                ], spacing=4, tight=True),
                bgcolor=GREY, border_radius=6, padding=ft.Padding(6, 2, 2, 2)))
        for path in ai_pending_files:
            ai_attach_row.controls.append(ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, size=CONSTANTS.ICON_SM, color=YELLOW),
                    ft.Text(os.path.basename(path), size=CONSTANTS.TEXT_SM, color=WHITE),
                    ft.IconButton(ft.Icons.CLOSE, icon_size=CONSTANTS.ICON_SM, icon_color=RED,
                                 on_click=lambda e, p=path: _ai_remove_file(p)),
                ], spacing=4, tight=True),
                bgcolor=GREY, border_radius=6, padding=ft.Padding(6, 2, 2, 2)))
        ai_attach_row.visible = bool(ai_attach_row.controls)
        page.update()

    def _ai_attach_image(path, use_original=None):
        if any(e["path"] == path for e in ai_pending_images):
            return
        if use_original is None:
            use_original = ai_send_original_images["value"]
        try:
            if use_original:
                with open(path, "rb") as f:
                    b64_data = base64.b64encode(f.read()).decode("utf-8")
            else:
                with PILImage.open(path) as im:
                    im = im.convert("RGB")
                    max_side = 1024
                    w, h = im.size
                    if w > max_side or h > max_side:
                        ratio = min(max_side / w, max_side / h)
                        im = im.resize((int(w * ratio), int(h * ratio)), PILImage.LANCZOS)
                    buf = io.BytesIO()
                    im.save(buf, format="JPEG", quality=85)
                    b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception as exc:
            _ai_add_bubble("assistant", f"[Erreur] Impossible de lire l'image : {exc}")
            return
        ai_pending_images.append({"path": path, "b64": b64_data})
        _ai_refresh_attach_row()

    def _ai_remove_image(entry):
        if entry in ai_pending_images:
            ai_pending_images.remove(entry)
        _ai_refresh_attach_row()

    def _ai_attach_document_file(path):
        if path in ai_pending_files:
            return
        ai_pending_files.append(path)
        _ai_refresh_attach_row()

    def _ai_remove_file(path):
        if path in ai_pending_files:
            ai_pending_files.remove(path)
        _ai_refresh_attach_row()

    def _add_to_ai(paths):
        # Menu clic-droit Fichiers -> "Ajouter à l'IA" (cf. mémoire projet) :
        # images en pièce jointe visuelle, tout le reste en texte injecté.
        for p in paths:
            if os.path.splitext(p)[1].lower() in CONSTANTS.IMAGE_EXTS:
                _ai_attach_image(p)  # taille selon le bouton 1024/REEL
            else:
                _ai_attach_document_file(p)
        _select_surface("ia")

    # État micro (dictée logicielle, PAS le bouton PTT physique F15/pynput
    # de Dashboard — matériel spécifique, hors scope de cette passe).
    _mic_state = {"active": False, "rec": None}

    def _mic_toggle(event=None):
        if _mic_state["active"]:
            _mic_stop()
        else:
            _mic_start()

    def _mic_start():
        if _mic_state["active"]:
            return

        def _on_ready():
            async def _flip():
                if not _mic_state["active"]:
                    return
                ai_mic_button.icon = ft.Icons.STOP_CIRCLE
                ai_mic_button.icon_color = RED
                ai_mic_button.tooltip = "Enregistrement… cliquer pour arrêter"
                ai_status_text.value = "🎤 Parlez maintenant… (recliquer pour arrêter)"
                # Étape "enregistrement" : reste ouvert/en cours jusqu'à ce
                # que la transcription se termine (_busy_end appelé plus bas
                # dans _mic_stop/_apply, jamais ici — sinon la barre
                # clignoterait entre enregistrement et transcription).
                _busy_start()
                _log_to_terminal("🎤 Parlez maintenant… (recliquer pour arrêter)")
                page.update()
            _run_task(_flip)

        try:
            recorder = _MicRecorder(sample_rate=CONSTANTS.AI_VOICE_STT_SAMPLE_RATE)
            recorder.start(on_ready=_on_ready)
        except Exception as exc:
            ai_status_text.value = f"Micro indisponible : {exc}"
            _log_to_terminal(f"Micro indisponible : {exc}", RED)
            page.update()
            return
        _mic_state["rec"] = recorder
        _mic_state["active"] = True
        ai_mic_button.icon = ft.Icons.MIC
        ai_mic_button.icon_color = ORANGE
        ai_mic_button.tooltip = "Préparation du micro…"
        ai_status_text.value = "⏳ Préparation du micro… (attendez le rouge)"
        page.update()

    def _mic_stop(auto_send=False):
        """Arrête l'enregistrement et transcrit via Gemini.

        Copie de Dashboard.pyw:4299-4378 : ``auto_send`` (relâchement du
        bouton PTT physique) envoie le message dès la transcription, sans
        attendre une validation manuelle.
        """
        if not _mic_state["active"]:
            return
        _mic_state["active"] = False
        recorder = _mic_state["rec"]
        _mic_state["rec"] = None
        ai_mic_button.icon = ft.Icons.MIC_NONE
        ai_mic_button.icon_color = GREY
        ai_mic_button.tooltip = "Cliquer pour dicter (Gemini)"
        # Toujours l'étape "en cours" (enregistrement -> transcription,
        # même période _busy_start/_busy_end) : pas de _busy_end ici.
        ai_status_text.value = "Transcription en cours…"
        _log_to_terminal("Transcription en cours…")
        page.update()

        def _worker():
            text = None
            try:
                wav = recorder.stop() if recorder else None
                if wav:
                    text = _gemini_transcribe_audio(
                        wav, language_code=CONSTANTS.AI_VOICE_STT_LANGUAGE,
                        model=CONSTANTS.AI_VOICE_STT_MODEL)
            except Exception:
                text = None

            async def _apply():
                if text:
                    existing = (ai_input_field.value or "").rstrip()
                    combined = f"{existing} {text}".strip() if existing else text
                    ai_status_text.value = ""
                    _log_to_terminal(f"🎤 « {text} »", BLUE)
                    if auto_send and not ai_streaming["value"]:
                        # Bouton PTT physique (F15) : on a parlé pour poser
                        # la question, donc on veut la réponse parlée aussi
                        # — active la lecture auto si elle ne l'était pas
                        # déjà (retour user : désactivée par défaut, oubliée
                        # après un relance de l'app).
                        if not ai_tts_enabled["value"]:
                            ai_tts_enabled["value"] = True
                            ai_speaker_button.icon = ft.Icons.VOLUME_UP
                            ai_speaker_button.icon_color = BLUE
                            ai_speaker_button.tooltip = "Désactiver la lecture vocale"
                        ai_input_field.value = ""
                        # .update() sur un contrôle précis lève une erreur
                        # s'il n'est pas actuellement monté (onglet IA pas
                        # affiché — le rail change center.content, l'ancien
                        # onglet est détaché) : sans ce garde, l'exception
                        # avortait _apply() AVANT _send_ai_message, donc le
                        # PTT physique (F15) ne faisait plus rien en dehors
                        # de l'onglet IA (retour user).
                        try:
                            ai_input_field.update()
                        except Exception:
                            pass
                        # Fin de l'étape enregistrement/transcription — la
                        # suivante (attente de réponse) est démarrée par
                        # _send_ai_message elle-même juste après, donc le
                        # terminal reste ouvert en continu (retour user).
                        _busy_end()
                        _ai_generate(combined)
                    else:
                        ai_input_field.value = combined
                        try:
                            ai_input_field.update()
                        except Exception:
                            pass
                        try:
                            await ai_input_field.focus()
                        except Exception:
                            pass
                        _busy_end()
                else:
                    ai_status_text.value = "Aucun texte reconnu"
                    _log_to_terminal("Aucun texte reconnu", RED)
                    _busy_end()
                page.update()
            _run_task(_apply)

        threading.Thread(target=_worker, daemon=True).start()

    def _mic_hotkey_start():
        """Écoute CONSTANTS.AI_VOICE_PTT_KEY : bouton PTT physique (macropad).

        Copie de Dashboard.pyw:4380-4451. Touche f13-f20 (aucun clavier
        standard ne la produit). Appui maintenu = enregistre, relâchement =
        transcrit et envoie directement le message à l'IA, même si Hub n'a
        pas le focus (raccourci global, via pynput).
        """
        if not CONSTANTS.AI_VOICE_PTT_ENABLED:
            return
        ptt_name = CONSTANTS.AI_VOICE_PTT_KEY
        try:
            from pynput import keyboard as _pynput_kb
        except ImportError:
            _log_to_terminal(
                f"[IA] pynput absent : bouton micro physique ({ptt_name}) "
                "indisponible (pip install pynput).", ORANGE)
            return

        ptt_key = getattr(_pynput_kb.Key, ptt_name, None)
        if ptt_key is None:
            _log_to_terminal(
                f"[ERREUR] Touche PTT inconnue de pynput : {ptt_name!r} "
                "(voir CONSTANTS.AI_VOICE_PTT_KEY, doit être f13..f20).",
                RED)
            return

        # pynput ne livre pas toujours la même représentation à l'appui et
        # au relâchement (X11/Linux : Key.f15 à l'appui, KeyCode brut au
        # relâchement) — on compare aussi le vk pour reconnaître la même
        # touche physique dans les deux sens.
        target_vk = getattr(getattr(ptt_key, "value", ptt_key), "vk", None)

        def _is_ptt(key):
            if key == ptt_key:
                return True
            vk = getattr(getattr(key, "value", key), "vk", None)
            return target_vk is not None and vk == target_vk

        async def _press_async():
            _mic_start()

        async def _release_async():
            _mic_stop(auto_send=True)

        def _on_press(key):
            if _is_ptt(key):
                _run_task(_press_async)

        def _on_release(key):
            if _is_ptt(key):
                _run_task(_release_async)

        try:
            listener = _pynput_kb.Listener(
                on_press=_on_press, on_release=_on_release)
            listener.daemon = True
            listener.start()
        except Exception as hotkey_error:
            _log_to_terminal(
                f"[ERREUR] Bouton micro physique ({ptt_name}) : "
                f"{hotkey_error}", RED)
            return
        _mic_state["hotkey_listener"] = listener

    def _ai_submit(event=None):
        if _mic_state["active"]:
            # Envoyer pendant un enregistrement en cours (clic sur Envoyer
            # au lieu du bouton micro) : on n'envoie pas le texte actuel du
            # champ (vide ou périmé), on arrête l'enregistrement et on
            # enchaîne transcription + envoi auto, comme en mode PTT.
            _mic_stop(auto_send=True)
            return
        text = (ai_input_field.value or "").strip()
        if not text and not ai_pending_images and not ai_pending_files:
            return
        _history_add("ai", text)
        ai_input_field.value = ""
        page.update()
        if not text:
            return
        _ai_generate(text)  # galerie : plus de conversation (retour user)

    ai_input_field.on_submit = _ai_submit
    ai_send_button = ft.IconButton(ft.Icons.SEND, icon_color=BLUE,
                                   tooltip="Envoyer", on_click=_ai_submit)

    def _ai_vasy(event=None):
        if ai_streaming["value"]:
            return
        return  # ponytail: plus de conversation, bouton masqué

    ai_vasy_button = ft.IconButton(
        ft.Icons.PLAY_CIRCLE_FILL, icon_color=GREEN,
        tooltip="Vas-y (confirme et lance l'action en attente, sans taper de texte)",
        on_click=_ai_vasy)
    ai_stop_button = ft.IconButton(ft.Icons.STOP_CIRCLE, icon_color=RED,
                                   tooltip="Arrêter", visible=False, on_click=_ai_stop)
    # Ces trois-là changent d'état au début et à la fin d'une réponse
    # (désactivés pendant, bouton Arrêter visible) : sans eux dans la
    # liste, le rafraîchissement ciblé les laisserait figés.
    _ai_refresh_targets.extend(
        [ai_send_button, ai_vasy_button, ai_stop_button])
    ai_mic_button = ft.IconButton(
        ft.Icons.MIC_NONE, icon_color=GREY,
        tooltip="Cliquer pour dicter (Gemini)", on_click=_mic_toggle)
    ai_speaker_button = ft.IconButton(
        icon=ft.Icons.VOLUME_UP if ai_tts_enabled["value"] else ft.Icons.VOLUME_OFF,
        **SQUARE_BTN,
        icon_color=BLUE if ai_tts_enabled["value"] else LIGHT_GREY,
        icon_size=CONSTANTS.ICON_SM,
        tooltip=("Désactiver la lecture vocale" if ai_tts_enabled["value"]
                 else "Activer la lecture vocale"),
        visible=CONSTANTS.AI_VOICE_TTS_BTN_VISIBLE,
        on_click=_toggle_tts)
    ai_copy_button = ft.IconButton(
        ft.Icons.COPY_ALL, icon_color=BLUE, icon_size=CONSTANTS.ICON_SM,
        **SQUARE_BTN,
        tooltip="Copier la conversation IA",
        on_click=lambda e: _export_ai_conversation(to_notepad=False))
    ai_to_notepad_button = ft.IconButton(
        ft.Icons.SEND_TO_MOBILE, icon_color=VIOLET, icon_size=CONSTANTS.ICON_SM,
        **SQUARE_BTN,
        tooltip="Transférer la conversation vers le bloc-notes",
        on_click=lambda e: _export_ai_conversation(to_notepad=True))

    ai_image_mode_label = ft.Text(
        "REEL" if ai_send_original_images["value"] else "1024",
        color=GREEN if ai_send_original_images["value"] else BLUE,
        size=CONSTANTS.TEXT_SM - 3, weight=ft.FontWeight.BOLD)

    def _toggle_ai_image_size_mode(event=None):
        ai_send_original_images["value"] = not ai_send_original_images["value"]
        use_original = ai_send_original_images["value"]
        ai_image_size_button.icon_color = GREEN if use_original else BLUE
        ai_image_mode_label.value = "REEL" if use_original else "1024"
        ai_image_mode_label.color = GREEN if use_original else BLUE
        ai_image_size_button.tooltip = (
            "Images IA en taille réelle (fichier original)"
            if use_original else "Images IA optimisées (1024 px max)")
        # Images déjà jointes refaites à la nouvelle taille (retour user :
        # on peut basculer avant ou après avoir joint).
        paths = [e["path"] for e in ai_pending_images]
        ai_pending_images.clear()
        for p in paths:
            _ai_attach_image(p, use_original)
        page.update()

    ai_image_size_button = ft.IconButton(
        ft.Icons.IMAGE, **SQUARE_BTN,
        icon_color=GREEN if ai_send_original_images["value"] else BLUE,
        icon_size=CONSTANTS.ICON_SM,
        tooltip=(
            "Mode images IA en taille réelle (fichier original) — "
            "affecte uniquement les nouveaux fichiers joints"
            if ai_send_original_images["value"] else
            "Mode images IA optimisé (1024px max) — "
            "affecte uniquement les nouveaux fichiers joints"),
        on_click=_toggle_ai_image_size_mode)

    # Bouton + mode (« REEL »/« 1024 ») dans une seule pastille, à la
    # hauteur commune des boutons (retour user : l'icône seule n'était
    # pas claire).
    ai_image_size_group = ft.Container(
        content=ft.Row([ai_image_size_button, ai_image_mode_label],
                       spacing=0, tight=True),
        bgcolor=GREY, border_radius=CONSTANTS.BUTTON_RADIUS,
        height=CONSTANTS.HUB_TOOLBAR_H, padding=ft.Padding(0, 0, 10, 0))

    def _ai_header_separator():
        return ft.Container(ft.VerticalDivider(color=LIGHT_GREY),
                            height=CONSTANTS.HUB_TOOLBAR_H)

    return {
        "_ai_attach_image": _ai_attach_image,
        "_ai_header_separator": _ai_header_separator,
        "_ai_load_history": _ai_load_history,
        "ai_attach_row": ai_attach_row,
        "ai_copy_button": ai_copy_button,
        "ai_image_quality_dropdown": ai_image_quality_dropdown,
        "ai_image_size_group": ai_image_size_group,
        "ai_mic_button": ai_mic_button,
        "ai_model_dropdown": ai_model_dropdown,
        "ai_pending_images": ai_pending_images,
        "ai_progress_bar": ai_progress_bar,
        "ai_send_button": ai_send_button,
        "ai_speaker_button": ai_speaker_button,
        "ai_status_text": ai_status_text,
        "ai_stop_button": ai_stop_button,
        "ai_to_notepad_button": ai_to_notepad_button,
        "ai_vasy_button": ai_vasy_button,
        "_add_to_ai": _add_to_ai,
        "_ai_get_credential": _ai_get_credential,
        "_ai_navigate_async": _ai_navigate_async,
        "_ai_update_and_scroll": _ai_update_and_scroll,
        "_mic_hotkey_start": _mic_hotkey_start,
        "ai_chat_view": ai_chat_view,
        "ai_input_field": ai_input_field,
    }
