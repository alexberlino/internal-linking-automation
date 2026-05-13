# Internal Linking Optimization

Python pipeline that audits a website's existing internal links and proposes new, high-confidence link opportunities from blog content to priority pages.

The repository contains processing logic only. Client configs, input data, and generated reports are kept out of version control.

---

## What It Does

Given a client's blog content, page metadata, and existing internal links, the pipeline:

1. **Audits** current internal linking — inbound link counts per page, generic anchors, sitewide-only anchors, gaps on priority pages.
2. **Finds opportunities** — matches blog sentences to target pages using rule-based keyword matches plus semantic similarity (Sentence-Transformers), scores each suggestion, picks an anchor that respects per-client anchor quality rules, and caps suggestions per source and per target.
3. **Exports** a multi-sheet Excel report with the audit, the ranked opportunities, the proposed anchor for each link, and the source paragraph where it should be inserted.

---

## Repository Layout

```
.
├── main.py                          # CLI entry point
├── phases/
│   ├── client_config.py             # Loads settings.json + rules.csv per client
│   ├── phase_2_blog_loader.py       # Load blog content
│   ├── phase_2_metadata_loader.py   # Load page metadata
│   ├── phase_2_links_loader.py      # Load existing internal links
│   ├── phase_3_audit.py             # Audit current internal linking
│   ├── phase_4_opportunities.py     # Generate ranked opportunities
│   └── phase_5_reporting.py         # Build the Excel report
├── config/                          # Per-client configs (gitignored)
│   └── <client>/
│       ├── settings.json
│       └── rules.csv
├── data/                            # Per-client data (gitignored)
│   └── <client>/
│       ├── input/
│       │   ├── blog_content.csv
│       │   ├── page_metadata.csv
│       │   └── internal_links.csv
│       └── output/
│           └── internal_linking_report.xlsx
├── verify_refactor.py
└── README.md
```

Both `config/` and `data/` are gitignored — client-specific files live only on disk.

---

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pandas openpyxl scikit-learn sentence-transformers
```

The first run downloads the `all-MiniLM-L6-v2` Sentence-Transformers model.

---

## Running

```bash
python main.py --client <client_name>
```

`<client_name>` must match a folder under `config/` (e.g. `config/proofserve/`). The pipeline expects matching folders under `data/<client_name>/input/` and writes the report to `data/<client_name>/output/internal_linking_report.xlsx`.

Example:

```bash
python main.py --client proofserve
```

A structured summary (input counts, audit per priority tier, opportunity counts by tier and confidence, top targets, runtime) is printed at the end of each run.

---

## Per-Client Configuration

Each client folder under `config/<client>/` contains two files.

### `settings.json`

| Key | Type | Purpose |
| --- | --- | --- |
| `homepage_url` | str | Used for the brand-anchor rule. |
| `blog_paths` | list[str] | Path prefixes that identify blog sources (e.g. `/blog`, `/learn`). |
| `languages` | list[str] | Supported language codes. |
| `default_language` | str | Fallback when a URL has no language marker. |
| `language_url_patterns` | dict | Substring patterns mapping URLs to languages. |
| `brand_pattern` | str (regex) | Matches bare-brand anchors so they can be reserved for the homepage. |
| `sitewide_anchors` | list[str] | Anchors treated as navigational (footer/header/CTAs). |
| `sitewide_min_repeats` | int | Repeat count above which an anchor is treated as sitewide. |
| `anchor` | dict | Anchor selection + quality rules (overlap method, min words, stopwords, brand block, min char length). |
| `confidence` | dict | Penalties, tier thresholds (`strong`/`moderate`/`weak`), `discard_below`. |
| `similarity` | dict | `page_similarity_floor`, `sentence_similarity_floor`. |
| `volume` | dict | `max_targets_per_source`, plus `inbound_link_caps` that throttle suggestions for already-linked targets. |
| `deduplication` | dict | Per source-target pair dedup (`keep: highest_confidence`). |

Any block left out falls back to the defaults defined in `phases/client_config.py`.

### `rules.csv`

| Column | Required | Notes |
| --- | --- | --- |
| `target_url` | yes | The page that should receive links. |
| `keywords` | yes | Pipe-separated phrases, or a raw regex prefixed with `regex:`. Phrases are auto-wrapped in word boundaries with tolerant whitespace. |
| `label` | no | Human-readable rule name. Defaults to `target_url`. |
| `language` | no | Must be one of `languages` in `settings.json`. Defaults to `default_language`. |

---

## Input Files (`data/<client>/input/`)

- **`blog_content.csv`** — blog URLs and their body text. Source of opportunities.
- **`page_metadata.csv`** — every URL on the site with a priority `importance` (`A`/`B`/`C`) and any other metadata used by the audit.
- **`internal_links.csv`** — current internal link graph (source URL, target URL, anchor).

The pipeline fails fast with a clear message if any of these files are missing.

---

## Output (`data/<client>/output/internal_linking_report.xlsx`)

Multi-sheet Excel workbook covering:

- the audit per priority tier,
- the ranked opportunities (with confidence tier, chosen anchor, source paragraph),
- supporting views of the existing link graph.

---

## Data Handling

- `config/` and `data/` are gitignored — no client URLs, content, rules, or reports are ever committed.
- The repo only ships processing logic, defaults, and documentation.

---

## Version Control Rules

Tracked:
- Python source files (`main.py`, `phases/`)
- Documentation
- `.gitignore`

Ignored:
- `config/` (client-specific rules and settings)
- `data/` (inputs and outputs)
- Virtual environments, caches, OS files

This repository is for internal technical use. Client configs and data are managed outside of version control.
