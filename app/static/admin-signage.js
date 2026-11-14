/* Infoskærme i admin: liste, opret og en editor med levende forhåndsvisning.
   NoddSignage.mount(box, { scope: {tenant_id} | {partner_id}, api, toast, esc, platform }) */
(function () {
  "use strict";
  const fresh = (outer) => { const el = document.createElement("div"); el.className = "stack"; outer.replaceChildren(el); return el; };
  const SLIDES = {
    welcome: ["👋", "Velkomst", "Logo og en hilsen over firmaets baggrundsbillede"],
    text: ["📰", "Tekst eller nyhed", "Overskrift, tekst og evt. billede"],
    image: ["🖼️", "Billede", "Et billede i fuld størrelse med tekst"],
    guests: ["🤝", "Dagens gæster", "Forventede gæster i dag (kun firma eller fornavn)"],
    rooms: ["🚪", "Mødelokaler", "Ledig eller optaget lige nu"],
    menu: ["🍽️", "Dagens menu", "Kantinens menu, en tekst pr. ugedag"],
    qr: ["🔳", "QR-kode", "Fx til booking, hjemmeside eller feedback"],
  };
  const WIDGETS = { clock: "Ur og dato", weather: "Vejret", rooms: "Mødelokaler", guests: "Forventede gæster", wifi: "Gæste-wifi", menu: "Dagens menu", qr: "QR-kode" };
  const DAYS = ["Man", "Tir", "Ons", "Tor", "Fre", "Lør", "Søn"];
  const DAYS_LONG = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"];

  function mount(box, o) {
    box = fresh(box);  // ny container ved hver mount, så klik kun håndteres én gang
    const { api, toast, esc } = o;
    const q = o.scope.tenant_id ? "tenant_id=" + o.scope.tenant_id : "partner_id=" + o.scope.partner_id;
    let screens = [], mods = {}, cur = null, open = -1, dirty = false;

    async function load(keepId) {
      let r;
      try { r = await api("GET", "/api/admin/signage?" + q); } catch (err) { box.innerHTML = '<div class="card"><p class="muted">' + esc(err.message) + "</p></div>"; return; }
      screens = r.screens; mods = r.modules;
      if (keepId) { const s = screens.find((x) => x.id === keepId); if (s) { cur = JSON.parse(JSON.stringify(s)); dirty = false; } }
      render();
    }

    function render() {
      if (!mods.signage) {
        box.innerHTML = '<div class="card upsell"><h3>Infoskærme er ikke med i pakken</h3><p class="muted">' +
          (o.platform ? "Tilmeld Komplet, Hus eller tilkøbet Infoskærm under Abonnement." : "Kontakt jeres leverandør, hvis I vil have infoskærme.") + "</p></div>" +
          (screens.length ? '<p class="muted small">Eksisterende skærme er slået fra, indtil modulet er med igen.</p>' : "");
        return;
      }
      if (cur) return renderEditor();
      box.innerHTML = '<div class="card"><div class="row"><h3 class="grow">Infoskærme</h3><button class="btn pri sm" type="button" data-new>+ Ny infoskærm</button></div>' +
        '<p class="muted small">Tv-skærme i receptionen, kantinen eller på gangen med velkomst, nyheder, billeder, dagens gæster, mødelokaler og menu. Åbn skærmens link i tv\'ets browser.</p>' +
        '<form class="row sg-new" hidden><input name="name" required maxlength="120" placeholder="Fx Reception eller Kantine" aria-label="Skærmens navn" class="sg-in"><button class="btn pri sm" type="submit">Opret</button></form>' +
        '<div class="sg-list">' + (screens.map((s) => '<div class="sg-item" data-sid="' + s.id + '"><span class="scr ' + (s.online ? "on" : "") + '"><i></i></span><div class="grow"><b>' + esc(s.name) + "</b>" +
          (s.active ? "" : '<span class="tag">Slået fra</span>') + '<small class="muted">' + esc(s.content.slides.length + " slides · " + (s.layout === "full" ? "fuld skærm" : "med sidebar") + (s.online ? " · online" : "")) + "</small></div>" +
          '<button class="btn ghost sm" type="button" data-edit>Ret</button><a class="btn ghost sm" target="_blank" rel="noopener" href="' + esc(s.url) + '">Åbn skærm</a><button class="btn ghost sm" type="button" data-copy>Kopiér link</button></div>').join("") ||
          '<p class="muted">Ingen infoskærme endnu.</p>') + "</div></div>";
    }

    // ---------- editor ----------
    function field(label, html, hint) { return '<label class="fld"><span>' + label + "</span>" + html + (hint ? '<small class="hint">' + hint + "</small>" : "") + "</label>"; }
    function slideEditor(x, i) {
      const t = SLIDES[x.type];
      let f = "";
      if (["welcome", "text", "image", "menu", "qr", "guests", "rooms"].includes(x.type)) f += field("Overskrift", '<input data-k="title" maxlength="120" value="' + esc(x.title) + '" placeholder="' + esc({ welcome: "Velkommen", guests: "Vi glæder os til at se", rooms: "Mødelokaler i dag", menu: "Dagens menu", qr: "Scan koden" }[x.type] || "") + '">');
      if (["welcome", "text", "image", "menu", "qr"].includes(x.type)) f += field("Tekst", '<textarea data-k="text" rows="3" maxlength="800">' + esc(x.text) + "</textarea>");
      if (["welcome", "text", "image"].includes(x.type)) f += '<div class="row sg-img">' + (x.image ? '<img src="' + esc(cur.images[x.image] || "") + '" alt="">' : '<span class="muted small">' + (x.type === "welcome" ? "Bruger firmaets baggrundsbillede" : "Intet billede") + "</span>") +
        '<label class="btn ghost sm file">Upload billede<input type="file" accept="image/*" data-upload></label>' + (x.image ? '<button class="btn ghost sm" type="button" data-noimg>Fjern billede</button>' : "") + "</div>";
      if (x.type === "guests") f += field("Vis", '<select data-k="guest_mode"><option value="company"' + (x.guest_mode === "company" ? " selected" : "") + '>Kun gæstens firma</option><option value="first"' + (x.guest_mode === "first" ? " selected" : "") + ">Fornavn, forbogstav og firma</option></select>", "Gæster uden firma vises kun med fornavn. Mobil og mail vises aldrig.");
      if (x.type === "menu") f += '<div class="g4">' + DAYS_LONG.map((d, k) => field(d, '<input data-week="' + k + '" maxlength="300" value="' + esc((x.week || [])[k] || "") + '">')).join("") + "</div>";
      if (x.type === "qr") f += field("Link", '<input data-k="url" maxlength="300" placeholder="https://" value="' + esc(x.url) + '">');
      if (x.type === "rooms" && !mods.rooms) f += '<p class="warnbox small">Mødelokaler er ikke med i pakken. Slet blokken, ellers kan skærmen ikke gemmes.</p>';
      f += '<div class="g4">' + field("Vises i (sek.)", '<input type="number" min="5" max="300" data-k="duration" value="' + x.duration + '">') +
        field("Fra kl.", '<input type="time" data-k="from_time" value="' + esc(x.from_time) + '">') + field("Til kl.", '<input type="time" data-k="to_time" value="' + esc(x.to_time) + '">') +
        '<div class="fld"><span>Kun disse dage</span><div class="sg-days">' + DAYS.map((d, k) => '<label><input type="checkbox" data-day="' + k + '"' + ((x.days || []).includes(k) ? " checked" : "") + ">" + d + "</label>").join("") + "</div></div></div>";
      return '<div class="sg-slide' + (open === i ? " open" : "") + '" data-i="' + i + '"><div class="sg-sh" data-toggle><span class="sg-ico">' + t[0] + '</span><div class="grow"><b>' + esc(x.title || t[1]) + "</b><small class=\"muted\">" + esc(t[1] + " · " + x.duration + " sek." + (x.days && x.days.length ? " · " + x.days.map((k) => DAYS[k]).join(", ") : "") + (x.from_time || x.to_time ? " · " + (x.from_time || "00:00") + "–" + (x.to_time || "24:00") : "")) +
        '</small></div><button class="btn ghost sm" type="button" data-up aria-label="Flyt op">↑</button><button class="btn ghost sm" type="button" data-down aria-label="Flyt ned">↓</button><button class="btn ghost sm" type="button" data-del>Slet</button></div>' +
        (open === i ? '<div class="sg-body">' + f + "</div>" : "") + "</div>";
    }
    function widgetEditor(w, i) {
      let f = "";
      if (w.type === "weather") f = '<input data-wk="place" maxlength="80" value="' + esc(w.place) + '" placeholder="By" aria-label="By"><button class="btn ghost sm" type="button" data-geo>Find byen</button>' + (w.lat != null ? '<span class="muted small">' + w.lat.toFixed(2) + ", " + w.lon.toFixed(2) + "</span>" : "");
      if (w.type === "qr") f = '<input data-wk="url" maxlength="300" value="' + esc(w.url) + '" placeholder="https://" aria-label="Link"><input data-wk="title" maxlength="80" value="' + esc(w.title) + '" placeholder="Tekst" aria-label="Tekst">';
      if (w.type === "menu") f = '<span class="muted small">Teksten for dagen tages fra feltet nedenfor</span>';
      if (w.type === "wifi") f = '<span class="muted small">Navn og kode fra firmaets indstillinger (Gæsteflow)</span>';
      return '<div class="sg-w" data-wi="' + i + '"><b>' + esc(WIDGETS[w.type]) + "</b>" + f + '<span class="grow"></span><button class="btn ghost sm" type="button" data-wup aria-label="Flyt op">↑</button><button class="btn ghost sm" type="button" data-wdel>Fjern</button>' +
        (w.type === "menu" ? '<div class="g4 sg-wweek">' + DAYS_LONG.map((d, k) => '<input data-wweek="' + k + '" maxlength="300" placeholder="' + d + '" value="' + esc((w.week || [])[k] || "") + '">').join("") + "</div>" : "") + "</div>";
    }
    function renderEditor() {
      const c = cur.content, scrollY = window.scrollY;
      box.innerHTML = '<div class="card sg-wrap"><div class="row"><button class="btn ghost sm" type="button" data-back>← Alle skærme</button><h3 class="grow">' + esc(cur.name) + '</h3><span class="muted small sg-dirty"' + (dirty ? "" : " hidden") + '>Ikke gemt</span>' +
        '<a class="btn ghost sm" target="_blank" rel="noopener" href="' + esc(cur.url) + '">Åbn skærm</a><button class="btn pri sm" type="button" data-save>Gem</button></div>' +
        '<div class="sg-grid"><div class="sg-left">' +
        '<div class="g2">' + field("Navn", '<input data-top="name" maxlength="120" value="' + esc(cur.name) + '">') +
        '<div class="fld"><span>Skærmen er</span><label class="switch"><input type="checkbox" data-top="active"' + (cur.active ? " checked" : "") + "><i></i><em>Tændt</em></label></div></div>" +
        '<div class="g2"><div class="fld"><span>Opsætning</span><div class="seg" data-seg="layout"><button type="button" data-v="sidebar" aria-pressed="' + (cur.layout === "sidebar") + '">Med sidebar</button><button type="button" data-v="full" aria-pressed="' + (cur.layout === "full") + '">Fuld skærm</button></div></div>' +
        '<div class="fld"><span>Farver</span><div class="seg" data-seg="theme"><button type="button" data-v="brand" aria-pressed="' + (cur.theme === "brand") + '">Firmafarve</button><button type="button" data-v="dark" aria-pressed="' + (cur.theme === "dark") + '">Mørk</button><button type="button" data-v="light" aria-pressed="' + (cur.theme === "light") + '">Lys</button></div></div></div>' +
        "<h3>Slides</h3>" + '<div class="sg-slides">' + c.slides.map(slideEditor).join("") + "</div>" +
        '<div class="sg-add">' + Object.entries(SLIDES).map(([k, v]) => '<button class="btn ghost sm" type="button" data-add="' + k + '"' + (k === "rooms" && !mods.rooms ? ' disabled title="Kræver Mødelokaler"' : "") + ">" + v[0] + " " + esc(v[1]) + "</button>").join("") + "</div>" +
        (cur.layout === "sidebar" ? "<h3>Sidebar</h3>" + '<div class="sg-ws">' + c.side.map(widgetEditor).join("") + "</div>" +
          '<div class="sg-add">' + Object.entries(WIDGETS).filter(([k]) => !c.side.some((w) => w.type === k)).map(([k, v]) => '<button class="btn ghost sm" type="button" data-wadd="' + k + '"' + (k === "rooms" && !mods.rooms ? " disabled" : "") + ">+ " + esc(v) + "</button>").join("") + "</div>" : "") +
        "<h3>Nyhedsbånd</h3>" + field("Én besked pr. linje. Tom = intet bånd", '<textarea data-ticker rows="3" maxlength="4200">' + esc(c.ticker.join("\n")) + "</textarea>") +
        '<div class="row"><button class="btn bad sm" type="button" data-delscreen>Slet skærm</button><button class="btn ghost sm" type="button" data-newlink>Lav nyt link</button></div>' +
        '</div><div class="sg-right"><span class="lbl">Forhåndsvisning</span><div class="sg-pv"><iframe title="Forhåndsvisning af infoskærmen" src="' + esc(cur.url) + '?preview=1"></iframe></div>' +
        '<p class="muted small">Opdateres, når du gemmer.</p></div></div></div>';
      fit(); window.scrollTo(0, scrollY);
    }
    function fit() {
      const pv = box.querySelector(".sg-pv"), f = pv && pv.querySelector("iframe");
      if (f) f.style.transform = "scale(" + pv.clientWidth / 1600 + ")";
    }
    addEventListener("resize", fit);
    const mark = () => { dirty = true; const d = box.querySelector(".sg-dirty"); if (d) d.hidden = false; };
    const slideOf = (el) => { const s = el.closest("[data-i]"); return s ? cur.content.slides[+s.dataset.i] : null; };
    const NEW = { welcome: { title: "Velkommen" }, text: { title: "Nyhed" }, image: {}, guests: {}, rooms: {}, menu: { week: ["", "", "", "", "", "", ""] }, qr: { url: "https://" } };

    async function save() {
      const body = { name: cur.name, layout: cur.layout, theme: cur.theme, active: cur.active, content: cur.content };
      try {
        const s = await api("PATCH", "/api/admin/signage/" + cur.id, body);
        cur = JSON.parse(JSON.stringify(s)); dirty = false; toast("Infoskærmen er gemt"); renderEditor();
      } catch (err) { toast(err.message, true); }
    }

    box.addEventListener("click", async (e) => {
      const t = e.target, b = (s) => t.closest(s);
      let x;
      if (b("[data-new]")) { const f = box.querySelector(".sg-new"); f.hidden = !f.hidden; if (!f.hidden) f.name.focus(); return; }
      if ((x = b("[data-sid]"))) {
        const s = screens.find((y) => y.id === +x.dataset.sid);
        if (b("[data-edit]")) { cur = JSON.parse(JSON.stringify(s)); open = -1; dirty = false; return renderEditor(); }
        if (b("[data-copy]")) { (navigator.clipboard ? navigator.clipboard.writeText(s.url) : Promise.reject()).then(() => toast("Link kopieret. Åbn det i tv'ets browser i fuld skærm."), () => toast(s.url)); return; }
        return;
      }
      if (!cur) return;
      if (b("[data-back]")) { if (dirty && !confirm("Du har ændringer, der ikke er gemt. Gå tilbage alligevel?")) return; cur = null; return load(); }
      if (b("[data-save]")) return save();
      if ((x = b("[data-seg] [data-v]"))) { cur[x.closest("[data-seg]").dataset.seg] = x.dataset.v; mark(); return renderEditor(); }
      if ((x = b("[data-add]"))) { cur.content.slides.push(Object.assign({ type: x.dataset.add, duration: 12, title: "", text: "", image: "", url: "", week: [], guest_mode: "company", days: [], from_time: "", to_time: "" }, NEW[x.dataset.add])); open = cur.content.slides.length - 1; mark(); return renderEditor(); }
      if ((x = b("[data-wadd]"))) { cur.content.side.push({ type: x.dataset.wadd, title: "", place: "", lat: null, lon: null, url: "", guest_mode: "company", week: [] }); mark(); return renderEditor(); }
      const sl = cur.content.slides, i = (b("[data-i]") || {}).dataset ? +b("[data-i]").dataset.i : -1;
      if (b("[data-up]") && i > 0) { [sl[i - 1], sl[i]] = [sl[i], sl[i - 1]]; open = -1; mark(); return renderEditor(); }
      if (b("[data-down]") && i > -1 && i < sl.length - 1) { [sl[i + 1], sl[i]] = [sl[i], sl[i + 1]]; open = -1; mark(); return renderEditor(); }
      if (b("[data-del]") && i > -1) { sl.splice(i, 1); open = -1; mark(); return renderEditor(); }
      if (b("[data-noimg]")) { slideOf(t).image = ""; mark(); return renderEditor(); }
      if (b("[data-toggle]") && !b("button")) { open = open === i ? -1 : i; return renderEditor(); }
      const wi = b("[data-wi]") ? +b("[data-wi]").dataset.wi : -1, ws = cur.content.side;
      if (b("[data-wup]") && wi > 0) { [ws[wi - 1], ws[wi]] = [ws[wi], ws[wi - 1]]; mark(); return renderEditor(); }
      if (b("[data-wdel]") && wi > -1) { ws.splice(wi, 1); mark(); return renderEditor(); }
      if (b("[data-geo]") && wi > -1) {
        const w = ws[wi];
        try {
          const r = await fetch("https://geocoding-api.open-meteo.com/v1/search?count=1&language=da&name=" + encodeURIComponent(w.place));
          const j = await r.json(); const g = j.results && j.results[0];
          if (!g) { toast("Byen blev ikke fundet", true); return; }
          w.lat = g.latitude; w.lon = g.longitude; w.place = g.name; mark(); renderEditor(); toast("Fundet: " + g.name + (g.admin1 ? ", " + g.admin1 : ""));
        } catch (err) { toast("Kunne ikke slå byen op lige nu", true); }
        return;
      }
      if ((x = b("[data-delscreen]"))) {
        if (!x.dataset.sure) { x.dataset.sure = "1"; x.textContent = "Tryk igen for at slette"; setTimeout(() => { delete x.dataset.sure; x.textContent = "Slet skærm"; }, 4000); return; }
        try { await api("DELETE", "/api/admin/signage/" + cur.id); toast("Skærmen er slettet"); cur = null; load(); } catch (err) { toast(err.message, true); }
        return;
      }
      if ((x = b("[data-newlink]"))) {
        if (!x.dataset.sure) { x.dataset.sure = "1"; x.textContent = "Tryk igen: det gamle link stopper"; setTimeout(() => { delete x.dataset.sure; x.textContent = "Lav nyt link"; }, 4000); return; }
        try { const s = await api("POST", "/api/admin/signage/" + cur.id + "/link"); cur.url = s.url; cur.token = s.token; toast("Nyt link lavet. Åbn det på tv'et."); renderEditor(); } catch (err) { toast(err.message, true); }
      }
    });
    box.addEventListener("input", (e) => {
      const t = e.target; if (!cur) return;
      if (t.dataset.top === "name") { cur.name = t.value; mark(); return; }
      if (t.dataset.top === "active") { cur.active = t.checked; mark(); return; }
      if (t.matches("[data-ticker]")) { cur.content.ticker = t.value.split("\n"); mark(); return; }
      const s = slideOf(t);
      if (s && t.dataset.k) { s[t.dataset.k] = t.dataset.k === "duration" ? (parseInt(t.value, 10) || 12) : t.value; mark(); return; }
      if (s && t.dataset.week) { s.week = s.week && s.week.length === 7 ? s.week : ["", "", "", "", "", "", ""]; s.week[+t.dataset.week] = t.value; mark(); return; }
      if (s && t.dataset.day) { const k = +t.dataset.day; s.days = (s.days || []).filter((d) => d !== k).concat(t.checked ? [k] : []).sort(); mark(); return; }
      const wEl = t.closest("[data-wi]");
      if (wEl) {
        const w = cur.content.side[+wEl.dataset.wi];
        if (t.dataset.wk) { w[t.dataset.wk] = t.value; if (t.dataset.wk === "place") { w.lat = null; w.lon = null; } mark(); }
        if (t.dataset.wweek) { w.week = w.week && w.week.length === 7 ? w.week : ["", "", "", "", "", "", ""]; w.week[+t.dataset.wweek] = t.value; mark(); }
      }
    });
    box.addEventListener("change", async (e) => {
      const t = e.target;
      if (t.matches("[data-upload]") && cur) {
        const file = t.files[0], s = slideOf(t); if (!file || !s) return;
        const fd = new FormData(); fd.append("file", file);
        try { const r = await api("POST", "/api/admin/signage/" + cur.id + "/image", fd, true); s.image = r.image; cur.images[r.image] = r.url; mark(); renderEditor(); toast("Billedet er lagt på. Husk at gemme."); }
        catch (err) { toast(err.message, true); }
      }
    });
    box.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!e.target.classList.contains("sg-new")) return;
      const name = e.target.name.value.trim(); if (!name) return;
      try {
        const s = await api("POST", "/api/admin/signage", Object.assign({ name }, o.scope));
        toast(name + " er oprettet. Tilpas slides og gem."); await load(); cur = JSON.parse(JSON.stringify(screens.find((x) => x.id === s.id) || s)); open = -1; renderEditor();
      } catch (err) { toast(err.message, true); }
    });
    load();
  }

  window.NoddSignage = { mount };
})();
