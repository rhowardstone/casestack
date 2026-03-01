"""Image captioning processor for image-heavy document pages.

Supports two model backends:
- Florence-2 (default): ~0.9GB VRAM, fast task-based captions + OCR
- Qwen2-VL-2B: ~4.5GB VRAM, structured analysis with people/objects/text/setting
"""

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
from casestack.models.forensics import ExtractedImage, PageCaption

logger = logging.getLogger(__name__)

# Bates identifier pattern: uppercase letters followed by digits, nothing else
_BATES_RE = re.compile(r"^[A-Z]+\d+$")

_QWEN_ANALYSIS_PROMPT = """Analyze this document page image in detail. Extract:

1. PEOPLE: Describe each person visible (gender, approximate age, hair color, clothing, distinguishing features). Note if anyone appears to be a public figure.

2. TEXT: Transcribe ANY visible text exactly as written (signs, documents, labels, handwriting).

3. OBJECTS: List all significant objects (furniture, vehicles, electronics, bags, jewelry, etc.)

4. SETTING: Describe the setting (indoor/outdoor, type of room, landmarks, geographic hints).

5. ACTIVITY: What is happening in the image?

6. NOTABLE: Anything unusual, concerning, or potentially significant.

Format your response as:
PEOPLE: [descriptions]
TEXT: [any visible text]
OBJECTS: [list]
SETTING: [description]
ACTIVITY: [description]
NOTABLE: [observations]"""


def _is_image_heavy(text: str, char_threshold: int = 100) -> bool:
    """Return True if the page text suggests an image-heavy page."""
    stripped = text.strip()
    if len(stripped) < char_threshold:
        return True
    if _BATES_RE.match(stripped):
        return True
    return False


def _parse_qwen_sections(text: str) -> dict[str, str]:
    """Parse Qwen structured output into sections."""
    fields: dict[str, str] = {}
    current_field = None
    section_map = {
        "PEOPLE:": "people",
        "TEXT:": "text",
        "OBJECTS:": "objects",
        "SETTING:": "setting",
        "ACTIVITY:": "activity",
        "NOTABLE:": "notable",
    }

    for line in text.split("\n"):
        line_upper = line.strip().upper()
        matched = False
        for prefix, field_name in section_map.items():
            if line_upper.startswith(prefix):
                current_field = field_name
                content = line.strip()[len(prefix):].strip()
                fields[field_name] = content
                matched = True
                break
        if not matched and current_field and line.strip():
            fields[current_field] = fields.get(current_field, "") + " " + line.strip()

    return fields


class CaptionProcessor:
    """Caption image-heavy document pages using Florence-2 or Qwen2-VL."""

    def __init__(
        self,
        settings: Settings,
        model_name: str = "microsoft/Florence-2-base",
    ) -> None:
        self._model = None
        self._processor = None
        self._model_name = model_name
        self._settings = settings

    @property
    def _is_qwen(self) -> bool:
        return "qwen" in self._model_name.lower()

    def _load_model(self) -> None:
        """Load vision model to GPU. Called once on first use."""
        if self._model is not None:
            return

        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if device == "cuda" else torch.float32

        if self._is_qwen:
            self._load_qwen(device, dtype)
        else:
            self._load_florence(device, dtype)

        self._device = device
        self._dtype = dtype

    def _load_florence(self, device: str, dtype: "torch.dtype") -> None:
        """Load Florence-2 model."""
        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor

        logger.info("Loading Florence-2: %s", self._model_name)

        # Florence-2 remote code may define _supports_sdpa as a read-only
        # property incompatible with newer transformers.
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
        logger.info("Florence-2 loaded on %s", device)

    def _load_qwen(self, device: str, dtype: "torch.dtype") -> None:
        """Load Qwen2-VL model."""
        from transformers import Qwen2VLForConditionalGeneration, AutoProcessor

        logger.info("Loading Qwen2-VL: %s", self._model_name)

        self._model = Qwen2VLForConditionalGeneration.from_pretrained(
            self._model_name,
            torch_dtype=dtype,
            device_map="auto",
        )
        self._processor = AutoProcessor.from_pretrained(self._model_name)
        logger.info("Qwen2-VL loaded on %s", device)

    # ------------------------------------------------------------------
    # Florence-2 inference
    # ------------------------------------------------------------------

    def _florence_run_task(self, image: "PIL.Image.Image", task: str) -> str:
        """Run a Florence-2 task on an image."""
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
        if isinstance(result, dict):
            return str(next(iter(result.values()), ""))
        return str(result)

    def _florence_caption(self, image: "PIL.Image.Image") -> tuple[str, str | None]:
        """Caption with Florence-2: DETAILED_CAPTION + optional OCR."""
        caption = self._florence_run_task(image, "<DETAILED_CAPTION>")

        ocr_text = None
        text_hints = {"handwrit", "letter", "note", "memo", "text", "written", "document"}
        if any(hint in caption.lower() for hint in text_hints):
            ocr_result = self._florence_run_task(image, "<OCR>")
            if ocr_result.strip():
                ocr_text = ocr_result.strip()

        return caption, ocr_text

    # ------------------------------------------------------------------
    # Qwen2-VL inference
    # ------------------------------------------------------------------

    def _qwen_caption(self, image: "PIL.Image.Image") -> tuple[str, str | None]:
        """Structured analysis with Qwen2-VL."""
        import torch

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": _QWEN_ANALYSIS_PROMPT},
                ],
            }
        ]

        text = self._processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self._processor(
            text=[text], images=[image], return_tensors="pt", padding=True
        )
        inputs = inputs.to(self._model.device)

        with torch.inference_mode():
            output_ids = self._model.generate(**inputs, max_new_tokens=1500)

        output = self._processor.batch_decode(output_ids, skip_special_tokens=True)[0]

        # Extract assistant response (after the last "assistant" marker)
        if "assistant" in output.lower():
            output = output.split("assistant")[-1].strip()

        # Parse structured sections
        sections = _parse_qwen_sections(output)
        ocr_text = sections.get("text", "").strip() or None

        return output, ocr_text

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def caption_page(self, image: "PIL.Image.Image") -> tuple[str, str | None]:
        """Return (caption, ocr_text) for a single page image."""
        self._load_model()
        if self._is_qwen:
            return self._qwen_caption(image)
        return self._florence_caption(image)

    def process_batch(
        self,
        ocr_dir: Path,
        documents_dir: Path,
        output_dir: Path,
        char_threshold: int = 100,
    ) -> list[PageCaption]:
        """Find image-heavy pages, render from PDF, caption them.

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
        model_label = "Qwen2-VL" if self._is_qwen else "Florence-2"
        logger.info(
            "Captioning (%s): %d PDFs with %d image-heavy pages (%d already done)",
            model_label,
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

                # Resolve PDF path
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
        direct = documents_dir / f"{stem}.pdf"
        if direct.exists():
            return direct
        matches = list(documents_dir.rglob(f"{stem}.pdf"))
        if matches:
            return matches[0]
        for p in documents_dir.rglob("*.pdf"):
            if p.stem.lower() == stem.lower():
                return p
        return None

    def analyze_images(
        self,
        images: list[ExtractedImage],
        output_dir: Path,
    ) -> list[ExtractedImage]:
        """Run vision model on extracted images to populate descriptions.

        Parameters
        ----------
        images:
            List of ExtractedImage objects with file_path set.
        output_dir:
            Pipeline output directory (results saved under output_dir/image_analysis/).

        Returns
        -------
        list[ExtractedImage]
            The same images with description fields populated.
        """
        from PIL import Image

        analysis_dir = output_dir / "image_analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)

        # Group images by document for resume and crash-safe saving
        doc_groups: dict[str, list[ExtractedImage]] = {}
        for img in images:
            doc_groups.setdefault(img.document_id, []).append(img)

        # Resume: load existing analysis results
        existing = set(f.stem for f in analysis_dir.glob("*.json"))
        for doc_id in existing:
            if doc_id in doc_groups:
                try:
                    saved = json.loads(
                        (analysis_dir / f"{doc_id}.json").read_text(encoding="utf-8")
                    )
                    desc_map = {
                        (e["page_number"], e["image_index"]): e.get("description")
                        for e in saved
                    }
                    for img in doc_groups[doc_id]:
                        desc = desc_map.get((img.page_number, img.image_index))
                        if desc:
                            img.description = desc
                except Exception:
                    continue

        to_analyze = [
            img for img in images if img.description is None and img.file_path
        ]

        if not to_analyze:
            if images:
                logger.info("Image analysis resume: all %d images already analyzed", len(images))
            return images

        model_label = "Qwen2-VL" if self._is_qwen else "Florence-2"
        logger.info(
            "Analyzing images (%s): %d to process (%d already done)",
            model_label,
            len(to_analyze),
            len(images) - len(to_analyze),
        )

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
        )

        # Track which docs were modified for saving
        dirty_docs: set[str] = set()

        with progress:
            task = progress.add_task("Analyzing images", total=len(to_analyze))

            for img in to_analyze:
                progress.update(
                    task,
                    description=f"Analyze: {Path(img.file_path).name}",
                )

                try:
                    pil_img = Image.open(img.file_path).convert("RGB")
                    caption, _ocr = self.caption_page(pil_img)
                    img.description = caption
                    dirty_docs.add(img.document_id)
                except Exception as exc:
                    logger.warning(
                        "Failed to analyze image %s: %s",
                        img.file_path,
                        exc,
                    )

                progress.advance(task)

        # Save results per document (crash-safe)
        for doc_id in dirty_docs:
            if doc_id in doc_groups:
                out_path = analysis_dir / f"{doc_id}.json"
                out_path.write_text(
                    json.dumps(
                        [i.model_dump() for i in doc_groups[doc_id]],
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

        return images

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
