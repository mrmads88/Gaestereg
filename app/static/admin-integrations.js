/* Integrationer i admin: webhooks (med test og log), API-nøgler og et katalog over systemer.
   NoddIntegrations.mount(box, { scope: {tenant_id} | {partner_id} | {platform: true}, api, toast, esc }) */
(function () {
  "use strict";
  const fresh = (outer) => { const el = document.createElement("div"); el.className = "stack int"; outer.replaceChildren(el); return el; };
  const when = (s) => s ? new Date(s).toLocaleString(NODD_LOC(), { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
  const STATUS = { ok: "Leveret", failed: "Prøver igen", pending: "Venter", dead: "Opgivet" };
  // Katalog: hvordan de kendte systemer forbindes i dag. help = guide i hjælpecentret.
  const CATALOG = [
    { name: "Zapier", how: "Webhook", note: "Send hændelser videre til 6.000+ apps.", scopes: ["tenant", "partner", "platform"] },
    { name: "Make", how: "Webhook", note: "Byg forløb til fx e-conomic, Dinero, Billy og Salesforce.", scopes: ["tenant", "partner", "platform"] },
    { name: "Power Automate", how: "Webhook", note: "Microsoft 365: Teams, SharePoint, Outlook og Dynamics.", scopes: ["tenant", "partner", "platform"] },
    { name: "ServiceNow", how: "Webhook / API", note: "Opret besøg eller sager, når en gæst tjekker ind.", scopes: ["tenant", "partner"] },
    { name: "Salesforce", how: "Webhook / API", note: "Log kundebesøg på kontoen i Salesforce.", scopes: ["tenant", "partner"] },
    { name: "HR og Microsoft 365", how: "API", note: "Hold personlisten opdateret (hosts/sync).", scopes: ["tenant", "partner"] },
    { name: "Salary og Danløn", how: "CSV / API", note: "Arbejdstid fra Tid. Direkte overførsel kommer.", scopes: ["tenant", "partner"] },
    { name: "Power BI og Excel", how: "API", note: "Hent besøg, bookinger og arbejdstid til rapporter.", scopes: ["tenant", "partner"] },
    { name: "e-conomic, Dinero og Billy", how: "Webhook via Make/Zapier", note: "Godkendte fakturaer til regnskabet. Direkte kobling kommer.", scopes: ["platform"] },
  ];

  function mount(outer, o) {
    const box = fresh(outer);
    const { api, toast, esc } = o;
    const q = o.scope.platform ? "platform=true" : o.scope.tenant_id ? "tenant_id=" + o.scope.tenant_id : "partner_id=" + o.scope.partner_id;
    let D = null, open = null, shown = null;

    async function load() {
      try { D = await api("GET", "/api/admin/integrations?" + q); }
      catch (err) { box.innerHTML = '<div class="card"><p class="muted">' + esc(err.message) + "</p></div>"; return; }
      render();
    }
    const pill = (s) => '<span class="pill ' + ({ ok: "sendt", failed: "venter", pending: "venter", dead: "fejl" }[s] || "test") + '">' + esc(STATUS[s] || s) + "</span>";
    const evName = (k) => (D.events.find((e) => e.key === k) || { label: k }).label;

    function render() {
      const hooks = D.webhooks.map((w) => '<li class="int-hook" data-id="' + w.id + '"><div class="row"><span class="grow"><b>' + esc(w.name) + '</b><code class="int-url">' + esc(w.url) + "</code></span>" +
        '<label class="check"><input type="checkbox" data-act="toggle"' + (w.enabled ? " checked" : "") + "> Aktiv</label></div>" +
        '<div class="chips int-ev">' + w.events.map((e) => "<span>" + esc(evName(e)) + "</span>").join("") + "</div>" +
        '<p class="muted small">' + (w.last_error_at && (!w.last_ok_at || w.last_error_at > w.last_ok_at) ? '<span class="int-bad">Sidste fejl ' + esc(when(w.last_error_at)) + ": " + esc(w.last_error) + "</span>" :
          w.last_ok_at ? "Sidst leveret " + esc(when(w.last_ok_at)) : "Ikke brugt endnu") + "</p>" +
        '<div class="row"><button class="btn ghost sm" type="button" data-act="test">Send test</button><button class="btn ghost sm" type="button" data-act="log">' + (open === w.id ? "Skjul log" : "Vis log") + "</button>" +
        '<button class="btn ghost sm" type="button" data-act="secret">Ny hemmelighed</button><span class="grow"></span><button class="btn ghost sm" type="button" data-act="del">Slet</button></div>' +
        (open === w.id ? '<div class="tablewrap"><table class="int-log"><thead><tr><th>Tid</th><th>Hændelse</th><th>Status</th><th>Svar</th><th></th></tr></thead><tbody>' +
          (w.deliveries.length ? w.deliveries.map((d) => "<tr><td>" + esc(when(d.created_at)) + "</td><td>" + esc(d.event === "ping" ? "Test" : evName(d.event)) + "</td><td>" + pill(d.status) +
            (d.attempts > 1 ? ' <small class="muted">' + d.attempts + " forsøg</small>" : "") + "</td><td>" + esc(d.response_code || "") + (d.error ? '<small class="int-bad">' + esc(d.error) + "</small>" : "") + "</td><td>" +
            (d.status !== "ok" ? '<button class="btn ghost sm" type="button" data-act="retry" data-did="' + d.id + '">Prøv igen</button>' : "") + "</td></tr>").join("")
            : '<tr><td colspan="5" class="muted">Ingen afsendelser endnu.</td></tr>') + "</tbody></table></div>" : "") + "</li>").join("");
      const keys = (D.api_keys || []).map((k) => '<li data-kid="' + k.id + '" class="' + (k.revoked ? "int-revoked" : "") + '"><span class="grow"><b>' + esc(k.name) + '</b><small><code>' + esc(k.prefix) + "…</code> · " +
        esc(k.scopes.join(", ")) + " · " + (k.revoked ? "Tilbagekaldt" : k.last_used_at ? "Sidst brugt " + esc(when(k.last_used_at)) : "Ikke brugt endnu") + "</small></span>" +
        (k.revoked ? "" : '<button class="btn ghost sm" type="button" data-act="revoke">Tilbagekald</button>') + "</li>").join("");
      const scope = D.scope;
      box.innerHTML = (shown ? '<div class="card int-shown"><b>' + esc(shown.title) + '</b><code translate="no">' + esc(shown.value) + '</code><small>' + esc(shown.hint) +
          '</small><div class="row"><button class="btn ghost sm" type="button" data-act="copy">Kopiér</button><button class="btn ghost sm" type="button" data-act="hide">Jeg har gemt den</button></div></div>' : "") +
        '<div class="card"><h3>Webhooks</h3><p class="muted small">' + (scope === "platform" ? "Dine egne hændelser, fx når en faktura godkendes. Forbind til regnskabet via Make eller Zapier." :
          "Nodd sender en besked til adressen, når noget sker. Brug den i fx Power Automate, Make, Zapier, ServiceNow eller Salesforce.") +
        " Beskederne er signeret, og fejl prøves igen i op til 12 timer.</p>" +
        (hooks ? '<ul class="int-hooks">' + hooks + "</ul>" : "") +
        '<form class="stack int-new" data-form="hook"><div class="row int-row"><label class="fld"><span>Navn</span><input name="name" maxlength="120" placeholder="Fx Power Automate"></label>' +
        '<label class="fld grow"><span>Adresse (https)</span><input name="url" type="url" required maxlength="500" placeholder="https://"></label></div>' +
        '<div class="fld"><span>Hændelser</span><div class="int-evpick">' + D.events.map((e, i) => '<label class="check"><input type="checkbox" name="ev" value="' + esc(e.key) + '"' + (i === 0 ? " checked" : "") + "> " + esc(e.label) + "</label>").join("") + "</div></div>" +
        '<div class="row"><button class="btn pri sm" type="submit">Tilføj webhook</button></div></form></div>' +
        (scope !== "platform" ? '<div class="card"><h3>API-nøgler</h3><p class="muted small">Til systemer, der selv henter data fra Nodd (/api/v1): besøg, personer, bookinger og arbejdstid. Nøglen vises kun én gang.</p>' +
          (keys ? '<ul class="int-keys">' + keys + "</ul>" : "") +
          '<form class="row int-row" data-form="key"><label class="fld grow"><span>Navn</span><input name="name" required maxlength="120" placeholder="Fx Power BI eller HR-system"></label>' +
          '<label class="check"><input type="checkbox" name="write"> Må opdatere personlisten</label><button class="btn ghost sm" type="submit">Lav nøgle</button></form></div>' : "") +
        '<div class="card"><h3>Forbind med</h3><div class="int-cat">' + CATALOG.filter((c) => c.scopes.includes(scope)).map((c) => '<a class="int-tile" href="' + esc(window.NoddHelp ? window.NoddHelp.url("integrationer") : "/hjaelp#integrationer") +
          '" target="_blank" rel="noopener"><b>' + esc(c.name) + "</b><span>" + esc(c.how) + "</span><small>" + esc(c.note) + "</small></a>").join("") + "</div></div>";
    }

    box.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-act]"); if (!b) return;
      const act = b.dataset.act, hook = b.closest("[data-id]"), id = hook && hook.dataset.id;
      try {
        if (act === "log") { open = open === +id ? null : +id; return render(); }
        if (act === "hide") { shown = null; return render(); }
        if (act === "copy") { (navigator.clipboard ? navigator.clipboard.writeText(shown.value) : Promise.reject()).then(() => toast("Kopieret"), () => {}); return; }
        if (act === "test") { const d = await api("POST", "/api/admin/integrations/" + id + "/test"); toast(d.status === "ok" ? "Testen kom frem (" + d.response_code + ")" : "Testen fejlede: " + (d.error || d.status), d.status !== "ok"); open = +id; }
        else if (act === "retry") { const d = await api("POST", "/api/admin/deliveries/" + b.dataset.did + "/retry"); toast(d.status === "ok" ? "Leveret" : "Fejlede igen: " + d.error, d.status !== "ok"); }
        else if (act === "secret") { const r = await api("POST", "/api/admin/integrations/" + id + "/secret"); shown = { title: "Ny hemmelighed", value: r.secret, hint: "Brug den til at tjekke signaturen (X-Nodd-Signature). Den gamle virker ikke længere." }; }
        else if (act === "del") {
          if (!b.dataset.sure) { b.dataset.sure = "1"; b.textContent = "Tryk igen"; setTimeout(() => { delete b.dataset.sure; b.textContent = "Slet"; }, 3500); return; }
          await api("DELETE", "/api/admin/integrations/" + id); toast("Slettet");
        } else if (act === "revoke") {
          if (!b.dataset.sure) { b.dataset.sure = "1"; b.textContent = "Tryk igen"; setTimeout(() => { delete b.dataset.sure; b.textContent = "Tilbagekald"; }, 3500); return; }
          await api("DELETE", "/api/admin/api-keys/" + b.closest("[data-kid]").dataset.kid); toast("Nøglen virker ikke længere");
        } else return;
        await load();
      } catch (err) { toast(err.message, true); }
    });
    box.addEventListener("change", async (e) => {
      if (e.target.dataset.act !== "toggle") return;
      try { await api("PATCH", "/api/admin/integrations/" + e.target.closest("[data-id]").dataset.id, { enabled: e.target.checked }); await load(); } catch (err) { toast(err.message, true); }
    });
    box.addEventListener("submit", async (e) => {
      const f = e.target.closest("form[data-form]"); if (!f) return;
      e.preventDefault();
      try {
        if (f.dataset.form === "hook") {
          const events = Array.from(f.querySelectorAll("[name=ev]:checked")).map((x) => x.value);
          if (!events.length) { toast("Vælg mindst én hændelse", true); return; }
          const r = await api("POST", "/api/admin/integrations", { ...o.scope, name: f.name.value.trim(), url: f.url.value.trim(), events });
          shown = { title: "Hemmelighed til " + r.name, value: r.secret, hint: "Gem den nu. Den bruges til at tjekke, at beskederne kommer fra Nodd (X-Nodd-Signature)." };
          open = r.id;
        } else {
          const r = await api("POST", "/api/admin/api-keys", { ...o.scope, name: f.name.value.trim(), scopes: f.write.checked ? ["read", "people:write"] : ["read"] });
          shown = { title: "API-nøgle: " + r.name, value: r.key, hint: "Gem den nu. Den vises ikke igen. Brug den som Authorization: Bearer <nøgle>." };
        }
        await load(); window.scrollTo({ top: box.getBoundingClientRect().top + window.scrollY - 80, behavior: "smooth" });
      } catch (err) { toast(err.message, true); }
    });
    load();
  }

  window.NoddIntegrations = { mount };
})();
