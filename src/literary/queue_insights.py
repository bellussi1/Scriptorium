"""Read-only insights for the literary queue UI.

The queue snapshot answers "what is queued"; this module answers "what is
happening now" and "what came out".  It reads the queue-run logs and reports,
opens the best available EPUB, and computes a small reader-facing quality
summary.  Nothing here mutates the queue or the artifacts.
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .epub import iter_spine_documents, read_epub, validate_epub_structure
from .per_file_audit import PT_PT_BLOCKING_PATTERNS, PT_PT_PATTERNS

DEFAULT_RUN_DIR = Path("data/queue-runs")
DEFAULT_PILOT_DIR = Path("data/pilots")
DEFAULT_KINDLE_DIR = Path("translated_files/kindle")
DEFAULT_COMPILED_DIR = Path("data/compiled")
DEFAULT_AUDITS_DIR = Path("data/audits")
DEFAULT_BUDGETS_PATH = Path("data/budgets.json")
DEFAULT_UPLOADS_DIR = Path("data/uploads")

_SYNC_LINE_RE = re.compile(r"(?:^|\]\s*)sync:\s*checked=")
_CHECKPOINT_CHUNKS_RE = re.compile(r"Checkpoint chunks \(xhtml state\):\s*(\d+)/(\d+)")
_TRANSLATING_FILE_RE = re.compile(
    r"Translating file (\d+)/(\d+):\s*([^\s(]+)\s*\((\d+)\s+chunks\)"
)
_FILE_CHUNK_RE = re.compile(
    r"(?:Checkpoint saved: chunk|Resuming '[^']+' from chunk)\s+(\d+)/(\d+)"
)
_CLI_ID_RE = re.compile(r"\bcli_[0-9a-f]+\b")


def slug(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9]+", "-", value or "").strip("-").lower()
    return result or "book"


def find_log(
    title: str,
    run_dir: Path = DEFAULT_RUN_DIR,
    pilot_dir: Path = DEFAULT_PILOT_DIR,
) -> Optional[Path]:
    direct = Path(run_dir) / f"{slug(title)}.log"
    candidates = []
    if direct.is_file():
        candidates.append(direct)
    candidates.extend(Path(pilot_dir).glob(f"**/*{slug(title)}*.log"))
    if not candidates:
        return None
    # An active queue run writes a small, recent direct log; a completed pilot
    # keeps the much richer full log in data/pilots.  Prefer the recent direct
    # log while it is live, otherwise the most informative file.
    try:
        if direct.is_file() and (time.time() - direct.stat().st_mtime) < 600:
            return direct
    except OSError:
        pass
    return max(candidates, key=lambda path: path.stat().st_size)


def find_report(
    title: str,
    run_dir: Path = DEFAULT_RUN_DIR,
    pilot_dir: Path = DEFAULT_PILOT_DIR,
) -> Optional[Path]:
    direct = Path(run_dir) / f"{slug(title)}.report.json"
    if direct.is_file():
        return direct
    candidates = sorted(
        Path(pilot_dir).glob(f"**/*{slug(title)}*.report.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def clean_log_lines(lines: Sequence[str]) -> List[str]:
    """Strip noisy periodic sync heartbeats and giant option/glossary dumps."""
    cleaned: List[str] = []
    for raw in lines:
        line = str(raw)
        if _SYNC_LINE_RE.search(line):
            continue
        if "prompt_options={" in line and len(line) > 300:
            head = line.split("(prompt_options={", 1)[0].rstrip()
            cleaned.append(f"{head} (custom instructions + glossary active)")
            continue
        if ("'category':" in line or "'forbidden':" in line) and len(line) > 300:
            cleaned.append(f"{line[:200]} … [glossary truncated]")
            continue
        cleaned.append(line)
    return cleaned


def tail_lines(path: Optional[Path], limit: int = 80, *, skip_sync: bool = False) -> List[str]:
    if path is None or not path.is_file():
        return []
    limit = max(1, min(int(limit), 500))
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    if skip_sync:
        lines = clean_log_lines(lines)
    return lines[-limit:]


def read_json(path: Optional[Path]) -> Dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _issue_list(issues: Iterable[Any]) -> List[Dict[str, Any]]:
    result = []
    for issue in issues:
        if hasattr(issue, "to_dict"):
            result.append(issue.to_dict())
        elif isinstance(issue, dict):
            result.append(issue)
        else:
            result.append({"message": str(issue)})
    return result


def _compiled_forbidden_forms(
    title: str,
    compiled_dir: Optional[Path] = None,
) -> List[str]:
    """Read book-specific forbidden forms from its compiled glossary JSON."""
    if not (title or "").strip():
        return []
    base = DEFAULT_COMPILED_DIR if compiled_dir is None else Path(compiled_dir)
    path = base / f"{slug(title)}-glossary.json"
    if not path.is_file():
        return []
    payload = read_json(path)
    terms = payload.get("terms")
    if not isinstance(terms, list):
        return []
    forms: List[str] = []
    for entry in terms:
        if not isinstance(entry, dict):
            continue
        raw = entry.get("forbidden")
        if isinstance(raw, str):
            parts = [part.strip() for part in raw.split("|") if part.strip()]
        elif isinstance(raw, list):
            parts = [str(part).strip() for part in raw if str(part).strip()]
        else:
            parts = []
        forms.extend(parts)
    return list(dict.fromkeys(forms))


def _forbidden_sources(title: str = "") -> List[str]:
    """Collect deduplicated forbidden source forms across repairs and glossary."""
    from .reading_repair import _reader_repairs

    data = _reader_repairs()
    sources = [old for old, _new in data.get("reader_terms", [])]
    sources += [old for old, _new in data.get("reader_casing", [])]
    if (title or "").strip():
        sources.extend(_compiled_forbidden_forms(title))
    return list(dict.fromkeys(form for form in sources if form))


def forbidden_form_hits(
    text: str,
    *,
    title: str = "",
    limit: int = 8,
) -> List[Dict[str, Any]]:
    """Return remaining forbidden source forms sorted by occurrence count."""
    if not text:
        return []
    hits: List[Dict[str, Any]] = []
    for form in _forbidden_sources(title):
        count = len(re.findall(r"(?<!\w)" + re.escape(form) + r"(?!\w)", text))
        if count:
            hits.append({"form": form, "count": count})
    hits.sort(key=lambda item: (-int(item["count"]), str(item["form"]).casefold()))
    return hits[: max(0, int(limit))]


def forbidden_form_count(text: str, *, title: str = "") -> int:
    """Count the source forms the reader must replace (terms and casing) that still appear."""
    if not text:
        return 0
    return sum(
        len(re.findall(r"(?<!\w)" + re.escape(form) + r"(?!\w)", text))
        for form in _forbidden_sources(title)
    )


def _count_pattern_hits(text: str, patterns: Sequence[str]) -> int:
    return sum(len(re.findall(pattern, text, re.IGNORECASE)) for pattern in patterns)


def _collect_review_samples(
    documents: Sequence[Dict[str, Any]],
    sources: Sequence[str],
    *,
    limit: int = 6,
) -> List[Dict[str, str]]:
    """Collect up to ``limit`` concrete forbidden/PT-PT occurrences by spine document."""
    samples: List[Dict[str, str]] = []
    seen = set()
    for doc in documents:
        doc_text = str(doc.get("text") or "")
        href = str(doc.get("href") or "")
        if not doc_text:
            continue
        for form in sources:
            for match in re.finditer(r"(?<!\w)" + re.escape(form) + r"(?!\w)", doc_text):
                key = (href, "forbidden", match.group(0))
                if key in seen:
                    continue
                seen.add(key)
                samples.append({"href": href, "kind": "forbidden", "match": match.group(0)})
                if len(samples) >= limit:
                    return samples
        for pattern in PT_PT_BLOCKING_PATTERNS:
            for match in re.finditer(pattern, doc_text, re.IGNORECASE):
                key = (href, "pt_pt_blocking", match.group(0))
                if key in seen:
                    continue
                seen.add(key)
                samples.append({"href": href, "kind": "pt_pt_blocking", "match": match.group(0)})
                if len(samples) >= limit:
                    return samples
    return samples


def epub_metrics(path: str | Path, *, title: str = "") -> Dict[str, Any]:
    """Compute the small set of metrics that matter for a reading copy."""
    path = Path(path)
    info = read_epub(str(path), include_text=False)
    documents = list(iter_spine_documents(str(path)))
    text = "\n\n".join(doc.get("text", "") for doc in documents)
    paragraphs = 0
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name.lower().endswith((".xhtml", ".html")):
                raw = archive.read(name).decode("utf-8", "replace")
                paragraphs += len(re.findall(r"<p\b", raw, re.IGNORECASE))
    structural = validate_epub_structure(str(path))
    issues = _issue_list(structural) + _issue_list(info.issues)
    sources = _forbidden_sources(title)
    hits = forbidden_form_hits(text, title=title)
    forbidden_total = sum(
        len(re.findall(r"(?<!\w)" + re.escape(form) + r"(?!\w)", text))
        for form in sources
    )
    pt_pt_blocking = _count_pattern_hits(text, PT_PT_BLOCKING_PATTERNS)
    pt_pt_total = _count_pattern_hits(text, PT_PT_PATTERNS)
    review_samples = _collect_review_samples(documents, sources)
    metrics = {
        "words": info.word_count,
        "documents": info.document_count,
        "chapters": len(info.toc),
        "paragraphs": paragraphs,
        "curly_open": text.count("“"),
        "curly_close": text.count("”"),
        "straight_quotes": text.count('"'),
        "brackets": text.count("[") + text.count("]"),
        "em_dashes": text.count("—"),
        "forbidden_forms": forbidden_total,
        "pt_pt_blocking": pt_pt_blocking,
        "pt_pt_total": pt_pt_total,
    }
    flags = []
    if metrics["forbidden_forms"]:
        flags.append("forbidden_forms_remaining")
    if metrics["pt_pt_blocking"]:
        flags.append("pt_pt_blocking_remaining")
    if metrics["brackets"]:
        flags.append("brackets_remaining")
    if metrics["straight_quotes"]:
        flags.append("straight_quotes_remaining")
    if any(issue.get("severity") in {"error", "critical"} for issue in issues):
        flags.append("structural_error")
    return {
        "metrics": metrics,
        "issues": issues[:20],
        "quality_flags": flags,
        "forbidden_hits": hits,
        "review_samples": review_samples,
        "epubcheck": _sidecar_epubcheck(path),
    }


def quality_sidecar_path(path: str | Path) -> Path:
    path = Path(path)
    return path.with_suffix(".quality.json")


def _sidecar_epubcheck(path: Path) -> Optional[Dict[str, Any]]:
    payload = read_json(quality_sidecar_path(path))
    check = payload.get("epubcheck")
    return check if isinstance(check, dict) else None


def _report_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    if not report:
        return {}
    validation = report.get("refined_validation") or report.get("validation") or {}
    epubcheck = report.get("refined_epubcheck") or report.get("epubcheck") or {}
    refine = report.get("refine") or {}
    reader = report.get("reader_repair") or {}
    return {
        "validation": {
            "passed": validation.get("passed"),
            "blocking": validation.get("blocking"),
            "warnings": validation.get("warnings"),
        }
        if isinstance(validation, dict)
        else {},
        "epubcheck": epubcheck if isinstance(epubcheck, dict) else {},
        "refine": refine if isinstance(refine, dict) else {},
        "reader_repair": reader if isinstance(reader, dict) else {},
        "queue_state": report.get("queue_state"),
        "duration_s": report.get("duration_s"),
        "model": report.get("model"),
        "provider": report.get("provider"),
    }


def quality_payload(
    book: Dict[str, Any],
    artifact: Dict[str, Any],
    *,
    run_dir: Path = DEFAULT_RUN_DIR,
    pilot_dir: Path = DEFAULT_PILOT_DIR,
    log_limit: int = 80,
) -> Dict[str, Any]:
    artifact_path = Path(str(artifact.get("path") or ""))
    if not artifact_path.is_file():
        raise FileNotFoundError("artifact not found")
    title = str(book.get("title") or "")
    insights = epub_metrics(artifact_path, title=title)
    sidecar = read_json(quality_sidecar_path(artifact_path))
    if insights.get("epubcheck") is None and isinstance(sidecar.get("epubcheck"), dict):
        insights["epubcheck"] = sidecar["epubcheck"]
    report_path = find_report(title, run_dir=run_dir, pilot_dir=pilot_dir)
    report = _report_summary(read_json(report_path))
    if not report.get("reader_repair") and isinstance(sidecar.get("reader_repair"), dict):
        report["reader_repair"] = sidecar["reader_repair"]
    if not report.get("epubcheck") and isinstance(sidecar.get("epubcheck"), dict):
        report["epubcheck"] = sidecar["epubcheck"]
    log_path = find_log(title, run_dir=run_dir, pilot_dir=pilot_dir)
    return {
        "status": "ok",
        "book": {
            "id": book.get("id"),
            "title": title,
            "author": book.get("author"),
            "series": book.get("series"),
            "series_index": book.get("series_index"),
            "state": book.get("state") or book.get("status"),
            "translation_id": book.get("translation_id") or "",
        },
        "artifact": {
            "filename": artifact.get("filename"),
            "kind": artifact.get("kind"),
            "size": artifact.get("size"),
            "download_url": artifact.get("download_url"),
        },
        **insights,
        "report": report,
        "log": {
            "filename": log_path.name if log_path else "",
            "lines": tail_lines(log_path, log_limit, skip_sync=True),
        },
    }


def kindle_zip(folder: str | Path = DEFAULT_KINDLE_DIR) -> io.BytesIO:
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError("Kindle folder not found")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            if path.name.startswith("."):
                continue
            archive.write(path, path.relative_to(folder).as_posix())
    buffer.seek(0)
    return buffer


def _read_head_and_tail(path: Path, *, head_bytes: int = 4096, tail_bytes: int = 131072) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size <= tail_bytes:
                return fh.read().decode("utf-8", "replace")
            head = fh.read(head_bytes).decode("utf-8", "replace")
            fh.seek(-tail_bytes, 2)
            tail = fh.read().decode("utf-8", "replace")
            return head + "\n" + tail
    except OSError:
        return ""


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    if "T" not in text and " " in text:
        text = text.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def live_translation_progress(
    title: str,
    translation_id: str = "",
    *,
    run_dir: Path = DEFAULT_RUN_DIR,
    pilot_dir: Path = DEFAULT_PILOT_DIR,
    uploads_dir: Path = DEFAULT_UPLOADS_DIR,
) -> Dict[str, Any]:
    """Read live per-5-chunk XHTML progress, current file, and pipeline stage."""
    tid = str(translation_id or "").strip()
    log_path = find_log(title, run_dir, pilot_dir) if title else None
    states_dir = Path(uploads_dir) / tid / "xhtml_states" if tid else None
    has_states = bool(states_dir and states_dir.is_dir())

    if log_path is not None and tid:
        sample_text = _read_head_and_tail(log_path)
        found_ids = set(_CLI_ID_RE.findall(sample_text))
        if not has_states and found_ids and tid not in found_ids:
            log_path = None

    newest_mtime: Optional[float] = None
    if has_states and states_dir is not None:
        for state_file in states_dir.glob("*.json"):
            try:
                mtime = state_file.stat().st_mtime
                if newest_mtime is None or mtime > newest_mtime:
                    newest_mtime = mtime
            except OSError:
                continue

    tail_lines_raw: List[str] = []
    if log_path is not None and log_path.is_file():
        try:
            mtime = log_path.stat().st_mtime
            if newest_mtime is None or mtime > newest_mtime:
                newest_mtime = mtime
        except OSError:
            pass
        text = _read_head_and_tail(log_path, head_bytes=0, tail_bytes=131072)
        tail_lines_raw = text.splitlines()[-300:]

    if not tail_lines_raw and not has_states:
        return {}

    checkpoint_count: Optional[int] = None
    total_chunks: Optional[int] = None
    current_file_index: Optional[int] = None
    total_files: Optional[int] = None
    current_file_name = ""
    file_chunk: Optional[int] = None
    file_total_chunks: Optional[int] = None

    start_idx = 0
    for idx, line in enumerate(tail_lines_raw):
        if "queue run for book" in line or "TRANSLATION STARTED" in line:
            start_idx = idx
    run_lines = tail_lines_raw[start_idx:]

    stage = "preparing"
    for line in run_lines:
        if "TRANSLATION STARTED" in line:
            stage = "translating"
        m_file = _TRANSLATING_FILE_RE.search(line)
        if m_file:
            current_file_index = int(m_file.group(1))
            total_files = int(m_file.group(2))
            current_file_name = m_file.group(3)
            file_total_chunks = int(m_file.group(4))
            file_chunk = 0
            stage = "translating"
            continue
        m_chunk = _FILE_CHUNK_RE.search(line)
        if m_chunk:
            file_chunk = int(m_chunk.group(1))
            file_total_chunks = int(m_chunk.group(2))
            stage = "translating"
        m_total = _CHECKPOINT_CHUNKS_RE.search(line)
        if m_total:
            checkpoint_count = int(m_total.group(1))
            total_chunks = int(m_total.group(2))
            stage = "translating"
        if (
            "translation process exited with 0" in line
            or "repairing dropcaps" in line
            or "rewriting pt-PT" in line
        ):
            stage = "repairing"
        elif "validation passed" in line or "reader repair:" in line:
            stage = "validating"
        elif "EPUBCheck" in line or "series metadata" in line or "finished; report=" in line:
            stage = "auditing"

    if (
        stage == "translating"
        and checkpoint_count is not None
        and total_chunks
        and checkpoint_count >= total_chunks
    ):
        stage = "repairing"

    now = time.time()
    last_cp_iso = (
        datetime.fromtimestamp(newest_mtime, timezone.utc).isoformat(timespec="seconds")
        if newest_mtime is not None
        else None
    )
    last_cp_age = round(max(0.0, now - newest_mtime), 1) if newest_mtime is not None else None

    result: Dict[str, Any] = {
        "pipeline_stage": stage,
        "last_checkpoint_at": last_cp_iso,
        "last_checkpoint_age_seconds": last_cp_age,
        "log_filename": log_path.name if log_path else "",
    }
    if checkpoint_count is not None:
        result["checkpoint_count"] = checkpoint_count
    if total_chunks is not None:
        result["total_chunks"] = total_chunks
    if current_file_index is not None:
        result["current_file_index"] = current_file_index
    if total_files is not None:
        result["total_files"] = total_files
    if current_file_name:
        result["current_file_name"] = current_file_name
    if file_chunk is not None:
        result["file_chunk"] = file_chunk
    if file_total_chunks is not None:
        result["file_total_chunks"] = file_total_chunks
    return result


def read_process_telemetry(db_path: str | Path) -> Dict[str, Any]:
    """Read live host supervisor and worker process status next to the queue DB."""
    path = Path(db_path)
    now = time.time()

    def _file_age(file_path: Path, data: Dict[str, Any]) -> Optional[float]:
        stamp = _parse_iso_datetime(data.get("heartbeat"))
        if stamp is not None:
            return round(max(0.0, now - stamp.timestamp()), 1)
        try:
            return round(max(0.0, now - file_path.stat().st_mtime), 1)
        except OSError:
            return None

    sup_path = path.with_name("literary_queue.supervisor.json")
    sup_data = read_json(sup_path)
    sup_age = _file_age(sup_path, sup_data) if sup_data else None
    sup_online = bool(sup_data and sup_age is not None and sup_age <= 45.0)
    worker_raw = sup_data.get("worker") if isinstance(sup_data.get("worker"), dict) else {}
    restart_raw = sup_data.get("restart") if isinstance(sup_data.get("restart"), dict) else {}
    sup_info: Dict[str, Any] = {
        "online": sup_online,
        "state": sup_data.get("state") if sup_online else ("offline" if sup_data else "stopped"),
        "pid": sup_data.get("pid"),
        "heartbeat_age_s": sup_age,
        "worker_pid": worker_raw.get("pid"),
        "worker_running": bool(worker_raw.get("running")) if sup_online else False,
        "worker_heartbeat_age_s": worker_raw.get("heartbeat_age_s"),
        "restarts_last_hour": int(restart_raw.get("attempts_last_hour") or 0),
        "max_restarts_per_hour": int(restart_raw.get("max_per_hour") or 3),
        "last_restart_reason": restart_raw.get("last_reason"),
        "message": sup_data.get("message") or "",
    }

    auto_path = path.with_name("literary_queue.auto.json")
    auto_data = read_json(auto_path)
    auto_age = _file_age(auto_path, auto_data) if auto_data else None
    auto_online = bool(auto_data and auto_age is not None and auto_age <= 75.0)
    auto_info: Dict[str, Any] = {
        "online": auto_online,
        "pid": auto_data.get("pid"),
        "ppid": auto_data.get("ppid"),
        "running": bool(auto_data.get("running")) if auto_online else False,
        "phase": auto_data.get("phase") or "",
        "reason": auto_data.get("reason") or "",
        "book_id": auto_data.get("book_id"),
        "title": auto_data.get("title") or "",
        "heartbeat_age_s": auto_age,
        "message": auto_data.get("message") or "",
    }
    return {"supervisor": sup_info, "auto_worker": auto_info}


def read_budget_summary(
    books: Sequence[Dict[str, Any]],
    budgets_path: Path = DEFAULT_BUDGETS_PATH,
) -> Dict[str, Any]:
    """Compute calibrated USD/BRL spend estimates and remaining credit cap."""
    budgets = read_json(budgets_path)
    gemini_cfg = budgets.get("gemini") if isinstance(budgets.get("gemini"), dict) else {}
    cap_usd = float(gemini_cfg.get("cap_usd") or gemini_cfg.get("cap") or 40.0)
    usd_to_brl = float(gemini_cfg.get("usd_to_brl") or 5.75)
    rate_uncached = float(gemini_cfg.get("rate_per_m_words_uncached") or 13.02) / 1_000_000.0
    rate_optimized = float(gemini_cfg.get("rate_per_m_words_optimized") or 10.80) / 1_000_000.0

    def _est_usd(book: Dict[str, Any], state: str) -> float:
        actual = float(book.get("actual_cost") or 0.0)
        if actual > 0:
            return actual
        words = int(book.get("word_count") or 0)
        if words > 0:
            rate = (
                rate_uncached
                if state in {"completed", "needs_review"} or int(book.get("id") or 0) == 6
                else rate_optimized
            )
            return round(words * rate, 2)
        est = float(book.get("estimated_cost") or 0.0)
        return est if est > 0 else 0.0

    completed_usd = 0.0
    active_usd = 0.0
    core_remaining_usd = 0.0
    total_remaining_usd = 0.0
    active_states = {"preparing", "translating", "reviewing", "validating"}
    for book in books:
        provider = str(book.get("provider") or "gemini").strip().lower()
        if provider and provider != "gemini":
            continue
        state = str(book.get("state") or book.get("status") or "pending").lower()
        cost = _est_usd(book, state)
        if state in {"completed", "needs_review"}:
            completed_usd += cost
        elif state in active_states:
            active_usd += cost
        elif state in {"pending", "paused", "failed"}:
            total_remaining_usd += cost
            if int(book.get("priority") or 0) >= 20:
                core_remaining_usd += cost

    completed_usd = round(completed_usd, 2)
    active_usd = round(active_usd, 2)
    core_remaining_usd = round(core_remaining_usd, 2)
    total_remaining_usd = round(total_remaining_usd, 2)
    remaining_cap_usd = round(max(0.0, cap_usd - completed_usd - active_usd), 2)
    return {
        "provider": "gemini",
        "currency": str(gemini_cfg.get("currency") or "USD"),
        "cap_usd": round(cap_usd, 2),
        "completed_usd": completed_usd,
        "active_usd": active_usd,
        "core_remaining_usd": core_remaining_usd,
        "total_remaining_usd": total_remaining_usd,
        "remaining_cap_usd": remaining_cap_usd,
        "usd_to_brl": round(usd_to_brl, 2),
        "completed_brl": round(completed_usd * usd_to_brl, 2),
        "active_brl": round(active_usd * usd_to_brl, 2),
        "core_remaining_brl": round(core_remaining_usd * usd_to_brl, 2),
        "total_remaining_brl": round(total_remaining_usd * usd_to_brl, 2),
        "cap_brl": round(cap_usd * usd_to_brl, 2),
        "remaining_cap_brl": round(remaining_cap_usd * usd_to_brl, 2),
        "is_estimated": True,
    }


_CLOUD_BUDGET_PROVIDERS = {
    "gemini",
    "openai",
    "deepseek",
    "openrouter",
    "mistral",
    "poe",
    "nim",
    "litellm",
}


def check_cloud_budget_gate(
    book: Any,
    db_path: Any,
    budgets_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Return whether starting ``book`` stays within the hard monthly cloud USD cap."""
    book_dict = book.to_dict() if hasattr(book, "to_dict") else dict(book)
    provider = str(book_dict.get("provider") or "ollama").strip().lower()
    if provider not in _CLOUD_BUDGET_PROVIDERS:
        return {"allowed": True, "provider": provider, "message": "local provider"}

    if budgets_path is None:
        sibling = Path(db_path).with_name("budgets.json")
        resolved_budgets = sibling if sibling.is_file() else DEFAULT_BUDGETS_PATH
    else:
        resolved_budgets = Path(budgets_path)

    from .queue import QueueStore

    store = QueueStore(str(db_path))
    try:
        all_books = [item.to_dict() for item in store.list_books(limit=500)]
    finally:
        store.close()

    budgets = read_json(resolved_budgets)
    gemini_cfg = budgets.get("gemini") if isinstance(budgets.get("gemini"), dict) else {}
    book_id = int(book_dict.get("id") or 0)
    other_books = [item for item in all_books if int(item.get("id") or 0) != book_id]
    other_summary = read_budget_summary(other_books, budgets_path=resolved_budgets)
    spent_usd = round(
        float(other_summary["completed_usd"]) + float(other_summary["active_usd"]), 2
    )
    cap_usd = float(other_summary["cap_usd"])

    words = int(book_dict.get("word_count") or 0)
    rate_uncached = float(gemini_cfg.get("rate_per_m_words_uncached") or 13.02) / 1_000_000.0
    book_cost_usd = (
        round(words * rate_uncached, 2)
        if words > 0
        else round(float(book_dict.get("estimated_cost") or 0.0), 2)
    )
    projected_usd = round(spent_usd + book_cost_usd, 2)
    allowed = projected_usd <= cap_usd
    return {
        "allowed": allowed,
        "provider": provider,
        "cap_usd": cap_usd,
        "spent_usd": spent_usd,
        "book_cost_usd": book_cost_usd,
        "projected_usd": projected_usd,
        "remaining_cap_usd": round(max(0.0, cap_usd - spent_usd), 2),
        "message": (
            "within monthly cloud budget cap"
            if allowed
            else (
                f"monthly cloud budget cap (${cap_usd:.2f}) reached: "
                f"spent ${spent_usd:.2f} + ${book_cost_usd:.2f} for "
                f"'{book_dict.get('title')}' = ${projected_usd:.2f} > ${cap_usd:.2f}"
            )
        ),
    }


def _exported_kindle_ids(kindle_dir: Path) -> set[int]:
    manifest = Path(kindle_dir) / "manifest.csv"
    if not manifest.is_file():
        return set()
    exported: set[int] = set()
    try:
        with manifest.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    exported.add(int(row.get("book_id") or 0))
                except (TypeError, ValueError):
                    continue
    except OSError:
        return set()
    return exported


def read_book_quality_summaries(
    books: Sequence[Dict[str, Any]],
    *,
    run_dir: Path = DEFAULT_RUN_DIR,
    pilot_dir: Path = DEFAULT_PILOT_DIR,
    audits_dir: Path = DEFAULT_AUDITS_DIR,
    kindle_dir: Path = DEFAULT_KINDLE_DIR,
) -> Dict[str, Dict[str, Any]]:
    """Return compact EPUBCheck / audit / Kindle badges for completed or reviewed books."""
    exported_ids = _exported_kindle_ids(Path(kindle_dir))
    audits_root = Path(audits_dir)
    summaries: Dict[str, Dict[str, Any]] = {}

    for book in books:
        book_id = int(book.get("id") or 0)
        state = str(book.get("state") or book.get("status") or "pending").lower()
        if not book_id or (not book.get("artifact") and state not in {"completed", "needs_review"}):
            continue
        title = str(book.get("title") or "")
        book_slug = slug(title)
        report_data = read_json(find_report(title, run_dir, pilot_dir)) if title else {}

        audit_data: Dict[str, Any] = {}
        if audits_root.is_dir() and book_slug:
            candidates = sorted(
                audits_root.glob(f"{book_slug}-*/audit.json"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                audit_data = read_json(candidates[0])

        epubcheck = (
            report_data.get("refined_epubcheck")
            or report_data.get("epubcheck")
            or {}
        )
        errors = epubcheck.get("errors")
        fatals = epubcheck.get("fatals")
        warnings = epubcheck.get("warnings")
        if errors is None and isinstance(audit_data.get("gate"), dict):
            errors = audit_data["gate"].get("epubcheck_errors")
            fatals = 0 if errors == 0 else None
        epubcheck_ok: Optional[bool] = None
        if errors is not None:
            epubcheck_ok = int(errors or 0) == 0 and int(fatals or 0) == 0

        glossary = audit_data.get("glossary") if isinstance(audit_data.get("glossary"), dict) else {}
        terms_block = audit_data.get("terms") if isinstance(audit_data.get("terms"), dict) else {}
        per_file_totals = (
            (audit_data.get("per_file") or {}).get("totals")
            if isinstance(audit_data.get("per_file"), dict)
            else {}
        )
        cov = glossary.get("coverage")
        if cov is None and isinstance(per_file_totals, dict):
            cov = per_file_totals.get("glossary_coverage")
        terms_cov = terms_block.get("coverage")
        forbidden_raw = glossary.get("forbidden_hits")
        forbidden_hits = len(forbidden_raw) if isinstance(forbidden_raw, list) else forbidden_raw

        reader = (
            report_data.get("reader_repair")
            if isinstance(report_data.get("reader_repair"), dict)
            else {}
        )
        artefact_changes = (
            reader.get("artefact_changes")
            if isinstance(reader.get("artefact_changes"), dict)
            else reader.get("artifact_changes")
            if isinstance(reader.get("artifact_changes"), dict)
            else {}
        )
        splits = artefact_changes.get("split_dialogue_paragraphs")

        summaries[str(book_id)] = {
            "epubcheck_ok": epubcheck_ok,
            "epubcheck_errors": int(errors) if errors is not None else None,
            "epubcheck_warnings": int(warnings) if warnings is not None else None,
            "gate_passed": report_data.get("gate_passed"),
            "glossary_coverage": float(cov) if cov is not None else None,
            "glossary_coverage_terms": float(terms_cov) if terms_cov is not None else None,
            "forbidden_hits": int(forbidden_hits) if forbidden_hits is not None else None,
            "reader_merged": reader.get("merged"),
            "reader_splits": splits,
            "kindle_exported": book_id in exported_ids,
        }
    return summaries
