from casestack.pipeline import PIPELINE_STEPS, get_manifest, get_enabled_steps


def test_manifest_has_all_steps():
    manifest = get_manifest()
    assert len(manifest) >= 10
    for step in manifest:
        assert step["id"]
        assert step["label"]
        assert step["description"]
        assert "default_enabled" in step


def test_enabled_steps_filters():
    overrides = {"ocr": False, "embeddings": True}
    enabled = get_enabled_steps(overrides)
    assert "ocr" not in enabled
    assert "embeddings" in enabled


def test_step_ids_unique():
    ids = [s.id for s in PIPELINE_STEPS]
    assert len(ids) == len(set(ids))
