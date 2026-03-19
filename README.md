# Meta-Researcher

A personal research automation pipeline that turns a natural-language research question into a curated, searchable paper collection — from semantic search to PDF archival to vector-embedded memory.

> **This tool is intended solely for individual, non-commercial meta-research use.**
> Please respect publisher terms of service, copyright law, and your institution's acceptable-use policies. Downloaded PDFs should be treated as personal research copies under fair use or equivalent provisions in your jurisdiction.

## How It Works

```
                         ┌──────────────────┐
                         │ Research Question │
                         └────────┬─────────┘
                                  │
              ┌───────────────────▼────────────────────┐
              │  Stage 1 — Elicit Semantic Search       │
              │  POST /api/v1/search                    │
              │  → ranked DOI list + metadata            │
              │  → auto-filter JOV abstracts / no-DOI    │
              └───────────────────┬────────────────────┘
                                  │
              ┌───────────────────▼────────────────────┐
              │  Stage 2 — PDF Acquisition + Zotero     │
              │                                         │
              │  6-tier download strategy:               │
              │   1. Unpaywall (all OA locations)        │
              │   2. CrossRef direct PDF links           │
              │   3. EuropePMC (PMCID → render)          │
              │   4. Sci-Hub (sci-hub.kr mirror)         │
              │   5. Publisher URL patterns               │
              │   6. Playwright browser (Cloudflare      │
              │      bypass with institutional login)     │
              │                                         │
              │  → Zotero Web API or SQLite backend      │
              │  → subcollection auto-creation            │
              │  → PDF attachment upload                  │
              └───────────────────┬────────────────────┘
                                  │
                   ┌──────────────┴──────────────┐
                   ▼                              ▼
    ┌──────────────────────┐      ┌──────────────────────┐
    │  Stage 3a — Memory    │      │  Stage 3b — Reports   │
    │                       │      │   (on-demand)         │
    │  PyMuPDF text extract │      │                       │
    │  → chunk (512 words)  │      │  Elicit Reports API   │
    │  → Nemotron embed     │      │  POST /api/v1/reports │
    │  → ChromaDB store     │      │  → structured review  │
    │                       │      │  → markdown export    │
    │  Enables:             │      │                       │
    │  · semantic search    │      │                       │
    │  · paper clustering   │      │                       │
    │  · similarity ranking │      │                       │
    └──────────────────────┘      └──────────────────────┘
```

## Setup

```bash
git clone https://github.com/Joonoh991119/meta-researcher.git
cd meta-researcher

pip install -r requirements.txt

# For browser-based PDF download (optional but recommended)
pip install playwright && playwright install chromium

# Configure API keys
cp config.example.yaml config.yaml
# Edit config.yaml — see "API Keys" section below
```

## Usage

```bash
# Full pipeline: search → download → Zotero → embed
python pipeline.py

# Custom research question
python pipeline.py --query "Bayesian inference in visual working memory" --max-papers 30

# Specific stages only
python pipeline.py --stage 1        # Elicit search
python pipeline.py --stage 2        # PDF + Zotero
python pipeline.py --stage 3a       # Embedding
python pipeline.py --stage 1,2,3a   # All except reports (default)
python pipeline.py --stage all      # Include Elicit report generation

# Preview without executing
python pipeline.py --dry-run
```

### Individual Stage Commands

```bash
# Stage 1 — search with filters
python stage1_elicit_search.py --query "..." --max-results 50 --year-from 2015 --has-pdf

# Stage 2 — process a Stage 1 output file
python stage2_doi2zotero.py --input outputs/stage1_*.json --collection "My_Papers"
python stage2_doi2zotero.py --input stage1.json --no-browser   # skip Playwright fallback
python stage2_doi2zotero.py --input stage1.json --zotero-mode sqlite  # direct DB mode

# Stage 3a — search your embedded papers
python stage3a_embedding.py --search "efficient coding predicts set size effects"
python stage3a_embedding.py --stats   # show memory store statistics

# Stage 3b — generate Elicit analysis report
python stage3b_elicit_reports.py --question "How does divisive normalization explain VWM?"

# Browser-only PDF download (standalone)
python -m utils.browser_download --doi "10.1073/pnas.2021531118" --output ./pdfs/
```

## PDF Download Strategy

The pipeline uses a 6-tier fallback strategy. Each DOI is tried through these sources in order until a valid PDF is obtained:

| Tier | Source | How it works | Best for |
|------|--------|-------------|----------|
| 1 | **Unpaywall** | All OA locations (publisher + PMC repos) | Open Access papers |
| 2 | **CrossRef Links** | PDF URLs embedded in CrossRef metadata | MIT Press, some Springer |
| 3 | **EuropePMC** | PMCID lookup → render endpoint | PMC-indexed papers |
| 4 | **Sci-Hub** | Mirror crawling (sci-hub.kr priority) | Paywalled journals |
| 5 | **Publisher Direct** | DOI redirect → meta tags + URL patterns | When institutional access works |
| 6 | **Browser (Playwright)** | Full browser with cookies/JS | Cloudflare-protected sites |

### Publisher Compatibility

| Publisher | Tiers 1–5 | Tier 6 (Browser) | Notes |
|-----------|-----------|-------------------|-------|
| PLOS, Frontiers, MDPI | ✅ Unpaywall | — | Fully open access |
| bioRxiv, medRxiv | ✅ Unpaywall | — | Preprints |
| MIT Press | ✅ CrossRef link | ✅ | Direct PDF via CrossRef metadata |
| J Neuroscience | ✅ Sci-Hub | ✅ | PMC available for older papers |
| PNAS | ❌ Cloudflare | ✅ fetch in epdf viewer | OA but bot-blocked |
| Royal Society | ❌ Cloudflare | ✅ tokenized PDF link | OA but bot-blocked |
| Elsevier (Neuron, etc.) | ✅ Sci-Hub | ✅ institutional | Requires subscription or Sci-Hub |
| Nature / Springer | ⚠ partial | ✅ institutional | Subscription required |
| IEEE | ❌ | ✅ institutional | Subscription required |
| Wiley (books) | ❌ | ❌ | Not supported |

## Project Structure

```
meta-researcher/
├── pipeline.py                 # Orchestrator (chains all stages)
├── stage1_elicit_search.py     # Elicit API → DOI list + metadata
├── stage2_doi2zotero.py        # DOI → PDF → Zotero (with browser fallback)
├── stage3a_embedding.py        # PDF → text → Nemotron embed → ChromaDB
├── stage3b_elicit_reports.py   # Elicit Reports API (on-demand)
├── utils/
│   ├── pdf_utils.py            # 5-tier automated PDF download
│   ├── zotero_utils.py         # Zotero dual backend (Web API + SQLite)
│   └── browser_download.py     # Playwright browser-based PDF download
├── config.example.yaml         # Configuration template
├── requirements.txt
└── README.md
```

## API Keys

| Service | Where to get | Required |
|---------|-------------|----------|
| **Elicit** | [elicit.com](https://elicit.com) → Settings → API (Pro plan) | Yes |
| **OpenRouter** | [openrouter.ai](https://openrouter.ai) → API Keys | For Stage 3a |
| **Zotero** | [zotero.org/settings/keys](https://www.zotero.org/settings/keys) | For Stage 2 |

CrossRef and Unpaywall require only a contact email (no API key). Playwright requires a Chromium install (`playwright install chromium`).

## Zotero Integration

The pipeline supports two Zotero backends, selectable via `--zotero-mode`:

- **`api`** (default, recommended): Uses the Zotero Web API. Zotero can remain open. Syncs automatically.
- **`sqlite`**: Directly manipulates the local Zotero SQLite database. Faster for bulk imports but requires Zotero to be closed and carries sync-conflict risk.

Both backends support automatic subcollection creation, PDF attachment upload, and duplicate detection.

## Disclaimer

This project is a personal research tool built for academic meta-research workflows. It is shared as-is for educational and research purposes.

- **Do not use this tool for bulk redistribution of copyrighted material.**
- PDF downloads are intended as personal research copies, analogous to manually saving papers from your browser.
- Sci-Hub access may not be legal in all jurisdictions. The pipeline places Sci-Hub as a lower-priority fallback; open-access and legitimate sources are always tried first.
- Respect publisher rate limits. The pipeline includes configurable delays between requests.
- If you are affiliated with a research institution, use your institutional credentials (via the Playwright browser tier) for the most reliable and legally sound access.

## License

MIT
