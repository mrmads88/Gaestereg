"""Find de danske tekster, som admin og medarbejdernes sider viser, så de kan oversættes i app/static/i18n-en.js.

Dansk er kildeteksten. Den engelske ordbog slår op på hele tekster og på de stykker, JavaScript sætter sammen
(fx " personer" i n + " personer"). Serverens fejlbeskeder (HTTPException, ValueError) er med, fordi de vises i admin.

  python tools/i18n_extract.py            # skriv de tekster, der mangler en oversættelse
  python tools/i18n_extract.py --all      # skriv alle tekster
  python tools/i18n_extract.py --json     # alle manglende som JSON-skabelon

tests/test_i18n.py fejler, hvis en tekst mangler i ordbogen.
"""
import ast
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
APP = ROOT / "app"

# Siderne, der følger brugerens sprog. Gæsteskærmen (kiosk) har sit eget sprogsystem i kiosk.js.
JS_FILES = sorted(STATIC.glob("admin*.js"))
HTML_FILES = [STATIC / n for n in ("admin.html", "time.html", "booking.html", "evac.html", "kitchen.html", "report.html")]

_LIT = re.compile(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|`(?:\\.|[^`\\])*`')
_TAG = re.compile(r"<[^>]*>")
_ATTR = re.compile(r'(?:placeholder|title|aria-label|alt)="([^"<>{}]*)"')
_DANISH = re.compile(r"[æøåÆØÅé]")
_CODEY = re.compile(r"[{};]|\w=|=[\"\'\w]|=>|&&|\|\||^\s*[#/]|^\s*\.\w|https?:|/api/|\bpx\b|^\w+\(|\$\{|\\u")


def _unescape(s: str) -> str:
    return s.replace("\\'", "'").replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")


def is_text(raw: str) -> bool:
    """Ligner det tekst, en person læser (og ikke kode, CSS-klasser eller id'er)?"""
    s = raw.strip()
    if len(s) < 2 or not re.search(r"[A-Za-zæøåÆØÅ]{2}", s):
        return False
    if _CODEY.search(s):
        return False
    if re.fullmatch(r"[a-z0-9_-]+", s) and not raw.startswith(" ") and not raw.endswith(" "):
        return False  # klasser, id'er, nøgler
    if " " not in s and (re.fullmatch(r"[a-z]+[A-Z]\w*", s) or "_" in s):
        return False  # camelCase og snake_case
    if _DANISH.search(s):
        return True
    if " " in raw.strip() or raw != raw.strip():
        return True
    return bool(re.fullmatch(r"[A-ZÆØÅ][a-zæøåéèüö]+[.!?:…]*", s))


def text_pieces(literal: str) -> list[str]:
    """Teksten i en streng-literal: uden HTML-tags og med placeholder/title/aria-label."""
    out = [m.group(1) for m in _ATTR.finditer(literal)]
    s = literal
    first_lt, first_gt = s.find("<"), s.find(">")
    if first_gt != -1 and (first_lt == -1 or first_gt < first_lt):
        s = s[first_gt + 1:]  # slutningen af et tag fra forrige stykke: '">Gem</button>'
    last_lt, last_gt = s.rfind("<"), s.rfind(">")
    if last_lt > last_gt:
        s = s[:last_lt]  # starten af et tag, der fortsætter i næste stykke
    for part in _TAG.split(s):
        part = part.replace("&nbsp;", " ").replace("&amp;", "&")
        for line in part.split("\n"):
            if is_text(line):
                out.append(line)
    return out


def from_js(src: str) -> set[str]:
    found = set()
    for m in _LIT.finditer(src):
        lit = _unescape(m.group(0)[1:-1])
        for p in text_pieces(lit):
            if is_text(p):
                found.add(p.strip())
    return found


class _Html(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found, self.skip, self.scripts = set(), 0, []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        for k, v in attrs:
            if k in ("placeholder", "title", "aria-label", "alt") and v and is_text(v):
                self.found.add(v.strip())

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1

    def handle_data(self, data):
        if self.skip:
            self.scripts.append(data)
        elif is_text(data):
            self.found.add(" ".join(data.split()))


def from_html(src: str) -> set[str]:
    p = _Html()
    p.feed(src)
    found = set(p.found)
    for s in p.scripts:
        found |= from_js(s)
    return found


def _py_parts(node) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
    if isinstance(node, ast.BinOp):
        return _py_parts(node.left) + _py_parts(node.right)
    if isinstance(node, ast.IfExp):
        return _py_parts(node.body) + _py_parts(node.orelse)
    return []


def from_python(src: str) -> set[str]:
    """Fejlbeskeder og meddelelser, som admin viser: HTTPException, ValueError, "message" og de danske navnelister."""
    found = set()
    for node in ast.walk(ast.parse(src)):
        parts = []
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if name in ("HTTPException", "ValueError", "_off", "log_system", "failed"):
                for a in node.args:
                    parts += _py_parts(a)
        elif isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value in ("message", "detail", "label", "status_text", "text"):
                    parts += _py_parts(v)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and (t.id.endswith("_DA") or t.id in (
                "NAMES", "STAGES", "WRONG", "checks", "CATALOG")) for t in node.targets):
            for sub in ast.walk(node.value):
                parts += _py_parts(sub) if isinstance(sub, (ast.Constant, ast.JoinedStr)) else []
        elif isinstance(node, ast.Return) and node.value is not None and isinstance(node.value, (ast.Constant, ast.JoinedStr)):
            parts += _py_parts(node.value)
        for p in parts:
            for line in p.split("\n"):
                if is_text(line) and (_DANISH.search(line) or re.search(
                        r"\b(?:er|og|ikke|til|med|for|af|på|en|et|det|kan|fra|at|om|ud|ind|der|som|har|skal|vil|eller|i)\b", line)
                                      or re.fullmatch(r"\s*[A-ZÆØÅ][a-zæøå]+[.!?]?\s*", line)):
                    found.add(line.strip())
    return found


def from_catalog(src: str) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "CATALOG" for t in node.targets):
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and is_text(sub.value):
                    found.add(sub.value.strip())
        elif isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value in ("name", "description"):
                    for p in _py_parts(v):
                        if is_text(p):
                            found.add(p.strip())
    return found


def collect() -> set[str]:
    found = set()
    for f in JS_FILES:
        found |= from_js(f.read_text(encoding="utf-8"))
    for f in HTML_FILES:
        found |= from_html(f.read_text(encoding="utf-8"))
    for f in sorted(APP.glob("*.py")):
        found |= from_python(f.read_text(encoding="utf-8"))
    # Prislisten (pakkernes navne, beskrivelser og punkter) kommer fra migrationerne og vises i admin.
    for f in sorted((APP / "migrations" / "versions").glob("*.py")):
        found |= from_catalog(f.read_text(encoding="utf-8"))
    return {s for s in found if s}


def catalog() -> dict:
    """Ordbogen fra app/static/i18n-en.js (JSON mellem de to markører)."""
    src = (STATIC / "i18n-en.js").read_text(encoding="utf-8")
    body = src.split("/*BEGIN*/", 1)[1].split("/*END*/", 1)[0]
    return json.loads(body)


def missing() -> list[str]:
    have = catalog()
    return sorted(s for s in collect() if s not in have)


if __name__ == "__main__":
    if "--all" in sys.argv:
        items = sorted(collect())
    else:
        try:
            items = missing()
        except FileNotFoundError:
            items = sorted(collect())
    if "--json" in sys.argv:
        print(json.dumps({s: "" for s in items}, ensure_ascii=False, indent=1))
    else:
        print("\n".join(items))
        print(f"\n{len(items)} tekster", file=sys.stderr)
