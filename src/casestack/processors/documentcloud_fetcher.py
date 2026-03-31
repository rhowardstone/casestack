"""DocumentCloud ingest connector.

Downloads PDFs (and optional annotations) from a DocumentCloud project into a
local directory, where they are picked up by the standard Casestack ingest
pipeline.

DocumentCloud REST API is used directly (no auth required for public projects).
Authenticated access requires DOCUMENTCLOUD_USERNAME + DOCUMENTCLOUD_PASSWORD
environment variables.

URL patterns accepted:
  - https://www.documentcloud.org/projects/12345-my-project/
  - https://www.documentcloud.org/projects/my-project/  (slug-only, resolves via search)
  - "12345"  (project ID as string)

PDF storage:
  PDFs are written as {document_id}-{slug}.pdf so filenames are stable across
  re-fetches.  Files already present are skipped (unless overwrite=True).

Annotations:
  Optional.  Saved as {document_id}-{slug}.json (DocumentCloud annotation JSON).
"""
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Iterator

import httpx

logger = logging.getLogger(__name__)

_DC_API = "https://api.www.documentcloud.org/api"
_DC_S3 = "https://s3.documentcloud.org"

# Seconds to sleep between page fetches to stay within rate limits
_PAGE_SLEEP = 0.25


class DocumentCloudFetcher:
    """Download PDFs from a DocumentCloud project.

    Parameters
    ----------
    username : str | None
        DocumentCloud username (for private projects).
    password : str | None
        DocumentCloud password.
    timeout : float
        HTTP request timeout in seconds.
    """

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._username = username or os.environ.get("DOCUMENTCLOUD_USERNAME")
        self._password = password or os.environ.get("DOCUMENTCLOUD_PASSWORD")
        self._timeout = timeout
        self._auth_headers: dict[str, str] = {}
        if self._username and self._password:
            self._auth_headers = self._get_auth_token()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_project(
        self,
        project_ref: str,
        output_dir: Path,
        *,
        overwrite: bool = False,
        fetch_annotations: bool = False,
        max_docs: int | None = None,
    ) -> list[dict]:
        """Download all PDFs from a DocumentCloud project.

        Parameters
        ----------
        project_ref : str
            Project URL, slug, or numeric ID.
        output_dir : Path
            Directory to write PDFs (created if absent).
        overwrite : bool
            Re-download even if PDF already exists.
        fetch_annotations : bool
            Also save annotation JSON alongside each PDF.
        max_docs : int | None
            Limit number of documents fetched (for testing / incremental runs).

        Returns
        -------
        list[dict]
            Metadata for each downloaded document
            (id, title, slug, pages, pdf_path).
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        project_id = self._resolve_project_id(project_ref)
        logger.info("Fetching project %s → %s", project_id, output_dir)

        fetched: list[dict] = []
        for doc in self._iter_project_docs(project_id):
            if max_docs is not None and len(fetched) >= max_docs:
                break

            pdf_path = output_dir / f"{doc['id']}-{doc['slug']}.pdf"
            if pdf_path.exists() and not overwrite:
                logger.debug("Skip existing: %s", pdf_path.name)
                fetched.append({**doc, "pdf_path": pdf_path, "status": "skipped"})
                continue

            try:
                self._download_pdf(doc, pdf_path)
                if fetch_annotations:
                    ann_path = output_dir / f"{doc['id']}-{doc['slug']}-annotations.json"
                    self._download_annotations(doc["id"], ann_path)
                fetched.append({**doc, "pdf_path": pdf_path, "status": "downloaded"})
                logger.info("Downloaded: %s (%d pages)", pdf_path.name, doc.get("page_count", 0))
            except Exception as exc:
                logger.warning("Failed to download %s: %s", doc["slug"], exc)
                fetched.append({**doc, "pdf_path": None, "status": "failed", "error": str(exc)})

        downloaded = sum(1 for d in fetched if d["status"] == "downloaded")
        skipped = sum(1 for d in fetched if d["status"] == "skipped")
        failed = sum(1 for d in fetched if d["status"] == "failed")
        logger.info(
            "Project %s: %d downloaded, %d skipped, %d failed",
            project_id, downloaded, skipped, failed,
        )
        return fetched

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_project_id(self, ref: str) -> str:
        """Extract numeric project ID from a URL, slug, or raw ID string."""
        ref = ref.strip().rstrip("/")

        # Numeric ID already
        if re.fullmatch(r"\d+", ref):
            return ref

        # URL with numeric project ID: /projects/12345-slug/
        m = re.search(r"/projects/(\d+)", ref)
        if m:
            return m.group(1)

        # Slug-only URL or bare slug — search by slug
        slug = ref.split("/")[-1]
        r = self._get(f"{_DC_API}/projects/", params={"slug": slug})
        results = r.json().get("results", [])
        if not results:
            raise ValueError(f"No DocumentCloud project found for: {ref!r}")
        return str(results[0]["id"])

    def _iter_project_docs(self, project_id: str) -> Iterator[dict]:
        """Paginate through all documents in a project."""
        url = f"{_DC_API}/documents/"
        params: dict = {"project": project_id, "per_page": 25, "ordering": "id"}

        while url:
            r = self._get(url, params=params)
            data = r.json()
            for doc in data.get("results", []):
                yield doc
            url = data.get("next")  # type: ignore[assignment]
            params = {}  # next URL already contains params
            if url:
                time.sleep(_PAGE_SLEEP)

    def _download_pdf(self, doc: dict, dest: Path) -> None:
        """Download a document's PDF to *dest*."""
        pdf_url = f"{_DC_S3}/documents/{doc['id']}/{doc['slug']}.pdf"
        r = self._get(pdf_url, stream=True)
        dest.write_bytes(r.content)

    def _download_annotations(self, doc_id: int | str, dest: Path) -> None:
        """Download annotations JSON for a document."""
        import json
        r = self._get(f"{_DC_API}/documents/{doc_id}/annotations/")
        dest.write_text(json.dumps(r.json(), indent=2, ensure_ascii=False), encoding="utf-8")

    def _get_auth_token(self) -> dict[str, str]:
        """Obtain a Bearer token from MuckRock accounts API."""
        try:
            r = httpx.post(
                "https://accounts.muckrock.com/api/token/",
                data={"username": self._username, "password": self._password},
                timeout=self._timeout,
            )
            r.raise_for_status()
            token = r.json()["access"]
            return {"Authorization": f"Bearer {token}"}
        except Exception as exc:
            logger.warning("DocumentCloud auth failed: %s — using anonymous access", exc)
            return {}

    def _get(self, url: str, params: dict | None = None, stream: bool = False) -> httpx.Response:
        r = httpx.get(
            url,
            params=params,
            headers=self._auth_headers,
            timeout=self._timeout,
            follow_redirects=True,
        )
        r.raise_for_status()
        return r
