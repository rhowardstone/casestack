"""Pipeline manifest and configuration routes."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from casestack.api.deps import get_app_state
from casestack.pipeline import get_manifest

router = APIRouter()


@router.get("/pipeline/manifest")
def global_manifest():
    """Return the global pipeline manifest (no case context)."""
    return get_manifest()


@router.get("/cases/{slug}/pipeline")
def case_pipeline(slug: str):
    """Return pipeline manifest with case-specific enablement."""
    state = get_app_state()
    case_info = state.get_case(slug)
    if not case_info:
        raise HTTPException(404, "Case not found")

    from casestack.case import CaseConfig
    case_yaml = Path(case_info["case_yaml_path"])
    if case_yaml.exists():
        case = CaseConfig.from_yaml(case_yaml)
    else:
        case = CaseConfig(name=case_info["name"], slug=slug)

    manifest = get_manifest()
    for step in manifest:
        step["enabled"] = case.is_step_enabled(step["id"])
    return {"steps": manifest, "pipeline_overrides": case.pipeline}
