# CaseStack Frontend Design

**Date:** 2026-03-01
**Status:** Approved
**Goal:** Transform CaseStack from a CLI-only tool into a local-first web application with a React SPA frontend, replacing Datasette as the serving layer.

---

## Vision

CaseStack becomes a local-first app like Calibre or Plex. The primary interface is a web UI that a layperson can use. The CLI becomes a secondary/power-user path.

```
pip install casestack
casestack start          # browser opens to localhost:8000
                         # wizard walks through everything
```

A user with no technical background should be able to: open a terminal, paste a few commands from the README, and have a fully functional document research platform running in their browser.

---

## Architecture

### Single Process: FastAPI + React SPA

```
┌─────────────────────────────────────────────┐
│  FastAPI (Python, uvicorn)                   │
│  ├── /api/cases          (CRUD cases)        │
│  ├── /api/ingest         (start/stop/status) │
│  ├── /api/pipeline       (manifest + config) │
│  ├── /api/search         (FTS5 queries)      │
│  ├── /api/entities       (entity registry)   │
│  ├── /api/images         (gallery + detail)  │
│  ├── /api/transcripts    (media + text)      │
│  ├── /api/ask            (AI assistant, SSE) │
│  ├── /ws/ingest          (WebSocket progress)│
│  └── /*                  (serves React SPA)  │
│                                              │
│  SQLite: per-case DBs + app state DB         │
└─────────────────────────────────────────────┘
```

### Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture | FastAPI + React SPA, single process | One port, WebSocket support, full API control |
| Shipping | Pre-built frontend bundled in pip package | `pip install casestack` gets everything, no node needed on user machine |
| Data layer | Direct SQLite queries, no Datasette | Full control over endpoints, caching, cross-table joins. Datasette kept as optional power-user tool via `casestack serve-datasette` |
| Frontend | React + Vite, TypeScript | Largest ecosystem, component libraries, well-understood |
| Real-time | WebSocket for ingest progress, SSE for AI streaming | WebSocket for bidirectional (pause/cancel ingest), SSE for unidirectional AI token stream |
| Visualization | d3-force for entity graph, Leaflet+TopoJSON for heatmap | Both bundled in the build, not CDN-loaded |
| State | `~/.casestack/casestack.db` for app state | Separate from per-case data DBs. Tracks registered cases, ingest runs, AI conversations |
| Design | Neutral professional palette, Inter font, information-dense | Case-agnostic. Optional per-case accent color in config (stretch goal) |

### What Replaces Datasette

Datasette currently provides: (1) the query engine, (2) the JSON API, (3) the HTML UI.

- **(1) Query engine** — replaced by direct SQLite queries in FastAPI route handlers. We already know the schema; we don't need Datasette's generic introspection.
- **(2) JSON API** — replaced by purpose-built FastAPI endpoints. Better for the SPA (typed responses, pagination, unified search).
- **(3) HTML UI** — replaced entirely by the React SPA.
- **Power users** who want raw SQL access can still run `casestack serve-datasette --case case.yaml` which launches Datasette on the case DB directly (the existing `serve` command, renamed).

---

## User Flows

### Flow 1: First Run (New User)

```
pip install casestack → casestack start → browser opens → no cases → "Create your first case"
```

### Flow 2: New Case Wizard (4 steps)

**Step 1: Point to documents**
- User provides a directory path (browse button or paste)
- Backend scans the directory, returns file type counts:
  - "Found: 847 PDFs, 23 media files (mp4, m4a, wav), 5 text files, 1 PNG"
- This scan drives the smart defaults in Step 3

**Step 2: Name the case**
- Name field (free text): "City Council FOIA Response"
- Slug field (auto-derived, editable): "city-council-foia"
- Description field (optional)

**Step 3: Configure pipeline**
- Each pipeline step renders as a toggle card, auto-generated from `get_manifest()`
- **Smart defaults based on Step 1 scan:**
  - No media files found → Transcription toggle OFF and dimmed
  - No PDFs found → OCR toggle OFF
  - Steps with `requires_extra` that aren't installed → shown with install instruction, toggle disabled
- **Dependency enforcement:** `depends_on` from the manifest grays out steps whose dependencies are disabled. Disabling OCR dims page_captions, image_extraction, image_analysis, entities, dedup.
- Each card shows expandable config knobs (model selection, worker count, thresholds) pulled from `config_keys` in the manifest
- Toggle card layout:
  ```
  ┌─────────────────────────────────────┐
  │ [ON/OFF] PDF OCR                    │
  │ Extract text from 847 PDFs          │
  │ ▸ Advanced: backend, workers        │
  ├─────────────────────────────────────┤
  │ [ON/OFF] Transcription              │
  │ Transcribe 23 media files           │
  │ ▸ Advanced: whisper model, device   │
  ├─────────────────────────────────────┤
  │ [OFF] Semantic Embeddings           │
  │ ⚠ requires: pip install             │
  │   'casestack[embeddings]'           │
  └─────────────────────────────────────┘
  ```

**Step 4: Review & Start**
- Summary: case name, document counts by type, enabled steps listed
- [Start Ingest] button
- Redirects to case dashboard with live progress

### Flow 3: Case Dashboard

The dashboard is the hub for a case. It has two modes:

**During ingest (live progress via WebSocket):**
```
Pipeline Progress
  ✅ OCR         847/847  ██████████ 100%
  🔄 Transcribe  14/23   ██████░░░░  61%
  ⏳ Captions     —       ░░░░░░░░░░  0%
  ⏳ Entities     —       ░░░░░░░░░░  0%
  ⏳ Export       —       ░░░░░░░░░░  0%

Stats (update live)
  847 docs · 12,400 pages · 142 images · 23 transcripts

Recent Activity (log stream)
  14:32 — Transcribed EFTA00064598.mp4
  14:31 — Captioned 12 image-heavy pages
  14:28 — OCR complete (847 documents)
```

**After ingest (research mode):**
- Progress section collapses to a summary line: "Ingested 847 docs, 12.4k pages — completed 2h ago"
- Stats cards are prominent
- Quick action buttons: Search, Entities, Images, Transcripts, Map, Ask AI
- Each button is only enabled if the relevant pipeline step ran (no Images button if image_extraction was disabled)

### Flow 4: Returning User (Case Selector)

```
casestack start → browser opens →

Your Cases
┌─────────────────────────────────────────┐
│ City Council FOIA    847 docs   1.2 GB  │
│ Last opened 2h ago             [Open →] │
├─────────────────────────────────────────┤
│ Epstein FOIA         531k docs  48 GB   │
│ Ingesting... 62%               [Open →] │
├─────────────────────────────────────────┤
│ Whistleblower Docs   23 docs    45 MB   │
│ Last opened 3 days ago         [Open →] │
└─────────────────────────────────────────┘
                              [+ New Case]
```

Cases that are mid-ingest show progress inline. Clicking opens the case dashboard.

---

## Pages & Features

### Search (the core research tool)

**URL:** `/case/:slug/search?q=...&type=...`

**Unified search** — one query hits pages (FTS5), transcripts (FTS5), image descriptions (LIKE/FTS), entity names. Results interleaved by relevance, not siloed.

**Result types** with visual indicators:
- 📄 **Page result** — document title, page number, snippet with `<mark>` highlighting, char count. Click "View page" to expand inline document reader (full page text, prev/next navigation, no page load).
- 🎙 **Transcript result** — media filename, timestamp, snippet. "Play from here" opens audio/video player seeked to that moment.
- 🖼 **Image result** — thumbnail, AI description snippet, source document + page. Click opens lightbox.
- 👤 **Entity result** — entity name, type badge, mention count. Click navigates to entity detail.

**Filter sidebar** (collapsible):
- Result type checkboxes (Pages, Transcripts, Images, Entities)
- Date range (if dates were extracted)
- Entity filter (type-ahead, filter results to docs mentioning a specific entity)
- Document type (PDF, Audio, Video, Text)

**Bates quick lookup:** if query matches a bates number pattern (configured via `bates_prefixes` in case config), the first result is a document card with metadata.

**API:** `GET /api/cases/:slug/search?q=...&type=pages,transcripts&offset=0&limit=50`
Returns typed results array with relevance scores, snippets, and metadata.

### Entity Network Viewer

**URL:** `/case/:slug/entities`

Two views:

**Directory view (default):** Paginated, filterable list of entities. Filter by type (Person, Org, Location, Date, Money). Search by name. Each card shows entity name, type badge, document mention count, connection count.

**Graph view (toggle):** Interactive force-directed graph using d3-force.
- Nodes = entities, colored by type
- Edges = relationships (traveled_with, employed_by, associated, etc.)
- Edge thickness = weight (number of co-occurrences)
- Click node to select → sidebar shows entity detail
- Drag to reposition, scroll to zoom, standard graph interactions

**Entity detail** (sidebar or dedicated page):
- Name, type, aliases
- Connection list grouped by relationship type, with weight and document citations
- Documents mentioning this entity (paginated)
- [Search all documents →] link pre-fills the search page

**Data source:**
- If knowledge_graph step ran: full graph from `knowledge-graph.json` (nodes + edges with relationships)
- If only entity extraction ran: directory of named entities from documents (no relationship edges, graph view shows unconnected nodes)
- If neither ran: page not available (hidden from nav)

**API:**
- `GET /api/cases/:slug/entities?type=PERSON&q=smith&offset=0&limit=50`
- `GET /api/cases/:slug/entities/:id` (detail + connections)
- `GET /api/cases/:slug/entities/graph` (full graph JSON for d3)

### Image Gallery

**URL:** `/case/:slug/images`

**Grid layout** of image thumbnails, sorted by document order.

**Filters:**
- Has description / No description
- Minimum size
- Source document

**Lightbox** on click:
- Full-size image
- AI description (from image_analysis step)
- Source: document ID, page number
- [View in document context →] links to document reader at that page

**Data:**
- Image metadata from `extracted_images` table in case DB
- Actual image files served statically from `output/{slug}/images/{doc_id}/`
- Only available if image_extraction step ran

**API:**
- `GET /api/cases/:slug/images?has_description=true&offset=0&limit=50`
- `GET /api/cases/:slug/images/:id` (metadata + description)
- Static: `/api/cases/:slug/images/file/{doc_id}/{filename}` (actual image)

### Transcript Browser

**URL:** `/case/:slug/transcripts`

**Listing:** All transcribed media files with duration, format, word count.

**Transcript detail:**
- HTML5 `<audio>` or `<video>` element (files served from documents directory, no transcoding)
- Timestamped segments below the player
- Each segment is a clickable row → seeks the player to that timestamp
- Search within transcript (highlights matching segments)
- Silence detection markers shown as gray gaps in the timeline (from transcription processor)

**Data:**
- Transcript metadata from `transcripts` table in case DB
- Segment-level data from transcription processor output (JSON in output dir)
- Media files served from `documents_dir`
- Only available if transcription step ran

**API:**
- `GET /api/cases/:slug/transcripts`
- `GET /api/cases/:slug/transcripts/:id` (full transcript with segments)
- Static: `/api/cases/:slug/media/{filename}` (proxied from documents_dir)

### Geographic Heatmap

**URL:** `/case/:slug/map`

**Interactive world map** using Leaflet.js + TopoJSON (both bundled, ~150KB).

- Countries shaded by mention frequency (choropleth)
- Color scale from light to dark based on mention count
- Click country → sidebar/popup with:
  - Country name, mention count
  - Sample document citations with snippets
  - [Search all mentions →] link

**Data source:** Post-processing step after entity extraction — aggregate GPE entities by country. Stored as `heatmap_data.json` in case output.

**Availability:** Only renders if entity extraction ran and GPE entities were found. Hidden from nav otherwise.

**API:** `GET /api/cases/:slug/map` (returns country → count + sample citations)

### AI Research Assistant

**URL:** `/case/:slug/ask`

**Chat interface** with conversation history (per-case, persisted in app state DB).

**RAG pipeline (same architecture as epstein-datasette ask-proxy, generalized):**
1. User question → sent to LLM with system prompt describing available data
2. LLM generates search queries (FTS5 syntax)
3. Queries executed against case DB (pages, transcripts, images)
4. Results + original question → LLM synthesizes answer with citations
5. Response streamed via SSE (token by token)

**UI elements:**
- Message bubbles (user / assistant)
- Source citations as clickable chips → navigate to document/page
- Search query chips showing what FTS5 queries were generated (transparency)
- Markdown rendering in responses (with marked.js, bundled)
- Bates number auto-linking in responses → clickable links to document detail

**LLM configuration:**
- API key configured in case.yaml (`openrouter_api_key_env`) or via the wizard
- Model selection in settings (default: use OpenRouter free tier models with fallback chain)
- No hardcoded model — user brings their own key

**Availability:** Only available if an API key is configured. Hidden from nav otherwise.

**API:** `POST /api/cases/:slug/ask` (body: `{question, conversation_id?}`) → SSE stream

### Case Settings

**URL:** `/case/:slug/settings`

- Edit case name, description
- Re-configure pipeline steps (same toggle cards as wizard Step 3)
- Re-run ingest (with changed config)
- Delete case (with confirmation)
- Export case (download case.yaml + data as archive)

---

## Backend API Specification

### Cases

```
GET    /api/cases                    List all cases
POST   /api/cases                    Create case (from wizard)
GET    /api/cases/:slug              Case detail + stats
PUT    /api/cases/:slug              Update case config
DELETE /api/cases/:slug              Delete case + data
```

### Ingest

```
POST   /api/cases/:slug/ingest/start     Start ingest pipeline
POST   /api/cases/:slug/ingest/stop      Stop/cancel ingest
GET    /api/cases/:slug/ingest/status     Current step, progress, errors

WebSocket: /ws/cases/:slug/ingest
  Server → Client messages:
    { type: "step_start", step_id: "ocr", total: 847 }
    { type: "step_progress", step_id: "ocr", current: 142, total: 847 }
    { type: "step_complete", step_id: "ocr", stats: { processed: 847, errors: 0 } }
    { type: "log", message: "Transcribed EFTA00064598.mp4", level: "info" }
    { type: "complete", stats: { documents: 847, pages: 12400, ... } }
    { type: "error", step_id: "transcription", message: "..." }
  Client → Server messages:
    { type: "cancel" }
```

### Pipeline

```
GET    /api/cases/:slug/pipeline         Manifest + case-specific enablement
PUT    /api/cases/:slug/pipeline         Update pipeline config (toggle steps)
GET    /api/pipeline/manifest            Global manifest (no case context)
```

### Search

```
GET    /api/cases/:slug/search?q=...&type=pages,transcripts&offset=0&limit=50
  Response:
  {
    total: 847,
    results: [
      { type: "page", document_id: "...", page_number: 3, snippet: "...", rank: 0.95 },
      { type: "transcript", document_id: "...", timestamp: 134.5, snippet: "...", rank: 0.88 },
      { type: "image", image_id: "...", description_snippet: "...", rank: 0.72 },
      { type: "entity", entity_id: "...", name: "...", mention_count: 47, rank: 0.65 }
    ]
  }
```

### Documents

```
GET    /api/cases/:slug/documents?offset=0&limit=50
GET    /api/cases/:slug/documents/:doc_id
GET    /api/cases/:slug/documents/:doc_id/pages
GET    /api/cases/:slug/documents/:doc_id/pages/:page_number
```

### Entities

```
GET    /api/cases/:slug/entities?type=PERSON&q=smith&offset=0&limit=50
GET    /api/cases/:slug/entities/:entity_id
GET    /api/cases/:slug/entities/graph
```

### Images

```
GET    /api/cases/:slug/images?has_description=true&offset=0&limit=50
GET    /api/cases/:slug/images/:image_id
GET    /api/cases/:slug/images/file/:doc_id/:filename     (static file)
```

### Transcripts

```
GET    /api/cases/:slug/transcripts
GET    /api/cases/:slug/transcripts/:transcript_id
GET    /api/cases/:slug/media/:filename                   (static file, proxied from documents_dir)
```

### Map

```
GET    /api/cases/:slug/map
```

### Ask (AI Assistant)

```
POST   /api/cases/:slug/ask
  Body: { question: "...", conversation_id: "..." }
  Response: SSE stream
    event: status    data: { message: "Generating search queries..." }
    event: queries   data: { queries: ["wire transfer offshore", "foundation account"] }
    event: results   data: { count: 12, sources: [...] }
    event: token     data: { text: "Based on" }
    event: token     data: { text: " the documents," }
    event: done      data: { conversation_id: "...", sources: [...] }
    event: error     data: { message: "..." }
```

---

## Ingest Progress Hooks

The existing `run_ingest()` function prints to console via Rich. To support WebSocket progress, we add a **callback protocol**:

```python
class IngestCallback(Protocol):
    def on_step_start(self, step_id: str, total: int) -> None: ...
    def on_step_progress(self, step_id: str, current: int, total: int) -> None: ...
    def on_step_complete(self, step_id: str, stats: dict) -> None: ...
    def on_log(self, message: str, level: str) -> None: ...
    def on_complete(self, stats: dict) -> None: ...
    def on_error(self, step_id: str, message: str) -> None: ...
```

`run_ingest()` accepts an optional `callback: IngestCallback` parameter. The CLI uses a `ConsoleCallback` that prints via Rich (current behavior). The API uses a `WebSocketCallback` that sends JSON messages over the WebSocket.

This is a non-breaking change — `callback=None` preserves current behavior.

---

## App State Database

Location: `~/.casestack/casestack.db` (configurable via `CASESTACK_HOME` env var)

```sql
CREATE TABLE cases (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    case_yaml_path TEXT NOT NULL,      -- absolute path to case.yaml
    output_dir TEXT NOT NULL,          -- absolute path to output dir
    documents_dir TEXT NOT NULL,       -- absolute path to documents
    created_at TEXT NOT NULL,
    last_opened_at TEXT,
    document_count INTEGER DEFAULT 0,
    page_count INTEGER DEFAULT 0,
    image_count INTEGER DEFAULT 0,
    transcript_count INTEGER DEFAULT 0,
    entity_count INTEGER DEFAULT 0,
    db_size_bytes INTEGER DEFAULT 0
);

CREATE TABLE ingest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_slug TEXT NOT NULL REFERENCES cases(slug),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT DEFAULT 'running',     -- running, completed, failed, cancelled
    current_step TEXT,
    progress_json TEXT,                -- JSON: { step_id: { current, total, status } }
    error_message TEXT,
    stats_json TEXT                    -- JSON: final stats on completion
);

CREATE TABLE conversations (
    id TEXT PRIMARY KEY,               -- UUID
    case_slug TEXT NOT NULL REFERENCES cases(slug),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    title TEXT                         -- auto-generated from first question
);

CREATE TABLE conversation_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,                -- 'user' or 'assistant'
    content TEXT NOT NULL,
    sources_json TEXT,                 -- JSON array of source citations
    queries_json TEXT,                 -- JSON array of search queries used
    created_at TEXT NOT NULL
);
```

---

## Project Structure

```
casestack/
├── src/casestack/
│   ├── api/                        # NEW: FastAPI backend
│   │   ├── __init__.py
│   │   ├── app.py                  # App factory, static file serving, CORS
│   │   ├── deps.py                 # Dependency injection (DB connections, case loading)
│   │   ├── state.py                # App state DB (cases, ingest runs, conversations)
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── cases.py            # CRUD cases
│   │   │   ├── ingest.py           # Start/stop/status
│   │   │   ├── pipeline.py         # Manifest + config
│   │   │   ├── search.py           # Unified search
│   │   │   ├── documents.py        # Document + page browsing
│   │   │   ├── entities.py         # Entity directory + graph
│   │   │   ├── images.py           # Gallery + static file serving
│   │   │   ├── transcripts.py      # Transcript browser + media serving
│   │   │   ├── map.py              # Heatmap data
│   │   │   └── ask.py              # AI assistant (SSE)
│   │   └── websocket.py            # Ingest progress WebSocket
│   ├── processors/                 # (existing, unchanged)
│   ├── exporters/                  # (existing, unchanged)
│   ├── models/                     # (existing, unchanged)
│   ├── pipeline.py                 # (existing, provides manifest)
│   ├── ingest.py                   # (existing, add IngestCallback protocol)
│   ├── case.py                     # (existing, unchanged)
│   ├── config.py                   # (existing, unchanged)
│   ├── cli.py                      # (existing, add `start` command, rename `serve` to `serve-datasette`)
│   └── static/                     # NEW: pre-built React app
│       ├── index.html
│       └── assets/
│           ├── index-[hash].js
│           └── index-[hash].css
├── frontend/                       # NEW: React source (dev only, not in pip package)
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── index.html
│   ├── public/
│   │   └── favicon.svg
│   └── src/
│       ├── main.tsx                # React entry point
│       ├── App.tsx                 # Router setup
│       ├── api/                    # API client (fetch wrappers, types)
│       │   ├── client.ts           # Base fetch with error handling
│       │   ├── cases.ts
│       │   ├── search.ts
│       │   ├── entities.ts
│       │   ├── images.ts
│       │   ├── transcripts.ts
│       │   └── ask.ts              # SSE client
│       ├── hooks/                  # React hooks
│       │   ├── useIngestProgress.ts  # WebSocket hook
│       │   └── useSearch.ts          # Debounced search hook
│       ├── pages/
│       │   ├── CaseList.tsx        # Home / case selector
│       │   ├── NewCaseWizard.tsx   # 4-step wizard
│       │   ├── Dashboard.tsx       # Case dashboard
│       │   ├── Search.tsx          # Unified search
│       │   ├── EntityViewer.tsx    # Directory + graph views
│       │   ├── ImageGallery.tsx    # Grid + lightbox
│       │   ├── TranscriptBrowser.tsx  # Player + segments
│       │   ├── Heatmap.tsx         # Leaflet map
│       │   ├── AskAssistant.tsx    # Chat interface
│       │   └── CaseSettings.tsx    # Pipeline config editor
│       ├── components/             # Shared UI
│       │   ├── Layout.tsx          # Shell: sidebar nav + content area
│       │   ├── Sidebar.tsx         # Case nav (pages conditional on pipeline)
│       │   ├── SearchResult.tsx    # Typed result card
│       │   ├── DocumentReader.tsx  # Inline page viewer
│       │   ├── MediaPlayer.tsx     # Audio/video with seek
│       │   ├── PipelineToggle.tsx  # Step toggle card (wizard + settings)
│       │   ├── ProgressBar.tsx     # Ingest step progress
│       │   ├── Lightbox.tsx        # Image lightbox
│       │   └── EntityGraph.tsx     # d3-force graph
│       └── styles/
│           └── globals.css         # Design tokens, base styles
├── docs/
│   └── plans/
│       └── 2026-03-01-frontend-design.md  (this file)
├── pyproject.toml                  # Add static/ as package_data
├── Makefile                        # `make frontend` builds + copies
└── README.md
```

---

## Build & Ship

### Development Workflow

```bash
# Terminal 1: FastAPI backend with hot reload
cd casestack
uvicorn casestack.api.app:create_app --factory --reload --port 8000

# Terminal 2: Vite dev server with HMR, proxies API to :8000
cd frontend
npm run dev    # runs on :5173, proxy /api/* and /ws/* to :8000
```

### Production Build

```bash
# Build frontend
cd frontend && npm run build    # outputs to frontend/dist/

# Copy to package
make frontend                   # copies frontend/dist/* → src/casestack/static/

# Build pip package
pip wheel .                     # static/ included as package_data
```

### CI Pipeline

```yaml
# GitHub Actions (simplified)
- npm ci && npm run build       # in frontend/
- cp -r frontend/dist/* src/casestack/static/
- pip wheel .
- pip install dist/*.whl && pytest
```

### pyproject.toml Changes

```toml
[tool.setuptools.package-data]
casestack = ["static/**/*", "templates/**/*"]

[project.optional-dependencies]
# existing extras unchanged
server = ["fastapi>=0.100", "uvicorn[standard]>=0.20"]
```

The `server` extra is required for `casestack start`. Could also be a default dependency since the web UI is now the primary interface.

---

## Visual Identity

### Design Tokens

```css
:root {
  /* Colors */
  --bg:          #fafafa;
  --surface:     #ffffff;
  --text:        #1a1a2e;
  --text-muted:  #6b7280;
  --accent:      #2563eb;    /* blue — links, active states, CTAs */
  --accent-light:#dbeafe;    /* light blue — hover backgrounds */
  --success:     #16a34a;    /* green — completed, counts */
  --warning:     #d97706;    /* amber — in-progress */
  --danger:      #dc2626;    /* red — errors, destructive */
  --border:      #e5e7eb;

  /* Typography */
  --font-sans:   'Inter', system-ui, -apple-system, sans-serif;
  --font-mono:   'JetBrains Mono', 'Fira Code', monospace;

  /* Spacing */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-6: 24px;
  --space-8: 32px;

  /* Radii */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
}
```

### Principles

- **Professional and trustworthy** — these are serious documents (legal, FOIA, investigative)
- **Information-dense** — researchers need density, not whitespace. Cards, tables, compact lists.
- **Neutral** — not tied to any subject matter. The epstein-datasette seal-gold/parchment aesthetic was Epstein-specific.
- **Accessible** — high contrast text, keyboard navigable, screen reader friendly

### Per-Case Theming (Stretch Goal)

Cases can optionally define an accent color in case.yaml:

```yaml
serve:
  accent_color: "#8b2500"   # Epstein case could keep its seal-gold
```

The SPA reads this from the case API and sets `--accent` accordingly. Default is blue.

---

## Bundled Dependencies (Frontend)

| Library | Purpose | Size |
|---------|---------|------|
| React + ReactDOM | UI framework | ~45KB gzipped |
| React Router | Client-side routing | ~12KB |
| d3-force + d3-selection | Entity graph | ~20KB |
| Leaflet + TopoJSON | Geographic heatmap | ~40KB + ~110KB (world topo) |
| marked | Markdown rendering (AI responses) | ~8KB |
| Inter font | Typography | ~100KB (woff2, 2 weights) |

**Total estimated bundle:** ~350-400KB gzipped. Acceptable for a local-first app.

All bundled via Vite — no CDN dependencies, works fully offline.

---

## Migration Path

### What Stays

- All processors (OCR, transcription, captioning, entities, dedup, embeddings, KG, redaction) — unchanged
- `pipeline.py` manifest — consumed by both CLI and API
- `case.py` CaseConfig — the source of truth for case configuration
- `ingest.py` run_ingest — add callback protocol, otherwise unchanged
- `cli.py` — keep `ingest`, `scan-pii`, `redact` commands. Add `start`. Rename `serve` to `serve-datasette`.
- SQLite export format — the case DBs are the same

### What Changes

- `serve` command renamed to `serve-datasette` (keep as power-user escape hatch)
- `ingest.py` gains `IngestCallback` protocol for progress reporting
- New `api/` package with FastAPI routes
- New `static/` directory with pre-built React app
- New app state DB at `~/.casestack/`
- `casestack start` becomes the primary entry point

### What Gets Removed (Eventually)

- `templates/index.html` (the 222-line Datasette template) — replaced by React SPA
- `ask_server.py` (108-line Starlette app) — replaced by FastAPI ask route
- Direct Datasette dependency for serving (kept optional for `serve-datasette`)

---

## Open Questions for Implementation

1. **Ingest in background thread vs subprocess?** Background thread is simpler but GIL-bound. Subprocess is more isolated but needs IPC for progress. Recommendation: background thread with asyncio, since processors already use multiprocessing for CPU-heavy work.

2. **Authentication?** Not needed for local-first. If someone wants to expose CaseStack on a network, we could add optional basic auth later. Not in v1.

3. **Multiple simultaneous ingests?** v1: one ingest at a time (queue additional requests). Future: parallel ingest of different cases.

4. **File browser in wizard?** The wizard needs the user to provide a directory path. On a local machine, we could use a native file picker dialog... but we're in a browser. Options: (a) paste path, (b) drag-and-drop a folder, (c) use the File System Access API (Chrome only). Recommendation: paste path for v1, with instructions.
