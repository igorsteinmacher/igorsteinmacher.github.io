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
    research            data/research.toml   (+ paper titles from dblp_cache.xml)
    projects            data/projects.toml
    honors              data/honors.toml + data/awards.toml (+ dblp_cache.xml)
    courses             data/teaching.toml
    students-current    data/students.toml
    students-alumni     data/students.toml
    phd-alumni-count    data/students.toml   (inline: "nine", "ten", ...)
    service             data/service.toml
    talks               data/talks.toml
    software            data/software.toml

The data helpers here (load, entries, dblp_papers, paper_awards, ...) are
shared with build_cv.py and build_pubs.py.

No dependencies beyond the Python standard library (3.11+ for tomllib).
"""

import re
import sys
import textwrap
import tomllib
import xml.etree.ElementTree as ET
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DBLP_CACHE = ROOT / "dblp_cache.xml"

REGION_RE = re.compile(
    r"(?P<indent>[ \t]*)(?P<begin><!-- BEGIN:(?P<name>[\w-]+)[^>]*-->)\n"
    r".*?"
    r"(?P<end>[ \t]*<!-- END:(?P=name) -->)",
    re.S,
)
INLINE_RE = re.compile(r"(?P<begin><!-- BEGIN:(?P<name>[\w-]+)[^>]*-->)[^\n]*?(?P<end><!-- END:(?P=name) -->)")

NUMBER_WORDS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                "fourteen fifteen sixteen seventeen eighteen nineteen twenty").split()
AUTHOR_SUFFIX_RE = re.compile(r"\s+\d{4}$")  # DBLP disambiguation: "Igor Wiese 0001"


class DataError(Exception):
    pass


def esc(s) -> str:
    return escape(str(s), quote=False)


def attr(s) -> str:
    return escape(str(s), quote=True)


def wrap(text: str, width: int = 84) -> list[str]:
    """Collapse whitespace in a (possibly multi-line) TOML string and re-wrap it."""
    return textwrap.wrap(squash(text), width) or [""]


def squash(text) -> str:
    return " ".join(str(text).split())


# --------------------------------------------------------------------------
# Data access (shared with build_cv.py / build_pubs.py)
# --------------------------------------------------------------------------

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
        missing = [f for f in required if item.get(f) in (None, "")]
        if missing:
            raise DataError(f"{label} is missing {', '.join(missing)}")
        unknown = set(item) - allowed
        if unknown:
            raise DataError(f"{label} has unknown field(s) {', '.join(sorted(unknown))} "
                            f"(allowed: {', '.join(sorted(allowed))})")
    return items


STUDENT_FIELDS = ("topic", "now", "note", "url", "with", "thesis")


def students(table: str) -> list[dict]:
    year = "start" if table == "current" else "year"
    return entries("students.toml", table, ("name", "school", year), STUDENT_FIELDS)


def projects() -> list[dict]:
    return entries("projects.toml", "project", ("title", "start"),
                   ("url", "summary", "funder", "end", "completed", "role", "amount", "with"))


def project_years(p: dict) -> str:
    if p.get("end"):
        return f"{p['start']}–{p['end']}"
    return str(p["start"]) if p.get("completed") else f"{p['start']}–current"


def project_tail(p: dict) -> str:
    """'Funder, 2023–2027, lead PI, USD 498K, with Marco Gerosa' (plain text)."""
    parts = [p.get("funder"), project_years(p), p.get("role"), p.get("amount")]
    tail = ", ".join(x for x in parts if x)
    return tail + (f", with {p['with']}" if p.get("with") else "")


def year_key(y) -> int:
    m = re.search(r"\d{4}", str(y))
    return int(m.group()) if m else 0


_dblp: dict[str, dict] | None = None


def dblp_papers() -> dict[str, dict]:
    """DBLP key -> {title, year, venue, url, authors, kind} from dblp_cache.xml."""
    global _dblp
    if _dblp is None:
        _dblp = {}
        if DBLP_CACHE.exists():
            for r in ET.fromstring(DBLP_CACHE.read_bytes()).iter("r"):
                pub = r[0]
                _dblp[pub.get("key", "")] = {
                    "key": pub.get("key", ""),
                    "kind": pub.tag,
                    "informal": pub.get("publtype") == "informal",
                    "title": (pub.findtext("title") or "").strip().rstrip("."),
                    "year": (pub.findtext("year") or "").strip(),
                    "venue": (pub.findtext("journal") or pub.findtext("booktitle") or "").strip(),
                    "volume": pub.findtext("volume"),
                    "number": pub.findtext("number"),
                    "pages": pub.findtext("pages"),
                    "url": pub.findtext("ee") or "",
                    "authors": [AUTHOR_SUFFIX_RE.sub("", (a.text or "").strip())
                                for a in pub.findall("author")],
                }
    return _dblp


def nice_venue(v: str) -> str:
    """DBLP venue -> display name: 'ITiCSE (1)' -> 'ITiCSE', 'ICSE (SEET)' -> 'ICSE-SEET'."""
    v = re.sub(r"\s*\(\d+\)$", "", v)
    return re.sub(r"^(\S+) \(([A-Z]+)\)$", r"\1-\2", v)


def paper(key: str, where: str) -> dict:
    p = dblp_papers().get(key)
    if p is None:
        raise DataError(f"{where}: DBLP key {key!r} not found in dblp_cache.xml "
                        f"(typo, or renamed on DBLP?)")
    return p


def paper_awards() -> list[dict]:
    """Paper awards from data/awards.toml, joined with DBLP metadata."""
    out = []
    for key, val in load("awards.toml").items():
        val = {"award": val} if isinstance(val, str) else val
        p = dblp_papers().get(key)
        if p is None:
            print(f"WARNING: data/awards.toml key {key!r} not in dblp_cache.xml; skipped",
                  file=sys.stderr)
            continue
        out.append({"year": p["year"], "award": val["award"],
                    "venue": f'{val.get("venue") or nice_venue(p["venue"])} {p["year"]}',
                    "title": p["title"], "url": p["url"]})
    return out


def honors() -> list[dict]:
    """Paper awards + other honors, newest first. Each: year, title, detail, url."""
    items = [{"year": a["year"], "title": f'{a["award"]} — {a["venue"]}',
              "detail": f'“{a["title"]}”', "url": None, "paper_url": a["url"]}
             for a in paper_awards()]
    items += [dict(h, paper_url=None)
              for h in entries("honors.toml", "honor", ("year", "title"), ("detail", "url"))]
    return sorted(items, key=lambda h: year_key(h["year"]), reverse=True)


def talks() -> list[dict]:
    return entries("talks.toml", "talk", ("year", "event"),
                   ("kind", "title", "place", "url", "slides", "video"))


def courses() -> list[dict]:
    return entries("teaching.toml", "course", ("code", "title"), ("level", "terms", "url"))


# --------------------------------------------------------------------------
# Renderers — each returns a list of unindented lines.
# --------------------------------------------------------------------------

def link(text: str, url: str | None) -> str:
    if not url:
        return esc(text)
    external = url.startswith("http")
    extra = ' target="_blank" rel="noopener"' if external else ""
    return f'<a href="{attr(url)}"{extra}>{esc(text)}</a>'


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


def render_research(page: str) -> list[str]:
    lines = []
    themes = entries("research.toml", "theme", ("tag", "title", "text"), ("papers",))
    for t in themes:
        lines.append('<div class="theme">')
        lines.append(f'  <span class="tag">{esc(t["tag"])}</span>')
        lines.append(f'  <h3>{esc(t["title"])}</h3>')
        lines.append(f'  <p>{esc(squash(t["text"]))}</p>')
        if t.get("papers"):
            lines.append('  <ul class="papers">')
            for key in t["papers"]:
                p = paper(key, f'data/research.toml: theme "{t["title"]}"')
                venue = f'{nice_venue(p["venue"])} {p["year"]}'
                lines.append(f'    <li>{link(p["title"], p["url"])} <span class="yr">{esc(venue)}</span></li>')
            lines.append("  </ul>")
        lines.append("</div>")
    return lines


def render_projects(page: str) -> list[str]:
    groups = {"Current": [], "Completed": []}
    for p in projects():
        summary = f" — {esc(p['summary'])}" if p.get("summary") else ""
        groups["Completed" if p.get("completed") else "Current"].append(
            f"<li><strong>{link(p['title'], p.get('url'))}</strong>{summary} — "
            f"{esc(project_tail(p))}.</li>")
    lines = []
    for name, items in groups.items():
        if items:
            lines += [f'<p class="sub-h">{name}</p>', '<ul class="clean">']
            lines += [f"  {li}" for li in items]
            lines.append("</ul>")
    return lines


def render_honors(page: str) -> list[str]:
    lines = []
    for h in honors():
        title = link(h["title"], h.get("url"))
        detail = h.get("detail")
        if detail and h.get("paper_url"):
            detail = link(detail, h["paper_url"])
        elif detail:
            detail = esc(detail)
        lines.append(f'<li><span class="yr">{esc(h["year"])}</span> {title}'
                     + (f": {detail}" if h.get("paper_url") else f" — {detail}" if detail else "")
                     + "</li>")
    return lines


def render_courses(page: str) -> list[str]:
    items = courses()
    if not items:
        return []
    lines = ['<p class="sub-h">Courses</p>', '<ul class="clean">']
    for c in items:
        extra = " · ".join(esc(x) for x in (c.get("level"), c.get("terms")) if x)
        lines.append(f'  <li><span class="yr">{esc(c["code"])}</span> {link(c["title"], c.get("url"))}'
                     + (f" — {extra}" if extra else "") + "</li>")
    lines.append("</ul>")
    return lines


def render_talks(page: str) -> list[str]:
    lines = []
    for t in talks():
        event = link(t["event"], t.get("url"))
        text = f"{esc(t['kind'])}, {event}" if t.get("kind") else event
        if t.get("title"):
            text += f": “{esc(t['title'])}”"
        if t.get("place"):
            text += f" ({esc(t['place'])})"
        extras = [link(lbl, t[k]) for k, lbl in (("slides", "slides"), ("video", "video")) if t.get(k)]
        if extras:
            text += " · " + " · ".join(extras)
        lines.append(f'<li><span class="yr">{esc(t["year"])}</span> {text}</li>')
    return lines


def _student_line(s: dict, when: str, extra_parts: list) -> str:
    tail = " · ".join(esc(x) for x in extra_parts if x)
    return (f"<li>{link(s['name'], s.get('url'))} ({esc(s['school'])}, {when})"
            + (f" — {tail}" if tail else "") + "</li>")


def render_students_current(page: str) -> list[str]:
    return [_student_line(s, f"{esc(s['start'])}–current", [s.get("topic"), s.get("note")])
            for s in students("current")]


def render_students_alumni(page: str) -> list[str]:
    return [_student_line(s, esc(s["year"]),
                          [s.get("topic"), f"now {s['now']}" if s.get("now") else None, s.get("note")])
            for s in students("alumni")]


def render_phd_alumni_count(page: str) -> list[str]:
    n = len(students("alumni"))
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
    "research": render_research,
    "projects": render_projects,
    "honors": render_honors,
    "courses": render_courses,
    "students-current": render_students_current,
    "students-alumni": render_students_alumni,
    "phd-alumni-count": render_phd_alumni_count,
    "service": render_service,
    "talks": render_talks,
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
