"""Document staging routes — upload, extract archives, manage intake."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from casestack.api.deps import get_casestack_home

router = APIRouter()

ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z"}
SUPPORTED_EXTENSIONS = {
    ".pdf", ".mp3", ".mp4", ".m4a", ".m4v", ".wav", ".flac", ".ogg", ".avi",
    ".mov", ".wmv", ".webm", ".mkv", ".vob", ".ts",
    ".txt", ".md", ".csv", ".html", ".htm", ".json", ".xml",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp",
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z",
}


def _staging_dir() -> Path:
    d = get_casestack_home() / "staging"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _scan_dir(directory: Path) -> dict:
    """Count files by type in a directory."""
    counts: dict[str, int] = {}
    errors: list[str] = []
    for f in directory.rglob("*"):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        category = _categorize(ext)
        counts[category] = counts.get(category, 0) + 1
    counts["total"] = sum(counts.values())
    return {"counts": counts, "errors": errors}


def _categorize(ext: str) -> str:
    if ext == ".pdf":
        return "pdf"
    if ext in {".mp3", ".mp4", ".m4a", ".m4v", ".wav", ".flac", ".ogg", ".avi",
               ".mov", ".wmv", ".webm", ".mkv", ".vob", ".ts"}:
        return "media"
    if ext in {".txt", ".md", ".csv", ".html", ".htm", ".json", ".xml"}:
        return "text"
    if ext in {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp"}:
        return "office"
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"}:
        return "image"
    # Return the actual extension instead of generic "other"
    return ext.lstrip(".") if ext else "other"


def _extract_archive(archive_path: Path, dest: Path) -> list[str]:
    """Extract an archive, return list of extracted file names."""
    import tarfile
    import zipfile

    name = archive_path.name.lower()
    extracted = []

    if name.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(dest)
            extracted = zf.namelist()
    elif name.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")):
        with tarfile.open(archive_path, "r:*") as tf:
            tf.extractall(dest, filter="data")
            extracted = tf.getnames()
    elif name.endswith(".gz") and not name.endswith(".tar.gz"):
        import gzip
        out_name = archive_path.stem
        with gzip.open(archive_path, "rb") as gz:
            (dest / out_name).write_bytes(gz.read())
        extracted = [out_name]
    elif name.endswith(".bz2") and not name.endswith(".tar.bz2"):
        import bz2
        out_name = archive_path.stem
        with bz2.open(archive_path, "rb") as bz:
            (dest / out_name).write_bytes(bz.read())
        extracted = [out_name]

    # Remove the archive after extraction
    archive_path.unlink(missing_ok=True)
    return extracted


class AddLocalDirRequest(BaseModel):
    path: str


@router.post("/staging/create")
def create_session():
    """Create a new staging session, returns session_id."""
    session_id = uuid.uuid4().hex[:12]
    session_dir = _staging_dir() / session_id
    session_dir.mkdir(parents=True)
    return {"session_id": session_id, "path": str(session_dir)}


@router.post("/staging/{session_id}/upload")
async def upload_files(session_id: str, files: list[UploadFile] = File(...)):
    """Upload files (including archives) to a staging session."""
    session_dir = _staging_dir() / session_id
    if not session_dir.is_dir():
        raise HTTPException(404, "Staging session not found")

    results = []
    for upload in files:
        fname = upload.filename or "unnamed"
        dest = session_dir / fname

        # Save file — create parent dirs for nested paths (e.g. from webkitdirectory)
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = await upload.read()
        dest.write_bytes(content)

        ext = dest.suffix.lower()
        is_archive = ext in ARCHIVE_EXTENSIONS or fname.lower().endswith((".tar.gz", ".tar.bz2", ".tar.xz"))

        if is_archive:
            try:
                extracted = _extract_archive(dest, session_dir)
                results.append({
                    "name": fname,
                    "type": "archive",
                    "status": "extracted",
                    "files_extracted": len(extracted),
                })
            except Exception as e:
                results.append({
                    "name": fname,
                    "type": "archive",
                    "status": "error",
                    "error": str(e),
                })
        else:
            results.append({
                "name": fname,
                "type": _categorize(ext),
                "status": "ok",
                "size": len(content),
            })

    scan = _scan_dir(session_dir)
    return {"uploads": results, **scan}


@router.post("/staging/{session_id}/add-local")
def add_local_directory(session_id: str, body: AddLocalDirRequest):
    """Reference a local directory (localhost mode). Creates a symlink."""
    session_dir = _staging_dir() / session_id
    if not session_dir.is_dir():
        raise HTTPException(404, "Staging session not found")

    src = Path(body.path)
    if not src.is_dir():
        raise HTTPException(400, f"Directory not found: {body.path}")

    # Write a marker file so we know this session references a local dir
    (session_dir / ".local_ref").write_text(str(src))

    scan = _scan_dir(src)
    return {"path": str(src), "mode": "local_reference", **scan}


@router.get("/staging/{session_id}")
def get_session(session_id: str):
    """Get staging session status and file counts."""
    session_dir = _staging_dir() / session_id
    if not session_dir.is_dir():
        raise HTTPException(404, "Staging session not found")

    local_ref = session_dir / ".local_ref"
    if local_ref.exists():
        src = Path(local_ref.read_text().strip())
        scan = _scan_dir(src)
        return {"session_id": session_id, "mode": "local_reference", "path": str(src), **scan}

    scan = _scan_dir(session_dir)
    return {"session_id": session_id, "mode": "uploaded", "path": str(session_dir), **scan}


@router.delete("/staging/{session_id}")
def delete_session(session_id: str):
    """Clean up a staging session."""
    session_dir = _staging_dir() / session_id
    if session_dir.is_dir():
        shutil.rmtree(session_dir)
    return {"status": "deleted"}
