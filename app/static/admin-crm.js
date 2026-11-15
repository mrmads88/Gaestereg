/* Leverandørens CRM i admin (kun platform).
   NoddCrm.mount(box, { api, toast, esc, openNodd(kind, id) }) */
(function () {
  "use strict";
  // "Emne" betyder også en mails emne, så CRM-status har sin egen engelske tekst (ordbogen oversætter "Emne" til "Subject").
  const EN = window.NODD_I18N && window.NODD_I18N.lang === "en";
  const STATUS = EN ? { emne: "Lead", kunde: "Customer", tidligere: "Former customer" } : { emne: "Emne", kunde: "Kunde", tidligere: "Tidligere kunde" };
  const SEGMENT = { firma: "Firma", kontorhotel: "Kontorhotel", andet: "Andet" };
  const KIND = { note: "Note", opkald: "Opkald", moede: "Møde", mail: "Mail", opgave: "Opgave", system: "Ændring", nodd: "Nodd" };
  const pad = (n) => String(n).padStart(2, "0");
  const isoToday = () => { const d = new Date(); return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); };
  const money = (o) => Math.round((o || 0) / 100).toLocaleString(NODD_LOC()) + " kr.";
  const day = (s) => s ? new Date(s.length === 10 ? s + "T12:00" : s).toLocaleDateString(NODD_LOC(), { day: "numeric", month: "short", year: "numeric" }) : "";
  const when = (s) => s ? new Date(s).toLocaleString(NODD_LOC(), { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
  // "1.250", "1250,50" og "649" → øre
  const toOre = (v) => { const s = String(v || "").replace(/\s|kr\.?/gi, "").replace(/\.(?=\d{3}(\D|$))/g, "").replace(",", "."); const n = parseFloat(s); return isFinite(n) && n > 0 ? Math.round(n * 100) : 0; };
  const kr = (o) => o ? String(Math.round(o / 100)) : "";
  const fresh = (outer) => { const el = document.createElement("div"); el.className = "stack crm"; outer.replaceChildren(el); return el; };

  function mount(outer, o) {
    const box = fresh(outer);
    const { api, toast, esc } = o;
    let view = "overview", companyId = null, q = "", status = "", newOpen = false, noddOpts = null;
    let C = null; // åbent firma

    const statusPill = (s) => '<span class="pill crm-st ' + esc(s) + '">' + esc(STATUS[s] || s) + "</span>";
    const empty = (t) => '<p class="muted small">' + esc(t) + "</p>";
    const taskRow = (a, withCompany) => '<li class="crm-task' + (a.done ? " done" : "") + (a.overdue ? " late" : "") + '" data-aid="' + a.id + '">' +
      '<input type="checkbox" data-act="task-done"' + (a.done ? " checked" : "") + ' aria-label="Klaret">' +
      '<span class="grow"><b>' + esc(a.text) + "</b>" + (withCompany && a.company ? '<button class="linkbtn" type="button" data-act="open" data-cid="' + a.company_id + '">' + esc(a.company) + "</button>" : "") + "</span>" +
      '<span class="crm-due">' + (a.overdue ? "Forfalden · " : "") + esc(a.due_date === isoToday() ? "I dag" : day(a.due_date)) + "</span>" +
      (withCompany ? "" : '<button class="btn ghost sm" type="button" data-act="del-activity" aria-label="Slet">×</button>') + "</li>";

    function head() {
      const tab = (k, t) => '<button type="button" data-act="view" data-view="' + k + '" aria-pressed="' + (view === k || (k === "companies" && view === "company")) + '">' + t + "</button>";
      return '<div class="row crm-head"><h1 class="crm-h1">CRM</h1><div class="seg">' + tab("overview", "Overblik") + tab("pipeline", "Pipeline") + tab("companies", "Firmaer") +
        '</div><span class="grow"></span><button class="btn pri sm" type="button" data-act="new">+ Nyt firma</button></div>' +
        (newOpen ? '<form class="card crm-new" data-form="new"><div class="crm-grid3"><label class="fld"><span>Firmaets navn</span><input name="name" required maxlength="160" placeholder="Fx Havnens Advokater"></label>' +
          '<label class="fld"><span>Type</span><select name="segment">' + Object.entries(SEGMENT).map(([k, v]) => '<option value="' + k + '">' + v + "</option>").join("") + "</select></label>" +
          '<label class="fld"><span>Status</span><select name="status">' + Object.entries(STATUS).map(([k, v]) => '<option value="' + k + '">' + v + "</option>").join("") + '</select></label></div>' +
          '<div class="row"><button class="btn pri sm" type="submit">Opret</button><button class="btn ghost sm" type="button" data-act="new">Annullér</button></div></form>' : "");
    }

    async function render() {
      let body = "";
      try {
        if (view === "overview") body = await overview();
        else if (view === "pipeline") body = await pipeline();
        else if (view === "companies") body = await companies();
        else body = await company();
      } catch (err) { body = '<p class="muted">' + esc(err.message) + "</p>"; }
      box.innerHTML = head() + body;
      const f = box.querySelector("[data-form=new] input[name=name]"); if (f) f.focus();
      if (view === "companies") { const s = box.querySelector("[data-act=search]"); if (s && document.activeElement !== s && q) { s.focus(); s.setSelectionRange(q.length, q.length); } }
    }

    // ---------- overblik ----------
    async function overview() {
      const ov = await api("GET", "/api/admin/crm/overview");
      const tile = (l, v, s) => '<div class="crm-tile"><span>' + esc(l) + "</span><b>" + esc(v) + "</b><small>" + esc(s) + "</small></div>";
      return (ov.unlinked ? '<div class="card crm-sync row"><span class="grow"><b>' + ov.unlinked + (ov.unlinked === 1 ? " firma eller hus" : " firmaer og huse") +
        "</b> i Nodd er ikke i CRM endnu.</span><button class=\"btn pri sm\" type=\"button\" data-act=\"sync\">Hent dem</button></div>" : "") +
        '<div class="crm-tiles">' + tile("Omsætning pr. md.", money(ov.mrr), "fra aktive pakker, ekskl. moms") +
        tile("Åben pipeline", money(ov.open_monthly) + "/md.", "vægtet " + money(ov.weighted) + "/md.") +
        tile("Vundet i denne måned", String(ov.won_month.count), money(ov.won_month.monthly) + "/md.") +
        tile("Kunder", String(ov.counts.kunde), ov.counts.emne + " emner · " + ov.counts.tidligere + " tidligere") + "</div>" +
        '<div class="crm-cols"><div class="card"><h3>I dag</h3>' + (ov.due.length ? '<ul class="crm-tasks">' + ov.due.map((a) => taskRow(a, true)).join("") + "</ul>" : empty("Ingen opfølgninger i dag.")) +
        (ov.later.length ? '<h3 class="crm-sub">Kommende</h3><ul class="crm-tasks">' + ov.later.map((a) => taskRow(a, true)).join("") + "</ul>" : "") + "</div>" +
        '<div class="card"><h3>Seneste aktivitet</h3>' + (ov.recent.length ? '<ul class="crm-tl">' + ov.recent.map((a) => tlRow(a, true)).join("") + "</ul>" : empty("Intet endnu. Opret et firma og skriv en note.")) + "</div></div>";
    }

    // ---------- pipeline ----------
    async function pipeline() {
      const r = await api("GET", "/api/admin/crm/deals");
      return '<p class="muted small">Træk et kort til en ny fase. Vundne og tabte vises i 60 dage. Vægtet = beløb × sandsynlighed.</p><div class="crm-board">' + r.stages.map((s) => {
        const ds = r.deals.filter((d) => d.stage === s.key);
        const sum = ds.reduce((a, d) => a + d.monthly, 0);
        return '<section class="crm-col ' + s.key + '" data-stage="' + s.key + '"><header><b>' + esc(s.label) + "</b><span>" + ds.length + "</span><small>" + money(sum) + "/md." +
          (s.chance && s.chance < 100 ? " · " + s.chance + " %" : "") + "</small></header>" +
          ds.map((d) => '<article class="crm-card" draggable="true" data-did="' + d.id + '" data-act="open" data-cid="' + d.company_id + '" tabindex="0"><b>' + esc(d.title) + "</b><span>" + esc(d.company || "") + "</span>" +
            '<small>' + (d.monthly ? money(d.monthly) + "/md." : "") + (d.once ? (d.monthly ? " + " : "") + money(d.once) + " opstart" : "") + "</small>" +
            (d.expected_close && d.open ? '<small class="muted">Forventet ' + esc(day(d.expected_close)) + "</small>" : "") + "</article>").join("") + "</section>";
      }).join("") + "</div>";
    }

    // ---------- firmaer ----------
    async function companies() {
      const rows = await api("GET", "/api/admin/crm/companies?q=" + encodeURIComponent(q) + "&status=" + status);
      const chip = (k, t) => '<button type="button" data-act="status" data-status="' + k + '" aria-pressed="' + (status === k) + '">' + t + "</button>";
      return '<div class="row crm-filter"><input class="crm-search" type="search" data-act="search" placeholder="Søg i firma, CVR eller kontakt" value="' + esc(q) + '" aria-label="Søg">' +
        '<div class="seg">' + chip("", "Alle") + chip("emne", "Emner") + chip("kunde", "Kunder") + chip("tidligere", "Tidligere") + "</div>" +
        '<a class="btn ghost sm" href="/api/admin/crm/companies.csv?q=' + encodeURIComponent(q) + "&status=" + status + '">Hent CSV</a></div>' +
        (rows.length ? '<div class="tablewrap card crm-tablecard"><table class="crm-table"><thead><tr><th>Firma</th><th>Status</th><th>Kontakt</th><th class="n">Pipeline</th><th class="n">Omsætning</th><th>Næste opgave</th></tr></thead><tbody>' +
          rows.map((r) => '<tr data-act="open" data-cid="' + r.id + '" tabindex="0"><td><b>' + esc(r.name) + "</b><small>" + esc(r.segment_text) + (r.linked ? " · i Nodd" : "") + "</small></td><td>" + statusPill(r.status) + "</td>" +
            "<td>" + (r.contact ? esc(r.contact.name) + "<small>" + esc(r.contact.email || r.contact.phone || r.contact.title) + "</small>" : '<span class="muted">–</span>') + "</td>" +
            '<td class="n">' + (r.open_deals ? money(r.pipeline) + "/md.<small>" + r.open_deals + (r.open_deals === 1 ? " mulighed" : " muligheder") + "</small>" : '<span class="muted">–</span>') + "</td>" +
            '<td class="n">' + (r.mrr ? money(r.mrr) + "/md." : '<span class="muted">–</span>') + "</td>" +
            "<td>" + (r.next_task ? '<span class="' + (r.next_task.overdue ? "crm-late" : "") + '">' + esc(r.next_task.text) + "</span><small>" + esc(day(r.next_task.due_date)) + "</small>" : '<span class="muted">–</span>') + "</td></tr>").join("") +
          "</tbody></table></div>" : '<div class="card">' + empty(q || status ? "Ingen firmaer passer på søgningen." : "Ingen firmaer endnu. Opret det første, eller hent kunderne fra Nodd under Overblik.") + "</div>");
    }

    // ---------- ét firma ----------
    const tlRow = (a, withCompany) => '<li class="crm-tl-' + esc(a.kind) + '" data-aid="' + (a.id || "") + '"><span class="crm-kind">' + esc(KIND[a.kind] || a.kind) + "</span>" +
      '<span class="grow"><span class="crm-text">' + esc(a.text) + "</span>" + (withCompany && a.company ? '<button class="linkbtn" type="button" data-act="open" data-cid="' + a.company_id + '">' + esc(a.company) + "</button>" : "") + "</span>" +
      '<time>' + esc(when(a.at)) + "</time>" + (!withCompany && a.id && a.kind !== "system" && a.kind !== "nodd" ? '<button class="btn ghost sm" type="button" data-act="del-activity" aria-label="Slet">×</button>' : "") + "</li>";

    async function company() {
      C = await api("GET", "/api/admin/crm/companies/" + companyId);
      if (!noddOpts) noddOpts = await api("GET", "/api/admin/crm/nodd-options").catch(() => []);
      const L = C.linked;
      const cur = C.tenant_id ? "tenant:" + C.tenant_id : C.partner_id ? "partner:" + C.partner_id : "";
      const opt = (obj, val) => Object.entries(obj).map(([k, v]) => '<option value="' + k + '"' + (k === val ? " selected" : "") + ">" + esc(v) + "</option>").join("");
      const field = (n, l, v, extra) => '<label class="fld"><span>' + l + '</span><input name="' + n + '" value="' + esc(v || "") + '"' + (extra || "") + "></label>";
      const kpi = L ? '<div class="crm-tiles small">' +
        '<div class="crm-tile"><span>Omsætning pr. md.</span><b>' + money(L.mrr) + "</b><small>ekskl. moms</small></div>" +
        '<div class="crm-tile"><span>Gæster denne måned</span><b>' + L.visits_month + "</b><small>" + L.visits_prev + " sidste måned</small></div>" +
        '<div class="crm-tile"><span>Seneste login</span><b>' + esc(L.last_login ? day(L.last_login) : "Aldrig") + "</b><small>" + (L.kind === "partner" ? L.firms + " firmaer i huset" : "kundens admins") + "</small></div>" +
        '<div class="crm-tile"><span>Databehandleraftale</span><b>' + (L.dpa ? "Accepteret" : "Mangler") + "</b><small>" + esc(L.name) + "</small></div></div>" : "";
      return '<div class="row crm-chead"><button class="btn ghost sm" type="button" data-act="view" data-view="companies">← Firmaer</button><h2 class="grow">' + esc(C.name) + "</h2>" + statusPill(C.status) +
        (L ? '<button class="btn ghost sm" type="button" data-act="nodd">Åbn i Nodd</button>' : "") + '<button class="btn ghost sm" type="button" data-act="del-company">Slet</button></div>' + kpi +
        '<div class="crm-cols">' +
        // venstre
        '<div class="stack"><form class="card" data-form="company"><h3>Stamdata</h3><div class="crm-grid2">' + field("name", "Navn", C.name, ' required maxlength="160"') +
        '<label class="fld"><span>Status</span><select name="status">' + opt(STATUS, C.status) + "</select></label>" +
        '<label class="fld"><span>Type</span><select name="segment">' + opt(SEGMENT, C.segment) + "</select></label>" + field("cvr", "CVR", C.cvr, ' maxlength="20" inputmode="numeric"') +
        field("phone", "Telefon", C.phone, ' maxlength="40" type="tel"') + field("email", "E-mail", C.email, ' maxlength="200" type="email"') +
        field("website", "Hjemmeside", C.website, ' maxlength="200"') + field("source", "Kilde", C.source, ' maxlength="80" placeholder="Fx anbefaling, messe"') + "</div>" +
        field("address", "Adresse", C.address, ' maxlength="300"') +
        '<label class="fld"><span>Kunde i Nodd</span><select name="link"><option value="">Ikke koblet</option>' + noddOpts.map((x) => '<option value="' + esc(x.value) + '"' + (x.value === cur ? " selected" : "") + ">" + esc(x.label) + "</option>").join("") + '</select><small class="hint">Så vises omsætning, besøg og fakturaer her.</small></label>' +
        '<label class="fld"><span>Noter</span><textarea name="notes" rows="4" maxlength="20000">' + esc(C.notes) + '</textarea></label><div class="row"><button class="btn pri sm" type="submit">Gem</button></div></form>' +
        '<div class="card"><h3>Kontakter</h3>' + (C.contacts.length ? '<ul class="crm-contacts">' + C.contacts.map((x) => '<li data-xid="' + x.id + '"><span class="grow"><b>' + esc(x.name) + (x.is_primary ? ' <span class="pill crm-st kunde">Primær</span>' : "") + "</b><small>" +
          [x.title, x.email ? '<a href="mailto:' + esc(x.email) + '">' + esc(x.email) + "</a>" : "", x.phone ? '<a href="tel:' + esc(x.phone) + '">' + esc(x.phone) + "</a>" : ""].filter(Boolean).map((v, i) => i === 0 && x.title ? esc(v) : v).join(" · ") + "</small></span>" +
          (x.is_primary ? "" : '<button class="btn ghost sm" type="button" data-act="primary">Gør primær</button>') + '<button class="btn ghost sm" type="button" data-act="del-contact" aria-label="Slet">×</button></li>').join("") + "</ul>" : empty("Ingen kontakter endnu.")) +
        '<form class="crm-inline" data-form="contact"><input name="name" placeholder="Navn" required maxlength="120" aria-label="Navn"><input name="title" placeholder="Titel" maxlength="120" aria-label="Titel">' +
        '<input name="email" type="email" placeholder="E-mail" maxlength="200" aria-label="E-mail"><input name="phone" type="tel" placeholder="Telefon" maxlength="40" aria-label="Telefon"><button class="btn ghost sm" type="submit">Tilføj</button></form></div></div>' +
        // højre
        '<div class="stack"><div class="card"><h3>Salgsmuligheder</h3>' + (C.deals.length ? '<ul class="crm-deals">' + C.deals.map((d) => '<li data-did="' + d.id + '"><span class="grow"><b>' + esc(d.title) + "</b><small>" +
          (d.monthly ? money(d.monthly) + "/md." : "") + (d.once ? (d.monthly ? " + " : "") + money(d.once) + " opstart" : "") + (d.expected_close && d.open ? " · forventet " + esc(day(d.expected_close)) : "") + (d.closed_at ? " · lukket " + esc(day(d.closed_at)) : "") + "</small></span>" +
          '<select data-act="stage" aria-label="Fase">' + ["ny", "kontakt", "demo", "tilbud", "vundet", "tabt"].map((k) => '<option value="' + k + '"' + (k === d.stage ? " selected" : "") + ">" + { ny: "Ny", kontakt: "I dialog", demo: "Demo", tilbud: "Tilbud sendt", vundet: "Vundet", tabt: "Tabt" }[k] + "</option>").join("") + "</select>" +
          '<button class="btn ghost sm" type="button" data-act="del-deal" aria-label="Slet">×</button></li>').join("") + "</ul>" : empty("Ingen salgsmuligheder endnu.")) +
        '<form class="crm-inline" data-form="deal"><input name="title" placeholder="Fx Plus-pakke + 2 lokaleskærme" required maxlength="160" aria-label="Titel" class="wide">' +
        '<input name="monthly" inputmode="decimal" placeholder="Kr. pr. md." aria-label="Kroner pr. måned"><input name="once" inputmode="decimal" placeholder="Opstart, kr." aria-label="Opstart i kroner">' +
        '<input name="expected_close" type="date" aria-label="Forventet lukket"><button class="btn ghost sm" type="submit">Tilføj</button></form></div>' +
        '<div class="card"><h3>Opgaver</h3>' + (C.tasks.length ? '<ul class="crm-tasks">' + C.tasks.map((a) => taskRow(a, false)).join("") + "</ul>" : empty("Ingen opgaver. Tilføj en opfølgning med en dato.")) +
        '<form class="crm-inline" data-form="task"><input name="text" placeholder="Fx ring om tilbuddet" required maxlength="5000" aria-label="Opgave" class="wide"><input name="due_date" type="date" value="' + isoToday() + '" aria-label="Dato"><button class="btn ghost sm" type="submit">Tilføj</button></form></div>' +
        '<div class="card"><h3>Tidslinje</h3><form class="crm-compose" data-form="note"><div class="seg">' + ["note", "opkald", "moede", "mail"].map((k, i) => '<button type="button" data-act="kind" data-kind="' + k + '" aria-pressed="' + (i === 0) + '">' + KIND[k] + "</button>").join("") + "</div>" +
        '<textarea name="text" rows="2" placeholder="Hvad skete der?" maxlength="5000" aria-label="Tekst" required></textarea><div class="row"><button class="btn pri sm" type="submit">Tilføj</button></div></form>' +
        (C.timeline.length ? '<ul class="crm-tl">' + C.timeline.map((a) => tlRow(a, false)).join("") + "</ul>" : "") + "</div></div></div>";
    }

    const open = (cid) => { view = "company"; companyId = +cid; newOpen = false; render(); window.scrollTo(0, 0); };

    // ---------- klik ----------
    box.addEventListener("click", async (e) => {
      const t = e.target.closest("[data-act]"); if (!t) return;
      const act = t.dataset.act;
      if (act === "view") { view = t.dataset.view; C = null; render(); }
      else if (act === "new") { newOpen = !newOpen; render(); }
      else if (act === "status") { status = t.dataset.status; render(); }
      else if (act === "open" && t.dataset.cid) { if (e.target.closest("input,select,a")) return; open(t.dataset.cid); }
      else if (act === "sync") { try { toast((await api("POST", "/api/admin/crm/sync")).message); render(); } catch (err) { toast(err.message, true); } }
      else if (act === "nodd" && C && C.linked) o.openNodd(C.linked.kind, C.linked.id);
      else if (act === "kind") { t.parentElement.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === t))); }
      else if (act === "task-done") {
        const id = t.closest("[data-aid]").dataset.aid;
        try { await api("PATCH", "/api/admin/crm/activities/" + id, { done: t.checked }); render(); } catch (err) { toast(err.message, true); }
      } else if (act === "del-activity") {
        if (!sure(t)) return;
        try { await api("DELETE", "/api/admin/crm/activities/" + t.closest("[data-aid]").dataset.aid); render(); } catch (err) { toast(err.message, true); }
      } else if (act === "del-contact") {
        if (!sure(t)) return;
        try { await api("DELETE", "/api/admin/crm/contacts/" + t.closest("[data-xid]").dataset.xid); render(); } catch (err) { toast(err.message, true); }
      } else if (act === "primary") {
        try { await api("PATCH", "/api/admin/crm/contacts/" + t.closest("[data-xid]").dataset.xid, { is_primary: true }); render(); } catch (err) { toast(err.message, true); }
      } else if (act === "del-deal") {
        if (!sure(t)) return;
        try { await api("DELETE", "/api/admin/crm/deals/" + t.closest("[data-did]").dataset.did); render(); } catch (err) { toast(err.message, true); }
      } else if (act === "del-company") {
        if (!sure(t, "Slet firmaet")) return;
        try { await api("DELETE", "/api/admin/crm/companies/" + C.id); toast(C.name + " er slettet fra CRM"); view = "companies"; C = null; render(); } catch (err) { toast(err.message, true); }
      }
    });
    function sure(b, label) {
      if (b.dataset.sure) return true;
      const old = b.textContent; b.dataset.sure = "1"; b.textContent = label ? "Tryk igen for at slette" : "Slet?";
      setTimeout(() => { delete b.dataset.sure; b.textContent = old; }, 3500);
      return false;
    }
    box.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.matches("[data-act=open][data-cid]")) open(e.target.dataset.cid); });
    box.addEventListener("change", async (e) => {
      if (e.target.matches("[data-act=stage]")) {
        try { await api("PATCH", "/api/admin/crm/deals/" + e.target.closest("[data-did]").dataset.did, { stage: e.target.value }); render(); } catch (err) { toast(err.message, true); }
      }
    });
    let searchT;
    box.addEventListener("input", (e) => {
      if (!e.target.matches("[data-act=search]")) return;
      clearTimeout(searchT); searchT = setTimeout(() => { q = e.target.value.trim(); render(); }, 250);
    });

    // ---------- formularer ----------
    box.addEventListener("submit", async (e) => {
      const f = e.target.closest("form[data-form]"); if (!f) return;
      e.preventDefault();
      const v = Object.fromEntries(new FormData(f).entries());
      try {
        if (f.dataset.form === "new") {
          const c = await api("POST", "/api/admin/crm/companies", v); toast(c.name + " er oprettet"); open(c.id); return;
        }
        if (f.dataset.form === "company") { await api("PATCH", "/api/admin/crm/companies/" + C.id, v); toast("Gemt"); }
        else if (f.dataset.form === "contact") await api("POST", "/api/admin/crm/companies/" + C.id + "/contacts", v);
        else if (f.dataset.form === "deal") {
          await api("POST", "/api/admin/crm/companies/" + C.id + "/deals", { title: v.title, monthly: toOre(v.monthly), once: toOre(v.once), expected_close: v.expected_close || null });
        } else if (f.dataset.form === "task") {
          await api("POST", "/api/admin/crm/companies/" + C.id + "/activities", { kind: "opgave", text: v.text, due_date: v.due_date || null });
        } else if (f.dataset.form === "note") {
          const k = f.querySelector("[data-kind][aria-pressed=true]");
          await api("POST", "/api/admin/crm/companies/" + C.id + "/activities", { kind: k ? k.dataset.kind : "note", text: v.text });
        }
        render();
      } catch (err) { toast(err.message, true); }
    });

    // ---------- træk og slip i pipelinen ----------
    box.addEventListener("dragstart", (e) => { const c = e.target.closest("[data-did]"); if (c) { e.dataTransfer.setData("text/plain", c.dataset.did); c.classList.add("dragging"); } });
    box.addEventListener("dragend", (e) => { const c = e.target.closest("[data-did]"); if (c) c.classList.remove("dragging"); box.querySelectorAll(".crm-col.over").forEach((x) => x.classList.remove("over")); });
    box.addEventListener("dragover", (e) => { const col = e.target.closest(".crm-col"); if (col) { e.preventDefault(); box.querySelectorAll(".crm-col.over").forEach((x) => x !== col && x.classList.remove("over")); col.classList.add("over"); } });
    box.addEventListener("drop", async (e) => {
      const col = e.target.closest(".crm-col"); if (!col) return;
      e.preventDefault();
      const id = e.dataTransfer.getData("text/plain"); if (!id) return;
      try { const d = await api("PATCH", "/api/admin/crm/deals/" + id, { stage: col.dataset.stage }); toast(d.title + ": " + d.stage_text); render(); } catch (err) { toast(err.message, true); }
    });

    if (o.company) open(o.company); else render();
  }

  window.NoddCrm = { mount };
})();
