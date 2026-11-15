/* Opsætning af nye kunder.
   NoddOnboard.wizard({ api, toast, esc, platform, partners, partnerId, onDone(tenantId) }): guiden ved "+ Ny kunde".
   NoddOnboard.checklist(box, { api, esc, tenantId, setTab }): "Kom i gang"-tjeklisten øverst på kunden. */
(function () {
  "use strict";
  const pad = (n) => String(n).padStart(2, "0");
  const today = () => { const d = new Date(); return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); };
  const kr = (o) => Math.round(o / 100).toLocaleString(NODD_LOC()) + " kr.";

  function wizard(o) {
    const { api, toast, esc } = o;
    let step = 1, T = null, products = [], made = { people: 0, admin: "" };
    const veil = document.createElement("div");
    veil.className = "al-veil ob-veil";
    veil.innerHTML = '<div class="al-box ob-box" role="dialog" aria-modal="true" aria-labelledby="obH"><div class="ob-steps" id="obSteps"></div><div id="obBody"></div></div>';
    document.body.appendChild(veil);
    const body = veil.querySelector("#obBody");
    const STEPS = ["Kunden", "Udseende", "Personer", "Skærmen", "Administrator"];
    const close = () => { veil.remove(); if (T) o.onDone(T.id); };

    function frame(h, lead, inner, foot) {
      veil.querySelector("#obSteps").innerHTML = STEPS.map((s, i) => '<span class="' + (i + 1 < step ? "done" : i + 1 === step ? "on" : "") + '"><b>' + (i + 1 < step ? "✓" : i + 1) + "</b>" + s + "</span>").join("");
      body.innerHTML = '<h2 id="obH">' + h + '</h2><p class="muted small">' + lead + "</p>" + inner + '<div class="row ob-foot">' + foot + "</div>";
      const f = body.querySelector("input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=file])"); if (f) f.focus();
    }
    const skip = '<button class="btn ghost sm" type="button" data-act="next">Spring over</button>';
    const later = '<button class="btn ghost sm" type="button" data-act="close">Luk guiden</button>';

    async function render() {
      if (step === 1) {
        if (o.platform && !products.length) products = await api("GET", "/api/admin/billing/products").catch(() => []);
        const pkgs = products.filter((p) => p.kind === "package" && p.active && p.audience !== "house");
        const addons = products.filter((p) => p.kind === "addon" && p.active && p.audience !== "house");
        frame("Ny kunde", "Navn og pakke. Resten kan rettes bagefter.",
          '<form class="stack" data-form="s1"><label class="fld"><span>Kundens navn</span><input name="name" required maxlength="120" placeholder="Fx Junckers"></label>' +
          (o.platform && o.partners.length ? '<label class="fld"><span>Hører til</span><select name="partner_id"><option value="">Selvstændig kunde</option>' +
            o.partners.map((p) => '<option value="' + p.id + '"' + (p.id === o.partnerId ? " selected" : "") + ">" + esc(p.name) + "</option>").join("") + "</select></label>" : "") +
          (o.platform && pkgs.length ? '<div class="fld"><span>Pakke</span><div class="ob-pkgs">' +
            pkgs.map((p, i) => '<label class="ob-pkg"><input type="radio" name="pkg" value="' + esc(p.code) + '"' + (i === 0 ? " checked" : "") + "><b>" + esc(p.name) + "</b><small>" + esc(kr(p.price)) + " / md.</small><span>" + esc(p.description) + "</span></label>").join("") +
            '<label class="ob-pkg"><input type="radio" name="pkg" value=""><b>Vælg senere</b><small>&nbsp;</small><span>Kunden kan bruge skærmen, men faktureres ikke endnu.</span></label></div></div>' +
            (addons.length ? '<div class="fld"><span>Tilkøb</span><div class="ob-addons">' + addons.map((p) => '<label class="check"><input type="checkbox" name="addon" value="' + esc(p.code) + '"> ' + esc(p.name) + ' <small class="muted">' + esc(kr(p.price)) + " / md.</small></label>").join("") + "</div></div>" : "") : "") +
          '<button type="submit" hidden></button></form>',
          later + '<span class="grow"></span><button class="btn pri" type="button" data-act="create">Opret og fortsæt</button>');
      } else if (step === 2) {
        frame("Udseende", "Logo og farve bruges på skærmen, gæstekortet og QR-plakaten.",
          '<div class="ob-look"><div class="ob-logo" id="obLogo">' + (T.logo_url ? '<img src="' + esc(T.logo_url) + '" alt="">' : '<span class="muted small">Intet logo</span>') + "</div>" +
          '<div class="stack grow"><label class="btn ghost sm file">Upload logo<input type="file" accept="image/*" id="obLogoIn"></label>' +
          '<label class="fld"><span>Farve</span><input type="color" id="obColor" value="' + esc(T.color || "#1f3a5a") + '"></label></div></div>' +
          '<label class="fld"><span>Velkomsttekst</span><input id="obWelcome" maxlength="200" value="' + esc(T.welcome_text || "") + '" placeholder="Velkommen til ' + esc(T.name) + '"></label>',
          skip + '<span class="grow"></span><button class="btn pri" type="button" data-act="look">Gem og fortsæt</button>');
      } else if (step === 3) {
        const row = () => '<div class="ob-person"><input name="name" placeholder="Navn" maxlength="120" aria-label="Navn"><input name="title" placeholder="Titel" maxlength="120" aria-label="Titel">' +
          '<input name="email" type="email" placeholder="E-mail" maxlength="200" aria-label="E-mail"><input name="phone" type="tel" placeholder="Mobil" maxlength="40" aria-label="Mobil"></div>';
        frame("Personer", "Dem, gæsterne kan vælge. De får besked på SMS og/eller e-mail. Mange personer? Brug Importér fra Excel under Personer bagefter.",
          '<div class="ob-people" id="obPeople">' + row() + row() + row() + '</div><button class="btn ghost sm" type="button" data-act="more">+ Flere</button>',
          skip + '<span class="grow"></span><button class="btn pri" type="button" data-act="people">Gem og fortsæt</button>');
        body.querySelector("[data-act=more]")._row = row;
      } else if (step === 4) {
        const url = location.origin + "/k/" + T.kiosk_token;
        frame("Skærmen", "Åbn linket på tabletten i receptionen, eller hæng QR-plakaten op, så gæsterne tjekker ind på deres egen telefon.",
          '<div class="ob-link"><code>' + esc(url) + '</code><button class="btn ghost sm" type="button" data-act="copy">Kopiér</button>' +
          '<a class="btn ghost sm" href="/k/' + esc(T.kiosk_token) + '" target="_blank" rel="noopener">Åbn skærm</a>' +
          '<a class="btn ghost sm" href="/api/admin/tenants/' + T.id + '/poster" target="_blank" rel="noopener">QR til døren</a></div>' +
          '<ul class="ob-tips"><li>Brug Chrome i fuld skærm, eller Fully Kiosk Browser til fast brug.</li><li>Prikken ved skærmlinket viser, om skærmen er online.</li><li>Prøv selv at tjekke ind, så kan I se, hvad værten får.</li></ul>',
          '<span class="grow"></span><button class="btn pri" type="button" data-act="next">Fortsæt</button>');
      } else if (step === 5) {
        const ss = T.self_service;
        frame("Administrator", "Kundens egen administrator kan rette skærm, personer og beskeder.",
          (ss || o.platform ? '<form class="stack" data-form="s5">' + (!ss ? '<label class="check"><input type="checkbox" name="ss" checked> Slå selvbetjening til for kunden</label>' : "") +
            '<div class="ob-person two"><input name="name" placeholder="Navn" maxlength="120" aria-label="Navn"><input name="email" type="email" placeholder="E-mail" maxlength="200" aria-label="E-mail"></div>' +
            '<div id="obInv"></div></form>' : '<p class="muted small">Pakken har ikke selvbetjening. Kontakt din leverandør, hvis kunden selv skal kunne rette.</p>'),
          '<button class="btn ghost sm" type="button" data-act="done">Spring over</button><span class="grow"></span>' + (ss || o.platform ? '<button class="btn pri" type="button" data-act="invite">Invitér og afslut</button>' : '<button class="btn pri" type="button" data-act="done">Afslut</button>'));
      } else {
        frame(esc(T.name) + " er klar", "Tjeklisten øverst på kunden viser, hvad der mangler. Den krydser selv af.",
          '<ul class="ob-sum"><li>✓ Oprettet' + (T.pkg ? " med pakken " + esc(T.pkg) : "") + "</li>" + (T.logo_url ? "<li>✓ Logo</li>" : "") +
          (made.people ? "<li>✓ " + made.people + (made.people === 1 ? " person" : " personer") + "</li>" : "") + (made.admin ? "<li>✓ Administrator inviteret: " + esc(made.admin) + "</li>" : "") + "</ul>",
          '<span class="grow"></span><button class="btn pri" type="button" data-act="close">Åbn kunden</button>');
      }
    }

    veil.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-act]"); if (!b) return;
      const act = b.dataset.act;
      try {
        if (act === "close") return close();
        if (act === "next") { step++; return render(); }
        if (act === "done") { step = 6; return render(); }
        if (act === "more") { body.querySelector("#obPeople").insertAdjacentHTML("beforeend", b._row()); return; }
        if (act === "copy") { (navigator.clipboard ? navigator.clipboard.writeText(location.origin + "/k/" + T.kiosk_token) : Promise.reject()).then(() => toast("Link kopieret"), () => {}); return; }
        b.disabled = true;
        if (act === "create") {
          const f = body.querySelector("[data-form=s1]");
          const name = f.name.value.trim(); if (!name) { toast("Skriv kundens navn", true); f.name.focus(); b.disabled = false; return; }
          const pid = f.partner_id ? (+f.partner_id.value || null) : (o.partnerId || null);
          T = await api("POST", "/api/admin/tenants", { name, partner_id: o.platform ? pid : null });
          const pkg = f.pkg ? (f.querySelector("[name=pkg]:checked") || {}).value : "";
          const codes = [pkg, ...Array.from(f.querySelectorAll("[name=addon]:checked")).map((x) => x.value)].filter(Boolean);
          for (const code of codes) await api("POST", "/api/admin/billing/account/subscriptions?tenant_id=" + T.id, { product: code, start: today() });
          T = Object.assign(await api("GET", "/api/admin/tenants/" + T.id), { pkg: pkg ? (products.find((p) => p.code === pkg) || {}).name : "" });
          step = 2;
        } else if (act === "look") {
          const c = body.querySelector("#obColor").value, w = body.querySelector("#obWelcome").value.trim();
          T = Object.assign(T, await api("PATCH", "/api/admin/tenants/" + T.id, { color: c, welcome_text: w }));
          step = 3;
        } else if (act === "people") {
          let n = 0;
          for (const r of body.querySelectorAll(".ob-person")) {
            const v = (k) => r.querySelector("[name=" + k + "]").value.trim();
            if (!v("name")) continue;
            await api("POST", "/api/admin/tenants/" + T.id + "/hosts", { name: v("name"), title: v("title"), email: v("email"), phone: v("phone"), notify_sms: !!v("phone"), notify_email: !!v("email") });
            n++;
          }
          made.people += n; step = 4;
        } else if (act === "invite") {
          const f = body.querySelector("[data-form=s5]");
          const email = f.email.value.trim(); if (!email) { toast("Skriv en e-mail", true); f.email.focus(); b.disabled = false; return; }
          if (f.ss && f.ss.checked) await api("PATCH", "/api/admin/tenants/" + T.id + "/subscription", { self_service: true });
          const res = await api("POST", "/api/admin/tenants/" + T.id + "/users", { email, name: f.name.value.trim() });
          made.admin = email + (res.emailed ? "" : " (send linket: " + res.invite_url + ")");
          step = 6;
        }
        await render();
      } catch (err) { toast(err.message, true); b.disabled = false; }
    });
    veil.addEventListener("change", async (e) => {
      if (e.target.id !== "obLogoIn" || !e.target.files[0]) return;
      const fd = new FormData(); fd.append("file", e.target.files[0]);
      try { T = Object.assign(T, await api("POST", "/api/admin/tenants/" + T.id + "/image/logo", fd, true)); body.querySelector("#obLogo").innerHTML = '<img src="' + esc(T.logo_url) + '" alt="">'; }
      catch (err) { toast(err.message, true); }
    });
    veil.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); if (e.key === "Enter" && e.target.closest("[data-form=s1]")) { e.preventDefault(); veil.querySelector("[data-act=create]").click(); } });
    render();
  }

  // ---------- "Kom i gang" på kunden ----------
  async function checklist(box, o) {
    const { api, esc } = o;
    let c;
    try { c = await api("GET", "/api/admin/tenants/" + o.tenantId + "/checklist"); } catch (err) { box.hidden = true; return; }
    if (c.complete || c.hidden) { box.hidden = true; return; }
    box.hidden = false;
    box.innerHTML = '<div class="row"><h3 class="grow">Kom i gang <span class="muted small">' + c.done + " af " + c.total + ' klar</span></h3><button class="btn ghost sm" type="button" data-hide>Skjul</button></div>' +
      '<div class="ob-bar"><i style="width:' + Math.round(100 * c.done / c.total) + '%"></i></div><ul class="ob-check">' +
      c.items.map((x) => '<li class="' + (x.done ? "done" : "") + '"><span class="ob-tick" aria-hidden="true">' + (x.done ? "✓" : "") + "</span><span class=\"grow\"><b>" + esc(x.label) + "</b>" +
        (x.done ? "" : "<small>" + esc(x.hint) + "</small>") + "</span>" + (x.done ? "" : '<button class="btn ghost sm" type="button" data-tab="' + esc(x.tab) + '">Gå dertil</button>') + "</li>").join("") + "</ul>";
    box.onclick = async (e) => {
      const t = e.target.closest("[data-tab]"); if (t) { o.setTab(t.dataset.tab); return; }
      if (e.target.closest("[data-hide]")) { await api("POST", "/api/admin/tenants/" + o.tenantId + "/checklist/hide", { hidden: true }).catch(() => {}); box.hidden = true; }
    };
  }

  window.NoddOnboard = { wizard, checklist };
})();
