"""Pipeline step registry for frontend discovery."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PipelineStep:
    id: str
    label: str
    description: str
    default_enabled: bool = True
    requires_extra: str | None = None
    depends_on: list[str] = field(default_factory=list)
    config_keys: list[str] = field(default_factory=list)


PIPELINE_STEPS: list[PipelineStep] = [
    PipelineStep(
        id="ocr",
        label="PDF OCR",
        description="Extract text from PDFs",
        config_keys=["ocr_backend", "ocr_workers"],
    ),
    PipelineStep(
        id="transcription",
        label="Audio/Video Transcription",
        description="Transcribe media files with Whisper",
        requires_extra="transcription",
        config_keys=["whisper_model", "whisper_device"],
    ),
    PipelineStep(
        id="doc_conversion",
        label="Document Conversion",
        description="Convert Office/text files to searchable text",
        requires_extra="documents",
    ),
    PipelineStep(
        id="page_captions",
        label="Page Captions",
        description="AI-describe image-heavy PDF pages",
        requires_extra="captioning",
        depends_on=["ocr"],
        config_keys=["caption_model", "caption_char_threshold"],
    ),
    PipelineStep(
        id="image_extraction",
        label="Image Extraction",
        description="Extract embedded images from PDFs",
        depends_on=["ocr"],
        config_keys=["image_min_size", "image_min_bytes", "image_page_scan_ratio"],
    ),
    PipelineStep(
        id="image_analysis",
        label="Image Analysis",
        description="AI-describe extracted images with Qwen2-VL",
        requires_extra="captioning",
        depends_on=["image_extraction"],
        config_keys=["image_analysis_model"],
    ),
    PipelineStep(
        id="entities",
        label="Entity Extraction",
        description="Link persons, orgs, dates to a registry",
        depends_on=["ocr"],
        config_keys=["entity_types", "spacy_model", "registry_path", "fuzzy_threshold"],
    ),
    PipelineStep(
        id="dedup",
        label="Deduplication",
        description="Find near-duplicate documents",
        depends_on=["ocr"],
        config_keys=["dedup_threshold", "bates_prefixes"],
    ),
    PipelineStep(
        id="embeddings",
        label="Semantic Embeddings",
        description="Generate vector embeddings for semantic search",
        default_enabled=False,
        requires_extra="embeddings",
        depends_on=["ocr"],
        config_keys=[
            "embedding_model",
            "embedding_dimensions",
            "embedding_chunk_size",
            "embedding_chunk_overlap",
            "embedding_batch_size",
            "embedding_device",
        ],
    ),
    PipelineStep(
        id="knowledge_graph",
        label="Knowledge Graph",
        description="Build entity relationship graph",
        default_enabled=False,
        depends_on=["entities"],
        config_keys=[],
    ),
    PipelineStep(
        id="redaction_analysis",
        label="Redaction Analysis",
        description="Detect and classify redactions in PDFs",
        default_enabled=False,
        depends_on=["ocr"],
        config_keys=["redaction_workers"],
    ),
    PipelineStep(
        id="export",
        label="SQLite Export",
        description="Build searchable database with FTS",
    ),
]


def get_manifest() -> list[dict]:
    """Return JSON-serializable pipeline manifest for frontend."""
    return [
        {
            "id": s.id,
            "label": s.label,
            "description": s.description,
            "default_enabled": s.default_enabled,
            "requires_extra": s.requires_extra,
            "depends_on": s.depends_on,
            "config_keys": s.config_keys,
        }
        for s in PIPELINE_STEPS
    ]


def get_enabled_steps(overrides: dict[str, bool] | None = None) -> set[str]:
    """Return set of enabled step IDs given user overrides."""
    enabled = set()
    for s in PIPELINE_STEPS:
        on = s.default_enabled
        if overrides and s.id in overrides:
            on = overrides[s.id]
        if on:
            enabled.add(s.id)
    return enabled
