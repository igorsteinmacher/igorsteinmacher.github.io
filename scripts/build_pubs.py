#!/usr/bin/env python3
"""
build_pubs.py — regenerate publications.html from DBLP.

Usage:
    python scripts/build_pubs.py

Fetches https://dblp.org/pid/70/3474.xml (Igor Steinmacher's DBLP record),
groups journal and conference papers by year, and writes publications.html.
Informal publications (arXiv/CoRR preprints) are skipped.

No dependencies beyond the Python standard library.
"""

import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

DBLP_PID = "70/3474"
DBLP_URL = f"https://dblp.org/pid/{DBLP_PID}.xml"
OUT = Path(__file__).resolve().parent.parent / "publications.html"

# Optional: mark award papers (DBLP key fragment -> award label)
AWARDS = {
    "conf/icse/TrinkenreichSSG23": "ACM SIGSOFT Distinguished Paper",
    "conf/icse/DiasMCSWP21": "ACM SIGSOFT Distinguished Paper",
    "conf/esem/FelizardoLDCS24": "Best Paper Award",
    "conf/icsm/WesselSWSG20": "IEEE TCSE Distinguished Paper",
    "conf/icse/TrinkenreichBGS22": "Best Paper Award (SEIS)",
}

HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Publications — Igor Steinmacher</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Source+Serif+4:ital,wght@0,400;0,600;1,400&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="style.css">
</head>
<body>
<header class="site">
  <div class="row">
    <a class="brand" href="index.html">Igor Steinmacher</a>
    <nav>
      <a href="index.html#research">Research</a>
      <a href="publications.html">Publications</a>
      <a href="software.html">Software</a>
      <a href="index.html#students">Students</a>
      <a href="index.html#service">Service</a>
      <a href="index.html#contact">Contact</a>
    </nav>
  </div>
</header>
<main>
<section>
<h2>Publications</h2>
<p class="lead">Peer-reviewed journal and conference papers, generated automatically
from <a href="https://dblp.org/pid/70/3474.html" target="_blank" rel="noopener">DBLP</a>. Preprints live on
<a href="https://arxiv.org/a/steinmacher_i_1" target="_blank" rel="noopener">arXiv</a>.</p>
"""

FOOT = """</section>
</main>
<footer>
  <div class="row">
    <span>© Igor Steinmacher · list auto-generated from DBLP</span>
    <a href="https://github.com/igorsteinmacher/igorsteinmacher.github.io" target="_blank" rel="noopener">source</a>
  </div>
</footer>
</body>
</html>
"""


def fetch_xml() -> ET.Element:
    req = urllib.request.Request(DBLP_URL, headers={"User-Agent": "pubs-builder/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return ET.fromstring(r.read())


def esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main() -> None:
    root = fetch_xml()
    by_year = defaultdict(list)

    for r in root.iter("r"):
        pub = r[0]
        kind = pub.tag  # article | inproceedings | ...
        if kind not in ("article", "inproceedings"):
            continue
        if pub.get("publtype") == "informal":  # skip arXiv/CoRR
            continue

        key = pub.get("key", "")
        year = (pub.findtext("year") or "????").strip()
        title = (pub.findtext("title") or "").strip().rstrip(".")
        authors = ", ".join(a.text or "" for a in pub.findall("author"))
        venue = (pub.findtext("journal") or pub.findtext("booktitle") or "").strip()
        ee = pub.findtext("ee") or ""
        vol = pub.findtext("volume")
        pages = pub.findtext("pages")
        detail = ""
        if kind == "article" and vol:
            detail = f" {vol}" + (f": {pages}" if pages else "")

        label = "journal" if kind == "article" else "conference"
        award = AWARDS.get(key)

        title_html = f'<a href="{esc(ee)}" target="_blank" rel="noopener">{esc(title)}</a>' if ee else esc(title)
        award_html = f'<span class="award">★ {esc(award)}</span>' if award else ""
        by_year[year].append(
            f'<div class="pub">\n'
            f'  <div class="meta"><span>{label}</span>'
            f'<span class="venue">{esc(venue)}{esc(detail)}</span>{award_html}</div>\n'
            f'  <div class="title">{title_html}</div>\n'
            f'  <div class="authors">{esc(authors)}</div>\n'
            f"</div>"
        )

    parts = [HEAD]
    for year in sorted(by_year, reverse=True):
        parts.append(f'<h3 class="year-h">{year}</h3>')
        parts.extend(by_year[year])
    parts.append(FOOT)

    OUT.write_text("\n".join(parts), encoding="utf-8")
    total = sum(len(v) for v in by_year.values())
    print(f"Wrote {OUT} with {total} publications across {len(by_year)} years.")


if __name__ == "__main__":
    main()
