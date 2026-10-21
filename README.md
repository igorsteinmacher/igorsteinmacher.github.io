# igor.pro.br

Plain HTML site on GitHub Pages. Lists live in `data/*.toml`; scripts fill them
into the pages. Python 3.11+ standard library only — nothing to install.

## How do I update…

| What | Edit | Then |
|---|---|---|
| Students (current / alumni) | `data/students.toml` | `python3 scripts/build_site.py` |
| Software / tools | `data/software.toml` | `python3 scripts/build_site.py` |
| Funded projects | `data/projects.toml` | `python3 scripts/build_site.py` |
| Service & leadership | `data/service.toml` | `python3 scripts/build_site.py` |
| Top navigation (all pages) | `data/site.toml` | `python3 scripts/build_site.py` |
| Paper awards (★ badges) | `data/awards.toml` | `python3 scripts/build_pubs.py` |
| Publications | nothing — pulled from DBLP monthly | or run `python3 scripts/build_pubs.py` |
| Paper PDFs | drop into `publications/` (see `missing_preprints.md` for names) | `python3 scripts/build_pubs.py` |
| About / research / teaching text | `index.html` directly | — |

Skipping the "Then" step is fine: pushing a change under `data/` triggers a
GitHub Action that rebuilds the pages and commits the result, so you can also
edit the TOML files straight from the GitHub web editor.

## How it works

Generated parts of each page are wrapped in marker comments:

```html
<!-- BEGIN:students-current (generated from data/students.toml — edit there) -->
...replaced on every build...
<!-- END:students-current -->
```

Edit anything outside the markers by hand; anything inside is overwritten.
`build_site.py` reports a clear error for a missing required field or a
misspelled field name.

## Preview locally

```bash
python3 -m http.server 8000
```

Then open <http://localhost:8000>.
