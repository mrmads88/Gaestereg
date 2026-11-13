"""Tegner Nodd-logoet som SVG-filer i app/static/brand.

Valgt november 2026: ordmærke W1 "Nikket" + symbol S6 "Gæstekortet", palet "Messing".
Kør: python tools/brand.py  (PNG-ikonerne laves bagefter med tools/brand_png.js)
"""
from pathlib import Path

INK = "#12352e"      # dyb grøn
BRASS = "#c99a3e"    # messing
PAPER = "#f4f2ea"
OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "brand"

SW = 13  # stregtykkelse i ordmærket (x-højde 60)


def _n(x, c):
    return f'<path d="M{x + 6.5} 60V30A23.5 23.5 0 0 1 {x + 53.5} 30V60" fill="none" stroke="{c}" stroke-width="{SW}"/>'


def _d(x, c):
    return (f'<circle cx="{x + 30}" cy="30" r="23.5" fill="none" stroke="{c}" stroke-width="{SW}"/>'
            f'<path d="M{x + 53.5} -34V60" stroke="{c}" stroke-width="{SW}"/>')


def wordmark(c):
    """n + hoved (o'et, der dykker som et nik) + d + d. Spænder x 0..276, y -34..68."""
    return _n(0, c) + f'<circle cx="102" cy="40" r="28" fill="{BRASS}"/>' + _d(144, c) + _d(216, c)


def symbol(fg, ac=BRASS):
    """Gæstekortet: kort med strop-hul og en gæst. 100x100-gitter."""
    return (f'<g transform="rotate(-8 50 52)"><rect x="22" y="14" width="56" height="74" rx="11" fill="none" '
            f'stroke="{fg}" stroke-width="9"/><rect x="40" y="24" width="20" height="6" rx="3" fill="{fg}"/>'
            f'<circle cx="50" cy="51" r="9" fill="{ac}"/><path d="M35 75a15 13 0 0 1 30 0" fill="none" '
            f'stroke="{ac}" stroke-width="7" stroke-linecap="round"/></g>')


def svg(viewbox, body, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}" role="img" aria-label="{title}">'
            f'<title>{title}</title>{body}</svg>\n')


FILES = {
    "nodd-wordmark.svg": svg("-4 -38 284 110", wordmark(INK), "Nodd"),
    "nodd-wordmark-light.svg": svg("-4 -38 284 110", wordmark("#ffffff"), "Nodd"),
    "nodd-symbol.svg": svg("8 6 84 90", symbol(INK), "Nodd"),
    # App-ikon og favicon: grøn flise med hvidt kort.
    "nodd-icon.svg": svg("0 0 100 100", f'<rect width="100" height="100" rx="22" fill="{INK}"/>'
                         f'<g transform="translate(15 13) scale(.7)">{symbol("#ffffff")}</g>', "Nodd"),
    # Symbol og ordmærke side om side. Symbolet spænder fra d'ernes top til hovedets bund.
    "nodd-lockup.svg": svg("4 -40 410 114", f'<g transform="translate(-6 -38) scale(1.08)">{symbol(INK)}</g>'
                           f'<g transform="translate(130 0)">{wordmark(INK)}</g>', "Nodd"),
    "nodd-lockup-light.svg": svg("4 -40 410 114", f'<g transform="translate(-6 -38) scale(1.08)">{symbol("#ffffff")}</g>'
                                 f'<g transform="translate(130 0)">{wordmark("#ffffff")}</g>', "Nodd"),
}

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, content in FILES.items():
        (OUT / name).write_text(content, encoding="utf-8")
        print("skrev", name)
