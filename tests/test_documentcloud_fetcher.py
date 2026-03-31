"""Tests for DocumentCloudFetcher.

Uses httpx mocking (no real network calls) to test URL resolution, pagination,
PDF download, and error handling.
"""
from __future__ import annotations

import json
import struct
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from casestack.processors.documentcloud_fetcher import DocumentCloudFetcher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_doc(doc_id: int, slug: str, pages: int = 5) -> dict:
    return {
        "id": doc_id,
        "title": slug.replace("-", " ").title(),
        "slug": slug,
        "access": "public",
        "page_count": pages,
        "asset_url": "https://s3.documentcloud.org/",
    }


def _mock_get(responses: dict):
    """Return a mock _get method that returns canned responses by URL."""
    def _get(url, params=None, stream=False):
        # Match by URL prefix
        for key, response in responses.items():
            if key in url:
                mock = MagicMock()
                mock.content = response if isinstance(response, bytes) else b""
                mock.json.return_value = response if isinstance(response, dict) else {}
                mock.raise_for_status.return_value = None
                return mock
        raise ValueError(f"No mock for URL: {url}")
    return _get


# ---------------------------------------------------------------------------
# _resolve_project_id
# ---------------------------------------------------------------------------

class TestResolveProjectId:
    def _fetcher(self):
        f = DocumentCloudFetcher.__new__(DocumentCloudFetcher)
        f._auth_headers = {}
        f._timeout = 10.0
        return f

    def test_numeric_id_returned_as_is(self):
        f = self._fetcher()
        assert f._resolve_project_id("12345") == "12345"

    def test_extracts_id_from_url(self):
        f = self._fetcher()
        url = "https://www.documentcloud.org/projects/31049-my-project/"
        assert f._resolve_project_id(url) == "31049"

    def test_extracts_id_from_url_no_trailing_slash(self):
        f = self._fetcher()
        url = "https://www.documentcloud.org/projects/99999-something"
        assert f._resolve_project_id(url) == "99999"

    def test_slug_lookup_calls_api(self):
        f = self._fetcher()
        f._get = _mock_get({
            "/projects/": {"results": [{"id": 777, "slug": "my-slug"}]}
        })
        result = f._resolve_project_id("my-slug")
        assert result == "777"

    def test_slug_lookup_raises_when_not_found(self):
        f = self._fetcher()
        f._get = _mock_get({"/projects/": {"results": []}})
        with pytest.raises(ValueError, match="No DocumentCloud project"):
            f._resolve_project_id("nonexistent-slug")


# ---------------------------------------------------------------------------
# _iter_project_docs
# ---------------------------------------------------------------------------

class TestIterProjectDocs:
    def _fetcher(self):
        f = DocumentCloudFetcher.__new__(DocumentCloudFetcher)
        f._auth_headers = {}
        f._timeout = 10.0
        return f

    def test_single_page_returns_all_docs(self):
        docs = [_make_doc(1, "doc-one"), _make_doc(2, "doc-two")]
        f = self._fetcher()
        f._get = _mock_get({
            "/documents/": {"next": None, "results": docs}
        })
        result = list(f._iter_project_docs("123"))
        assert len(result) == 2
        assert result[0]["id"] == 1

    def test_pagination_follows_next_url(self):
        page1 = {"next": "https://api/documents/?cursor=abc", "results": [_make_doc(1, "a")]}
        page2 = {"next": None, "results": [_make_doc(2, "b")]}
        calls = []

        def _get(url, params=None, stream=False):
            calls.append(url)
            mock = MagicMock()
            mock.raise_for_status.return_value = None
            if "cursor" in url:
                mock.json.return_value = page2
            else:
                mock.json.return_value = page1
            return mock

        f = self._fetcher()
        f._get = _get
        with patch("casestack.processors.documentcloud_fetcher.time.sleep"):
            result = list(f._iter_project_docs("123"))
        assert len(result) == 2
        assert len(calls) == 2  # two HTTP calls

    def test_empty_project_returns_nothing(self):
        f = self._fetcher()
        f._get = _mock_get({"/documents/": {"next": None, "results": []}})
        result = list(f._iter_project_docs("123"))
        assert result == []


# ---------------------------------------------------------------------------
# fetch_project
# ---------------------------------------------------------------------------

class TestFetchProject:
    def _fetcher(self, responses: dict):
        f = DocumentCloudFetcher.__new__(DocumentCloudFetcher)
        f._auth_headers = {}
        f._timeout = 10.0
        f._get = _mock_get(responses)
        return f

    def test_pdfs_written_to_output_dir(self, tmp_path):
        doc = _make_doc(42, "test-document")
        fake_pdf = b"%PDF-1.4 fake content"
        f = DocumentCloudFetcher.__new__(DocumentCloudFetcher)
        f._auth_headers = {}
        f._timeout = 10.0

        def _get(url, params=None, stream=False):
            mock = MagicMock()
            mock.raise_for_status.return_value = None
            if "documents/" in url and not "annotations" in url and params:
                mock.json.return_value = {"next": None, "results": [doc]}
            elif str(doc["id"]) in url and url.endswith(".pdf"):
                mock.content = fake_pdf
                mock.json.return_value = {}
            elif "projects" in url:
                mock.json.return_value = {"next": None, "results": []}
            else:
                mock.json.return_value = {"next": None, "results": [doc]}
            return mock

        f._get = _get
        # Bypass _resolve_project_id
        with patch.object(f, "_resolve_project_id", return_value="123"):
            results = f.fetch_project("123", tmp_path)

        assert len(results) == 1
        assert results[0]["status"] == "downloaded"
        pdf_path = tmp_path / f"{doc['id']}-{doc['slug']}.pdf"
        assert pdf_path.exists()
        assert pdf_path.read_bytes() == fake_pdf

    def test_existing_pdf_skipped_by_default(self, tmp_path):
        doc = _make_doc(10, "existing-doc")
        # Pre-create the PDF
        pdf_path = tmp_path / f"{doc['id']}-{doc['slug']}.pdf"
        pdf_path.write_bytes(b"existing content")

        f = DocumentCloudFetcher.__new__(DocumentCloudFetcher)
        f._auth_headers = {}
        f._timeout = 10.0

        def _get(url, params=None, stream=False):
            mock = MagicMock()
            mock.raise_for_status.return_value = None
            mock.json.return_value = {"next": None, "results": [doc]}
            mock.content = b"new content"
            return mock

        f._get = _get
        with patch.object(f, "_resolve_project_id", return_value="123"):
            results = f.fetch_project("123", tmp_path)

        assert results[0]["status"] == "skipped"
        # Original content untouched
        assert pdf_path.read_bytes() == b"existing content"

    def test_max_docs_limits_download(self, tmp_path):
        docs = [_make_doc(i, f"doc-{i}") for i in range(5)]

        f = DocumentCloudFetcher.__new__(DocumentCloudFetcher)
        f._auth_headers = {}
        f._timeout = 10.0

        def _get(url, params=None, stream=False):
            mock = MagicMock()
            mock.raise_for_status.return_value = None
            mock.json.return_value = {"next": None, "results": docs}
            mock.content = b"%PDF fake"
            return mock

        f._get = _get
        with patch.object(f, "_resolve_project_id", return_value="123"):
            results = f.fetch_project("123", tmp_path, max_docs=2)

        assert len(results) == 2

    def test_failed_download_reported_not_raised(self, tmp_path):
        doc = _make_doc(99, "bad-doc")

        f = DocumentCloudFetcher.__new__(DocumentCloudFetcher)
        f._auth_headers = {}
        f._timeout = 10.0
        call_count = [0]

        def _get(url, params=None, stream=False):
            mock = MagicMock()
            mock.raise_for_status.return_value = None
            call_count[0] += 1
            if "s3.documentcloud.org" in url:
                raise httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock())
            mock.json.return_value = {"next": None, "results": [doc]}
            mock.content = b""
            return mock

        import httpx
        f._get = _get
        with patch.object(f, "_resolve_project_id", return_value="123"):
            results = f.fetch_project("123", tmp_path)

        assert results[0]["status"] == "failed"
        assert "error" in results[0]
