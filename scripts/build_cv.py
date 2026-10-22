#!/usr/bin/env python3
"""
build_cv.py — generate the CV from data/*.toml and DBLP.

Usage:
    python3 scripts/build_cv.py                # writes cv/CV.md and cv/index.html
    python3 scripts/build_cv.py --pdf          # ...and prints Steinmacher_CV.pdf with Chrome
    python3 scripts/build_cv.py --out DIR      # write somewhere else (e.g. for a preview)

Outputs:
    cv/CV.md          the CV as Markdown — the file to read in pull-request diffs
    cv/index.html     the same content, styled for screen and print (igor.pro.br/cv/)
    Steinmacher_CV.pdf  printed from cv/index.html by headless Chrome (--pdf)

Sources: data/cv.toml (header, education, experience, highlights, detailed
service) plus the data the website uses — projects.toml (grants), honors.toml
and awards.toml (awards), students.toml (supervision), talks.toml,
teaching.toml — and dblp_cache.xml (publications).

The GitHub Action .github/workflows/update-cv.yml runs this and opens a pull
request whenever cv/CV.md would change, so nothing goes live until merged.

Chrome is looked up in $CHROME, the usual macOS location, then google-chrome /
chromium on PATH. Otherwise no dependencies beyond the Python standard library.
"""

import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
from html import escape
from pathlib import Path

from build_site import (ROOT, DataError, courses, dblp_papers, entries, honors, load,
                        nice_venue, paper_awards, project_tail, projects, squash,
                        students, talks)

SELF = "Igor Steinmacher"
PDF_DEFAULT = ROOT / "Steinmacher_CV.pdf"

# --------------------------------------------------------------------------
# Content model: a list of sections; each section is a list of blocks.
# Text is a small Markdown subset (**bold**, *italic*, [text](url)).
# --------------------------------------------------------------------------

MD_SPECIAL = re.compile(r"([\\*_\[\]])")


def md(s) -> str:
    """Escape data text for Markdown."""
    return MD_SPECIAL.sub(r"\\\1", squash(s))


def mdlink(text, url) -> str:
    return f"[{md(text)}]({url})" if url else md(text)


def cv_data() -> dict:
    return load("cv.toml")


def counters() -> dict:
    venues = [a["venue"] for a in sorted(paper_awards(), key=lambda a: a["year"], reverse=True)
              if "honorable" not in a["award"].lower()]
    return {
        "phd_alumni": len(students("alumni")),
        "phd_current": len(students("current")),
        "msc_alumni": len(students("masters")),
        "award_venues": ", ".join(venues),
    }


def section_header() -> list[str]:
    p = cv_data().get("person", {})
    lines = [f"# {md(p.get('name', SELF))}", ""]
    lines += [md(t) + "  " for t in p.get("titles", [])]
    if p.get("affiliation"):
        lines.append(md(p["affiliation"]) + "  ")
    contact = []
    if p.get("email"):
        contact.append(f"[{p['email']}](mailto:{p['email']})")
    if p.get("website"):
        contact.append(f"[{p['website'].removeprefix('https://')}]({p['website']})")
    contact += [mdlink(l["label"], l["url"]) for l in p.get("links", [])]
    lines.append(" · ".join(contact))
    return lines


def bullet_section(title: str, items: list[str]) -> list[str]:
    if not items:
        return []
    return ["", f"## {title}", ""] + [f"- {i}" for i in items]


def sub_bullets(title: str, items: list[str]) -> list[str]:
    if not items:
        return []
    return ["", f"### {title}", ""] + [f"- {i}" for i in items]


def citation(p: dict) -> str:
    authors = ", ".join(f"**{md(a)}**" if a == SELF else md(a) for a in p["authors"])
    detail = ""
    if p["volume"]:
        detail = p["volume"] + (f"({p['number']})" if p["number"] else "")
    if p["pages"]:
        detail += f": {p['pages']}" if detail else f", {p['pages']}"
    venue = f"*{md(nice_venue(p['venue']))}*" + (f" {md(detail)}" if detail else "") + f" ({p['year']})"
    title = mdlink(p["title"], p["url"]) + ("" if p["title"].endswith(("?", "!")) else ".")
    return f"{authors}. {title} {venue}."


def publication_lists() -> tuple[list[str], list[str]]:
    awards = {k: (v if isinstance(v, str) else v["award"]) for k, v in load("awards.toml").items()}
    journals, confs = [], []
    pubs = [p for p in dblp_papers().values()
            if p["kind"] in ("article", "inproceedings") and not p["informal"]
            and not p["key"].startswith(("journals/corr/", "data/"))]
    for p in sorted(pubs, key=lambda p: (p["year"], p["title"]), reverse=True):
        item = citation(p) + (f" ★ {md(awards[p['key']])}" if p["key"] in awards else "")
        (journals if p["kind"] == "article" else confs).append(item)
    return journals, confs


def supervision_item(s: dict, degree: str, when: str) -> str:
    school = cv_data().get("schools", {}).get(s["school"], s["school"])
    parts = [f"{md(s['name'])} ({md(when)}). {degree}, {md(school)}."]
    if s.get("thesis"):
        parts.append(f"*{md(s['thesis'])}.*")
    parts.append(f"Co-supervisor (with {md(s['with'])})." if s.get("with") else "Supervisor.")
    return " ".join(parts)


def build_markdown() -> str:
    cv = cv_data()
    c = counters()
    out = section_header()

    out += bullet_section("Highlights", [md(h.format(**c)) for h in cv.get("highlights", [])])

    out += bullet_section("Education", [
        f"**{e['year']}** — {md(e['degree'])}, {md(e['institution'])}"
        for e in entries("cv.toml", "education", ("degree", "year", "institution"), ())])

    out += bullet_section("Professional Experience", [
        f"**{md(e['period'])}** — {md(e['position'])}, {md(e['institution'])}"
        + (f" ({md(e['note'])})" if e.get("note") else "")
        for e in entries("cv.toml", "experience", ("period", "position", "institution"), ("note",))])

    grants = []
    for p in projects():
        head = mdlink(p["title"], p.get("url"))
        summary = f" — {md(p['summary'])}" if p.get("summary") else ""
        grants.append(f"**{head}**{summary}. {md(project_tail(p))}.")
    out += bullet_section("Grants", grants)

    out += bullet_section("Awards and Honors", [
        f"**{md(h['year'])}** — {md(h['title'])}"
        + (f": {mdlink(h['detail'], h['paper_url'])}" if h.get("paper_url")
           else f" — {md(h['detail'])}" if h.get("detail") else "")
        for h in honors()])

    journals, confs = publication_lists()
    out += ["", "## Publications", "",
            f"{len(journals)} journal articles and {len(confs)} conference and workshop papers, "
            f"from [DBLP](https://dblp.org/pid/70/3474.html). ★ marks award-winning papers."]
    out += sub_bullets("Journal Articles", journals)
    out += sub_bullets("Conference and Workshop Papers", confs)

    out += ["", "## Supervision"]
    out += sub_bullets("Ongoing Ph.D.", [
        f"{md(s['name'])} ({s['start']}–current), {md(cv.get('schools', {}).get(s['school'], s['school']))}"
        + (f" — {md(s['topic'])}" if s.get("topic") else "")
        for s in students("current")])
    out += sub_bullets("Concluded Ph.D.", [supervision_item(s, "Ph.D.", str(s["year"]))
                                           for s in students("alumni")])
    out += sub_bullets("Concluded M.Sc.", [supervision_item(s, "M.Sc.", str(s["year"]))
                                           for s in students("masters")])

    out += bullet_section("Teaching", [
        f"**{md(t['code'])}** — {mdlink(t['title'], t.get('url'))}"
        + "".join(f" · {md(t[k])}" for k in ("level", "terms") if t.get(k))
        for t in courses()])

    talk_items = []
    for t in talks():
        s = f"**{t['year']}** — " + (f"{md(t['kind'])}, " if t.get("kind") else "")
        s += mdlink(t["event"], t.get("url"))
        if t.get("title"):
            s += f": “{md(t['title'])}”"
        if t.get("place"):
            s += f" ({md(t['place'])})"
        talk_items.append(s)
    out += bullet_section("Keynotes, Invited Talks and Panels", talk_items)

    out += ["", "## Professional Service"]
    for g in entries("cv.toml", "service", ("title",), ("items",)):
        out += sub_bullets(g["title"], [md(i) for i in g.get("items", [])])

    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------
# Markdown subset -> HTML (only what build_markdown() emits)
# --------------------------------------------------------------------------

def inline_html(text: str) -> str:
    stash: list[str] = []

    def keep(s: str) -> str:
        stash.append(s)
        return f"\x00{len(stash) - 1}\x00"

    text = re.sub(r"\\([\\*_\[\]])", lambda m: keep(escape(m.group(1))), text)
    text = escape(text, quote=False)
    text = re.sub(r"\[([^\]]*)\]\(([^)\s]+)\)",
                  lambda m: keep(f'<a href="{escape(m.group(2), quote=True)}">') + m.group(1) + keep("</a>"),
                  text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)


def markdown_to_html(src: str) -> str:
    html, in_list, header = [], False, []
    for line in src.splitlines():
        if line.startswith("- "):
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"  <li>{inline_html(line[2:])}</li>")
            continue
        if in_list:
            html.append("</ul>")
            in_list = False
        if line.startswith("# "):
            html.append(f'<header><h1>{inline_html(line[2:])}</h1>')
            header = True
        elif line.startswith("## "):
            if header:
                html.append("</header>")
                header = False
            html.append(f"<h2>{inline_html(line[3:])}</h2>")
        elif line.startswith("### "):
            html.append(f"<h3>{inline_html(line[4:])}</h3>")
        elif line.strip():
            html.append(f"<p>{inline_html(line.rstrip().removesuffix('  ').rstrip())}</p>")
    if in_list:
        html.append("</ul>")
    return "\n".join(html)


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CV — Igor Steinmacher</title>
<meta name="description" content="Curriculum vitae of Igor Steinmacher, Associate Professor at Northern Arizona University.">
<link rel="stylesheet" href="{fonts}">
<link rel="icon" href="{root}favicon.svg" type="image/svg+xml">
<style>
  :root {{ --ink: #1b1f24; --slate: #57606a; --line: #d8dee4; --green: #2da44e; --green-deep: #1a7f37; }}
  body {{ margin: 0; color: var(--ink); background: #fafbfc;
    font-family: "Source Serif 4", Georgia, serif; font-size: 15px; line-height: 1.5; }}
  main {{ max-width: 820px; margin: 0 auto; padding: 40px 28px 60px; background: #fff; }}
  header p {{ margin: 0; color: var(--slate); }}
  header p:last-child {{ margin-top: 8px; font-family: "JetBrains Mono", monospace; font-size: 12px; }}
  h1 {{ font-family: "Space Grotesk", sans-serif; font-size: 30px; margin: 0 0 6px; letter-spacing: -.02em; }}
  h2 {{ font-family: "Space Grotesk", sans-serif; font-size: 17px; margin: 28px 0 8px; padding-bottom: 4px;
    border-bottom: 2px solid var(--green); break-after: avoid; }}
  h3 {{ font-family: "Space Grotesk", sans-serif; font-size: 14px; margin: 16px 0 4px; color: var(--slate);
    break-after: avoid; }}
  ul {{ margin: 0; padding-left: 18px; }}
  li {{ margin: 3px 0; break-inside: avoid; }}
  li::marker {{ color: var(--green); }}
  a {{ color: var(--green-deep); text-decoration: none; }}
  strong {{ font-weight: 600; }}
  footer {{ margin-top: 36px; font-family: "JetBrains Mono", monospace; font-size: 11px; color: var(--slate); }}
  @page {{
    size: letter; margin: 0.6in 0.65in 0.7in;
    @bottom-right {{ content: "Igor Steinmacher — CV · " counter(page) " / " counter(pages);
      font-family: "JetBrains Mono", monospace; font-size: 8pt; color: #57606a; }}
  }}
  @media print {{
    body {{ background: #fff; font-size: 10pt; line-height: 1.38; }}
    main {{ max-width: none; padding: 0; }}
    h1 {{ font-size: 22pt; }}
    h2 {{ font-size: 12.5pt; margin-top: 18px; }}
    h3 {{ font-size: 10.5pt; margin-top: 10px; }}
    a {{ color: inherit; }}
  }}
</style>
</head>
<body>
<main>
{body}
<footer>Last updated {updated} · generated from <a href="https://igor.pro.br">igor.pro.br</a> data and DBLP</footer>
</main>
</body>
</html>
"""


def find_chrome() -> str | None:
    candidates = [os.environ.get("CHROME"),
                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Chromium.app/Contents/MacOS/Chromium",
                  shutil.which("google-chrome"), shutil.which("google-chrome-stable"),
                  shutil.which("chromium"), shutil.which("chromium-browser")]
    return next((c for c in candidates if c and Path(c).exists()), None)


def print_pdf(html_path: Path, pdf_path: Path) -> None:
    chrome = find_chrome()
    if not chrome:
        raise SystemExit("ERROR: Chrome/Chromium not found (set $CHROME to its path).")
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
                    "--no-pdf-header-footer", "--run-all-compositor-stages-before-draw",
                    "--virtual-time-budget=10000", f"--print-to-pdf={pdf_path}",
                    html_path.resolve().as_uri()],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Wrote {pdf_path}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "cv", help="output folder (default: cv/)")
    ap.add_argument("--pdf", type=Path, nargs="?", const=PDF_DEFAULT,
                    help=f"also print a PDF (default path: {PDF_DEFAULT.name})")
    args = ap.parse_args()

    try:
        text = build_markdown()
    except DataError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "CV.md").write_text(text, encoding="utf-8")
    root_rel = os.path.relpath(ROOT, out).replace(os.sep, "/") + "/"
    html = PAGE.format(fonts=f"{root_rel}fonts/fonts.css", root=root_rel,
                       body=markdown_to_html(text),
                       updated=datetime.date.today().strftime("%B %Y"))
    (out / "index.html").write_text(html, encoding="utf-8")
    print(f"Wrote {out / 'CV.md'} and {out / 'index.html'}")

    if args.pdf:
        print_pdf(out / "index.html", args.pdf.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
