// Laver PNG-ikoner af SVG-filerne i app/static/brand med den indbyggede Chromium.
// Kør: node tools/brand_png.js   (efter python tools/brand.py)
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const dir = path.join(__dirname, "..", "app", "static", "brand");
const jobs = [
  ["nodd-icon.svg", "nodd-icon-180.png", 180, 180],  // apple-touch-icon
  ["nodd-icon.svg", "nodd-icon-192.png", 192, 192],
  ["nodd-icon.svg", "nodd-icon-512.png", 512, 512],
  ["nodd-icon.svg", "nodd-icon-32.png", 32, 32],
  ["nodd-lockup.svg", "nodd-lockup.png", 480, 134],  // til e-mails (2x af 240 px)
];
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage();
  for (const [src, out, w, h] of jobs) {
    const data = fs.readFileSync(path.join(dir, src), "utf8");
    await p.setViewportSize({ width: w, height: h });
    await p.setContent(`<style>html,body{margin:0;background:transparent}svg{display:block;width:${w}px;height:${h}px}</style>${data}`);
    await p.screenshot({ path: path.join(dir, out), omitBackground: true });
    console.log("skrev", out);
  }
  await b.close();
})();
