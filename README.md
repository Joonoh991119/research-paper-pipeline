# Research Paper Pipeline

Automated research pipeline: Elicit API search → PDF download → Zotero storage → Embedding memory layer.

## Architecture

```
[Research Question]
        │
        ▼
┌─── Stage 1: Elicit Search ──────┐
│  /api/v1/search → DOI list      │
└──────────┬──────────────────────┘
           │
           ▼
┌─── Stage 2: DOI → Zotero ───────┐
│  PDF download (3-tier fallback)  │
│  → Zotero subcollection         │
└──────────┬──────────────────────┘
           │
     ┌─────┴─────┐
     ▼           ▼
┌─ 3a: Memory ─┐  ┌─ 3b: Reports ──┐
│ Nemotron embed│  │ Elicit Reports │
│ → ChromaDB    │  │ (on-demand)    │
└───────────────┘  └────────────────┘
```

## Setup

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml
# Edit config.yaml with your API keys
```

## Usage

```bash
# Stage 1: Search papers
python stage1_elicit_search.py

# With CLI overrides
python stage1_elicit_search.py --query "Bayesian inference in VWM" --max-results 50
```

## API Keys Required

| Service | Where to get |
|---------|-------------|
| Elicit | elicit.com → Settings → API |
| OpenRouter | openrouter.ai → API Keys |
| Zotero | zotero.org/settings/keys |

## License

MIT
