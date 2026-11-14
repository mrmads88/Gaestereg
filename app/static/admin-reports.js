/* Overblik og månedsrapport i admin.
   NoddReports.mount(box, { scope: {tenant_id} | {partner_id}, api, toast, esc, platform, onEmail(v) }) */
(function () {
  "use strict";
  const fresh = (outer) => { const el = document.createElement("div"); el.className = "stack"; outer.replaceChildren(el); return el; };
  const pad = (n) => String(n).padStart(2, "0");

  function mount(box, o) {
    box = fresh(box);  // ny container ved hver mount, så klik kun håndteres én gang
    const { api, toast, esc } = o;
    const q = o.scope.tenant_id ? "tenant_id=" + o.scope.tenant_id : "partner_id=" + o.scope.partner_id;
    const d = new Date(), lm = new Date(d.getFullYear(), d.getMonth() - 1, 1);
    const lastMonth = lm.getFullYear() + "-" + pad(lm.getMonth() + 1);
    const lastQ = (() => { const qn = Math.floor(d.getMonth() / 3); return qn === 0 ? (d.getFullYear() - 1) + "-Q4" : d.getFullYear() + "-Q" + qn; })();
    const url = (p) => "/admin/rapport?" + q + "&period=" + p;

    async function load() {
      let s;
      try { s = await api("GET", "/api/admin/report/settings?" + q); }
      catch (err) { box.innerHTML = '<div class="card"><p class="muted">' + esc(err.message) + "</p></div>"; return; }
      const months = ["januar", "februar", "marts", "april", "maj", "juni", "juli", "august", "september", "oktober", "november", "december"];
      box.innerHTML =
        (!s.module ? '<div class="card upsell"><h3>Overblik er ikke med i pakken</h3><p class="muted">' +
          (o.platform ? "Du kan stadig åbne overblikket og vise det til kunden. Månedsmailen sendes først, når kunden har Plus, Komplet, Hus eller tilkøbet Overblik og månedsrapport." : "Kontakt jeres leverandør, hvis I vil have overblik og månedsrapport.") + "</p></div>" : "") +
        '<div class="card rp-hero"><div class="grow"><h3>Overblik til ledelsen</h3><p class="muted">Gæster, pakker, mødelokaler og forplejning med udvikling mod forrige periode. Kan vises på møder og gemmes som PDF.</p></div>' +
        '<div class="row"><a class="btn pri" target="_blank" rel="noopener" href="' + url(lastMonth) + '">Åbn ' + months[lm.getMonth()] + "</a>" +
        '<a class="btn ghost" target="_blank" rel="noopener" href="' + url(lastQ) + '">Sidste kvartal</a>' +
        '<a class="btn ghost" target="_blank" rel="noopener" href="' + url(String(d.getFullYear())) + '">I år</a></div></div>' +
        '<div class="card"><h3>Månedsrapport på mail</h3><p class="muted small">Sendes den 1. i måneden kl. 7 med nøgletal og en CSV-fil til Excel. Ingen navne på gæster og ingen mødetitler.</p>' +
        '<label class="fld"><span>Modtagere</span><input class="rp-email" type="text" maxlength="500" placeholder="direktion@firma.dk, bogholderi@firma.dk" value="' + esc(s.report_email) + '">' +
        '<small class="hint">Adskil flere adresser med komma. Tom = ingen månedsrapport.</small></label>' +
        '<div class="row"><button class="btn ghost sm" type="button" data-test>Send en prøve nu</button><a class="btn ghost sm" target="_blank" rel="noopener" href="/api/admin/report/mail-preview?' + q + "&period=" + lastMonth + '">Vis mailen</a></div>' +
        (s.runs.length ? '<div class="tablewrap"><table><thead><tr><th>Måned</th><th>Status</th><th>Modtagere</th><th>Tidspunkt</th></tr></thead><tbody>' +
          s.runs.map((r) => "<tr><td>" + esc(r.label) + '</td><td><span class="pill ' + (r.status === "sendt" ? "sendt" : r.status === "fejl" ? "fejl" : "test") + '" title="' + esc(r.error) + '">' + esc(r.status_text) + "</span></td><td>" + esc(r.recipients) + '</td><td class="n">' + esc(r.at) + "</td></tr>").join("") +
          "</tbody></table></div>" : '<p class="muted small">Ingen rapporter sendt endnu.</p>') + "</div>";
    }

    box.addEventListener("change", async (e) => {
      if (!e.target.classList.contains("rp-email")) return;
      try { await o.onEmail(e.target.value.trim()); load(); } catch (err) { toast(err.message, true); }
    });
    box.addEventListener("click", async (e) => {
      if (!e.target.closest("[data-test]")) return;
      const el = box.querySelector(".rp-email");
      try { const r = await api("POST", "/api/admin/report/send-test?" + q, { to: el ? el.value.trim() : "" }); toast(r.message); }
      catch (err) { toast(err.message, true); }
    });
    load();
  }

  window.NoddReports = { mount };
})();
