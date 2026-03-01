"""Pipeline configuration using Pydantic BaseSettings with CASESTACK_ env prefix."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Pipeline settings loaded from environment variables prefixed with CASESTACK_.

    Example:
        CASESTACK_DATA_DIR=/mnt/data
        CASESTACK_SPACY_MODEL=en_core_web_lg
        CASESTACK_DEDUP_THRESHOLD=0.95
    """

    model_config = {"env_prefix": "CASESTACK_"}

    data_dir: Path = Path("./data")
    output_dir: Path = Path("./output")
    cache_dir: Path = Path("./.cache")
    persons_registry_path: Path = Path("./data/persons-registry.json")

    # Processing settings
    spacy_model: str = "en_core_web_sm"
    dedup_threshold: float = 0.90
    ocr_batch_size: int = 50
    max_workers: int = 4
    ocr_backend: str = "docling"  # "docling", "pymupdf", or "both"

    # AI / Vision settings
    vision_model: str = "llava"  # for image description
    summarizer_provider: str = "ollama"
    summarizer_model: str = "llama3.2"

    # Transcription
    whisper_model: str = "auto"
    whisper_device: str = "auto"

    # Captioning
    caption_model: str = "microsoft/Florence-2-base"
    caption_char_threshold: int = 100
    caption_min_image_size: int = 50

    # Image extraction / analysis
    image_analysis_model: str = "Qwen/Qwen2-VL-2B-Instruct"
    image_min_bytes: int = 5120
    image_page_scan_ratio: float = 0.8

    # Redaction
    redaction_workers: int = 4

    # Embedding settings
    embedding_model: str = "nomic-ai/nomic-embed-text-v2-moe"
    embedding_dimensions: int = 768  # 768 full, 256 Matryoshka
    embedding_chunk_size: int = 3200  # chars (~800 tokens)
    embedding_chunk_overlap: int = 800  # chars (~200 tokens)
    embedding_batch_size: int | None = None  # None = auto-detect
    embedding_device: str | None = None  # None = auto-detect

    @classmethod
    def from_case(cls, case: "CaseConfig") -> "Settings":
        """Create Settings from a CaseConfig.

        This bridges the per-case YAML configuration into the flat Settings
        object that processors expect.
        """
        from casestack.case import CaseConfig  # noqa: F811

        return cls(
            data_dir=case.data_dir,
            output_dir=case.output_dir,
            cache_dir=case.cache_dir,
            persons_registry_path=(
                case.registry_path
                or case.data_dir / "persons-registry.json"
            ),
            spacy_model=case.spacy_model,
            dedup_threshold=case.dedup_threshold,
            max_workers=case.ocr_workers,
            ocr_backend=case.ocr_backend,
            embedding_model=case.embedding_model,
            embedding_dimensions=case.embedding_dimensions,
            whisper_model=case.whisper_model,
            whisper_device=case.whisper_device,
            caption_model=case.caption_model,
            caption_char_threshold=case.caption_char_threshold,
            caption_min_image_size=case.caption_min_image_size,
            image_analysis_model=case.image_analysis_model,
            image_min_bytes=case.image_min_bytes,
            image_page_scan_ratio=case.image_page_scan_ratio,
            redaction_workers=case.redaction_workers,
        )

    def ensure_dirs(self) -> None:
        """Create data, output, and cache directories if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
