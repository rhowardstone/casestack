"""Case configuration — loaded from case.yaml."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


# Aliases for nested YAML keys (section, key) -> model field
_ALIASES: dict[tuple[str, str], str] = {
    ("entities", "types"): "entity_types",
    ("entities", "registry"): "registry_path",
    ("entities", "fuzzy_threshold"): "fuzzy_threshold",
    ("entities", "spacy_model"): "spacy_model",
    ("dedup", "threshold"): "dedup_threshold",
    ("dedup", "bates_prefixes"): "bates_prefixes",
    ("serve", "port"): "serve_port",
    ("serve", "title"): "serve_title",
    ("transcription", "model"): "whisper_model",
    ("transcription", "device"): "whisper_device",
    ("captioning", "model"): "caption_model",
    ("captioning", "char_threshold"): "caption_char_threshold",
    ("captioning", "min_image_size"): "caption_min_image_size",
    ("captioning", "image_analysis_model"): "image_analysis_model",
    ("images", "min_size"): "caption_min_image_size",
    ("images", "min_bytes"): "image_min_bytes",
    ("images", "page_scan_ratio"): "image_page_scan_ratio",
    ("images", "analysis_model"): "image_analysis_model",
    ("redaction", "workers"): "redaction_workers",
}

# Aliases for 3-level nested keys: section_subsection_key -> model field
_NESTED_ALIASES: dict[str, str] = {
    "serve_ask_proxy_enabled": "ask_proxy_enabled",
    "serve_ask_proxy_openrouter_api_key_env": "openrouter_api_key_env",
}


class CaseConfig(BaseModel):
    """Configuration for a single case/document collection."""

    model_config = {"populate_by_name": True}

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

    # Transcription
    whisper_model: str = "auto"
    whisper_device: str = "auto"

    # Captioning
    caption_model: str = "microsoft/Florence-2-base"
    caption_char_threshold: int = 100  # pages with fewer chars get captioned
    caption_min_image_size: int = 50  # skip extracted images smaller than NxN px

    # Image extraction / analysis
    image_analysis_model: str = "Qwen/Qwen2-VL-2B-Instruct"
    image_min_bytes: int = 5120  # skip images < 5KB
    image_page_scan_ratio: float = 0.8  # skip images covering >80% of page

    # Embeddings
    embedding_model: str = "nomic-ai/nomic-embed-text-v2-moe"
    embedding_dimensions: int = 768

    # Redaction
    redaction_workers: int = 4

    # Pipeline step overrides (step_id -> enabled)
    pipeline: dict[str, bool] = Field(default_factory=dict)

    # Serving
    serve_port: int = 8001
    serve_title: str = ""
    ask_proxy_enabled: bool = False
    openrouter_api_key_env: str = "OPENROUTER_API_KEY"

    # Optional absolute path overrides — set in case.yaml or by the API at
    # case-creation time.  When None the legacy relative paths are used.
    output_dir_override: Optional[Path] = Field(default=None, alias="output_dir")

    @property
    def data_dir(self) -> Path:
        return Path(f"./data/{self.slug}")

    @property
    def output_dir(self) -> Path:
        if self.output_dir_override is not None:
            return self.output_dir_override
        return Path(f"./output/{self.slug}")

    @property
    def cache_dir(self) -> Path:
        return Path(f"./.cache/{self.slug}")

    @property
    def db_path(self) -> Path:
        return self.output_dir / f"{self.slug}.db"

    def is_step_enabled(self, step_id: str) -> bool:
        """Check if a pipeline step is enabled for this case."""
        from casestack.pipeline import get_enabled_steps

        return step_id in get_enabled_steps(self.pipeline or None)

    @classmethod
    def from_yaml(cls, path: Path) -> CaseConfig:
        """Load case config from a YAML file.

        Supports nested sections like:
            ocr:
              backend: "pymupdf"
              workers: 4
        Which get flattened to ocr_backend, ocr_workers.
        """
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid case config: {path} (expected YAML mapping, got {type(raw).__name__})")
        flat: dict = {}
        for key, value in raw.items():
            if isinstance(value, dict) and key in ("ocr", "serve", "entities", "dedup", "transcription", "captioning", "images", "redaction"):
                for sub_key, sub_value in value.items():
                    # Handle nested dicts (e.g., serve.ask_proxy.enabled)
                    if isinstance(sub_value, dict):
                        for k2, v2 in sub_value.items():
                            nested_key = f"{key}_{sub_key}_{k2}"
                            nested_alias = _NESTED_ALIASES.get(nested_key, nested_key)
                            flat[nested_alias] = v2
                        continue
                    # Map nested keys with explicit aliases
                    alias = _ALIASES.get((key, sub_key))
                    flat[alias or f"{key}_{sub_key}"] = sub_value
            else:
                flat[key] = value
        return cls(**flat)
