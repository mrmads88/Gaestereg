/* Forplejning i admin (fase 5b): køkkener, menu og bestillinger/faktureringsgrundlag.
   NoddCatering.mount(box, { scope: {tenant_id} | {partner_id}, api, toast, esc }) */
(function () {
  "use strict";
  const UNITS = ["pr. person", "stk.", "portion", "kande", "flaske", "fad", "kurv"];
  const TAGS = ["Vegetar", "Vegansk", "Glutenfri", "Laktosefri", "Økologisk", "Indeholder nødder"];
  const STATUS = { new: "Ny", confirmed: "Bekræftet", delivered: "Leveret", cancelled: "Annulleret" };
  const ICON = (c, n) => { const s = (n || "") + " " + (c || "");  // ikon ud fra varens navn, ellers kategorien
    return /vand|juice|sodavand|saft/i.test(s) ? "🥤" : /salat/i.test(s) ? "🥗" : /frugt/i.test(s) ? "🍎" : /kage|cookie|sød|snack/i.test(s) ? "🍰"
      : /kaffe|\bte\b/i.test(s) ? "☕" : /brød|morgen|croissant/i.test(s) ? "🥐" : /sandwich|frokost|mad/i.test(s) ? "🥪" : /drik/i.test(s) ? "🥤" : "🍽️"; };
  const pad = (n) => String(n).padStart(2, "0");

  const fresh = (outer) => { const el = document.createElement("div"); el.className = "stack"; outer.replaceChildren(el); return el; };
  function mount(box, o) {
    // Ny container ved hver mount, så klik-håndteringen ikke lægges på flere gange (ét klik = én handling).
    box = fresh(box);
    const { api, toast, esc } = o;
    const q = o.scope.tenant_id ? "tenant_id=" + o.scope.tenant_id : "partner_id=" + o.scope.partner_id;
    const isHouse = !!o.scope.partner_id;
    let kitchens = [], editK = null, editI = null, itemKitchen = null;
    const now = new Date();
    let month = now.getFullYear() + "-" + pad(now.getMonth() + 1);

    box.innerHTML =
      '<div class="card"><div class="row"><h3 class="grow">Forplejning</h3><button class="btn pri sm" type="button" data-newk>+ Nyt køkken</button></div>' +
      '<p class="muted small">' + (isHouse ? "Husets køkken eller en ekstern leverandør. Alle firmaer i huset kan bestille forplejning, når de booker et lokale."
        : "Firmaets eget køkken eller en leverandør. Husets køkkener vises også her, men rettes af huset.") +
      " Køkkenet får besked på mail eller SMS og har sin egen side med dagens bestillinger. Mødernes titler vises aldrig for køkkenet.</p>" +
      '<form class="ct-k card inset" hidden autocomplete="off"><h3 class="ct-k-h"></h3>' +
      '<div class="g2"><label class="fld"><span>Navn</span><input name="name" required maxlength="120" placeholder="Fx Husets køkken"></label>' +
      '<label class="fld"><span>Type</span><select name="kind"><option value="internal">Eget køkken</option><option value="external">Ekstern leverandør</option></select></label></div>' +
      '<div class="g2"><label class="fld"><span>E-mail til bestillinger</span><input name="email" type="email" maxlength="200"></label>' +
      '<label class="fld"><span>Mobil til SMS</span><input name="phone" type="tel" maxlength="40"></label></div>' +
      '<div class="g2"><label class="fld"><span>Bestil senest (timer før)</span><input name="lead_hours" type="number" min="0" max="168"></label>' +
      '<label class="fld"><span>Besked til dem, der bestiller</span><input name="note" maxlength="300" placeholder="Fx Frokost bestilles senest kl. 12 dagen før"></label></div>' +
      '<div class="row ct-edit"><label class="switch"><input type="checkbox" name="active"><i></i><em>Kan bestilles fra</em></label></div>' +
      '<div class="row"><button class="btn bad sm ct-edit" type="button" data-delk>Slet køkken</button><button class="btn ghost sm ct-edit" type="button" data-newlink>Lav nyt link til køkkenet</button>' +
      '<span class="grow"></span><button class="btn ghost sm" type="button" data-closek>Luk</button><button class="btn pri sm" type="submit">Gem</button></div></form>' +
      '<form class="ct-i card inset" hidden autocomplete="off"><h3 class="ct-i-h"></h3>' +
      '<div class="g2"><label class="fld"><span>Navn</span><input name="name" required maxlength="120" placeholder="Fx Sandwich"></label>' +
      '<label class="fld"><span>Kategori</span><input name="category" maxlength="40" list="ct-cats" placeholder="Fx Frokost"></label></div>' +
      '<datalist id="ct-cats"><option value="Morgenmad"><option value="Frokost"><option value="Drikkevarer"><option value="Snacks"></datalist>' +
      '<div class="g2"><label class="fld"><span>Pris i kr.</span><input name="price" type="number" min="0" step="0.01" inputmode="decimal" required></label>' +
      '<label class="fld"><span>Enhed</span><select name="unit">' + UNITS.map((u) => "<option>" + u + "</option>").join("") + "</select></label></div>" +
      '<label class="fld"><span>Beskrivelse</span><input name="description" maxlength="300" placeholder="Fx Grovbrød med kylling, pesto og salat"></label>' +
      '<div class="fld"><span>Mærker</span><div class="row">' + TAGS.map((t) => '<label class="check"><input type="checkbox" name="tag" value="' + t + '"> ' + t + "</label>").join("") + "</div></div>" +
      '<div class="row"><span class="ct-photo ct-iedit"></span><label class="btn ghost sm file ct-iedit">Upload billede<input type="file" accept="image/*" name="photo"></label>' +
      '<label class="switch"><input type="checkbox" name="active"><i></i><em>På menuen</em></label></div>' +
      '<div class="row"><button class="btn bad sm ct-iedit" type="button" data-deli>Slet vare</button><span class="grow"></span><button class="btn ghost sm" type="button" data-closei>Luk</button><button class="btn pri sm" type="submit">Gem</button></div></form>' +
      '<div class="ct-list"></div></div>' +

      '<div class="card"><div class="row"><h3 class="grow">Bestillinger og fakturering</h3><input type="month" class="ct-month rm-day" aria-label="Måned">' +
      '<a class="btn ghost sm ct-csv">Hent som Excel (CSV)</a></div>' +
      '<p class="muted small">Alle bestillinger i måneden med firma, omkostningssted og beløb. Kan bruges som faktureringsgrundlag.</p>' +
      '<div class="ct-sum"></div><div class="tablewrap"><table><thead><tr><th>Levering</th><th>Firma</th><th>Lokale</th><th>Varer</th><th>Beløb</th><th>Status</th></tr></thead><tbody class="ct-rows"></tbody></table></div></div>';

    const $$ = (s) => box.querySelector(s);
    const kForm = $$(".ct-k"), iForm = $$(".ct-i");
    $$(".ct-month").value = month;

    async function load() {
      try { kitchens = await api("GET", "/api/admin/kitchens?" + q); } catch (err) { toast(err.message, true); return; }
      render(); loadOrders();
    }

    function render() {
      $$(".ct-list").innerHTML = kitchens.map((k) => '<div class="ct-kit" data-kid="' + k.id + '"><div class="row"><div class="grow"><b class="ct-name">' + esc(k.name) + "</b>" +
        '<span class="tag">' + (k.kind === "external" ? "Ekstern" : "Eget køkken") + "</span>" + (!k.own && !isHouse ? '<span class="tag house">Husets</span>' : "") +
        (k.active === false ? '<span class="tag">Slået fra</span>' : "") + '<div class="muted small">' +
        esc([k.items.length + (k.items.length === 1 ? " vare" : " varer"), "bestil " + k.lead_hours + " t før", k.email, k.phone].filter(Boolean).join(" · ")) + "</div></div>" +
        (k.can_manage ? '<button class="btn ghost sm" type="button" data-editk>Ret</button><a class="btn ghost sm" target="_blank" rel="noopener" href="' + esc(k.kitchen_url) +
          '">Køkkenets side</a><button class="btn ghost sm" type="button" data-copyk>Kopiér link</button>' : "") + "</div>" +
        '<div class="ct-menu">' + k.items.map((i) => '<button type="button" class="ct-item' + (i.active ? "" : " off") + '" data-iid="' + i.id + '"' + (k.can_manage ? "" : " disabled") + ">" +
          '<span class="ct-pic">' + (i.photo_url ? '<img src="' + esc(i.photo_url) + '" alt="">' : ICON(i.category, i.name)) + '</span><span class="ct-t"><b>' + esc(i.name) + "</b><small>" +
          esc(i.price_text + " " + i.unit + (i.category ? " · " + i.category : "")) + "</small></span></button>").join("") +
        (k.can_manage ? '<button type="button" class="ct-item ct-add" data-newi>+ Tilføj vare</button>' : "") + "</div>" +
        (k.can_manage && !k.items.length ? '<div class="row"><span class="muted small grow">Kom hurtigt i gang med en eksempelmenu, som I retter til.</span><button class="btn ghost sm" type="button" data-sample>Opret eksempelmenu</button></div>' : "") +
        "</div>").join("") || '<p class="muted">Ingen køkkener endnu. Opret husets køkken eller en ekstern leverandør, så kan man bestille forplejning med mødelokalet.</p>';
    }

    async function loadOrders() {
      $$(".ct-csv").href = "/api/admin/catering-orders?" + q + "&month=" + month + "&format=csv";
      let r;
      try { r = await api("GET", "/api/admin/catering-orders?" + q + "&month=" + month); } catch (err) { toast(err.message, true); return; }
      $$(".ct-sum").innerHTML = r.count ? '<div class="ct-kpi"><span><b>' + r.count + "</b> " + (r.count === 1 ? "bestilling" : "bestillinger") + "</span><span><b>" + esc(r.total_text) + "</b> i alt</span></div>" : "";
      const fmt = (s) => new Date(s).toLocaleString("da-DK", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
      $$(".ct-rows").innerHTML = r.orders.map((x) => '<tr class="' + (x.status === "cancelled" ? "muted" : "") + '"><td class="n">' + esc(fmt(x.deliver_at)) + "</td><td>" + esc(x.firm) +
        (x.cost_center ? '<div class="small muted">' + esc(x.cost_center) + "</div>" : "") + "</td><td>" + esc(x.room) + '<div class="small muted">' + esc(x.kitchen) + "</div></td><td>" +
        esc(x.lines.map((l) => l.qty + " × " + l.name).join(", ")) + '</td><td class="n">' + esc(x.total_text) + '</td><td><span class="pill ' + (x.status === "cancelled" ? "fejl" : x.status === "new" ? "venter" : "sendt") + '">' +
        esc(STATUS[x.status] || x.status) + "</span></td></tr>").join("") || '<tr><td colspan="6" class="muted">Ingen bestillinger i måneden.</td></tr>';
    }

    function openK(k) {
      editK = k || null; kForm.hidden = false; iForm.hidden = true;
      $$(".ct-k-h").textContent = k ? "Ret " + k.name : "Nyt køkken";
      box.querySelectorAll(".ct-edit").forEach((x) => (x.hidden = !k));
      kForm.name.value = k ? k.name : ""; kForm.kind.value = k ? k.kind : "internal";
      kForm.email.value = k ? k.email : ""; kForm.phone.value = k ? k.phone : ""; kForm.lead_hours.value = k ? k.lead_hours : 3;
      kForm.note.value = k ? k.note : ""; kForm.active.checked = k ? k.active : true;
      kForm.scrollIntoView({ behavior: "smooth", block: "nearest" }); kForm.name.focus();
    }

    function openI(k, i) {
      itemKitchen = k; editI = i || null; iForm.hidden = false; kForm.hidden = true;
      $$(".ct-i-h").textContent = (i ? "Ret " + i.name : "Ny vare") + " · " + k.name;
      box.querySelectorAll(".ct-iedit").forEach((x) => (x.hidden = !i));
      iForm.name.value = i ? i.name : ""; iForm.category.value = i ? i.category : "";
      iForm.price.value = i ? (i.price / 100).toFixed(2) : ""; iForm.unit.value = i ? i.unit : "pr. person";
      iForm.description.value = i ? i.description : ""; iForm.active.checked = i ? i.active : true;
      iForm.querySelectorAll('[name="tag"]').forEach((c) => (c.checked = !!i && i.tags.includes(c.value)));
      $$(".ct-photo").innerHTML = i && i.photo_url ? '<img src="' + esc(i.photo_url) + '" alt="">' : '<span class="muted small">Intet billede</span>';
      iForm.scrollIntoView({ behavior: "smooth", block: "nearest" }); iForm.name.focus();
    }

    const sure = (b, label, msg) => {
      if (b.dataset.sure) { delete b.dataset.sure; b.textContent = label; return true; }
      b.dataset.sure = "1"; b.textContent = msg; setTimeout(() => { delete b.dataset.sure; b.textContent = label; }, 4000); return false;
    };

    box.addEventListener("click", async (e) => {
      const t = e.target, kEl = t.closest("[data-kid]");
      const k = kEl && kitchens.find((x) => x.id === +kEl.dataset.kid);
      let b;
      if (t.closest("[data-newk]")) return openK(null);
      if (t.closest("[data-closek]")) { kForm.hidden = true; return; }
      if (t.closest("[data-closei]")) { iForm.hidden = true; return; }
      if (k && t.closest("[data-editk]")) return openK(k);
      if (k && t.closest("[data-newi]")) return openI(k, null);
      if (k && (b = t.closest("[data-iid]"))) return openI(k, k.items.find((x) => x.id === +b.dataset.iid));
      if (k && t.closest("[data-copyk]")) {
        (navigator.clipboard ? navigator.clipboard.writeText(k.kitchen_url) : Promise.reject()).then(() => toast("Link kopieret. Send det til køkkenet."), () => toast(k.kitchen_url));
        return;
      }
      if (k && t.closest("[data-sample]")) {
        try { await api("POST", "/api/admin/kitchens/" + k.id + "/sample-menu"); toast("Eksempelmenuen er oprettet. Ret priser og tilføj billeder."); load(); } catch (err) { toast(err.message, true); }
        return;
      }
      if ((b = t.closest("[data-delk]")) && editK) {
        if (!sure(b, "Slet køkken", "Tryk igen: menu og bestillinger slettes")) return;
        try { await api("DELETE", "/api/admin/kitchens/" + editK.id); toast(editK.name + " er slettet"); kForm.hidden = true; load(); } catch (err) { toast(err.message, true); }
        return;
      }
      if ((b = t.closest("[data-newlink]")) && editK) {
        if (!sure(b, "Lav nyt link til køkkenet", "Tryk igen: det gamle link holder op med at virke")) return;
        try { await api("POST", "/api/admin/kitchens/" + editK.id + "/link"); toast("Nyt link lavet. Send det til køkkenet."); load(); } catch (err) { toast(err.message, true); }
        return;
      }
      if ((b = t.closest("[data-deli]")) && editI) {
        if (!sure(b, "Slet vare", "Tryk igen for at slette")) return;
        try { await api("DELETE", "/api/admin/menu-items/" + editI.id); toast(editI.name + " er slettet"); iForm.hidden = true; load(); } catch (err) { toast(err.message, true); }
      }
    });

    kForm.addEventListener("submit", async (e) => {
      e.preventDefault(); const f = kForm;
      const body = { name: f.name.value.trim(), kind: f.kind.value, email: f.email.value.trim(), phone: f.phone.value.trim(),
        lead_hours: +f.lead_hours.value || 0, note: f.note.value.trim() };
      try {
        if (editK) { body.active = f.active.checked; await api("PATCH", "/api/admin/kitchens/" + editK.id, body); toast("Gemt"); }
        else { await api("POST", "/api/admin/kitchens", Object.assign(body, o.scope)); toast(body.name + " er oprettet. Tilføj varer til menuen."); }
        f.hidden = true; load();
      } catch (err) { toast(err.message, true); }
    });

    iForm.addEventListener("submit", async (e) => {
      e.preventDefault(); const f = iForm;
      const body = { name: f.name.value.trim(), category: f.category.value.trim(), price: Math.max(0, parseFloat(String(f.price.value).replace(",", ".")) || 0),
        unit: f.unit.value, description: f.description.value.trim(), active: f.active.checked,
        tags: [...f.querySelectorAll('[name="tag"]:checked')].map((c) => c.value) };
      try {
        if (editI) { await api("PATCH", "/api/admin/menu-items/" + editI.id, body); toast("Gemt"); f.hidden = true; }
        else {
          const i = await api("POST", "/api/admin/kitchens/" + itemKitchen.id + "/items", body);
          toast(i.name + " er på menuen. Tilføj gerne et billede."); await load();
          const k = kitchens.find((x) => x.id === itemKitchen.id); openI(k, k.items.find((x) => x.id === i.id)); return;
        }
        load();
      } catch (err) { toast(err.message, true); }
    });

    iForm.photo.addEventListener("change", async (e) => {
      const file = e.target.files[0]; if (!file || !editI) return;
      const fd = new FormData(); fd.append("file", file);
      try { const i = await api("POST", "/api/admin/menu-items/" + editI.id + "/photo", fd, true); editI = i; $$(".ct-photo").innerHTML = '<img src="' + esc(i.photo_url) + '" alt="">'; toast("Billedet er gemt"); load(); }
      catch (err) { toast(err.message, true); }
      e.target.value = "";
    });

    $$(".ct-month").addEventListener("change", (e) => { month = e.target.value || month; loadOrders(); });

    load();
    return { reload: load };
  }

  window.NoddCatering = { mount };
})();
