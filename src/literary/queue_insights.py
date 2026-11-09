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
from typing import Any, Dict, Iterable, List, Optional

from .epub import iter_spine_documents, read_epub, validate_epub_structure

DEFAULT_RUN_DIR = Path("data/queue-runs")
DEFAULT_PILOT_DIR = Path("data/pilots")
DEFAULT_KINDLE_DIR = Path("translated_files/kindle")


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


def epub_metrics(path: str | Path) -> Dict[str, Any]:
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
        "chantry": len(re.findall(r"\bChantry\b", text)),
        "chantria": len(re.findall(r"\bChantria\b", text)),
        "cielcin_upper": len(re.findall(r"\bCielcin\b", text)),
        "cielcin_lower": len(re.findall(r"\bcielcin\b", text)),
        "mericanii_upper": len(re.findall(r"\bMericanii\b", text)),
        "mericanii_lower": len(re.findall(r"\bmericanii\b", text)),
        "halfmortal": len(re.findall(r"\bHalfmortal\b", text)),
        "semimortal": len(re.findall(r"\bSemimortal\b", text)),
    }
    flags = []
    if metrics["chantry"]:
        flags.append("chantry_remaining")
    if metrics["cielcin_upper"]:
        flags.append("cielcin_capitalized")
    if metrics["mericanii_upper"]:
        flags.append("mericanii_capitalized")
    if metrics["halfmortal"]:
        flags.append("halfmortal_remaining")
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
    insights = epub_metrics(artifact_path)
    sidecar = read_json(quality_sidecar_path(artifact_path))
    if insights.get("epubcheck") is None and isinstance(sidecar.get("epubcheck"), dict):
        insights["epubcheck"] = sidecar["epubcheck"]
    title = str(book.get("title") or "")
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
