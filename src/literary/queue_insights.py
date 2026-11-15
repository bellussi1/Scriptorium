"""Read-only insights for the literary queue UI.

The queue snapshot answers "what is queued"; this module answers "what is
happening now" and "what came out".  It reads the queue-run logs and reports,
opens the best available EPUB, and computes a small reader-facing quality
summary.  Nothing here mutates the queue or the artifacts.
"""
from __future__ import annotations

import io
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .epub import iter_spine_documents, read_epub, validate_epub_structure
from .per_file_audit import PT_PT_BLOCKING_PATTERNS, PT_PT_PATTERNS

DEFAULT_RUN_DIR = Path("data/queue-runs")
DEFAULT_PILOT_DIR = Path("data/pilots")
DEFAULT_KINDLE_DIR = Path("translated_files/kindle")
DEFAULT_COMPILED_DIR = Path("data/compiled")


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


def tail_lines(path: Optional[Path], limit: int = 80, *, skip_sync: bool = False) -> List[str]:
    if path is None or not path.is_file():
        return []
    limit = max(1, min(int(limit), 500))
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    if skip_sync:
        lines = [line for line in lines if "sync: checked=" not in line]
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
