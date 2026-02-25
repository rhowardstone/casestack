# CaseStack MVP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Generalize the Epstein-Pipeline into a case-agnostic document intelligence platform where any user can point at a folder of PDFs and get a searchable Datasette database with entity extraction, knowledge graph, and citation-locked AI Q&A.

**Architecture:** Fork the Epstein-Pipeline core processors (OCR, NER, dedup, embeddings, knowledge graph, SQLite export) into a new `casestack` package. Replace all hardcoded Epstein assumptions with a `case.yaml` config file. Add a single `ingest` command that orchestrates the full pipeline. Auto-generate Datasette config from case metadata. Ship an `epstein` preset that reproduces current behavior exactly.

**Tech Stack:** Python 3.10+, Click CLI, Pydantic settings, Datasette, spaCy, Docling/PyMuPDF OCR, rapidfuzz, sentence-transformers, OpenRouter (for ask proxy)

**Source repos (read-only references):**
- Pipeline: `/tmp/rhowa-gh/Epstein-Pipeline/` (cloned from `rhowardstone/Epstein-Pipeline`)
- Datasette layer: `/tmp/rhowa-gh/epstein-datasette/` (cloned from `rhowardstone/epstein-datasette`)

---

## Task 1: Scaffold the CaseStack package

**Files:**
- Create: `pyproject.toml`
- Create: `src/casestack/__init__.py`
- Create: `src/casestack/cli.py` (stub)
- Create: `README.md`
- Create: `case.yaml.example`
- Create: `.gitignore`

**Step 1: Write pyproject.toml**

Adapt from Epstein-Pipeline's pyproject.toml. Change:
- `name = "casestack"`
- `description = "Turn any document dump into a searchable evidence database"`
- `env_prefix` references: `CASESTACK_` instead of `EPSTEIN_`
- Entry point: `casestack = "casestack.cli:cli"`
- Same dependency groups (ocr, nlp, ai, embeddings, etc.)
- Add `datasette>=0.64` to base deps
- Add `pyyaml>=6.0` to base deps

```toml
[project]
name = "casestack"
version = "0.1.0"
description = "Turn any document dump into a searchable evidence database"
requires-python = ">=3.10"
dependencies = [
    "click>=8.1",
    "rich>=13.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "rapidfuzz>=3.0",
    "httpx>=0.25",
    "pyyaml>=6.0",
    "datasette>=0.64",
]

[project.scripts]
casestack = "casestack.cli:cli"
```

**Step 2: Write .gitignore**

Standard Python gitignore plus:
```
data/
output/
.cache/
*.db
*.sqlite
```

**Step 3: Write case.yaml.example**

```yaml
# CaseStack case configuration
# Copy this to case.yaml and customize for your document set.

name: "My Case"
slug: "my-case"
description: "Description of this document collection"

# Where raw documents live (PDFs, images, audio/video)
documents_dir: "./documents"

# Processing options
ocr:
  backend: "pymupdf"        # "docling", "pymupdf", or "both"
  workers: 4

entities:
  spacy_model: "en_core_web_sm"
  types: ["PERSON", "ORG", "GPE", "DATE", "MONEY", "PHONE", "EMAIL_ADDR"]
  # Optional: path to a JSON person registry for fuzzy matching
  # registry: "./data/persons-registry.json"
  # fuzzy_threshold: 85

dedup:
  threshold: 0.90

# Bates number prefixes for dedup overlap detection (optional)
# bates_prefixes: ["EFTA", "DOJ"]

# Serving
serve:
  port: 8001
  title: "My Case — Document Database"
  # ask_proxy:
  #   enabled: true
  #   openrouter_api_key_env: "OPENROUTER_API_KEY"
```

**Step 4: Write stub CLI and __init__**

```python
# src/casestack/__init__.py
"""CaseStack — Turn any document dump into a searchable evidence database."""
__version__ = "0.1.0"
```

```python
# src/casestack/cli.py (stub — fleshed out in Task 3)
import click

@click.group()
@click.version_option(package_name="casestack")
def cli():
    """CaseStack — document dump → searchable evidence database."""
    pass
```

**Step 5: Write README.md**

Brief: what it is, install, quickstart (`casestack ingest ./pdfs --name "My Case"`), link to case.yaml.example.

**Step 6: Initialize git and commit**

```bash
cd /mnt/c/Users/rhowa/Documents/startups/casestack
git init
git add pyproject.toml src/ README.md case.yaml.example .gitignore docs/
git commit -m "feat: scaffold casestack package"
```

---

## Task 2: Port core models and processors from Epstein-Pipeline

**Files:**
- Create: `src/casestack/models/__init__.py`
- Create: `src/casestack/models/document.py` — copy from Epstein-Pipeline, generalize `DocumentSource`
- Create: `src/casestack/models/registry.py` — copy unchanged (already generic)
- Create: `src/casestack/processors/__init__.py`
- Create: `src/casestack/processors/ocr.py` — copy from Epstein-Pipeline
- Create: `src/casestack/processors/entities.py` — copy from Epstein-Pipeline
- Create: `src/casestack/processors/dedup.py` — copy, remove EFTA-specific Bates assumptions
- Create: `src/casestack/processors/knowledge_graph.py` — copy from Epstein-Pipeline
- Create: `src/casestack/processors/embeddings.py` — copy from Epstein-Pipeline
- Create: `src/casestack/processors/chunker.py` — copy from Epstein-Pipeline
- Create: `src/casestack/exporters/__init__.py`
- Create: `src/casestack/exporters/sqlite_export.py` — copy, rename `epstein.db` default
- Create: `src/casestack/utils/__init__.py`
- Create: `src/casestack/utils/hashing.py` — copy from Epstein-Pipeline
- Create: `src/casestack/utils/progress.py` — copy from Epstein-Pipeline
- Create: `src/casestack/utils/parallel.py` — copy from Epstein-Pipeline
- Create: `src/casestack/state.py` — copy from Epstein-Pipeline

**Step 1: Copy models**

From `/tmp/rhowa-gh/Epstein-Pipeline/src/epstein_pipeline/models/`:
- `document.py`: Change `DocumentSource` Literal to be extensible. Remove hardcoded `"efta-ds1"` through `"efta-ds12"`. Keep generic sources: `"court-filing"`, `"fbi"`, `"foia"`, `"financial"`, `"correspondence"`, `"media"`, `"testimony"`, `"police"`, `"other"`. Add `"local"` as the default for ingested documents.
- `registry.py`: Copy as-is (fuzzy matching is already generic).
- If `forensics.py` exists, copy it too.

**Step 2: Copy processors**

From `/tmp/rhowa-gh/Epstein-Pipeline/src/epstein_pipeline/processors/`:
- `ocr.py`: Change default `source` from `"efta"` to `"local"` (line ~94). Change import paths from `epstein_pipeline` to `casestack`.
- `entities.py`: Change imports. No other Epstein-specific code.
- `dedup.py`: Change `_BATES_PATTERN` to accept configurable prefixes (read from case config). Change imports.
- `knowledge_graph.py`: Change imports only.
- `embeddings.py`: Change imports only.
- `chunker.py`: Change imports only.

For each file: `sed 's/epstein_pipeline/casestack/g'` then fix specific hardcoded values.

**Step 3: Copy exporters**

- `sqlite_export.py`: Change default output from `"epstein.db"` to `"corpus.db"`. Change imports.

**Step 4: Copy utils and state**

- Direct copy with import path changes.

**Step 5: Verify imports compile**

```bash
cd /mnt/c/Users/rhowa/Documents/startups/casestack
pip install -e ".[dev]" 2>&1 | tail -5
python -c "from casestack.models.document import Document; print('OK')"
python -c "from casestack.processors.ocr import OcrProcessor; print('OK')"
```

**Step 6: Commit**

```bash
git add src/casestack/models/ src/casestack/processors/ src/casestack/exporters/ src/casestack/utils/ src/casestack/state.py
git commit -m "feat: port core models and processors from Epstein-Pipeline"
```

---

## Task 3: Implement case config loader and generic Settings

**Files:**
- Create: `src/casestack/case.py` — Case config model (loads case.yaml)
- Create: `src/casestack/config.py` — Settings with `CASESTACK_` prefix, merges with case.yaml
- Test: `tests/test_case_config.py`

**Step 1: Write test for case config loading**

```python
# tests/test_case_config.py
import tempfile
from pathlib import Path
from casestack.case import CaseConfig

def test_load_case_yaml():
    yaml_content = """
name: "Test Case"
slug: "test-case"
description: "A test"
documents_dir: "./docs"
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        config = CaseConfig.from_yaml(Path(f.name))
    assert config.name == "Test Case"
    assert config.slug == "test-case"
    assert config.documents_dir == Path("./docs")

def test_case_defaults():
    config = CaseConfig(name="Minimal", slug="minimal")
    assert config.ocr_backend == "pymupdf"
    assert config.ocr_workers == 4
    assert config.dedup_threshold == 0.90
    assert config.entity_types == ["PERSON", "ORG", "GPE", "DATE", "MONEY"]

def test_case_data_dirs():
    config = CaseConfig(name="Test", slug="test-case")
    assert config.data_dir == Path("./data/test-case")
    assert config.output_dir == Path("./output/test-case")
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_case_config.py -v
```
Expected: FAIL (module not found)

**Step 3: Implement CaseConfig**

```python
# src/casestack/case.py
"""Case configuration — loaded from case.yaml."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class CaseConfig(BaseModel):
    """Configuration for a single case/document collection."""

    name: str
    slug: str
    description: str = ""
    documents_dir: Path = Path("./documents")

    # OCR
    ocr_backend: str = "pymupdf"
    ocr_workers: int = 4

    # Entities
    spacy_model: str = "en_core_web_sm"
    entity_types: list[str] = Field(
        default=["PERSON", "ORG", "GPE", "DATE", "MONEY"]
    )
    registry_path: Optional[Path] = None
    fuzzy_threshold: int = 85

    # Dedup
    dedup_threshold: float = 0.90
    bates_prefixes: list[str] = Field(default_factory=list)

    # Embeddings
    embedding_model: str = "nomic-ai/nomic-embed-text-v2-moe"
    embedding_dimensions: int = 768

    # Serving
    serve_port: int = 8001
    serve_title: str = ""
    ask_proxy_enabled: bool = False
    openrouter_api_key_env: str = "OPENROUTER_API_KEY"

    @property
    def data_dir(self) -> Path:
        return Path(f"./data/{self.slug}")

    @property
    def output_dir(self) -> Path:
        return Path(f"./output/{self.slug}")

    @property
    def cache_dir(self) -> Path:
        return Path(f"./.cache/{self.slug}")

    @property
    def db_path(self) -> Path:
        return self.output_dir / f"{self.slug}.db"

    @classmethod
    def from_yaml(cls, path: Path) -> CaseConfig:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        # Flatten nested sections
        flat = {}
        for key, value in raw.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    flat_key = f"{key}_{sub_key}" if key in ("ocr", "serve") else sub_key
                    flat[flat_key] = sub_value
            else:
                flat[key] = value
        return cls(**flat)
```

**Step 4: Implement Settings (adapts CaseConfig for processor compatibility)**

```python
# src/casestack/config.py
"""Pipeline settings — bridges CaseConfig to processor interfaces."""
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Settings loaded from env vars (CASESTACK_ prefix) or from CaseConfig."""

    model_config = {"env_prefix": "CASESTACK_"}

    data_dir: Path = Path("./data")
    output_dir: Path = Path("./output")
    cache_dir: Path = Path("./.cache")
    persons_registry_path: Path = Path("./data/persons-registry.json")

    spacy_model: str = "en_core_web_sm"
    dedup_threshold: float = 0.90
    ocr_batch_size: int = 50
    max_workers: int = 4
    ocr_backend: str = "pymupdf"

    vision_model: str = "llava"
    summarizer_provider: str = "ollama"
    summarizer_model: str = "llama3.2"
    whisper_model: str = "large-v3"

    embedding_model: str = "nomic-ai/nomic-embed-text-v2-moe"
    embedding_dimensions: int = 768
    embedding_chunk_size: int = 3200
    embedding_chunk_overlap: int = 800
    embedding_batch_size: int | None = None
    embedding_device: str | None = None

    site_dir: Path | None = None
    sea_doughnut_dir: Path | None = None

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_case(cls, case: "CaseConfig") -> "Settings":
        from casestack.case import CaseConfig
        return cls(
            data_dir=case.data_dir,
            output_dir=case.output_dir,
            cache_dir=case.cache_dir,
            persons_registry_path=case.registry_path or case.data_dir / "persons-registry.json",
            spacy_model=case.spacy_model,
            dedup_threshold=case.dedup_threshold,
            max_workers=case.ocr_workers,
            ocr_backend=case.ocr_backend,
            embedding_model=case.embedding_model,
            embedding_dimensions=case.embedding_dimensions,
        )
```

**Step 5: Run tests**

```bash
pytest tests/test_case_config.py -v
```
Expected: PASS

**Step 6: Commit**

```bash
git add src/casestack/case.py src/casestack/config.py tests/test_case_config.py
git commit -m "feat: case config loader and generic settings"
```

---

## Task 4: Implement the `ingest` command (the main pipeline orchestrator)

**Files:**
- Modify: `src/casestack/cli.py` — add `ingest` command + supporting commands
- Create: `src/casestack/ingest.py` — orchestration logic
- Test: `tests/test_ingest.py`

**Step 1: Write integration test with a tiny PDF**

```python
# tests/test_ingest.py
import tempfile
from pathlib import Path
from unittest.mock import patch
from casestack.ingest import run_ingest
from casestack.case import CaseConfig


def test_ingest_creates_sqlite_db(tmp_path):
    """Ingest a directory and verify SQLite output is created."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    # Create a minimal text file (OCR processor handles PDFs, but we test the flow)
    (docs_dir / "test.txt").write_text("John Smith met Jane Doe on January 5, 2024.")

    case = CaseConfig(
        name="Test Case",
        slug="test",
        documents_dir=docs_dir,
    )
    # Override output dirs to use tmp
    with patch.object(type(case), 'output_dir', new_callable=lambda: property(lambda self: tmp_path / "output")):
        with patch.object(type(case), 'data_dir', new_callable=lambda: property(lambda self: tmp_path / "data")):
            with patch.object(type(case), 'cache_dir', new_callable=lambda: property(lambda self: tmp_path / "cache")):
                run_ingest(case, skip_ocr=True)

    # Verify output structure exists
    assert (tmp_path / "output").exists()
```

**Step 2: Implement ingest.py**

```python
# src/casestack/ingest.py
"""Orchestrate the full ingest pipeline: scan → OCR → entities → dedup → export."""
from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from casestack.case import CaseConfig
from casestack.config import Settings

console = Console()


def run_ingest(
    case: CaseConfig,
    skip_ocr: bool = False,
    skip_entities: bool = False,
    skip_dedup: bool = False,
    skip_embeddings: bool = True,  # Heavy — opt-in
) -> Path:
    """Run the full ingest pipeline. Returns path to output SQLite DB."""

    settings = Settings.from_case(case)
    settings.ensure_dirs()

    ocr_dir = settings.output_dir / "ocr"
    entities_dir = settings.output_dir / "entities"
    ocr_dir.mkdir(parents=True, exist_ok=True)
    entities_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"\n[bold cyan]CaseStack[/bold cyan] — Ingesting: {case.name}")
    console.print(f"  Documents: {case.documents_dir}")
    console.print(f"  Output:    {settings.output_dir}")

    # --- Step 1: OCR ---
    if not skip_ocr:
        pdfs = sorted(case.documents_dir.rglob("*.pdf"))
        console.print(f"\n[bold]Step 1/4: OCR[/bold] — {len(pdfs)} PDFs")
        if pdfs:
            from casestack.processors.ocr import OcrProcessor
            processor = OcrProcessor(settings, backend=case.ocr_backend)
            results = processor.process_batch(pdfs, ocr_dir, max_workers=case.ocr_workers)
            ok = sum(1 for r in results if r.document is not None)
            console.print(f"  [green]{ok} succeeded[/green]")
        else:
            console.print("  [yellow]No PDFs found, scanning for text files...[/yellow]")
            _ingest_text_files(case.documents_dir, ocr_dir)
    else:
        console.print("\n[dim]Step 1/4: OCR — skipped[/dim]")

    # --- Step 2: Entity extraction ---
    if not skip_entities:
        console.print(f"\n[bold]Step 2/4: Entity extraction[/bold]")
        json_files = sorted(ocr_dir.glob("*.json"))
        if json_files:
            from casestack.models.document import ProcessingResult
            from casestack.processors.entities import EntityExtractor

            registry = None
            if case.registry_path and case.registry_path.exists():
                from casestack.models.registry import PersonRegistry
                registry = PersonRegistry.from_json(case.registry_path)
                console.print(f"  Registry: {len(registry)} persons")

            extractor = EntityExtractor(
                settings, registry,
                entity_types=set(case.entity_types),
            )

            count = 0
            for jf in json_files:
                try:
                    result = ProcessingResult.model_validate_json(
                        jf.read_text(encoding="utf-8")
                    )
                except Exception:
                    continue
                if result.document is None:
                    continue
                text_parts = [
                    t for t in [
                        result.document.title,
                        result.document.summary,
                        result.document.ocrText,
                    ] if t
                ]
                extraction = extractor.extract_all("\n".join(text_parts))
                result.document.personIds = extraction.person_ids
                count += len(extraction.person_ids)
                (entities_dir / jf.name).write_text(
                    result.model_dump_json(indent=2), encoding="utf-8"
                )
            console.print(f"  [green]{count} entity links extracted[/green]")
        else:
            console.print("  [yellow]No OCR output to extract from[/yellow]")
    else:
        console.print("\n[dim]Step 2/4: Entities — skipped[/dim]")

    # --- Step 3: Dedup ---
    if not skip_dedup:
        console.print(f"\n[bold]Step 3/4: Deduplication[/bold]")
        source_dir = entities_dir if list(entities_dir.glob("*.json")) else ocr_dir
        json_files = sorted(source_dir.glob("*.json"))
        if json_files:
            from casestack.models.document import Document, ProcessingResult
            from casestack.processors.dedup import Deduplicator

            documents = []
            for jf in json_files:
                try:
                    raw = json.loads(jf.read_text(encoding="utf-8"))
                    if "document" in raw and raw["document"] is not None:
                        result = ProcessingResult.model_validate(raw)
                        if result.document:
                            documents.append(result.document)
                    elif "id" in raw and "title" in raw:
                        documents.append(Document.model_validate(raw))
                except Exception:
                    continue

            deduplicator = Deduplicator(threshold=case.dedup_threshold)
            pairs = deduplicator.find_duplicates(documents)
            console.print(f"  [green]{len(pairs)} duplicate pairs found[/green]")

            report_path = settings.output_dir / "dedup-report.json"
            report_path.write_text(
                json.dumps([p.model_dump() for p in pairs], indent=2),
                encoding="utf-8",
            )
    else:
        console.print("\n[dim]Step 3/4: Dedup — skipped[/dim]")

    # --- Step 4: SQLite export ---
    console.print(f"\n[bold]Step 4/4: SQLite export[/bold]")
    source_dir = entities_dir if list(entities_dir.glob("*.json")) else ocr_dir
    json_files = sorted(source_dir.glob("*.json"))

    from casestack.models.document import Document, ProcessingResult
    from casestack.exporters.sqlite_export import SqliteExporter

    documents = []
    for jf in json_files:
        try:
            raw = json.loads(jf.read_text(encoding="utf-8"))
            if "document" in raw and raw["document"] is not None:
                result = ProcessingResult.model_validate(raw)
                if result.document:
                    documents.append(result.document)
            elif "id" in raw and "title" in raw:
                documents.append(Document.model_validate(raw))
        except Exception:
            continue

    db_path = case.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    exporter = SqliteExporter()
    exporter.export(documents=documents, persons=[], db_path=db_path)
    console.print(f"  [green]Exported {len(documents)} documents → {db_path}[/green]")

    # --- Generate Datasette config ---
    _generate_datasette_config(case, db_path)

    console.print(f"\n[bold green]Done![/bold green] Serve with:")
    console.print(f"  casestack serve --case case.yaml")
    console.print(f"  # or: datasette serve {db_path}")

    return db_path


def _ingest_text_files(docs_dir: Path, ocr_dir: Path) -> None:
    """Fallback: ingest plain text files as pseudo-OCR output."""
    from casestack.models.document import Document, ProcessingResult
    from casestack.utils.hashing import content_hash

    text_files = sorted(
        f for f in docs_dir.rglob("*")
        if f.suffix.lower() in (".txt", ".md", ".csv", ".json", ".html")
    )
    for tf in text_files:
        text = tf.read_text(encoding="utf-8", errors="replace")
        doc_id = f"txt-{content_hash(text)[:12]}"
        title = tf.stem.replace("_", " ").replace("-", " ").title()
        doc = Document(
            id=doc_id,
            title=title,
            source="local",
            category="other",
            ocrText=text,
            tags=["text-ingest"],
        )
        result = ProcessingResult(
            source_path=str(tf),
            document=doc,
            processing_time_ms=0,
            errors=[],
        )
        out_path = ocr_dir / f"{doc_id}.json"
        out_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    console.print(f"  [green]Ingested {len(text_files)} text files[/green]")


def _generate_datasette_config(case: CaseConfig, db_path: Path) -> None:
    """Generate a datasette.yaml config for this case."""
    import yaml

    config = {
        "title": case.serve_title or f"{case.name} — Document Database",
        "description": case.description,
        "settings": {
            "sql_time_limit_ms": 15000,
            "num_sql_threads": 4,
            "default_page_size": 50,
            "allow_download": False,
            "suggest_facets": False,
        },
        "databases": {
            case.slug: {
                "tables": {
                    "documents": {
                        "label_column": "title",
                        "description": "All processed documents",
                    },
                    "persons": {
                        "label_column": "name",
                        "description": "Extracted entities/persons",
                    },
                },
            }
        },
    }
    config_path = case.output_dir / "datasette.yaml"
    config_path.write_text(yaml.dump(config, default_flow_style=False), encoding="utf-8")
    console.print(f"  Datasette config: {config_path}")
```

**Step 3: Implement the full CLI**

```python
# src/casestack/cli.py
"""CaseStack CLI."""
from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

console = Console()

BANNER = """
[bold cyan]CaseStack[/bold cyan] — Document Intelligence Platform
[dim]Turn any document dump into a searchable evidence database[/dim]
"""


def _load_case(case_path: str | None) -> "CaseConfig":
    from casestack.case import CaseConfig
    if case_path:
        p = Path(case_path)
        if not p.exists():
            console.print(f"[red]Case config not found: {p}[/red]")
            sys.exit(1)
        return CaseConfig.from_yaml(p)
    # Check default locations
    for default in ["case.yaml", "case.yml"]:
        if Path(default).exists():
            return CaseConfig.from_yaml(Path(default))
    console.print("[red]No case.yaml found. Use --case or create one from case.yaml.example[/red]")
    sys.exit(1)


@click.group()
@click.version_option(package_name="casestack")
def cli():
    """CaseStack — document dump to searchable evidence database."""
    console.print(BANNER)


@cli.command()
@click.argument("documents_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--name", "-n", required=True, help="Case name (e.g. 'FOIA Response 2024')")
@click.option("--case", "case_path", type=click.Path(path_type=Path), default=None,
              help="Path to case.yaml (overrides --name and documents_dir)")
@click.option("--skip-ocr", is_flag=True, help="Skip OCR step")
@click.option("--skip-entities", is_flag=True, help="Skip entity extraction")
@click.option("--skip-dedup", is_flag=True, help="Skip deduplication")
def ingest(documents_dir, name, case_path, skip_ocr, skip_entities, skip_dedup):
    """Ingest a document directory into a searchable database.

    \b
    Examples:
      casestack ingest ./my-pdfs --name "City Council FOIA"
      casestack ingest ./documents --case case.yaml
    """
    if case_path:
        case = _load_case(str(case_path))
    else:
        from casestack.case import CaseConfig
        slug = name.lower().replace(" ", "-").replace("'", "")[:40]
        case = CaseConfig(name=name, slug=slug, documents_dir=documents_dir)

    from casestack.ingest import run_ingest
    run_ingest(case, skip_ocr=skip_ocr, skip_entities=skip_entities, skip_dedup=skip_dedup)


@cli.command()
@click.option("--case", "case_path", type=click.Path(), default=None)
@click.option("--port", "-p", type=int, default=None)
@click.option("--host", "-h", type=str, default="127.0.0.1")
def serve(case_path, port, host):
    """Serve the case database with Datasette.

    \b
    Examples:
      casestack serve
      casestack serve --case case.yaml --port 8080
    """
    import subprocess
    case = _load_case(case_path)
    db = case.db_path
    if not db.exists():
        console.print(f"[red]Database not found: {db}[/red]")
        console.print("Run 'casestack ingest' first.")
        sys.exit(1)

    ds_config = case.output_dir / "datasette.yaml"
    serve_port = port or case.serve_port

    cmd = [
        sys.executable, "-m", "datasette", "serve",
        str(db),
        "-h", host,
        "-p", str(serve_port),
    ]
    if ds_config.exists():
        cmd.extend(["--metadata", str(ds_config)])

    console.print(f"[bold]Serving[/bold] {db.name} at http://{host}:{serve_port}")
    subprocess.run(cmd)


@cli.command()
@click.option("--case", "case_path", type=click.Path(), default=None)
def status(case_path):
    """Show case status: documents processed, DB size, etc."""
    case = _load_case(case_path)
    db = case.db_path

    console.print(f"\n[bold]{case.name}[/bold] ({case.slug})")
    console.print(f"  Documents dir: {case.documents_dir}")
    console.print(f"  Output dir:    {case.output_dir}")

    if db.exists():
        size_mb = db.stat().st_size / 1_000_000
        console.print(f"  Database:      {db} ({size_mb:.1f} MB)")

        import sqlite3
        conn = sqlite3.connect(str(db))
        try:
            count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            console.print(f"  Documents:     {count:,}")
        except Exception:
            pass
        finally:
            conn.close()
    else:
        console.print("  [yellow]Not yet ingested. Run: casestack ingest[/yellow]")
```

**Step 4: Run integration test**

```bash
pytest tests/test_ingest.py -v
```

**Step 5: Manual smoke test**

```bash
cd /mnt/c/Users/rhowa/Documents/startups/casestack
mkdir -p /tmp/test-docs
echo "John Smith met Jane Doe at 123 Main Street on January 5, 2024. Call 555-0100." > /tmp/test-docs/meeting_notes.txt
python -m casestack.cli ingest /tmp/test-docs --name "Test Case"
# Should produce: output/test-case/test-case.db
python -m casestack.cli status
```

**Step 6: Commit**

```bash
git add src/casestack/cli.py src/casestack/ingest.py tests/test_ingest.py
git commit -m "feat: ingest command — full pipeline orchestrator"
```

---

## Task 5: Create Epstein preset and verify backwards compatibility

**Files:**
- Create: `presets/epstein.yaml` — full Epstein case config
- Create: `presets/epstein-persons-registry.json` — symlink or note pointing to Epstein-Pipeline's registry

**Step 1: Write epstein.yaml preset**

```yaml
# CaseStack preset for the Epstein case
# Usage: casestack ingest ./epstein-pdfs --case presets/epstein.yaml

name: "Epstein Files"
slug: "epstein"
description: "218GB DOJ Jeffrey Epstein File Release — 1.38M PDFs, 2.73M pages"

documents_dir: "./data/epstein/pdfs"

ocr:
  backend: "both"
  workers: 4

entities:
  spacy_model: "en_core_web_sm"
  types: ["PERSON", "ORG", "GPE", "DATE", "MONEY", "PHONE", "EMAIL_ADDR"]
  registry: "./presets/epstein-persons-registry.json"
  fuzzy_threshold: 85

dedup:
  threshold: 0.90

bates_prefixes: ["EFTA", "HOUSE_OVERSIGHT", "FBI_VAULT", "DOJ-OGR"]

serve:
  port: 8001
  title: "Epstein Files — Document Database"
```

**Step 2: Copy the persons registry**

```bash
cp /tmp/rhowa-gh/Epstein-Pipeline/data/persons-registry.json presets/epstein-persons-registry.json
```

**Step 3: Verify the preset loads**

```bash
python -c "
from casestack.case import CaseConfig
c = CaseConfig.from_yaml('presets/epstein.yaml')
print(f'Name: {c.name}')
print(f'Slug: {c.slug}')
print(f'Registry: {c.registry_path}')
print(f'Bates: {c.bates_prefixes}')
print(f'DB: {c.db_path}')
"
```

Expected:
```
Name: Epstein Files
Slug: epstein
Registry: ./presets/epstein-persons-registry.json
Bates: ['EFTA', 'HOUSE_OVERSIGHT', 'FBI_VAULT', 'DOJ-OGR']
DB: ./output/epstein/epstein.db
```

**Step 4: Commit**

```bash
git add presets/
git commit -m "feat: add Epstein case preset with persons registry"
```

---

## Task 6: Implement the `serve` layer with auto-generated Datasette + ask proxy

**Files:**
- Create: `src/casestack/serve/__init__.py`
- Create: `src/casestack/serve/ask_proxy.py` — generic citation-locked Q&A proxy
- Create: `src/casestack/serve/templates/index.html` — generic homepage template

**Step 1: Port ask-proxy.py from epstein-datasette**

From `/tmp/rhowa-gh/epstein-datasette/ask-proxy.py` (~1000 lines), create a generic version:
- Replace hardcoded `ENDPOINT_META` with auto-discovery from SQLite schema
- Replace Epstein-specific system prompt with generic: "You are analyzing documents from {case.name}. Only answer using evidence from the database. Cite document IDs."
- Replace hardcoded `REPORTS_DIR` with optional config
- Keep the model fallback chain (OpenRouter free models)
- Keep the caching, rate limiting, and streaming response logic

Key changes from the original:
```python
# OLD (epstein-specific):
SYSTEM_PROMPT = "You are analyzing the Epstein case files..."
ENDPOINT_META = {
    ("full_text_corpus", "pages"): {"text_field": "text_content"},
    ...
}

# NEW (generic):
SYSTEM_PROMPT = f"You are analyzing documents from '{case_name}'. ..."
# Auto-discover tables and text fields from SQLite schema
ENDPOINT_META = _discover_endpoints(db_path)
```

**Step 2: Create generic homepage template**

Adapt from `/tmp/rhowa-gh/epstein-datasette/templates/index.html`:
- Replace Epstein branding with `{{ case_name }}`
- Keep search box, table list, stats summary
- Remove investigation report links (case-specific)

**Step 3: Test serve command end-to-end**

```bash
# After running ingest from Task 4:
casestack serve --case case.yaml
# Visit http://127.0.0.1:8001 — should see Datasette with the case database
```

**Step 4: Commit**

```bash
git add src/casestack/serve/
git commit -m "feat: generic serve layer with ask proxy and templates"
```

---

## Task 7: End-to-end integration test with real PDFs

**Files:**
- Create: `tests/test_e2e.py`
- Create: `tests/fixtures/` — small test PDFs

**Step 1: Create a small test fixture**

Generate a 1-page PDF with known text content using Python:
```python
# tests/conftest.py
import pytest
from pathlib import Path

@pytest.fixture
def sample_pdf_dir(tmp_path):
    """Create a directory with a tiny test PDF."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        pytest.skip("pymupdf not installed")

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Meeting between John Smith and Jane Doe\n"
                                "Date: January 5, 2024\n"
                                "Location: 123 Main Street, New York\n"
                                "RE: Case #2024-001\n"
                                "Amount discussed: $50,000")
    pdf_path = tmp_path / "docs" / "meeting.pdf"
    pdf_path.parent.mkdir()
    doc.save(str(pdf_path))
    doc.close()
    return tmp_path / "docs"
```

**Step 2: Write E2E test**

```python
# tests/test_e2e.py
import sqlite3
from casestack.case import CaseConfig
from casestack.ingest import run_ingest


def test_full_pipeline_pdf(sample_pdf_dir, tmp_path, monkeypatch):
    """Full pipeline: PDF → OCR → entities → SQLite."""
    case = CaseConfig(name="E2E Test", slug="e2e-test", documents_dir=sample_pdf_dir)
    # Redirect output to tmp
    monkeypatch.setattr(type(case), 'output_dir', property(lambda self: tmp_path / "output"))
    monkeypatch.setattr(type(case), 'data_dir', property(lambda self: tmp_path / "data"))
    monkeypatch.setattr(type(case), 'cache_dir', property(lambda self: tmp_path / "cache"))
    monkeypatch.setattr(type(case), 'db_path', property(lambda self: tmp_path / "output" / "e2e.db"))

    db_path = run_ingest(case)
    assert db_path.exists()

    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    assert count >= 1

    # Check that entity extraction found something
    row = conn.execute("SELECT ocr_text FROM documents LIMIT 1").fetchone()
    assert "John Smith" in row[0] or "meeting" in row[0].lower()
    conn.close()
```

**Step 3: Run E2E test**

```bash
pip install -e ".[pymupdf,nlp,dev]"
python -m spacy download en_core_web_sm
pytest tests/test_e2e.py -v
```

**Step 4: Commit**

```bash
git add tests/
git commit -m "test: end-to-end integration test with real PDF"
```

---

## Task 8: Push to GitHub and document

**Step 1: Create GitHub repo**

```bash
cd /mnt/c/Users/rhowa/Documents/startups/casestack
gh repo create rhowardstone/casestack --private --source=. --push
```

**Step 2: Final README polish**

Update README.md with:
- Installation instructions
- Quickstart (3 commands: install, ingest, serve)
- Case config reference
- Link to epstein-data.com as proof-of-concept
- "Built by the team behind epstein-data.com"

**Step 3: Commit and push**

```bash
git add -A
git commit -m "docs: polish README with quickstart and config reference"
git push
```

---

## Summary of deliverables

| File | Purpose |
|------|---------|
| `pyproject.toml` | Package definition, dependencies |
| `case.yaml.example` | Template config for new cases |
| `src/casestack/case.py` | Case config model (loads YAML) |
| `src/casestack/config.py` | Settings bridge (env vars + case config) |
| `src/casestack/cli.py` | CLI: `ingest`, `serve`, `status` commands |
| `src/casestack/ingest.py` | Full pipeline orchestrator |
| `src/casestack/models/` | Document, Person, Registry models (ported) |
| `src/casestack/processors/` | OCR, NER, dedup, embeddings, graph (ported) |
| `src/casestack/exporters/` | SQLite + FTS5 export (ported) |
| `src/casestack/serve/` | Datasette config gen + ask proxy |
| `presets/epstein.yaml` | Epstein case preset |
| `presets/epstein-persons-registry.json` | 1,400+ Epstein entities |
| `tests/` | Unit + integration + E2E tests |
