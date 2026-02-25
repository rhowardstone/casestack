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
    assert config.db_path == Path("./output/test-case/test-case.db")


def test_nested_yaml_flattening():
    yaml_content = """
name: "Nested"
slug: "nested"
ocr:
  backend: "both"
  workers: 8
entities:
  types: ["PERSON", "ORG"]
  registry: "./my-registry.json"
dedup:
  threshold: 0.95
serve:
  port: 9000
  title: "My Title"
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        config = CaseConfig.from_yaml(Path(f.name))
    assert config.ocr_backend == "both"
    assert config.ocr_workers == 8
    assert config.entity_types == ["PERSON", "ORG"]
    assert config.registry_path == Path("./my-registry.json")
    assert config.dedup_threshold == 0.95
    assert config.serve_port == 9000
    assert config.serve_title == "My Title"


def test_nested_ask_proxy_config():
    yaml_content = """
name: "Ask Test"
slug: "ask-test"
serve:
  port: 8001
  ask_proxy:
    enabled: true
    openrouter_api_key_env: "MY_KEY"
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        config = CaseConfig.from_yaml(Path(f.name))
    assert config.ask_proxy_enabled is True
    assert config.openrouter_api_key_env == "MY_KEY"
    assert config.serve_port == 8001


def test_nested_spacy_model_and_bates():
    yaml_content = """
name: "Full"
slug: "full"
entities:
  spacy_model: "en_core_web_lg"
  fuzzy_threshold: 90
dedup:
  threshold: 0.85
  bates_prefixes: ["EFTA", "DOJ"]
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        config = CaseConfig.from_yaml(Path(f.name))
    assert config.spacy_model == "en_core_web_lg"
    assert config.fuzzy_threshold == 90
    assert config.dedup_threshold == 0.85
    assert config.bates_prefixes == ["EFTA", "DOJ"]


def test_settings_from_case():
    from casestack.config import Settings

    case = CaseConfig(name="Bridge", slug="bridge")
    settings = Settings.from_case(case)
    assert settings.data_dir == Path("./data/bridge")
    assert settings.output_dir == Path("./output/bridge")
    assert settings.ocr_backend == "pymupdf"
