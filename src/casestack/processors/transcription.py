"""Audio/video transcription processor using faster-whisper."""

from __future__ import annotations

import hashlib
import json
import logging
import multiprocessing
import time
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
from casestack.models.document import Document, Page, TranscriptionResult
from casestack.models.forensics import Transcript, TranscriptSegment

import numpy as np

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac", ".wma"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".m4v", ".vob", ".ts"}
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS


def _check_audio_content(
    path: str,
    sample_seconds: float = 10.0,
    silence_threshold_db: float = -40.0,
) -> tuple[bool, float, float]:
    """Quick audio content check using PyAV.

    Decodes the first *sample_seconds* of audio and measures RMS volume.

    Returns ``(has_speech, duration_seconds, rms_db)``.
    """
    import av

    try:
        with av.open(path, mode="r", metadata_errors="ignore") as container:
            audio_stream = next(
                (s for s in container.streams if s.type == "audio"), None
            )
            if audio_stream is None:
                return False, 0.0, -100.0

            duration = float(container.duration or 0) / av.time_base

            resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
            samples: list[np.ndarray] = []
            target = int(16000 * sample_seconds)

            for frame in container.decode(audio=0):
                for resampled in resampler.resample(frame):
                    arr = resampled.to_ndarray().flatten()
                    samples.append(arr)
                    if sum(len(s) for s in samples) >= target:
                        break
                if sum(len(s) for s in samples) >= target:
                    break

            if not samples:
                return False, duration, -100.0

            audio = np.concatenate(samples).astype(np.float32) / 32768.0
            rms = np.sqrt(np.mean(audio**2))
            rms_db = 20 * np.log10(rms + 1e-10)

            return bool(rms_db > silence_threshold_db), duration, float(rms_db)
    except Exception as exc:
        logger.warning("Audio content check failed for %s: %s", path, exc)
        # If we can't check, assume it has content and let Whisper handle it
        return True, 0.0, 0.0


def _detect_hardware() -> tuple[str, str, str]:
    """Detect available hardware and return (device, compute_type, model_size).

    Returns ``("cuda", "float16", "large-v3")`` when a CUDA GPU is available,
    otherwise ``("cpu", "int8", "tiny")``.
    """
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda", "float16", "large-v3"
    except ImportError:
        pass
    return "cpu", "int8", "tiny"


def _process_single_transcription(
    args: tuple[str, str, str, str],
) -> TranscriptionResult:
    """Transcribe a single audio/video file.

    Module-level function so it can be pickled if needed.
    Accepts ``(file_path, whisper_model, device, compute_type)``.
    """
    file_path_str, whisper_model, device, compute_type = args
    path = Path(file_path_str)
    start_ms = time.monotonic_ns() // 1_000_000
    errors: list[str] = []
    warnings: list[str] = []

    # Quick silence check — skip Whisper entirely for silent files
    has_speech, duration, rms_db = _check_audio_content(str(path))

    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    doc_id = f"transcript-{content_hash[:12]}"

    if not has_speech:
        warnings.append(
            f"Skipped {path.name}: silent (RMS={rms_db:.1f}dB, duration={duration:.0f}s)"
        )
        elapsed = (time.monotonic_ns() // 1_000_000) - start_ms
        return TranscriptionResult(
            source_path=str(path),
            transcript=None,
            document=Document(
                id=doc_id,
                title=path.stem.replace("_", " ").replace("-", " ").strip(),
                source="local",
                category="media",
                ocrText="",
                tags=["transcript", "silent"],
            ),
            pages=[],
            processing_time_ms=elapsed,
            errors=errors,
            warnings=warnings,
        )

    transcript_obj: Transcript | None = None
    document: Document | None = None
    page_objects: list[Page] = []

    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(whisper_model, device=device, compute_type=compute_type)
        segments_iter, info = model.transcribe(str(path), beam_size=5)

        segments: list[TranscriptSegment] = []
        full_text_parts: list[str] = []

        for seg in segments_iter:
            segments.append(
                TranscriptSegment(start=seg.start, end=seg.end, text=seg.text.strip())
            )
            full_text_parts.append(seg.text.strip())

        full_text = " ".join(full_text_parts)

        if not full_text.strip():
            warnings.append(f"Whisper produced empty transcript for {path.name}")
        else:
            transcript_obj = Transcript(
                source_path=str(path),
                document_id=doc_id,
                text=full_text,
                language=info.language or "en",
                duration_seconds=info.duration,
                segments=segments,
            )

            document = Document(
                id=doc_id,
                title=path.stem.replace("_", " ").replace("-", " ").strip(),
                source="local",
                category="media",
                ocrText=full_text,
                tags=["transcript"],
            )

            # Create pages from transcript segments (group ~30s chunks)
            _CHUNK_SECONDS = 30.0
            current_text_parts: list[str] = []
            chunk_start = 0.0
            page_num = 1

            for seg in segments:
                current_text_parts.append(seg.text)
                if seg.end - chunk_start >= _CHUNK_SECONDS:
                    page_text = " ".join(current_text_parts)
                    page_objects.append(
                        Page(
                            document_id=doc_id,
                            page_number=page_num,
                            text_content=page_text,
                            char_count=len(page_text),
                        )
                    )
                    page_num += 1
                    current_text_parts = []
                    chunk_start = seg.end

            # Flush remaining
            if current_text_parts:
                page_text = " ".join(current_text_parts)
                page_objects.append(
                    Page(
                        document_id=doc_id,
                        page_number=page_num,
                        text_content=page_text,
                        char_count=len(page_text),
                    )
                )

    except ImportError:
        errors.append(
            "faster-whisper not installed. Install with: pip install 'casestack[transcription]'"
        )
    except Exception as exc:
        errors.append(f"Transcription failed for {path.name}: {exc}")

    elapsed = (time.monotonic_ns() // 1_000_000) - start_ms
    return TranscriptionResult(
        source_path=str(path),
        transcript=transcript_obj,
        document=document,
        pages=page_objects,
        processing_time_ms=elapsed,
        errors=errors,
        warnings=warnings,
    )


def _subprocess_worker(
    args: tuple[str, str, str, str],
    result_queue: multiprocessing.Queue,
) -> None:
    """Entry point for the transcription subprocess."""
    try:
        result = _process_single_transcription(args)
        result_queue.put(result.model_dump_json())
    except Exception as exc:
        # If even serialization fails, send a minimal error result
        result_queue.put(json.dumps({
            "source_path": args[0],
            "transcript": None,
            "document": None,
            "pages": [],
            "processing_time_ms": 0,
            "errors": [f"Subprocess error: {exc}"],
            "warnings": [],
        }))


def _run_in_subprocess(
    file_path: str,
    whisper_model: str,
    device: str,
    compute_type: str,
    timeout: float = 600.0,
) -> TranscriptionResult:
    """Run transcription in a child process to survive segfaults."""
    ctx = multiprocessing.get_context("spawn")
    result_queue: multiprocessing.Queue = ctx.Queue()
    args = (file_path, whisper_model, device, compute_type)
    proc = ctx.Process(target=_subprocess_worker, args=(args, result_queue))
    proc.start()
    proc.join(timeout=timeout)

    path = Path(file_path)

    if proc.is_alive():
        proc.kill()
        proc.join()
        return TranscriptionResult(
            source_path=file_path,
            processing_time_ms=int(timeout * 1000),
            errors=[f"Transcription timed out after {timeout:.0f}s for {path.name}"],
        )

    if proc.exitcode != 0:
        return TranscriptionResult(
            source_path=file_path,
            processing_time_ms=0,
            errors=[
                f"Transcription subprocess crashed (exit code {proc.exitcode}) for {path.name}"
            ],
        )

    try:
        raw = result_queue.get_nowait()
        return TranscriptionResult.model_validate_json(raw)
    except Exception as exc:
        return TranscriptionResult(
            source_path=file_path,
            processing_time_ms=0,
            errors=[f"Failed to read subprocess result for {path.name}: {exc}"],
        )


class TranscriptionProcessor:
    """Process audio/video files through Whisper transcription."""

    def __init__(self, config: Settings) -> None:
        self.config = config
        self.device, self.compute_type, self._auto_model = _detect_hardware()

        # Use configured model or auto-detect
        if config.whisper_model and config.whisper_model != "auto":
            self.whisper_model = config.whisper_model
        else:
            self.whisper_model = self._auto_model

        # Allow explicit device override
        if config.whisper_device and config.whisper_device != "auto":
            self.device = config.whisper_device

        logger.info(
            "Transcription: model=%s device=%s compute=%s",
            self.whisper_model,
            self.device,
            self.compute_type,
        )

    def process_file(self, path: Path) -> TranscriptionResult:
        """Transcribe a single audio/video file in a subprocess.

        Running in a subprocess isolates the main pipeline from segfaults
        in native code (CTranslate2, PyAV, CUDA) that cannot be caught
        with try/except.
        """
        return _run_in_subprocess(
            str(path), self.whisper_model, self.device, self.compute_type
        )

    def process_batch(
        self,
        paths: list[Path],
        output_dir: Path,
        max_workers: int = 1,
    ) -> list[TranscriptionResult]:
        """Process multiple media files sequentially (GPU memory constraint).

        Files whose output JSON already exists are skipped (resumable).
        """
        transcripts_dir = output_dir / "transcripts"
        transcripts_dir.mkdir(parents=True, exist_ok=True)
        results: list[TranscriptionResult] = []

        # Filename-based resume check — existence only, no deserialization
        existing = set(f.stem for f in transcripts_dir.glob("*.json"))
        to_process: list[tuple[Path, str]] = []
        skipped = 0
        for p in paths:
            name_key = p.stem
            if name_key in existing:
                skipped += 1
            else:
                to_process.append((p, name_key))

        if skipped:
            logger.info("Transcription resume: %d already processed, %d new", skipped, len(to_process))

        if not to_process:
            return results

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
        )

        with progress:
            task = progress.add_task("Transcribing", total=len(to_process))
            for file_path, file_key in to_process:
                # Quick pre-check for duration display
                _, est_dur, _ = _check_audio_content(str(file_path), sample_seconds=0.1)
                dur_label = f" ({est_dur:.0f}s)" if est_dur > 0 else ""
                progress.update(
                    task,
                    description=f"Transcribe: {file_path.name[:30]}{dur_label}",
                )
                result = self.process_file(file_path)
                results.append(result)

                out_path = transcripts_dir / f"{file_key}.json"
                out_path.write_text(
                    result.model_dump_json(indent=2), encoding="utf-8"
                )
                progress.advance(task)

        return results
