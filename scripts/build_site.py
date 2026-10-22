#!/usr/bin/env python3
"""
build_site.py — fill the generated parts of the HTML pages from data/*.toml.

Usage:
    python3 scripts/build_site.py

The pages stay ordinary hand-editable HTML. Only the regions wrapped in
marker comments are rewritten:

    <!-- BEGIN:students-current (generated from data/students.toml) -->
    ...anything here is replaced on every build...
    <!-- END:students-current -->

Everything outside the markers (prose, layout, scripts) is left untouched, so
edit text in the HTML and lists in data/. The generated lines are indented to
match the BEGIN marker. A region can also sit inside a sentence, on one line:

    I have supervised <!-- BEGIN:phd-alumni-count -->nine<!-- END:phd-alumni-count --> PhD students

Regions and their sources:
    nav                 data/site.toml       (every page)
    projects            data/projects.toml
    students-current    data/students.toml
    students-alumni     data/students.toml
    phd-alumni-count    data/students.toml   (inline: "nine", "ten", ...)
    service             data/service.toml
    software            data/software.toml

No dependencies beyond the Python standard library (3.11+ for tomllib).
"""

import re
import sys
import textwrap
import tomllib
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

REGION_RE = re.compile(
    r"(?P<indent>[ \t]*)(?P<begin><!-- BEGIN:(?P<name>[\w-]+)[^>]*-->)\n"
    r".*?"
    r"(?P<end>[ \t]*<!-- END:(?P=name) -->)",
    re.S,
)
INLINE_RE = re.compile(r"(?P<begin><!-- BEGIN:(?P<name>[\w-]+)[^>]*-->)[^\n]*?(?P<end><!-- END:(?P=name) -->)")

NUMBER_WORDS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                "fourteen fifteen sixteen seventeen eighteen nineteen twenty").split()


class DataError(Exception):
    pass


def esc(s) -> str:
    return escape(str(s), quote=False)


def attr(s) -> str:
    return escape(str(s), quote=True)


def wrap(text: str, width: int = 84) -> list[str]:
    """Collapse whitespace in a (possibly multi-line) TOML string and re-wrap it."""
    return textwrap.wrap(" ".join(str(text).split()), width) or [""]


_data_cache: dict[str, dict] = {}


def load(name: str) -> dict:
    if name not in _data_cache:
        path = DATA / name
        try:
            _data_cache[name] = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise DataError(f"data/{name}: {e}") from e
    return _data_cache[name]


def entries(file: str, table: str, required: tuple, optional: tuple) -> list[dict]:
    """Return the [[table]] list from a data file, validating its fields."""
    items = load(file).get(table, [])
    allowed = set(required) | set(optional)
    for i, item in enumerate(items, 1):
        label = f'data/{file}: [[{table}]] #{i} ({item.get("name") or item.get("title") or "?"})'
        missing = [f for f in required if not item.get(f)]
        if missing:
            raise DataError(f"{label} is missing {', '.join(missing)}")
        unknown = set(item) - allowed
        if unknown:
            raise DataError(f"{label} has unknown field(s) {', '.join(sorted(unknown))} "
                            f"(allowed: {', '.join(sorted(allowed))})")
    return items


def link(text: str, url: str | None) -> str:
    if not url:
        return esc(text)
    external = url.startswith("http")
    extra = ' target="_blank" rel="noopener"' if external else ""
    return f'<a href="{attr(url)}"{extra}>{esc(text)}</a>'


# --------------------------------------------------------------------------
# Renderers — each returns a list of unindented lines.
# --------------------------------------------------------------------------

def render_nav(page: str) -> list[str]:
    lines = []
    for i, item in enumerate(load("site.toml").get("nav", []), 1):
        if not item.get("label") or not item.get("href"):
            raise DataError(f"data/site.toml: nav item #{i} needs label and href")
        href = item["href"]
        if page == "index.html" and href.startswith("index.html#"):
            href = href[len("index.html"):]
        lines.append(f'<a href="{attr(href)}">{esc(item["label"])}</a>')
    return lines


def render_projects(page: str) -> list[str]:
    lines = []
    for p in entries("projects.toml", "project", ("title",), ("url", "details")):
        details = f" {esc(p['details'])}" if p.get("details") else ""
        lines.append(f"<li><strong>{link(p['title'], p.get('url'))}</strong>{details}</li>")
    return lines


def render_students_current(page: str) -> list[str]:
    lines = []
    for s in entries("students.toml", "current", ("name", "school", "start"),
                     ("topic", "note", "url")):
        tail = " · ".join(esc(x) for x in (s.get("topic"), s.get("note")) if x)
        lines.append(f"<li>{link(s['name'], s.get('url'))} ({esc(s['school'])}, "
                     f"{esc(s['start'])}–current)" + (f" — {tail}" if tail else "") + "</li>")
    return lines


def render_students_alumni(page: str) -> list[str]:
    lines = []
    for s in entries("students.toml", "alumni", ("name", "school", "year"),
                     ("topic", "now", "note", "url")):
        parts = [s.get("topic"), f"now {s['now']}" if s.get("now") else None, s.get("note")]
        tail = " · ".join(esc(x) for x in parts if x)
        lines.append(f"<li>{link(s['name'], s.get('url'))} ({esc(s['school'])}, "
                     f"{esc(s['year'])})" + (f" — {tail}" if tail else "") + "</li>")
    return lines


def render_phd_alumni_count(page: str) -> list[str]:
    n = len(load("students.toml").get("alumni", []))
    return [NUMBER_WORDS[n] if n < len(NUMBER_WORDS) else str(n)]


def render_service(page: str) -> list[str]:
    lines = []
    for g in entries("service.toml", "group", ("title",), ("items",)):
        lines.append(f'<p class="sub-h">{esc(g["title"])}</p>')
        lines.append('<ul class="clean">')
        lines.extend(f"  <li>{esc(item)}</li>" for item in g.get("items", []))
        lines.append("</ul>")
    return lines


def render_software(page: str) -> list[str]:
    lines = []
    for t in entries("software.toml", "tool", ("name",), ("description", "links")):
        lines.append('<div class="sw">')
        lines.append(f"  <h3>{esc(t['name'])}</h3>")
        desc = wrap(t.get("description", ""))
        if len(desc) == 1:
            lines.append(f"  <p>{esc(desc[0])}</p>")
        else:
            lines.append(f"  <p>{esc(desc[0])}")
            lines.extend(f"  {esc(d)}" for d in desc[1:-1])
            lines.append(f"  {esc(desc[-1])}</p>")
        if t.get("links"):
            lines.append('  <div class="links">')
            for i, l in enumerate(t["links"], 1):
                if not l.get("label") or not l.get("url"):
                    raise DataError(f"data/software.toml: {t['name']} link #{i} needs label and url")
                lines.append(f"    {link(l['label'], l['url'])}")
            lines.append("  </div>")
        lines.append("</div>")
        lines.append("")
    return lines[:-1]  # drop trailing blank line


RENDERERS = {
    "nav": render_nav,
    "projects": render_projects,
    "students-current": render_students_current,
    "students-alumni": render_students_alumni,
    "phd-alumni-count": render_phd_alumni_count,
    "service": render_service,
    "software": render_software,
}


def fill_regions(html: str, page: str) -> str:
    """Rewrite every BEGIN/END region in an HTML string. `page` is its filename."""
    def render(name: str) -> list[str]:
        if name not in RENDERERS:
            raise DataError(f"{page}: unknown region '{name}' "
                            f"(known: {', '.join(RENDERERS)})")
        return RENDERERS[name](page)

    def block(m: re.Match) -> str:
        indent = m["indent"]
        body = "".join(f"{indent}{line}\n" if line else "\n" for line in render(m["name"]))
        return f"{indent}{m['begin']}\n{body}{m['end']}"

    def inline(m: re.Match) -> str:
        return f"{m['begin']}{''.join(render(m['name']))}{m['end']}"

    return INLINE_RE.sub(inline, REGION_RE.sub(block, html))


def main() -> int:
    changed = 0
    try:
        for path in sorted(ROOT.glob("*.html")):
            old = path.read_text(encoding="utf-8")
            new = fill_regions(old, path.name)
            if new != old:
                path.write_text(new, encoding="utf-8")
                changed += 1
                print(f"updated {path.name}")
    except DataError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"{changed} page(s) changed." if changed else "All pages up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
