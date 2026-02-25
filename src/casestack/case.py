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
        """Load case config from a YAML file.

        Supports nested sections like:
            ocr:
              backend: "pymupdf"
              workers: 4
        Which get flattened to ocr_backend, ocr_workers.
        """
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        flat: dict = {}
        for key, value in raw.items():
            if isinstance(value, dict) and key in ("ocr", "serve", "entities", "dedup"):
                for sub_key, sub_value in value.items():
                    # Map nested keys: ocr.backend -> ocr_backend, entities.types -> entity_types
                    if key == "entities" and sub_key == "types":
                        flat["entity_types"] = sub_value
                    elif key == "entities" and sub_key == "registry":
                        flat["registry_path"] = sub_value
                    elif key == "dedup" and sub_key == "threshold":
                        flat["dedup_threshold"] = sub_value
                    elif key == "serve" and sub_key == "port":
                        flat["serve_port"] = sub_value
                    elif key == "serve" and sub_key == "title":
                        flat["serve_title"] = sub_value
                    else:
                        flat[f"{key}_{sub_key}"] = sub_value
            else:
                flat[key] = value
        return cls(**flat)
