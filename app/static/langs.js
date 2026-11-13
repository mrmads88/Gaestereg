/* Sprog, skærmen kan vises på. Bruges af både skærmen (kiosk.js) og admin (admin.js).
 *
 * Nyt sprog, fx tysk:
 *   1. Tilføj en post her: kode, navn på dansk, navn på sproget selv, hilsen, locale og flag (SVG).
 *   2. Tilføj teksterne i kiosk.js under T.de (kopiér T.en og oversæt).
 *   3. Tilføj koden i SUPPORTED_LANGS i app/schemas.py.
 * tests/test_api.py tjekker, at de tre steder passer sammen.
 */
(function () {
  "use strict";
  let n = 0;
  const uid = () => "f" + (++n);
  window.NODD_LANGS = [
    {
      code: "da", name: "Dansk", native: "Dansk", hello: "Velkommen", locale: "da-DK",
      flag: () => '<svg viewBox="0 0 37 28" aria-hidden="true"><rect width="37" height="28" fill="#c8102e"/>' +
        '<rect x="12" width="4" height="28" fill="#fff"/><rect y="12" width="37" height="4" fill="#fff"/></svg>',
    },
    {
      code: "en", name: "Engelsk", native: "English", hello: "Welcome", locale: "en-GB",
      flag: () => {
        const a = uid(), b = uid();
        return '<svg viewBox="0 0 60 30" aria-hidden="true"><clipPath id="' + a + '"><path d="M0 0v30h60V0z"/></clipPath>' +
          '<clipPath id="' + b + '"><path d="M30 15h30v15zv15H0zH0V0zV0h30z"/></clipPath><g clip-path="url(#' + a + ')">' +
          '<path d="M0 0v30h60V0z" fill="#012169"/><path d="M0 0l60 30m0-30L0 30" stroke="#fff" stroke-width="6"/>' +
          '<path d="M0 0l60 30m0-30L0 30" clip-path="url(#' + b + ')" stroke="#c8102e" stroke-width="4"/>' +
          '<path d="M30 0v30M0 15h60" stroke="#fff" stroke-width="10"/><path d="M30 0v30M0 15h60" stroke="#c8102e" stroke-width="6"/></g></svg>';
      },
    },
  ];
  window.NODD_LANG = (code) => window.NODD_LANGS.find((l) => l.code === code);
})();
