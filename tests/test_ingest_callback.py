"""Tests for IngestCallback protocol."""
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def test_callback_protocol_exists():
    """IngestCallback is importable."""
    from casestack.ingest import IngestCallback
    assert hasattr(IngestCallback, 'on_step_start')
    assert hasattr(IngestCallback, 'on_step_progress')
    assert hasattr(IngestCallback, 'on_step_complete')
    assert hasattr(IngestCallback, 'on_log')
    assert hasattr(IngestCallback, 'on_complete')
    assert hasattr(IngestCallback, 'on_error')


def test_ingest_accepts_callback_parameter():
    """run_ingest accepts a callback parameter."""
    import inspect
    from casestack.ingest import run_ingest
    sig = inspect.signature(run_ingest)
    assert 'callback' in sig.parameters


def test_recording_callback(tmp_path):
    """A recording callback receives events during a minimal ingest."""
    # Create minimal case
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "test.txt").write_text("Hello world test document")

    from casestack.case import CaseConfig
    case = CaseConfig(
        name="CB Test", slug="cb-test",
        documents_dir=str(docs_dir),
        output_dir=str(tmp_path / "output"),
    )

    # Create a recording callback
    events = []

    class RecordingCallback:
        def on_step_start(self, step_id, total):
            events.append(('start', step_id, total))
        def on_step_progress(self, step_id, current, total):
            events.append(('progress', step_id, current, total))
        def on_step_complete(self, step_id, stats):
            events.append(('complete', step_id))
        def on_log(self, message, level):
            events.append(('log', message))
        def on_complete(self, stats):
            events.append(('done', stats))
        def on_error(self, step_id, message):
            events.append(('error', step_id, message))

    from casestack.ingest import run_ingest
    # Disable most steps to make it fast
    overrides = {
        "ocr": False, "transcription": False, "doc_conversion": True,
        "page_captions": False, "image_extraction": False, "image_analysis": False,
        "entities": False, "dedup": False, "embeddings": False,
        "knowledge_graph": False, "redaction_analysis": False,
    }
    run_ingest(case, skip_overrides=overrides, callback=RecordingCallback())

    # Should have received at least some events
    assert len(events) > 0
    start_events = [e for e in events if e[0] == 'start']
    done_events = [e for e in events if e[0] == 'done']
    assert len(done_events) == 1
