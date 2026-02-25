# CaseStack

Turn any document dump into a searchable evidence database.

Built by the team behind [epstein-data.com](https://epstein-data.com) — where we turned the 218GB DOJ Epstein file release into a fully searchable, entity-linked, citation-backed research database.

## Install

```bash
pip install -e ".[pymupdf,nlp]"
python -m spacy download en_core_web_sm
```

## Quickstart

```bash
# Point at a folder of PDFs, get a searchable database
casestack ingest ./my-documents --name "City Council FOIA"

# Serve it locally
casestack serve

# Check status
casestack status
```

## Configuration

Copy `case.yaml.example` to `case.yaml` and customize. See the example for all options.

## How It Works

1. **OCR** — Extract text from PDFs (Docling or PyMuPDF)
2. **Entity Extraction** — Find people, orgs, dates, money, phone numbers (spaCy NER)
3. **Deduplication** — Identify duplicate documents (content hash + fuzzy matching)
4. **Export** — SQLite database with FTS5 full-text search
5. **Serve** — Datasette web interface with search, filtering, and AI Q&A

## Case Presets

Pre-configured case files for known document sets:

- `presets/epstein.yaml` — DOJ Jeffrey Epstein File Release (218GB, 1.38M PDFs)
