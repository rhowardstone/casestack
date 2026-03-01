"""Image captioning processor using Florence-2 for image-heavy document pages."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from casestack.config import Settings
from casestack.models.forensics import PageCaption

logger = logging.getLogger(__name__)

# Bates identifier pattern: uppercase letters followed by digits, nothing else
_BATES_RE = re.compile(r"^[A-Z]+\d+$")


def _is_image_heavy(text: str, char_threshold: int = 100) -> bool:
    """Return True if the page text suggests an image-heavy page.

    A page is image-heavy if:
    - char_count < threshold (just a Bates stamp or near-blank), OR
    - The text is only a Bates identifier pattern after stripping whitespace
    """
    stripped = text.strip()
    if len(stripped) < char_threshold:
        return True
    if _BATES_RE.match(stripped):
        return True
    return False


class CaptionProcessor:
    """Caption image-heavy document pages using Florence-2."""

    def __init__(
        self,
        settings: Settings,
        model_name: str = "microsoft/Florence-2-base",
    ) -> None:
        self._model = None
        self._processor = None
        self._model_name = model_name
        self._settings = settings

    def _load_model(self) -> None:
        """Load Florence-2 to GPU. Called once on first use."""
        if self._model is not None:
            return

        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor

        logger.info("Loading Florence-2 model: %s", self._model_name)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if device == "cuda" else torch.float32

        # Florence-2 remote code may define _supports_sdpa as a read-only
        # property that's incompatible with newer transformers. Patch the
        # dispatch method to gracefully handle missing/broken _supports_sdpa.
        import transformers.modeling_utils

        def _safe_sdpa_dispatch(self_inner, is_init_check=False):
            try:
                return self_inner._supports_sdpa
            except (AttributeError, TypeError):
                return False

        transformers.modeling_utils.PreTrainedModel._sdpa_can_dispatch = _safe_sdpa_dispatch

        model = AutoModelForCausalLM.from_pretrained(
            self._model_name,
            torch_dtype=dtype,
            trust_remote_code=True,
        )
        self._model = model.to(device)
        self._processor = AutoProcessor.from_pretrained(
            self._model_name,
            trust_remote_code=True,
        )
        self._device = device
        self._dtype = dtype
        logger.info("Florence-2 loaded on %s", device)

    def _run_task(self, image: "PIL.Image.Image", task: str) -> str:
        """Run a Florence-2 task on an image and return the text result."""
        import torch

        inputs = self._processor(text=task, images=image, return_tensors="pt")
        inputs = {
            k: v.to(device=self._device, dtype=self._dtype)
            if v.is_floating_point()
            else v.to(self._device)
            for k, v in inputs.items()
        }

        with torch.inference_mode():
            generated = self._model.generate(
                **inputs,
                max_new_tokens=512,
                num_beams=1,
                use_cache=False,
            )

        decoded = self._processor.batch_decode(generated, skip_special_tokens=False)[0]
        result = self._processor.post_process_generation(
            decoded, task=task, image_size=(image.width, image.height)
        )
        # Result is a dict like {task: "text"} — extract the value
        if isinstance(result, dict):
            return str(next(iter(result.values()), ""))
        return str(result)

    def caption_page(self, image: "PIL.Image.Image") -> tuple[str, str | None]:
        """Return (caption, ocr_text) for a single page image.

        Runs DETAILED_CAPTION, then optionally OCR if the caption
        suggests handwriting or text content.
        """
        self._load_model()

        caption = self._run_task(image, "<DETAILED_CAPTION>")

        # Run OCR if caption mentions handwriting, text, letter, note, etc.
        ocr_text = None
        text_hints = {"handwrit", "letter", "note", "memo", "text", "written", "document"}
        if any(hint in caption.lower() for hint in text_hints):
            ocr_result = self._run_task(image, "<OCR>")
            if ocr_result.strip():
                ocr_text = ocr_result.strip()

        return caption, ocr_text

    def process_batch(
        self,
        ocr_dir: Path,
        documents_dir: Path,
        output_dir: Path,
        char_threshold: int = 100,
    ) -> list[PageCaption]:
        """Find image-heavy pages, render from PDF, caption with Florence-2.

        Parameters
        ----------
        ocr_dir:
            Directory containing OCR JSON output files.
        documents_dir:
            Directory containing source PDF files.
        output_dir:
            Pipeline output directory (captions saved under output_dir/captions/).
        char_threshold:
            Pages with fewer characters than this are considered image-heavy.

        Returns
        -------
        list[PageCaption]
            All generated captions.
        """
        import fitz  # PyMuPDF
        from PIL import Image
        import io

        captions_dir = output_dir / "captions"
        captions_dir.mkdir(parents=True, exist_ok=True)

        # Resume: skip OCR keys already captioned
        existing = set(f.stem for f in captions_dir.glob("*.json"))

        # 1. Scan OCR JSON to find image-heavy pages, grouped by source PDF
        # Structure: {ocr_key: {"source_path": str, "pages": [(doc_id, page_num), ...]}}
        pdf_groups: dict[str, dict] = {}
        json_files = sorted(ocr_dir.glob("*.json"))

        for jf in json_files:
            try:
                raw = json.loads(jf.read_text(encoding="utf-8"))
                doc_data = raw.get("document") or raw
                doc_id = doc_data.get("id", "")
                source_path = raw.get("source_path", "")
                pages_data = raw.get("pages", [])

                for page in pages_data:
                    text = page.get("text_content", "")
                    page_num = page.get("page_number", 0)
                    if _is_image_heavy(text, char_threshold):
                        ocr_key = jf.stem
                        if ocr_key not in pdf_groups:
                            pdf_groups[ocr_key] = {
                                "source_path": source_path,
                                "pages": [],
                            }
                        pdf_groups[ocr_key]["pages"].append((doc_id, page_num))
            except Exception:
                continue

        # Filter out already-processed groups
        to_process = {k: v for k, v in pdf_groups.items() if k not in existing}

        if not to_process:
            total_existing = sum(1 for _ in captions_dir.glob("*.json"))
            if total_existing:
                logger.info("Captioning resume: all %d PDFs already processed", total_existing)
            return self._load_existing_captions(captions_dir)

        total_pages = sum(len(v["pages"]) for v in to_process.values())
        logger.info(
            "Captioning: %d PDFs with %d image-heavy pages (%d already done)",
            len(to_process),
            total_pages,
            len(existing),
        )

        all_captions: list[PageCaption] = []

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
        )

        with progress:
            task = progress.add_task("Captioning", total=total_pages)

            for ocr_key, group in to_process.items():
                source_path = group["source_path"]
                page_list = group["pages"]

                # Resolve PDF path: use source_path from OCR, fall back to search
                pdf_path = Path(source_path) if source_path else None
                if pdf_path is None or not pdf_path.exists():
                    pdf_path = self._find_pdf(documents_dir, ocr_key)
                if pdf_path is None or not pdf_path.exists():
                    logger.warning(
                        "Source PDF not found for %s (tried %s) — skipping",
                        ocr_key,
                        source_path,
                    )
                    progress.advance(task, len(page_list))
                    continue

                pdf_name = pdf_path.stem
                pdf_captions: list[dict] = []

                try:
                    doc = fitz.open(str(pdf_path))
                    for doc_id, page_num in page_list:
                        progress.update(
                            task,
                            description=f"Caption: {pdf_name} p{page_num}",
                        )

                        try:
                            # Page numbers in OCR are 1-based, fitz is 0-based
                            fitz_page = doc[page_num - 1]
                            pix = fitz_page.get_pixmap(dpi=150)
                            img_bytes = pix.tobytes("png")
                            image = Image.open(io.BytesIO(img_bytes)).convert("RGB")

                            caption, ocr_text = self.caption_page(image)

                            pc = PageCaption(
                                document_id=doc_id,
                                page_number=page_num,
                                caption=caption,
                                ocr_text=ocr_text,
                            )
                            all_captions.append(pc)
                            pdf_captions.append(pc.model_dump())

                        except Exception as exc:
                            logger.warning(
                                "Failed to caption %s page %d: %s",
                                pdf_name,
                                page_num,
                                exc,
                            )

                        progress.advance(task)

                    doc.close()

                except Exception as exc:
                    logger.warning("Failed to open PDF %s: %s", pdf_path, exc)
                    progress.advance(task, len(page_list))

                # Save after each PDF (crash-safe)
                if pdf_captions:
                    out_path = captions_dir / f"{ocr_key}.json"
                    out_path.write_text(
                        json.dumps(pdf_captions, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )

        return all_captions

    def _find_pdf(self, documents_dir: Path, stem: str) -> Path | None:
        """Find a PDF by stem name in the documents directory."""
        # Direct match
        direct = documents_dir / f"{stem}.pdf"
        if direct.exists():
            return direct
        # Recursive search
        matches = list(documents_dir.rglob(f"{stem}.pdf"))
        if matches:
            return matches[0]
        # Case-insensitive fallback
        for p in documents_dir.rglob("*.pdf"):
            if p.stem.lower() == stem.lower():
                return p
        return None

    def _load_existing_captions(self, captions_dir: Path) -> list[PageCaption]:
        """Load all previously saved captions from disk."""
        captions: list[PageCaption] = []
        for jf in sorted(captions_dir.glob("*.json")):
            try:
                raw = json.loads(jf.read_text(encoding="utf-8"))
                for entry in raw:
                    captions.append(PageCaption.model_validate(entry))
            except Exception:
                continue
        return captions
