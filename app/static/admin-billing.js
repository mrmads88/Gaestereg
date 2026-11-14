/* Abonnement og fakturering i admin (kun leverandøren).
   NoddBilling.mountAccount(box, { scope: {tenant_id} | {partner_id}, api, toast, esc, onChange })
   NoddBilling.mountAdmin(box, { api, toast, esc }) – prisliste og fakturakørsel */
(function () {
  "use strict";
  const MOD = { rooms: "Mødelokaler", catering: "Forplejning", self_service: "Selvbetjening", reports: "Rapporter", signage: "Infoskærm" };
  const pad = (n) => String(n).padStart(2, "0");
  const isoToday = () => { const d = new Date(); return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); };
  const dk = (s) => s ? new Date(s + "T12:00").toLocaleDateString("da-DK", { day: "numeric", month: "short", year: "numeric" }) : "";
  const money = (o) => (o / 100).toLocaleString("da-DK", { minimumFractionDigits: o % 100 ? 2 : 0, maximumFractionDigits: 2 }) + " kr.";
  const STATE = { active: "Aktiv", ending: "Opsagt", future: "Starter", ended: "Stoppet" };
  const fresh = (outer) => { const el = document.createElement("div"); el.className = "stack"; outer.replaceChildren(el); return el; };

  // ---------- kunden ----------
  function mountAccount(box, o) {
    // Ny container ved hver mount, så klik-håndteringen ikke lægges på flere gange (ét klik = én handling).
    box = fresh(box);
    const { api, toast, esc } = o;
    const q = o.scope.tenant_id ? "tenant_id=" + o.scope.tenant_id : "partner_id=" + o.scope.partner_id;
    const isHouse = !!o.scope.partner_id;
    let acc = null, products = [];

    async function load() {
      try {
        [acc, products] = await Promise.all([api("GET", "/api/admin/billing/account?" + q), products.length ? products : api("GET", "/api/admin/billing/products")]);
      } catch (err) { box.innerHTML = '<p class="muted">' + esc(err.message) + "</p>"; return; }
      render();
    }
    const fits = (p) => p.audience === "all" || (p.audience === "house") === isHouse;
    const live = () => acc.subscriptions.filter((s) => s.state === "active" || s.state === "ending" || s.state === "future");
    const subOf = (code) => live().find((s) => s.product.code === code);
    const pkgMods = () => new Set(live().filter((s) => s.product.kind === "package" && s.state !== "future").flatMap((s) => s.product.modules));

    function render() {
      const pkgs = products.filter((p) => p.kind === "package" && p.active && fits(p));
      const addons = products.filter((p) => p.kind === "addon" && p.active && fits(p));
      const once = products.filter((p) => p.kind === "once" && p.active);
      const curPkg = live().find((s) => s.product.kind === "package" && s.state !== "future");
      const nextPkg = live().find((s) => s.product.kind === "package" && s.state === "future");
      const inPkg = pkgMods();
      const mods = acc.modules.map((m) => '<span class="chip on">' + esc(MOD[m] || m) + "</span>").join("") || '<span class="muted small">Kun gæsteregistrering</span>';

      box.innerHTML =
        '<div class="card bl-hero"><div><span class="lbl">Kunden betaler</span><div class="bl-big">' + esc(acc.monthly_text) + ' <small>pr. md. ekskl. moms</small></div>' +
        '<div class="chips">' + mods + "</div></div>" +
        '<div class="bl-next"><span class="lbl">Næste faktura · ' + esc(acc.next_invoice.period_text) + "</span><b>" + esc(acc.next_invoice.total_text) + '</b><small class="muted">inkl. moms</small></div></div>' +

        '<div class="card"><div class="row"><h3 class="grow">Pakke</h3><label class="fld bl-fromfld"><span>Ændringer gælder fra</span><input type="date" class="bl-from" value="' + (box.dataset.from || isoToday()) + '"></label></div>' +
        '<p class="muted small">Vælg pakke og tilkøb. Sker det midt i en periode, udregnes prisen forholdsmæssigt og kommer automatisk med på næste faktura.</p>' +
        '<div class="bl-pkgs">' + pkgs.map((p) => {
          const cur = curPkg && curPkg.product.code === p.code, nxt = nextPkg && nextPkg.product.code === p.code;
          return '<div class="bl-pkg' + (cur ? " cur" : "") + '" data-pkg="' + esc(p.code) + '"><div class="bl-pkg-h"><b>' + esc(p.name) + "</b>" + (cur ? '<span class="tag ss">Nuværende</span>' : nxt ? '<span class="tag">Fra ' + esc(dk(nextPkg.start)) + "</span>" : "") +
            '</div><div class="bl-price">' + esc(money(p.price)) + " <small>/ md.</small></div><p class=\"muted small\">" + esc(p.description) + "</p><ul>" +
            p.features.map((f) => "<li>" + esc(f) + "</li>").join("") + "</ul>" +
            (cur ? (curPkg.state === "ending" ? '<p class="small muted">Opsagt fra ' + esc(dk(curPkg.end)) + "</p>" : '<button class="btn ghost sm" type="button" data-endsub="' + curPkg.id + '">Opsig pakken</button>')
              : '<button class="btn pri sm" type="button" data-choose="' + esc(p.code) + '">' + (curPkg ? "Skift til " : "Vælg ") + esc(p.name) + "</button>") + "</div>";
        }).join("") + "</div></div>" +

        '<div class="card"><h3>Tilkøb</h3><div class="bl-list">' + addons.map((p) => {
          const s = subOf(p.code), included = p.modules.length && p.modules.every((m) => inPkg.has(m));
          return '<div class="bl-row" data-code="' + esc(p.code) + '"><div class="grow"><b>' + esc(p.name) + "</b> <span class=\"muted small\">" + esc(money(p.price)) + " / md." + "</span>" +
            (included ? '<span class="tag ss">Med i pakken</span>' : "") + '<div class="muted small">' + esc(p.description) + "</div>" +
            (s ? '<div class="small">' + esc((s.qty > 1 ? s.qty + " stk. · " : "") + (s.price_override != null ? "særpris " + s.unit_text + " · " : "") +
              (s.discount_pct ? s.discount_pct + " % rabat · " : "") + s.monthly_text + " / md. · " + STATE[s.state] + " " + dk(s.state === "future" ? s.start : s.state === "ending" ? s.end : s.start)) + "</div>" : "") +
            '</div><div class="acts">' + (s ? '<button class="btn ghost sm" type="button" data-edit="' + s.id + '">Ret</button>' +
              (s.state === "ending" ? "" : '<button class="btn ghost sm" type="button" data-endsub="' + s.id + '">Opsig</button>')
              : '<button class="btn ' + (included ? "ghost" : "pri") + ' sm" type="button" data-add="' + esc(p.code) + '">Tilføj</button>') + "</div></div>";
        }).join("") + "</div>" +
        '<form class="bl-edit card inset" hidden><h3 class="bl-edit-h"></h3><div class="g4">' +
        '<label class="fld"><span>Gælder fra</span><input type="date" name="start" required></label>' +
        '<label class="fld"><span>Antal</span><input type="number" name="qty" min="1" max="1000"></label>' +
        '<label class="fld"><span>Særpris kr./md.</span><input type="number" name="price" min="0" step="0.01" placeholder="Prislisten"></label>' +
        '<label class="fld"><span>Rabat %</span><input type="number" name="discount_pct" min="0" max="100"></label></div>' +
        '<p class="muted small">Ændringen gælder fra datoen. Er perioden allerede faktureret, reguleres forskellen på næste faktura.</p>' +
        '<div class="row"><span class="grow"></span><button class="btn ghost sm" type="button" data-close>Luk</button><button class="btn pri sm" type="submit">Gem</button></div></form></div>' +

        '<div class="card"><h3>Engangsposter og rabat</h3><p class="muted small">Kommer med på næste faktura. En rabat skrives som et negativt beløb, fx -500.</p>' +
        '<div class="row">' + once.map((p) => '<button class="btn ghost sm" type="button" data-once="' + esc(p.code) + '">+ ' + esc(p.name) + " (" + esc(money(p.price)) + ")</button>").join("") + "</div>" +
        '<form class="row bl-adj"><input name="description" placeholder="Tekst, fx Introduktionsrabat" maxlength="200" aria-label="Tekst">' +
        '<input name="amount" type="number" step="0.01" placeholder="Beløb kr." aria-label="Beløb i kr."><button class="btn pri sm" type="submit">Tilføj</button></form>' +
        '<div class="bl-list">' + acc.adjustments.map((a) => '<div class="bl-row"><span class="grow">' + esc(a.description) + (a.qty > 1 ? " × " + a.qty : "") +
          '</span><b class="n">' + esc(a.amount_text) + '</b><button class="btn ghost sm" type="button" data-deladj="' + a.id + '">Fjern</button></div>').join("") + "</div></div>" +

        '<div class="card"><h3>Kunde og betaling</h3><div class="g2">' +
        '<div class="fld"><span>Fakturering</span><div class="seg" id="blInt">' + [["month", "Månedlig"], ["quarter", "Kvartalsvis"], ["year", "Årlig · 2 mdr. gratis"]].map(([v, l]) =>
          '<button type="button" data-int="' + v + '" aria-pressed="' + (acc.interval === v) + '">' + l + "</button>").join("") + "</div></div>" +
        '<label class="fld"><span>Fast rabat på kunden (%)</span><input type="number" min="0" max="100" data-a="discount_pct" value="' + acc.discount_pct + '"></label></div>' +
        '<div class="g2"><label class="fld"><span>CVR</span><input data-a="cvr" maxlength="20" value="' + esc(acc.cvr) + '"></label>' +
        '<label class="fld"><span>Faktura-mail</span><input type="email" data-a="invoice_email" maxlength="200" value="' + esc(acc.invoice_email) + '"></label></div>' +
        '<div class="g2"><label class="fld"><span>Reference (att., EAN, ordrenr.)</span><input data-a="reference" maxlength="120" value="' + esc(acc.reference) + '"></label>' +
        '<label class="fld"><span>Note</span><input data-a="note" maxlength="500" value="' + esc(acc.note) + '"></label></div></div>' +

        '<div class="card"><div class="row"><h3 class="grow">Næste faktura · ' + esc(acc.next_invoice.period_text) + '</h3><button class="btn ghost sm" type="button" data-now>Lav faktura nu</button></div>' +
        invoiceTable(acc.next_invoice, esc) +
        (acc.invoices.length ? '<h3>Fakturaer</h3><div class="bl-list">' + acc.invoices.map((i) => '<div class="bl-row"><span class="grow">' + (i.number ? "Nr. " + i.number : "Kladde") + " · " + esc(i.period_text) +
          '</span><span class="pill ' + (i.status === "draft" ? "venter" : "sendt") + '">' + ({ draft: "Kladde", final: "Godkendt", paid: "Betalt" }[i.status]) + '</span><b class="n">' + esc(i.total_text) + "</b></div>").join("") + "</div>" : "") + "</div>";
    }

    async function act(fn, msg) {
      try { acc = await fn(); render(); if (msg) toast(msg); if (o.onChange) o.onChange(acc); } catch (err) { toast(err.message, true); }
    }
    let editing = null;
    const from = () => { const el = box.querySelector(".bl-from"); return (el && el.value) || isoToday(); };
    box.addEventListener("input", (e) => { if (e.target.classList.contains("bl-from")) box.dataset.from = e.target.value; });

    box.addEventListener("click", async (e) => {
      const t = e.target, b = (sel) => t.closest(sel);
      let x;
      if ((x = b("[data-choose]"))) {
        const p = products.find((y) => y.code === x.dataset.choose), start = from();
        return act(() => api("POST", "/api/admin/billing/account/subscriptions?" + q, { product: p.code, start }), p.name + " gælder fra " + dk(start) + " og kommer med på næste faktura.");
      }
      if ((x = b("[data-add]"))) {
        const p = products.find((y) => y.code === x.dataset.add), start = from();
        return act(() => api("POST", "/api/admin/billing/account/subscriptions?" + q, { product: p.code, start }), p.name + " er tilføjet fra " + dk(start) + ".");
      }
      if ((x = b("[data-endsub]"))) {
        const end = from(), label = x.textContent;
        if (!x.dataset.sure) { x.dataset.sure = "1"; x.textContent = "Tryk igen: opsig fra " + dk(end); setTimeout(() => { delete x.dataset.sure; x.textContent = label; }, 4000); return; }
        return act(() => api("POST", "/api/admin/billing/subscriptions/" + x.dataset.endsub + "/end", { end }), "Opsagt fra " + dk(end) + ". Betalt tid krediteres på næste faktura.");
      }
      if ((x = b("[data-edit]"))) {
        editing = acc.subscriptions.find((s) => s.id === +x.dataset.edit);
        const f = box.querySelector(".bl-edit"); f.hidden = false;
        box.querySelector(".bl-edit-h").textContent = "Ret " + editing.product.name;
        f.start.value = from(); f.qty.value = editing.qty; f.price.value = editing.price_override != null ? editing.price_override / 100 : ""; f.discount_pct.value = editing.discount_pct;
        f.scrollIntoView({ behavior: "smooth", block: "nearest" }); return;
      }
      if (b("[data-close]")) { box.querySelector(".bl-edit").hidden = true; return; }
      if ((x = b("[data-once]"))) return act(() => api("POST", "/api/admin/billing/account/adjustments?" + q, { product: x.dataset.once }), "Lagt på næste faktura");
      if ((x = b("[data-deladj]"))) return act(() => api("DELETE", "/api/admin/billing/adjustments/" + x.dataset.deladj), "Fjernet");
      if ((x = b("[data-int]"))) return act(() => api("PATCH", "/api/admin/billing/account?" + q, { interval: x.dataset.int }), "Gemt");
      if (b("[data-now]")) {
        try { const inv = await api("POST", "/api/admin/billing/account/invoice-now?" + q); toast("Kladde lavet: " + inv.total_text + ". Godkend den under Fakturering."); load(); }
        catch (err) { toast(err.message, true); }
      }
    });
    box.addEventListener("change", (e) => {
      const el = e.target.closest("[data-a]"); if (!el) return;  // datofeltet "gælder fra" gemmes ikke
      const v = el.type === "number" ? (parseInt(el.value, 10) || 0) : el.value;
      act(() => api("PATCH", "/api/admin/billing/account?" + q, { [el.dataset.a]: v }), "Gemt");
    });
    box.addEventListener("submit", (e) => {
      e.preventDefault();
      const f = e.target;
      if (f.classList.contains("bl-adj")) {
        const amount = parseFloat(String(f.amount.value).replace(",", "."));
        return act(() => api("POST", "/api/admin/billing/account/adjustments?" + q, { description: f.description.value.trim(), amount }), "Lagt på næste faktura");
      }
      if (f.classList.contains("bl-edit") && editing) {
        const body = { start: f.start.value, qty: +f.qty.value || 1, discount_pct: +f.discount_pct.value || 0 };
        if (f.price.value === "") body.clear_price = true; else body.price = parseFloat(String(f.price.value).replace(",", "."));
        f.hidden = true;
        return act(() => api("POST", "/api/admin/billing/subscriptions/" + editing.id + "/change", body), "Gemt fra " + dk(body.start));
      }
    });
    load();
    return { reload: load };
  }

  function invoiceTable(inv, esc) {
    if (!inv.lines.length) return '<p class="muted">Intet at fakturere.</p>';
    return '<div class="tablewrap"><table class="bl-inv"><tbody>' + inv.lines.map((l) => '<tr class="' + (l.amount < 0 ? "neg" : "") + '"><td>' + esc(l.description) +
      '</td><td class="n">' + esc(l.amount_text) + "</td></tr>").join("") +
      '<tr class="sum"><td>Subtotal ekskl. moms</td><td class="n">' + esc(inv.subtotal_text) + '</td></tr><tr><td>Moms 25 %</td><td class="n">' + esc(inv.vat_text) +
      '</td></tr><tr class="tot"><td>I alt</td><td class="n">' + esc(inv.total_text) + "</td></tr></tbody></table></div>";
  }

  // ---------- leverandørens fakturering ----------
  function mountAdmin(box, o) {
    // Ny container ved hver mount, så klik-håndteringen ikke lægges på flere gange (ét klik = én handling).
    box = fresh(box);
    const { api, toast, esc } = o;
    const d = new Date(); const nextMonth = new Date(d.getFullYear(), d.getMonth() + 1, 1);
    let month = nextMonth.getFullYear() + "-" + pad(nextMonth.getMonth() + 1), status = "draft", open = null;
    box.innerHTML =
      '<div class="ed-head"><div class="ed-title"><h1>Fakturering</h1><p class="muted">Prisliste, fakturakørsel og fakturagrundlag til bogføringen.</p></div></div>' +
      '<div class="card"><div class="row"><h3 class="grow">Fakturakørsel</h3><input type="month" class="rm-day bl-month" aria-label="Periode"><button class="btn pri sm" type="button" data-run>Lav kladder</button></div>' +
      '<p class="muted small">Laver fakturakladder for alle kunder, hvis periode starter i måneden (månedlige hver måned, kvartalsvise i jan/apr/jul/okt, årlige i januar). Kladder kan laves om, indtil de godkendes.</p>' +
      '<div class="row"><div class="seg" id="blStatus">' + [["draft", "Kladder"], ["final", "Godkendte"], ["paid", "Betalte"]].map(([v, l]) => '<button type="button" data-st="' + v + '" aria-pressed="' + (v === status) + '">' + l + "</button>").join("") +
      '</div><span class="grow"></span><a class="btn ghost sm bl-csv">Hent godkendte som CSV</a></div><div class="bl-invs"></div></div>' +
      '<div class="card"><h3>Prisliste</h3><p class="muted small">Priser i kr. ekskl. moms. Nye priser gælder fra næste faktura for alle uden særpris.</p><div class="tablewrap"><table><thead><tr><th>Produkt</th><th>Type</th><th>Pris</th><th>SMS/md.</th><th>Aktiv</th></tr></thead><tbody class="bl-prods"></tbody></table></div></div>';
    box.querySelector(".bl-month").value = month;
    box.querySelector(".bl-csv").href = "/api/admin/billing/invoices.csv";
    const KIND = { package: "Pakke", addon: "Tilkøb", usage: "Forbrug", once: "Engangs" };

    async function loadProducts() {
      const ps = await api("GET", "/api/admin/billing/products");
      box.querySelector(".bl-prods").innerHTML = ps.map((p) => '<tr data-pid="' + p.id + '"><td><b>' + esc(p.name) + '</b><div class="small muted">' + esc(p.description) + "</div>" +
        (p.kind === "package" ? '<textarea class="bl-feat" rows="3" aria-label="Punkter på pakkekortet">' + esc(p.features.join("\n")) + "</textarea>" : "") + "</td><td>" + KIND[p.kind] + (p.audience === "house" ? " · hus" : "") +
        '</td><td><input type="number" class="bl-price-in" min="0" step="0.01" value="' + p.price / 100 + '" aria-label="Pris"> <span class="small muted">/ ' + esc(p.unit) + "</span></td><td>" +
        (p.kind === "package" ? '<input type="number" class="bl-sms-in" min="0" value="' + p.included_sms + '" aria-label="SMS pr. måned">' : "") +
        '</td><td><label class="switch"><input type="checkbox" class="bl-act-in"' + (p.active ? " checked" : "") + "><i></i></label></td></tr>").join("");
    }
    async function loadInvoices() {
      const list = await api("GET", "/api/admin/billing/invoices?status=" + status);
      const total = list.reduce((s, i) => s + i.total, 0);
      box.querySelector(".bl-invs").innerHTML = list.length ? '<div class="tablewrap"><table><thead><tr><th>Nr.</th><th>Kunde</th><th>Periode</th><th>Ekskl. moms</th><th>I alt</th><th></th></tr></thead><tbody>' +
        list.map((i) => '<tr data-iid="' + i.id + '"><td class="n">' + (i.number || "–") + "</td><td>" + esc(i.customer) + (i.customer_kind === "hus" ? ' <span class="tag house">Hus</span>' : "") + "</td><td>" + esc(i.period_text) +
          '</td><td class="n">' + esc(i.subtotal_text) + '</td><td class="n"><b>' + esc(i.total_text) + '</b></td><td><div class="acts"><button class="btn ghost sm" type="button" data-show>Vis</button>' +
          (i.status === "draft" ? '<button class="btn pri sm" type="button" data-fin>Godkend</button><button class="btn ghost sm" type="button" data-del>Slet</button>' : i.status === "final" ? '<button class="btn ghost sm" type="button" data-paid>Betalt</button>' : "") +
          "</div></td></tr>" + (open === i.id ? '<tr class="bl-open"><td colspan="6" class="bl-detail"></td></tr>' : "")).join("") +
        '</tbody></table></div><p class="small muted">' + list.length + " fakturaer · " + money(total) + " inkl. moms</p>" : '<p class="muted">Ingen.</p>';
      if (open) { try { const inv = await api("GET", "/api/admin/billing/invoices/" + open); const td = box.querySelector(".bl-detail"); if (td) td.innerHTML = invoiceTable(inv, esc); } catch (e) { /* væk */ } }
    }

    box.addEventListener("click", async (e) => {
      const t = e.target, row = t.closest("[data-iid]"); let b;
      try {
        if (t.closest("[data-run]")) { const r = await api("POST", "/api/admin/billing/run", { period_start: month + "-01" }); toast(r.count + " kladder lavet"); status = "draft"; setSeg(); return loadInvoices(); }
        if ((b = t.closest("[data-st]"))) { status = b.dataset.st; setSeg(); return loadInvoices(); }
        if (row && t.closest("[data-show]")) { open = open === +row.dataset.iid ? null : +row.dataset.iid; return loadInvoices(); }
        if (row && t.closest("[data-fin]")) { const r = await api("POST", "/api/admin/billing/invoices/" + row.dataset.iid + "/finalize"); toast("Godkendt som nr. " + r.number); return loadInvoices(); }
        if (row && t.closest("[data-paid]")) { await api("POST", "/api/admin/billing/invoices/" + row.dataset.iid + "/paid"); toast("Markeret som betalt"); return loadInvoices(); }
        if (row && (b = t.closest("[data-del]"))) {
          if (!b.dataset.sure) { b.dataset.sure = "1"; b.textContent = "Tryk igen"; setTimeout(() => { delete b.dataset.sure; b.textContent = "Slet"; }, 3000); return; }
          await api("DELETE", "/api/admin/billing/invoices/" + row.dataset.iid); toast("Kladden er slettet"); return loadInvoices();
        }
      } catch (err) { toast(err.message, true); }
    });
    box.addEventListener("change", async (e) => {
      const t = e.target, row = t.closest("[data-pid]");
      if (t.classList.contains("bl-month")) { month = t.value; return; }
      if (!row) return;
      const body = t.classList.contains("bl-price-in") ? { price: parseFloat(String(t.value).replace(",", ".")) || 0 }
        : t.classList.contains("bl-sms-in") ? { included_sms: parseInt(t.value, 10) || 0 }
        : t.classList.contains("bl-act-in") ? { active: t.checked }
        : t.classList.contains("bl-feat") ? { features: t.value.split("\n") } : null;
      if (!body) return;
      try { await api("PATCH", "/api/admin/billing/products/" + row.dataset.pid, body); toast("Prislisten er gemt"); } catch (err) { toast(err.message, true); loadProducts(); }
    });
    const setSeg = () => box.querySelectorAll("#blStatus [data-st]").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.st === status)));
    loadProducts().catch((err) => toast(err.message, true));
    loadInvoices().catch((err) => toast(err.message, true));
  }

  window.NoddBilling = { mountAccount, mountAdmin };
})();
