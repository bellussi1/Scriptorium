"""Run one pending queue book end to end.

The queue stores what to run; this module is the missing executor. It compiles
the book's glossary/style, launches the upstream ``translate.py`` in the dev
container, attaches the upstream ``translation_id``, repairs and validates the
EPUB, optionally runs the source-aware refinement, and marks the book completed
when the gates pass. A failed gate leaves it in ``needs_review`` for optional
manual inspection.

It deliberately runs **one** book per invocation. The next book is not launched
until the previous result has been reviewed and the queue is advanced.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .queue import QueueStore
from .queue_control import (
    honor_pause_now,
    pause_now_requested,
    set_pause,
)
from .reading_repair import repair_reading_epub
from .repair import repair_doc_roles_in_epub, repair_dropcaps_in_epub
from .resources import (
    write_glossary_json,
    write_style_preset,
)
from .run_plan import build_run_plan, compile_book_resources, infer_scopes
from .validation import validate_epub_pair


ROOT = Path(__file__).resolve().parents[2]
QUEUE_DB = ROOT / "data" / "literary_queue.db"
CHECKPOINT_DB = ROOT / "data" / "jobs.db"
INVENTORY = ROOT / "data" / "calibre" / "targets.json"
OUTPUT_DIR = ROOT / "translated_files"
RUN_DIR = ROOT / "data" / "queue-runs"
EPUBCHECK_DIR = ROOT / "data" / "tools" / "epubcheck-5.4.0"

MODEL_ALIASES = {
    "hy-mt2-7b": "hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M",
    "hy-mt2": "hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M",
    "hy-mt2-7b-q4": "hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M",
    "hy-mt2-7b-q6": "hf.co/tencent/Hy-MT2-7B-GGUF:Q6_K",
}
CLOUD_PROVIDERS = {"gemini", "openai", "deepseek", "openrouter", "mistral", "poe", "nim"}


def _log_path(title: str) -> Path:
    return RUN_DIR / f"{_slug(title)}.log"


def _report_path(title: str) -> Path:
    return RUN_DIR / f"{_slug(title)}.report.json"


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value or "").strip("-").lower()
    return slug or "book"


def _is_sun_eater(book: Any) -> bool:
    """The reader pass has Sun Eater-specific terms and heading fixes."""
    author = str(getattr(book, "author", "") or "").casefold()
    series = str(getattr(book, "series", "") or "").casefold()
    return "ruocchio" in author or "sun eater" in series or "devorador do sol" in series


def log(title: str, message: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    with _log_path(title).open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)


def _inventory_row(calibre_id: int) -> Optional[Dict[str, Any]]:
    if not INVENTORY.exists():
        return None
    payload = json.loads(INVENTORY.read_text(encoding="utf-8"))
    for row in payload.get("books", []):
        if int(row.get("calibre_id") or 0) == int(calibre_id):
            return row
    return None


def host_source(book: Any) -> Path:
    path = Path(str(book.source_path))
    if path.exists():
        return path
    row = _inventory_row(int(book.calibre_id))
    if row and Path(str(row.get("epub_path") or "")).exists():
        return Path(str(row["epub_path"]))
    raise FileNotFoundError(f"source EPUB not found for {book.title}: {book.source_path}")


def container_source(book: Any) -> str:
    path = str(book.source_path or "")
    if path.startswith("/library/"):
        return path
    row = _inventory_row(int(book.calibre_id))
    if row:
        calibre_path = str(row.get("calibre_path") or "").replace("\\", "/").strip("/")
        filename = Path(path.replace("\\", "/")).name
        if calibre_path and filename:
            return f"/library/{calibre_path}/{filename}"
    raise FileNotFoundError(f"cannot map source path into /library: {path}")


def output_name(book: Any) -> str:
    title = re.sub(r'[<>:"/\\|?*]', "", str(book.title)).strip().strip(".")
    return f"{title} (pt-BR).epub"


def resolve_model(model: str) -> str:
    model = (model or "").strip()
    return MODEL_ALIASES.get(model, model)


def _compile_assets(book: Any, resources_root: str) -> Dict[str, str]:
    scopes = infer_scopes(book)
    compiled = compile_book_resources(book, resources_root)
    slug = _slug(book.title)
    glossary_host = ROOT / "data" / "compiled" / f"{slug}-glossary.json"
    style_host = ROOT / "Custom_Instructions" / f"queue-{slug}.yaml"
    write_glossary_json(compiled, str(glossary_host), name=book.title)
    write_style_preset(compiled, str(style_host), description=f"Queue preset: {book.title}")
    return {
        "glossary_host": str(glossary_host),
        "glossary_container": f"/app/data/compiled/{glossary_host.name}",
        "style_host": str(style_host),
        "style_container": style_host.name,
        "author": scopes.author,
        "universe": scopes.universe,
        "subseries": scopes.subseries,
        "book": scopes.book,
        "terms": str(len(compiled.glossary.terms)),
    }


def _translation_command(book: Any, model: str, provider: str, assets: Dict[str, str], output: str) -> List[str]:
    return [
        "docker",
        "compose",
        "-f",
        "docker-compose.dev.yml",
        "exec",
        "-T",
        "-e",
        "PYTHONUNBUFFERED=1",
        "app",
        "python",
        "translate.py",
        "-i",
        container_source(book),
        "-o",
        f"/app/translated_files/{output}",
        "-sl",
        "English",
        "-tl",
        "Portuguese (Brazil)",
        "--provider",
        provider,
        "-m",
        model,
        "--glossary",
        assets["glossary_container"],
        "--custom-instruction",
        assets["style_container"],
        "--no-color",
    ]


def _terminate_process_tree(process: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
        )
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def _container_translation_pids(output_name: str) -> List[int]:
    """PIDs of translate.py inside the app container, newest output first."""
    command = ["docker", "compose", "-f", "docker-compose.dev.yml", "top", "app"]
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except Exception:
        return []
    lines = [
        line for line in (completed.stdout or "").splitlines()
        if "translate.py" in line and "translation_api.py" not in line
    ]
    for require_output in (True, False):
        pids: List[int] = []
        for line in lines:
            if require_output and output_name and output_name not in line:
                continue
            parts = line.split()
            if len(parts) > 3 and parts[0] == "app" and parts[3].isdigit():
                pids.append(int(parts[3]))
        if pids:
            return pids
    return []


def _stop_translation_process(process: subprocess.Popen, output_name: str) -> None:
    """Stop the container-side translation, then the docker exec wrapper.

    The queue runner owns a ``docker compose exec`` process on the host; the
    actual ``translate.py`` runs inside the container. Killing only the host
    wrapper can leave the container process alive, so the container PID is
    signalled first. The per-chunk checkpoint on disk is what makes this safe.
    """
    for pid in _container_translation_pids(output_name):
        try:
            subprocess.run(
                [
                    "docker", "compose", "-f", "docker-compose.dev.yml",
                    "exec", "-T", "app", "kill", "-TERM", str(pid),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except Exception:
            pass
    deadline = time.time() + 20
    while process.poll() is None and time.time() < deadline:
        time.sleep(1)
    if process.poll() is None:
        _terminate_process_tree(process)


def _upstream_progress(translation_id: Optional[str] = None) -> Tuple[str, int, int]:
    if not CHECKPOINT_DB.exists():
        return "", 0, 0
    import sqlite3

    conn = sqlite3.connect(f"file:{CHECKPOINT_DB.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if translation_id:
            row = conn.execute(
                "SELECT status, progress FROM translation_jobs WHERE translation_id = ?",
                (translation_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT status, progress FROM translation_jobs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
    finally:
        conn.close()
    if not row:
        return "", 0, 0
    progress = json.loads(row["progress"] or "{}")
    return (
        str(row["status"]),
        int(progress.get("completed_chunks") or 0),
        int(progress.get("total_chunks") or 0),
    )


def _find_translation_id(title: str, since: Optional[str] = None) -> Optional[str]:
    import sqlite3

    if not CHECKPOINT_DB.exists():
        return None
    conn = sqlite3.connect(f"file:{CHECKPOINT_DB.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT translation_id, config, created_at FROM translation_jobs "
            "ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        if since and str(row["created_at"] or "") < since:
            continue
        cfg = json.loads(row["config"] or "{}")
        haystack = " ".join(
            str(cfg.get(key, ""))
            for key in ("input_file_path", "preserved_input_path", "output_file_path")
        )
        if title.casefold() in haystack.casefold():
            return str(row["translation_id"])
    return None


def _sync(book: Any) -> Dict[str, Any]:
    store = QueueStore(str(QUEUE_DB))
    try:
        return store.sync_from_upstream(str(CHECKPOINT_DB))
    finally:
        store.close()


def _epubcheck(path: Path) -> Dict[str, Any]:
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{EPUBCHECK_DIR}:/epubcheck:ro",
        "-v",
        f"{path.parent}:/books:ro",
        "eclipse-temurin:17-jre",
        "java",
        "-jar",
        "/epubcheck/epubcheck.jar",
        f"/books/{path.name}",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900
        )
    except Exception as exc:
        return {"error": str(exc)}
    text = (completed.stdout or "") + (completed.stderr or "")
    match = re.search(r"Messages:\s*(\d+)\s+fatals\s*/\s*(\d+)\s+errors\s*/\s*(\d+)\s+warnings", text)
    return {
        "returncode": completed.returncode,
        "fatals": int(match.group(1)) if match else None,
        "errors": int(match.group(2)) if match else None,
        "warnings": int(match.group(3)) if match else None,
        "tail": "\n".join(text.strip().splitlines()[-8:]),
    }


def _refine(
    source: Path,
    fixed: Path,
    refined: Path,
    assets: Dict[str, str],
    model: str,
    limit: int,
    pov: str,
    title: str,
) -> Dict[str, Any]:
    report_path = RUN_DIR / f"{_slug(title)}.refine.report.json"
    command = [
        sys.executable,
        "-m",
        "src.literary.cli",
        "refine-epub",
        "--source",
        str(source),
        "--target",
        str(fixed),
        "--out",
        str(refined),
        "--author",
        assets["author"],
        "--universe",
        assets["universe"],
        "--subseries",
        assets["subseries"],
        "--book",
        assets["book"],
        "--model",
        model,
        "--pov",
        pov,
        "--report",
        str(report_path),
    ]
    if limit and limit > 0:
        command.extend(["--limit", str(limit)])
    log(title, "refine-epub " + " ".join(command))
    completed = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    log(title, f"refine exit {completed.returncode}")
    if output.strip():
        log(title, output.strip()[-4000:])
    if report_path.exists():
        return json.loads(report_path.read_text(encoding="utf-8"))
    return {"error": f"refine failed with exit {completed.returncode}"}


def run_queue_book(
    *,
    db_path: str = str(QUEUE_DB),
    book_id: int = 0,
    resources_root: str = "literary-resources",
    refine_limit: int = 0,
    refine: bool = True,
    dry_run: bool = False,
    pov: str = "",
) -> Dict[str, Any]:
    store = QueueStore(db_path)
    try:
        book = store.get_book(book_id) if book_id else store.next_pending()
    finally:
        store.close()
    if not book:
        raise ValueError("no pending book in the queue")
    if book.status != "pending":
        raise ValueError(f"book {book.id} is {book.status}, not pending")
    source_language = str(book.source_language or "").casefold()
    target_language = str(book.target_language or "").casefold()
    if source_language and not source_language.startswith(("en", "eng")):
        raise ValueError(
            f"book {book.id} source is {book.source_language!r}; this fork only translates English sources"
        )
    if target_language and target_language not in {
        "pt-br",
        "portuguese",
        "portuguese (brazil)",
    }:
        raise ValueError(
            f"book {book.id} target is {book.target_language!r}; this fork only translates to pt-BR"
        )

    model = resolve_model(book.model)
    provider = (book.provider or "ollama").strip().lower()
    if not model:
        raise ValueError(f"book {book.id} has no model")
    if provider in CLOUD_PROVIDERS:
        raise ValueError(
            f"book {book.id} uses cloud provider {provider}; set a local model first"
        )

    plan = build_run_plan(book, resources_root=resources_root)
    assets = _compile_assets(book, resources_root)
    name = output_name(book)
    output_host = OUTPUT_DIR / name
    fixed_host = OUTPUT_DIR / f"{output_host.stem} - fixed.epub"
    v2_host = OUTPUT_DIR / f"{output_host.stem} - fixed-v2.epub"
    refined_host = OUTPUT_DIR / f"{output_host.stem}.refined.epub"
    command = _translation_command(book, model, provider, assets, name)

    if dry_run:
        return {
            "book": book.to_dict(),
            "plan": plan,
            "assets": assets,
            "command": command,
            "output": str(output_host),
            "refined_output": str(refined_host),
        }

    if output_host.exists():
        raise FileExistsError(f"output already exists: {output_host}")

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    _log_path(book.title).write_text("", encoding="utf-8")
    log(book.title, f"queue run for book {book.id}: {book.title}")
    log(book.title, " ".join(command))

    store = QueueStore(db_path)
    try:
        job_id = store.create_job(book.id)
        store.set_book_state(book.id, "preparing", "queue runner preparing")
        store.set_job_state(job_id, "preparing")
        store.add_event("queue runner started", book_id=book.id, job_id=job_id)
    finally:
        store.close()

    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    def reader() -> None:
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.rstrip()
            if line:
                with _log_path(book.title).open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")

    import threading

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    started = time.time()
    since = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    translation_id = None
    last_sync = 0.0
    complete_since = None
    stuck_terminated = False
    paused_by_user = False
    while process.poll() is None:
        if pause_now_requested(db_path):
            log(book.title, "pause-now requested; stopping the current translation")
            _stop_translation_process(process, output_host.name)
            paused_by_user = True
            break
        if translation_id is None and time.time() - started > 5:
            candidate = _find_translation_id(book.title, since)
            if candidate:
                store = QueueStore(db_path)
                try:
                    store.attach_translation_id(job_id, candidate)
                    store.add_event(
                        f"queue runner linked translation_id {candidate}",
                        book_id=book.id,
                        job_id=job_id,
                    )
                    translation_id = candidate
                    log(book.title, f"translation_id {candidate}")
                except ValueError as exc:
                    log(book.title, f"attach translation_id failed: {exc}")
                finally:
                    store.close()
        if time.time() - last_sync >= 30:
            report = _sync(book)
            log(
                book.title,
                "sync: checked={checked} matched={matched} updated={updated}".format(
                    checked=report.get("checked"),
                    matched=report.get("matched"),
                    updated=report.get("updated"),
                ),
            )
            last_sync = time.time()
        status, completed, total = _upstream_progress(translation_id)
        if total and completed >= total and output_host.exists():
            complete_since = complete_since or time.time()
            if time.time() - complete_since > 180:
                log(book.title, "translation is complete but docker exec is still open; terminating it")
                _terminate_process_tree(process)
                stuck_terminated = True
                break
        time.sleep(2)

    thread.join(timeout=15)
    returncode = process.wait()
    time.sleep(2)
    final_sync = _sync(book)
    log(book.title, f"translation process exited with {returncode}; final sync={final_sync}")
    if translation_id is None:
        translation_id = _find_translation_id(book.title, since)

    if paused_by_user:
        store = QueueStore(db_path)
        try:
            try:
                store.set_job_state(job_id, "paused", "paused by user from the queue UI")
            except ValueError:
                pass
            try:
                store.set_book_state(book.id, "paused", "paused by user from the queue UI")
            except ValueError:
                pass
            store.add_event(
                "queue runner paused by user",
                book_id=book.id,
                job_id=job_id,
                level="warning",
            )
        finally:
            store.close()
        honor_pause_now(db_path, {"id": book.id, "title": book.title})
        set_pause(db_path, False)
        report = {
            "book": book.to_dict(),
            "job_id": job_id,
            "translation_id": translation_id,
            "returncode": returncode,
            "paused": True,
            "queue_state": "paused",
            "duration_s": round(time.time() - started, 1),
            "output": str(output_host) if output_host.exists() else "",
        }
        _report_path(book.title).write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return report

    if not output_host.exists():
        store = QueueStore(db_path)
        try:
            store.set_job_state(job_id, "failed", "output EPUB was not created")
            store.set_book_state(book.id, "failed", "output EPUB was not created")
            store.add_event("queue runner failed: no output EPUB", book_id=book.id, job_id=job_id)
        finally:
            store.close()
        report = {
            "book": book.to_dict(),
            "job_id": job_id,
            "translation_id": translation_id,
            "returncode": returncode,
            "error": "output EPUB was not created",
            "duration_s": round(time.time() - started, 1),
        }
        _report_path(book.title).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    log(book.title, "repairing dropcaps")
    repair = repair_dropcaps_in_epub(str(output_host), str(fixed_host))
    log(book.title, "repairing invalid DPUB-ARIA roles")
    roles = repair_doc_roles_in_epub(str(fixed_host), str(v2_host))
    validation = validate_epub_pair(str(host_source(book)), str(v2_host), expected_language="pt-BR")
    log(book.title, f"validation passed={validation.get('passed')} blocking={validation.get('blocking')}")
    epubcheck = _epubcheck(v2_host)
    log(book.title, f"EPUBCheck {epubcheck}")

    refine_report = None
    if refine:
        refine_report = _refine(
            host_source(book),
            v2_host,
            refined_host,
            assets,
            model,
            refine_limit,
            pov,
            book.title,
        )
        if refined_host.exists():
            validation = validate_epub_pair(
                str(host_source(book)), str(refined_host), expected_language="pt-BR"
            )
            epubcheck = _epubcheck(refined_host)

    reader_report = None
    if _is_sun_eater(book):
        reader_input = refined_host if refined_host.exists() else v2_host
        reader_temp = OUTPUT_DIR / f".{output_host.stem}.reader.tmp.epub"
        log(book.title, "reader repair: joining chunk seams and normalising dialogue")
        try:
            reader_report = repair_reading_epub(
                str(reader_input),
                str(reader_temp),
                apply_terms=True,
            )
            reader_validation = validate_epub_pair(
                str(host_source(book)), str(reader_temp), expected_language="pt-BR"
            )
            reader_epubcheck = _epubcheck(reader_temp)
            if bool(reader_validation.get("passed")) and reader_epubcheck.get("errors") == 0:
                os.replace(reader_temp, refined_host)
                validation = reader_validation
                epubcheck = reader_epubcheck
                reader_report["accepted"] = True
                reader_report["final"] = str(refined_host)
                log(
                    book.title,
                    "reader repair accepted: merged={} quotes={} splits={}".format(
                        reader_report.get("merged"),
                        reader_report.get("quote_paragraphs"),
                        (reader_report.get("artefact_changes") or {}).get("split_dialogue_paragraphs"),
                    ),
                )
            else:
                reader_report["accepted"] = False
                reader_report["reason"] = "reader validation gate failed"
                log(book.title, "reader repair rejected: validation gate failed")
                if reader_temp.exists():
                    reader_temp.unlink()
        except Exception as exc:
            reader_report = {"accepted": False, "error": str(exc)}
            log(book.title, f"reader repair failed; keeping the previous artifact: {exc}")
            if reader_temp.exists():
                reader_temp.unlink()

    store = QueueStore(db_path)
    gate_ok = bool(validation.get("passed")) and epubcheck.get("errors") == 0
    target_state = "completed" if gate_ok else "needs_review"
    try:
        if target_state == "completed":
            for state in ("reviewing", "validating", "completed"):
                try:
                    store.set_job_state(job_id, state, "machine translation complete; review optional")
                except ValueError:
                    pass
                try:
                    store.set_book_state(book.id, state, "machine translation complete; review optional")
                except ValueError:
                    pass
        else:
            try:
                store.set_job_state(job_id, "needs_review", "validation gate failed; review required")
            except ValueError:
                store.set_job_state(job_id, "validating")
                store.set_job_state(job_id, "needs_review", "validation gate failed; review required")
            store.set_book_state(book.id, "needs_review", "validation gate failed; review required")
        store.add_event(
            f"queue runner finished: {target_state}",
            book_id=book.id,
            job_id=job_id,
        )
        job = store.get_job(job_id)
        final_book = store.get_book(book.id)
    finally:
        store.close()

    report = {
        "book": book.to_dict(),
        "job_id": job_id,
        "translation_id": translation_id,
        "returncode": returncode,
        "stuck_exec_terminated": stuck_terminated,
        "duration_s": round(time.time() - started, 1),
        "model": model,
        "provider": provider,
        "output": str(output_host),
        "fixed_output": str(v2_host),
        "refined_output": str(refined_host) if refined_host.exists() else "",
        "assets": assets,
        "dropcap_repair": {
            "total_changes": repair.get("total_changes"),
            "changed_files": [item["file"] for item in repair.get("changed_files", [])],
        },
        "role_repair": {
            "total_changes": roles.get("total_changes"),
            "changed_files": [item["file"] for item in roles.get("changed_files", [])],
        },
        "validation": validation,
        "epubcheck": epubcheck,
        "refine": refine_report,
        "reader_repair": reader_report,
        "queue_state": target_state,
        "review_required": target_state != "completed",
        "queue_job": job,
        "queue_book": final_book.to_dict() if final_book else None,
    }
    _report_path(book.title).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log(book.title, f"finished; report={_report_path(book.title)}")
    return report
