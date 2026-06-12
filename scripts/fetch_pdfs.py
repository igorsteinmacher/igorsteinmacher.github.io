#!/usr/bin/env python3
"""
fetch_pdfs.py — populate publications/ with locally hosted PDFs.

Usage:
    python scripts/fetch_pdfs.py            # download arXiv preprints for all papers
    python scripts/fetch_pdfs.py --oa       # also download CC-licensed open-access PDFs
    python scripts/fetch_pdfs.py --dry-run  # report what would happen, download nothing

What it does:
 1. Fetches your DBLP record and computes the canonical filename for every
    formal paper: publications/<dblp-key-with-dashes>.pdf
 2. Downloads the arXiv preprint PDF for every paper that has one and no
    local copy yet (polite 3s delay between downloads).
 3. With --oa: downloads the publisher's PDF for papers that are open access
    with a Creative Commons license (per Unpaywall / oa_cache.json). Papers
    that are merely free-to-read without a license are NOT downloaded —
    rehosting those is not clearly permitted.
 4. Scans publications/ for PDFs whose names don't match any paper ("orphans",
    e.g. files copied from your old site) and suggests `git mv` renames by
    fuzzy title matching. Suggestions go to pdf_report.md — review before
    running them; nothing is renamed automatically.

After running, run scripts/build_pubs.py to regenerate the page: papers with
a local PDF link to YOUR copy first.
"""

import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

DBLP_PID = "70/3474"
DBLP_URL = f"https://dblp.org/pid/{DBLP_PID}.xml"
ROOT = Path(__file__).resolve().parent.parent
PUB_DIR = ROOT / "publications"
OA_CACHE = ROOT / "oa_cache.json"
REPORT = ROOT / "pdf_report.md"
UNPAYWALL_EMAIL = "igor.steinmacher@nau.edu"

ARXIV_ID_RE = re.compile(r"(?:arxiv\.org/(?:abs|pdf)/|arXiv\.)(\d{4}\.\d{4,5})", re.I)
STOPWORDS = {"a", "an", "the", "of", "in", "on", "for", "to", "and", "with", "at"}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "pdf-fetcher/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


def key_slug(key: str) -> str:
    return key.replace("/", "-")


def title_tokens(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOPWORDS and len(w) > 2}


def arxiv_pdf_url(s: str) -> str | None:
    m = ARXIV_ID_RE.search(s or "")
    return f"https://arxiv.org/pdf/{m.group(1)}" if m else None


def is_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"


def download(url: str, dest: Path, dry: bool) -> str:
    if dry:
        return "would download"
    try:
        data = fetch(url)
        if not is_pdf(data):
            return "SKIPPED: response was not a PDF"
        dest.write_bytes(data)
        return f"downloaded ({len(data)//1024} KB)"
    except Exception as e:
        return f"FAILED: {type(e).__name__}"


def main() -> None:
    dry = "--dry-run" in sys.argv
    want_oa = "--oa" in sys.argv
    PUB_DIR.mkdir(exist_ok=True)

    oa_cache = {}
    if OA_CACHE.exists():
        try:
            oa_cache = json.loads(OA_CACHE.read_text())
        except Exception:
            pass

    root = ET.fromstring(fetch(DBLP_URL))

    # arXiv preprints from informal CoRR entries
    preprints: dict[str, str] = {}
    for r in root.iter("r"):
        pub = r[0]
        if pub.get("publtype") != "informal":
            continue
        t = (pub.findtext("title") or "").strip().rstrip(".")
        for ee in pub.findall("ee"):
            pdf = arxiv_pdf_url(ee.text or "")
            if pdf:
                preprints[norm_title(t)] = pdf
                break

    # formal papers
    papers = []  # (slug, title, doi, arxiv_pdf)
    for r in root.iter("r"):
        pub = r[0]
        if pub.tag not in ("article", "inproceedings") or pub.get("publtype") == "informal":
            continue
        title = (pub.findtext("title") or "").strip().rstrip(".")
        doi = None
        for ee in pub.findall("ee"):
            m = re.search(r"doi\.org/(10\.[^\s\"]+)", ee.text or "", re.I)
            if m:
                doi = m.group(1).rstrip(".")
                break
        papers.append((key_slug(pub.get("key", "")), title,
                       doi, preprints.get(norm_title(title))))

    lines = ["# PDF fetch report", ""]
    n_dl = n_have = n_none = 0

    # Phase 1: downloads
    lines.append("## Downloads")
    lines.append("")
    for slug, title, doi, arx in papers:
        dest = PUB_DIR / f"{slug}.pdf"
        if dest.exists():
            n_have += 1
            continue
        src_url, label = None, None
        if arx:
            src_url, label = arx, "arXiv"
        elif want_oa and doi:
            oa = oa_cache.get(doi, {})
            lic = ((oa.get("license") or "") if isinstance(oa, dict) else "")
            url = oa.get("oa_url") if isinstance(oa, dict) else None
            # only CC-licensed publisher PDFs; cache may lack license info -> query live
            if oa.get("is_oa") and url:
                if not lic:
                    try:
                        data = json.loads(fetch(
                            f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}"
                            f"?email={UNPAYWALL_EMAIL}"))
                        loc = data.get("best_oa_location") or {}
                        lic = loc.get("license") or ""
                        url = loc.get("url_for_pdf") or url
                        time.sleep(0.15)
                    except Exception:
                        lic = ""
                if lic.startswith("cc"):
                    src_url, label = url, f"publisher OA ({lic})"
        if src_url:
            result = download(src_url, dest, dry)
            if result.startswith("downloaded") or result == "would download":
                n_dl += 1
            lines.append(f"- `{dest.name}` ← {label}: {result}")
            if not dry:
                time.sleep(3)  # politeness between PDF downloads
        else:
            n_none += 1

    # Phase 2: orphan scan + rename suggestions
    expected = {f"{slug}.pdf" for slug, *_ in papers}
    orphans = [p for p in sorted(PUB_DIR.glob("*.pdf")) if p.name not in expected]
    lines += ["", "## Orphan files (names don't match any DBLP paper)", ""]
    if not orphans:
        lines.append("None — every PDF in publications/ matches a paper. ✅")
    confident, review = [], []
    for orphan in orphans:
        otokens = title_tokens(orphan.stem)
        scored = []
        for slug, title, *_ in papers:
            tt = title_tokens(title)
            if not tt or not otokens:
                continue
            denom = min(len(tt), len(otokens)) or 1
            scored.append((len(otokens & tt) / denom, slug, title))
        scored.sort(reverse=True)
        top = scored[:3]
        best_score = top[0][0] if top else 0.0
        second = top[1][0] if len(top) > 1 else 0.0
        if top and best_score >= 0.6 and best_score - second >= 0.2:
            _, slug, title = top[0]
            target = f"{slug}.pdf"
            mark = " ⚠️ (target exists — duplicate?)" if (PUB_DIR / target).exists() else ""
            confident.append(
                f"- `{orphan.name}` → **{title}**{mark}  \n"
                f"      `git mv 'publications/{orphan.name}' 'publications/{target}'`")
        else:
            entry = [f"- `{orphan.name}` — candidates:"]
            if not top:
                entry.append("    - (none — filename shares no words with any paper title)")
            for score, slug, title in top:
                entry.append(f"    - [ ] {score:.0%} match: **{title}** → "
                             f"`git mv 'publications/{orphan.name}' 'publications/{slug}.pdf'`")
            review.append("\n".join(entry))

    lines += ["", "### Confident matches (review, then run the commands)", ""]
    lines += confident or ["None."]
    lines += ["", "### Needs your judgment (ambiguous or weak matches)", ""]
    lines += review or ["None."]

    lines += ["", "## Summary", "",
              f"- already in place: {n_have}",
              f"- downloaded{' (dry run)' if dry else ''}: {n_dl}",
              f"- no source found (not on arXiv{', no CC-licensed OA' if want_oa else ''}): {n_none}",
              f"- orphan files: {len(orphans)}",
              "",
              "Next: review the rename suggestions above, run them, then "
              "`python scripts/build_pubs.py` to regenerate the page."]

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report: {REPORT}")
    print(f"in place: {n_have} | downloaded: {n_dl} | no source: {n_none} | orphans: {len(orphans)}")


if __name__ == "__main__":
    main()
