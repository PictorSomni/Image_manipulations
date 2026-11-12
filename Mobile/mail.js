// Fenêtre mail unique de la webapp : réponse, nouveau mail, « commande
// prête » depuis une tâche. Toute modification ici vaut partout.
// opts : to, phone, subject, text, textTu (modèle tutoyé), reply (mail
// auquel on répond), onSent(), extra (boutons en plus).
function mailSheet(opts = {}) {
  const m = opts.reply;
  const o = {tu: false, tone: "professionnel et chaleureux"};
  const choice = (key, opts2, after) => {
    const draw = () => seg(opts2, o[key], v => {
      o[key] = v; el.replaceWith(el = draw()); if (after) after(v); }, true);
    let el = draw();
    return el;
  };
  const to = h("input", {type: "email", placeholder: "À",
    value: m ? m.from : (opts.to || "")});
  if (m) to.readOnly = true;
  // Suggestions d'adresses déjà écrites ou reçues (cache du Pi).
  const sugg = h("div", {class: "row", style: {flexWrap: "wrap", gap: "6px"}});
  if (!m) {
    to.autocomplete = "off";
    to.oninput = async () => {
      const q = to.value.trim().toLowerCase();
      sugg.replaceChildren();
      if (q.length < 2) return;
      try { mailSheet.contacts ??= await api("/api/mail",
        {action: "contacts"}); } catch (e) { return; }
      mailSheet.contacts.filter(c => (c.a + " " + c.n).toLowerCase()
        .includes(q)).slice(0, 6).forEach(c => sugg.append(
          h("button", {class: "chipbtn", style: {background: "var(--blue)",
            fontSize: "13px", padding: "6px 10px"},
            onclick: () => { to.value = c.a; sugg.replaceChildren(); }},
            c.n ? `${c.n} · ${c.a}` : c.a)));
    };
  }
  const subj = h("input", {placeholder: "Objet", value: opts.subject || ""});
  const t = h("textarea", {rows: 11},
    opts.text ?? (m ? m.draft || "" : "Bonjour,\n\n"));
  let touched = false;
  t.oninput = () => { touched = true; };
  const hint = h("textarea", {rows: 2, placeholder: "Consignes"});
  const gen = h("button", {class: "btn out", onclick: async () => {
    gen.disabled = true; t.value = "Rédaction…";
    try {
      t.value = (await api("/api/mail", m
        ? {action: "draft", id: m.message_id, tu: o.tu, tone: o.tone,
           hint: hint.value.trim()}
        : {action: "compose", to: to.value, subject: subj.value, tu: o.tu,
           tone: o.tone, hint: hint.value.trim()})).ok;
      touched = true;
    } catch (e) { t.value = "Erreur : " + e.message; }
    gen.disabled = false;
  }}, ic("edit_note"), " Rédiger");
  const names = h("div", {class: "muted"});
  const pick = h("input", {type: "file", multiple: true,
    style: {display: "none"}, onchange: () => names.textContent =
      [...pick.files].map(f => f.name).join(", ")});
  const join = h("button", {class: "btn out", onclick: () => pick.click()},
    ic("attach_file"), " Joindre");
  const send = h("button", {class: "btn", onclick: async () => {
    if (!t.value.trim()) return;
    send.disabled = true; send.textContent = "Envoi…";
    try {
      const files = await Promise.all([...pick.files].map(f =>
        new Promise(ok => { const r = new FileReader();
          r.onload = () => ok({name: f.name,
            data: r.result.split(",")[1]});
          r.readAsDataURL(f); })));
      await api("/api/mail", m
        ? {action: "reply", id: m.message_id, text: t.value, files}
        : {action: "new", to: to.value, subject: subj.value,
           text: t.value, files});
      closeSheet(); S.status = "Mail envoyé";
      if (opts.onSent) opts.onSent();
      render();
    } catch (e) { send.disabled = false; send.textContent = "Erreur : " +
      e.message; }
  }}, ic("send"), " Envoyer");
  const sms = opts.phone ? h("button", {class: "btn out", onclick: () => {
    location.href = `sms:${tel(opts.phone)}&body=` +
      encodeURIComponent(t.value); closeSheet();
    if (opts.onSent) opts.onSent(); }}, ic("sms"), " SMS") : null;
  const card = (color, ...kids) => h("div", {class: "card", style: {
    borderLeft: `4px solid var(${color})`, margin: "10px 0"}}, ...kids);
  const form = [
    ...(opts.info || []),
    h("div", {class: "label"}, "Adresse"),
    choice("tu", [[false, "Vous"], [true, "Tu"]], v => {
      if (opts.textTu && !touched) t.value = v ? opts.textTu : opts.text;
    }),
    h("div", {class: "label"}, "Ton"),
    choice("tone", [["professionnel et chaleureux", "Chaleureux"],
      ["professionnel et sobre", "Sobre"], ["très bref", "Bref"]]),
    hint, h("div", {class: "row"}, gen), t, names,
    h("div", {class: "row"}, join, send, sms, ...(opts.extra || []))];
  const title = (txt, color) => h("div", {class: "label", style: {
    marginTop: 0, color: `var(${color})`, fontWeight: 700,
    fontSize: "14px"}}, txt);
  openSheet([
    h("b", {}, m ? (m.subject || "(sans sujet)") : "Mail"),
    ...(m ? [card("--grey", title("Message reçu", "--grey"),
               h("div", {class: "muted"}, m.from),
               (m.points || []).length ? md(m.points.map(x => "- **" + x +
                 "**").join("\n")) : null,
               md(m.body || ""),
               m.files_id ? mailFiles(m.files_id) : null),
             card("--blue", title("Réponse", "--blue"), ...form)]
          : [to, sugg, subj, ...form]),
    pick], true);
}
