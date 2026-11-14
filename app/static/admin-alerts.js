/* Nødbesked i admin: en rød knap i toppen af firmaet og huset, som åbner et vindue til at starte eller afslutte.
   NoddAlerts.mount(slot, { scope: {tenant_id} | {partner_id}, api, toast, esc, name }) */
(function () {
  "use strict";
  const KINDS = [
    ["evacuation", "Evakuering", "Rød besked på hele skærmen. Check-in stopper."],
    ["warning", "Vigtig besked", "Orange besked på hele skærmen, fx strømsvigt eller vandskade."],
    ["info", "Information", "Et bånd øverst. Skærmen kan stadig bruges."],
  ];
  const fmt = (s) => s ? new Date(s).toLocaleString("da-DK", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
  let modal = null;

  function ensureModal() {
    if (modal) return modal;
    modal = document.createElement("div");
    modal.className = "al-veil"; modal.hidden = true;
    modal.innerHTML = '<div class="al-box" role="dialog" aria-modal="true" aria-labelledby="alTitle"></div>';
    document.body.appendChild(modal);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && modal && !modal.hidden) modal.hidden = true; });
    return modal;
  }

  function mount(slot, o) {
    const { api, toast, esc } = o;
    const q = o.scope.tenant_id ? "tenant_id=" + o.scope.tenant_id : "partner_id=" + o.scope.partner_id;
    const who = o.scope.tenant_id ? "firmaets" : "husets og alle firmaernes";
    let data = null, kind = "evacuation";
    slot.innerHTML = '<button type="button" class="btn sm al-btn">Nødbesked</button>';
    const btn = slot.querySelector("button");

    async function load() {
      try { data = await api("GET", "/api/admin/alerts?" + q + "&kind=" + kind); } catch (err) { return; }
      const a = data.active[0];
      btn.classList.toggle("on", !!a);
      btn.textContent = a ? "Nødbesked vises nu" : "Nødbesked";
      if (modal && !modal.hidden && modal.dataset.owner === q) render();
    }

    function render() {
      const box = modal.querySelector(".al-box"), a = data.active[0], t = data.templates[kind];
      box.innerHTML = '<div class="al-h"><h2 id="alTitle">Nødbesked · ' + esc(o.name()) + '</h2><button type="button" class="btn ghost sm" data-close aria-label="Luk">×</button></div>' +
        (a ? '<div class="al-active ' + esc(a.kind) + '"><b>' + esc(a.title) + "</b><span>" + esc(a.message) + "</span><small>Vises siden " + esc(fmt(a.started_at)) +
          (a.ends_at ? " · slutter " + esc(fmt(a.ends_at)) : "") + " · startet af " + esc(a.created_by) +
          (a.notify ? " · " + (a.notified_count ? "sendt til " + a.notified_count + " (SMS, mail og Teams)" : "sendes til personerne nu") + (a.notified_count ? ". De får besked, når den afsluttes" : "") : "") + '</small><button type="button" class="btn al-end" data-end="' + a.id + '">Afslut nødbeskeden</button></div>' : "") +
        '<p class="muted small">Vises på ' + who + " skærme: gæsteskærme, lokaleskærme og infoskærme (" + data.screens + " i alt). Skærmene viser den inden for 15 sekunder.</p>" +
        '<div class="al-kinds">' + KINDS.map(([k, l, d]) => '<button type="button" class="al-kind ' + k + '" data-kind="' + k + '" aria-pressed="' + (k === kind) + '"><b>' + l + "</b><small>" + d + "</small></button>").join("") + "</div>" +
        '<label class="fld"><span>Overskrift</span><input class="al-title" maxlength="120" value="' + esc(t.title) + '"></label>' +
        '<label class="fld"><span>Besked</span><textarea class="al-msg" rows="3" maxlength="600">' + esc(t.message) + "</textarea></label>" +
        '<label class="fld"><span>Slutter</span><select class="al-min"><option value="">Når den afsluttes</option><option value="15">Om 15 minutter</option><option value="30">Om 30 minutter</option><option value="60">Om 1 time</option><option value="120">Om 2 timer</option><option value="480">Om 8 timer</option></select></label>' +
        notifyHtml() +
        '<button type="button" class="btn al-go ' + kind + '" data-go>' + (a ? "Erstat med ny besked" : "Vis på alle skærme") + "</button>" +
        (data.history.length ? '<details class="al-hist"><summary>Tidligere beskeder</summary>' + data.history.map((h) => "<div><b>" + esc(h.title) + "</b> " + esc(fmt(h.started_at)) +
          (h.ended_at ? " til " + esc(fmt(h.ended_at)) + (h.ended_by ? " (" + esc(h.ended_by) + ")" : "") : h.active ? " · vises nu" : " · udløbet") + "</div>").join("") + "</details>" : "");
    }

    function notifyHtml() {
      const n = data.notify;
      if (kind === "info") return "";
      if (!n.enabled) {
        return '<div class="al-notify off"><span>SMS og mail til personerne ved nødbesked er slået fra' + (n.own_setting ? "" : "") + ".</span>" +
          (n.can_change ? '<label class="switch"><input type="checkbox" data-setting><i></i><em>Slå til for ' + esc(o.name()) + "</em></label>" : "<small>Huset eller jeres leverandør kan slå det til.</small>") + "</div>";
      }
      const parts = [n.sms + " SMS", n.email + " mails"].concat(n.teams ? [n.teams + " Teams-kanaler"] : []);
      return '<label class="al-notify"><input type="checkbox" class="al-send" checked><span><b>Send også til alle personer</b><small>' + esc(parts.join(", ")) +
        (n.sms ? ". SMS koster ca. " + esc(n.cost_text) + ", hvis det er ud over pakkens SMS." : ".") + " De får også besked, når den afsluttes.</small></span></label>" +
        (n.can_change && n.own_setting ? '<label class="switch al-off"><input type="checkbox" data-setting checked><i></i><em>SMS og mail ved nødbesked er slået til for ' + esc(o.name()) + "</em></label>" : "");
    }

    btn.addEventListener("click", async () => {
      ensureModal(); modal.dataset.owner = q;
      modal.onclick = onModalClick;  // én håndtering ad gangen (vinduet deles af alle firmaer)
      await load(); render(); modal.hidden = false;
      const first = modal.querySelector(".al-end, .al-go"); if (first) first.focus();
    });
    async function onModalClick(e) {
      const t = e.target;
      if (t === modal || t.closest("[data-close]")) { modal.hidden = true; return; }
      const k = t.closest("[data-kind]");
      if (k) { kind = k.dataset.kind; await load(); render(); return; }
      const st = t.closest("[data-setting]");
      if (st) {
        try { await api("PATCH", "/api/admin/alerts/settings?" + q, { alert_notify: st.checked }); toast(st.checked ? "SMS og mail ved nødbesked er slået til" : "SMS og mail ved nødbesked er slået fra"); await load(); render(); }
        catch (err) { toast(err.message, true); st.checked = !st.checked; }
        return;
      }
      const end = t.closest("[data-end]");
      if (end) {
        try { await api("POST", "/api/admin/alerts/" + end.dataset.end + "/end"); toast("Nødbeskeden er afsluttet. Skærmene vender tilbage inden for 15 sekunder."); await load(); render(); }
        catch (err) { toast(err.message, true); }
        return;
      }
      if (t.closest("[data-go]")) {
        const box = modal.querySelector(".al-box");
        const body = Object.assign({ kind, title: box.querySelector(".al-title").value.trim(), message: box.querySelector(".al-msg").value.trim(),
          minutes: box.querySelector(".al-min").value ? +box.querySelector(".al-min").value : null,
          notify: !!(box.querySelector(".al-send") && box.querySelector(".al-send").checked) }, o.scope);
        const extra = body.notify ? " og sende " + data.notify.sms + " SMS og " + data.notify.email + " mails" : "";
        if (kind !== "info" && !confirm("Vis \"" + (body.title || "nødbesked") + "\" på hele skærmen på alle " + data.screens + " skærme" + extra + " nu?")) return;
        try {
          const r = await api("POST", "/api/admin/alerts", body); toast("Vises nu på " + r.screens + " skærme" + (r.notify ? ". Beskeder sendes til personerne." : ""));
          await load(); render();
          if (r.notify) setTimeout(async () => { await load(); if (!modal.hidden) render(); }, 2500);  // vis hvor mange der fik besked
        }
        catch (err) { toast(err.message, true); }
      }
    }
    load();
    return { reload: load };
  }

  window.NoddAlerts = { mount };
})();
