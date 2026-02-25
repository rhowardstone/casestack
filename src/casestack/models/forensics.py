"""Pydantic v2 models for forensic analysis data (redactions, images, transcripts, etc.)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RedactionScore(BaseModel):
    """Redaction analysis result for a single document."""

    document_id: str
    total_redactions: int = 0
    proper_redactions: int = 0
    improper_redactions: int = 0
    redaction_density: float = 0.0  # 0.0 - 1.0
    page_count: int | None = None


class RecoveredText(BaseModel):
    """Text recovered from under a redaction."""

    document_id: str
    page_number: int
    text: str
    confidence: float = 0.0  # 0.0 - 1.0


class Redaction(BaseModel):
    """A single detected redaction region."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    classification: str  # "proper", "bad_overlay", "recoverable"
    recovered_text: str | None = None


class RedactionAnalysisResult(BaseModel):
    """Full redaction analysis result for a PDF."""

    source_path: str
    document_id: str
    page_count: int
    redactions: list[Redaction] = Field(default_factory=list)
    total_redactions: int = 0
    proper: int = 0
    bad_overlay: int = 0
    recoverable: int = 0
    recovered_text_fragments: list[str] = Field(default_factory=list)


class ExtractedImage(BaseModel):
    """An image extracted from a PDF document."""

    document_id: str
    page_number: int
    image_index: int
    width: int
    height: int
    format: str  # "png", "jpeg", etc.
    file_path: str | None = None
    description: str | None = None  # AI-generated description
    size_bytes: int = 0


class Transcript(BaseModel):
    """A transcription of an audio/video file."""

    source_path: str
    document_id: str
    text: str
    language: str = "en"
    duration_seconds: float = 0.0
    segments: list[TranscriptSegment] = Field(default_factory=list)


class TranscriptSegment(BaseModel):
    """A single segment of a transcript with timing."""

    start: float  # seconds
    end: float  # seconds
    text: str


# Fix forward reference
Transcript.model_rebuild()


class ExtractedEntity(BaseModel):
    """An entity extracted by NLP or regex from document text."""

    document_id: str
    entity_type: str  # PERSON, ORG, GPE, DATE, MONEY, PHONE, etc.
    text: str
    confidence: float = 0.0
    person_id: str | None = None  # Matched person ID if applicable


class EmbeddingChunk(BaseModel):
    """A document chunk with its embedding vector."""

    document_id: str
    chunk_index: int
    chunk_text: str
    embedding: list[float] = Field(default_factory=list)
    model_name: str = "nomic-ai/nomic-embed-text-v2-moe"
    dimensions: int = 768


class ProvenanceRange(BaseModel):
    """A range in a provenance map.

    Maps a contiguous block of document numbers to their origin
    (e.g. subpoena, device extraction, prosecution files).
    """

    dataset: int
    prefix_start: str  # e.g. "PREFIX01343849"
    prefix_end: str
    source_description: str
    source_category: str  # prosecution, financial_subpoena, etc.
    doc_count: int = 0
    page_count: int = 0
    alt_bates_start: str | None = None  # Alternative Bates range if known
    alt_bates_end: str | None = None
    confidence: str = "high"  # high, medium, inferred


class ConcordanceSummary(BaseModel):
    """Summary of concordance metadata for the corpus.

    Concordance data links Bates numbers across different numbering systems
    and maps document provenance across dataset releases.
    """

    provenance_ranges: list[ProvenanceRange] = Field(default_factory=list)
    cross_reference_count: int = 0  # Cross-system direct mappings
    production_count: int = 0  # Discovery production entries
    load_file_document_count: int = 0  # Load file documents
