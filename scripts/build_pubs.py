#!/usr/bin/env python3
"""
build_pubs.py — regenerate publications.html from DBLP, with arXiv preprint links.

Usage:
    python scripts/build_pubs.py               # preprints via DBLP CoRR + open-access via Unpaywall
    python scripts/build_pubs.py --deep        # also query the arXiv API for unmatched papers (~3s/paper)
    python scripts/build_pubs.py --no-oa       # skip the Unpaywall open-access check
    python scripts/build_pubs.py --refresh-oa  # ignore the OA cache and re-query everything

Outputs:
    publications.html      — papers get an [open access] badge (published version is OA per
                             Unpaywall) or, failing that, a [preprint PDF] arXiv link
    missing_preprints.md   — papers that are neither OA nor on arXiv, so you can upload them
    oa_cache.json          — cached Unpaywall responses (committed, keeps monthly runs fast)

DBLP author names are cleaned of disambiguation suffixes (e.g. "Igor Wiese 0001").

How preprint matching works: DBLP lists your arXiv submissions as separate
"informal" CoRR entries. We normalize titles and match them against the formal
journal/conference versions. --deep additionally searches the arXiv API by
title for anything still unmatched (rate-limited per arXiv's ToS).

No dependencies beyond the Python standard library.
"""

import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

DBLP_PID = "70/3474"
DBLP_URL = f"https://dblp.org/pid/{DBLP_PID}.xml"
ROOT = Path(__file__).resolve().parent.parent
OUT_HTML = ROOT / "publications.html"
OUT_MD = ROOT / "missing_preprints.md"
OA_CACHE = ROOT / "oa_cache.json"
PUB_DIR = ROOT / "publications"  # drop self-hosted PDFs here, named <dblp-key-with-dashes>.pdf
UNPAYWALL_EMAIL = "igor.steinmacher@nau.edu"  # required by the Unpaywall API

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
      <a href="index.html#projects">Projects</a>
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
from <a href="https://dblp.org/pid/70/3474.html" target="_blank" rel="noopener">DBLP</a>.
Papers with an open preprint carry a [preprint PDF] link.</p>
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

ARXIV_ID_RE = re.compile(r"(?:arxiv\.org/(?:abs|pdf)/|arXiv\.)(\d{4}\.\d{4,5})", re.I)
AUTHOR_SUFFIX_RE = re.compile(r"\s+\d{4}$")  # DBLP disambiguation: "Igor Wiese 0001"
DOI_RE = re.compile(r"doi\.org/(10\.[^\s\"]+)", re.I)


def key_slug(key: str) -> str:
    """DBLP key -> safe filename: conf/icse/Smith16 -> conf-icse-Smith16."""
    return key.replace("/", "-")


def clean_author(name: str) -> str:
    """Strip DBLP's numeric disambiguation suffix from an author name."""
    return AUTHOR_SUFFIX_RE.sub("", (name or "").strip())


def extract_doi(pub) -> str | None:
    for ee in pub.findall("ee"):
        m = DOI_RE.search(ee.text or "")
        if m:
            return m.group(1).rstrip(".")
    return None


def unpaywall_lookup(doi: str) -> dict:
    """Query Unpaywall for a DOI. Returns {"is_oa": bool, "oa_url": str|None}."""
    url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={UNPAYWALL_EMAIL}"
    try:
        import json as _json
        data = _json.loads(fetch(url))
        loc = data.get("best_oa_location") or {}
        return {"is_oa": bool(data.get("is_oa")),
                "oa_url": loc.get("url_for_pdf") or loc.get("url")}
    except Exception:
        return {"is_oa": False, "oa_url": None, "error": True}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "pubs-builder/2.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def norm_title(t: str) -> str:
    """Normalize a title for fuzzy matching: lowercase, alphanumerics only."""
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


def esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def arxiv_pdf_url(any_url_or_id: str) -> str | None:
    m = ARXIV_ID_RE.search(any_url_or_id or "")
    return f"https://arxiv.org/pdf/{m.group(1)}" if m else None


def arxiv_api_lookup(title: str) -> str | None:
    """Search the arXiv API by exact title. Returns PDF URL or None."""
    q = urllib.parse.quote(f'ti:"{title}"')
    url = f"https://export.arxiv.org/api/query?search_query={q}&max_results=3"
    try:
        root = ET.fromstring(fetch(url))
    except Exception:
        return None
    ns = {"a": "http://www.w3.org/2005/Atom"}
    want = norm_title(title)
    for entry in root.findall("a:entry", ns):
        found = entry.findtext("a:title", default="", namespaces=ns)
        if norm_title(found) == want:
            eid = entry.findtext("a:id", default="", namespaces=ns)
            pdf = arxiv_pdf_url(eid)
            if pdf:
                return pdf
    return None


def main() -> None:
    import json
    deep = "--deep" in sys.argv
    use_oa = "--no-oa" not in sys.argv
    oa_cache: dict = {}
    if use_oa and OA_CACHE.exists() and "--refresh-oa" not in sys.argv:
        try:
            oa_cache = json.loads(OA_CACHE.read_text())
        except Exception:
            oa_cache = {}
    root = ET.fromstring(fetch(DBLP_URL))

    # Pass 1: harvest arXiv preprints from DBLP's informal CoRR entries
    preprints: dict[str, str] = {}  # normalized title -> arXiv PDF URL
    for r in root.iter("r"):
        pub = r[0]
        if pub.get("publtype") != "informal":
            continue
        title = (pub.findtext("title") or "").strip().rstrip(".")
        for ee in pub.findall("ee"):
            pdf = arxiv_pdf_url(ee.text or "")
            if pdf:
                preprints[norm_title(title)] = pdf
                break

    # Pass 2: formal papers
    by_year: dict[str, list[str]] = defaultdict(list)
    missing: dict[str, list[tuple[str, str, str]]] = defaultdict(list)  # year -> (title, venue, authors)
    n_linked = 0

    for r in root.iter("r"):
        pub = r[0]
        kind = pub.tag
        if kind not in ("article", "inproceedings"):
            continue
        if pub.get("publtype") == "informal":
            continue

        key = pub.get("key", "")
        year = (pub.findtext("year") or "????").strip()
        title = (pub.findtext("title") or "").strip().rstrip(".")
        authors = ", ".join(clean_author(a.text or "") for a in pub.findall("author"))
        venue = (pub.findtext("journal") or pub.findtext("booktitle") or "").strip()
        ee = pub.findtext("ee") or ""
        vol = pub.findtext("volume")
        pages = pub.findtext("pages")
        detail = ""
        if kind == "article" and vol:
            detail = f" {vol}" + (f": {pages}" if pages else "")

        # open-access first (Unpaywall by DOI), then arXiv preprint
        doi = extract_doi(pub)
        oa = None
        if use_oa and doi:
            if doi in oa_cache and not oa_cache[doi].get("error"):
                oa = oa_cache[doi]
            else:
                oa = unpaywall_lookup(doi)
                oa_cache[doi] = oa
                time.sleep(0.15)  # be polite to the API

        pdf = preprints.get(norm_title(title))
        if pdf is None and deep and not (oa and oa.get("is_oa")):
            time.sleep(3)  # arXiv API rate-limit etiquette
            pdf = arxiv_api_lookup(title)

        local_pdf = PUB_DIR / f"{key_slug(key)}.pdf"
        if oa and oa.get("is_oa"):
            n_linked += 1
            link = oa.get("oa_url") or f"https://doi.org/{doi}"
            badge = (f'<a class="preprint" href="{esc(link)}" target="_blank" '
                     f'rel="noopener">[open access]</a>')
        elif pdf:
            n_linked += 1
            badge = (f'<a class="preprint" href="{esc(pdf)}" target="_blank" '
                     f'rel="noopener">[preprint PDF]</a>')
        elif local_pdf.exists():
            n_linked += 1
            badge = (f'<a class="preprint" href="publications/{esc(local_pdf.name)}" '
                     f'target="_blank" rel="noopener">[PDF]</a>')
        else:
            badge = ""
            missing[year].append((title, venue, authors, key_slug(key)))

        label = "journal" if kind == "article" else "conference"
        award = AWARDS.get(key)
        title_html = (f'<a href="{esc(ee)}" target="_blank" rel="noopener">{esc(title)}</a>'
                      if ee else esc(title))
        award_html = f'<span class="award">★ {esc(award)}</span>' if award else ""

        by_year[year].append(
            f'<div class="pub">\n'
            f'  <div class="meta"><span>{label}</span>'
            f'<span class="venue">{esc(venue)}{esc(detail)}</span>{award_html}</div>\n'
            f'  <div class="title">{title_html}</div>\n'
            f'  <div class="authors">{esc(authors)}'
            + (f" · {badge}" if badge else "") + "</div>\n"
            f"</div>"
        )

    # Write HTML
    parts = [HEAD]
    for year in sorted(by_year, reverse=True):
        parts.append(f'<h3 class="year-h">{year}</h3>')
        parts.extend(by_year[year])
    parts.append(FOOT)
    OUT_HTML.write_text("\n".join(parts), encoding="utf-8")

    # Write missing-preprints checklist
    n_missing = sum(len(v) for v in missing.values())
    md = ["# Papers that are not open access and have no arXiv preprint",
          "",
          f"Generated by `scripts/build_pubs.py`. {n_missing} of "
          f"{n_missing + n_linked} papers have no open version.",
          "",
          "For each paper, either upload it to arXiv OR drop the author-accepted",
          "manuscript PDF into the `publications/` folder using the exact filename",
          "shown — the next script run will pick it up and link it automatically.",
          "(Check the publisher's self-archiving policy; most ACM/IEEE venues allow",
          "hosting the accepted manuscript on a personal site.)",
          ""]
    for year in sorted(missing, reverse=True):
        md.append(f"## {year}")
        md.append("")
        for title, venue, authors, slug in missing[year]:
            md.append(f"- [ ] **{title}** — *{venue}* — {authors}  ")
            md.append(f"      drop PDF at: `publications/{slug}.pdf`")
        md.append("")
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    if use_oa:
        OA_CACHE.write_text(json.dumps(oa_cache, indent=0, sort_keys=True))
    total = sum(len(v) for v in by_year.values())
    print(f"Wrote {OUT_HTML}: {total} papers, {n_linked} with open-access/preprint links.")
    print(f"Wrote {OUT_MD}: {n_missing} papers still need preprints.")
    if not deep and n_missing:
        print("Tip: run with --deep to also search the arXiv API directly.")


if __name__ == "__main__":
    main()
