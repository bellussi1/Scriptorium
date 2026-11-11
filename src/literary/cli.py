"""Command line interface for the literary layer.

Examples::

    python -m src.literary.cli inventory --library "C:/.../Biblioteca do calibre" --out data/calibre/inventory.json --scan
    python -m src.literary.cli resources validate --root literary-resources
    python -m src.literary.cli resources compile --root literary-resources \
        --author robin-hobb --universe realm-of-the-elderlings --subseries farseer \
        --book assassins-apprentice --glossary-out data/compiled/farseer-1.json
    python -m src.literary.cli estimate --words 165049 --provider gemini --model gemini-3.8-flash
    python -m src.literary.cli validate epub --source book.epub --target "book (Portuguese).epub"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .calibre import CalibreLibrary
from .cost import SCENARIOS, estimate_book, estimate_scenario, estimate_series, get_pricing
from .epub import read_epub, update_opf_metadata, validate_epub_structure
from .models import BookRecord, Severity
from .queue import QueueStore
from .queue_control import honor_pause, pause_requested, set_pause, set_pause_now
from .refine_runner import (
    find_flagged_segments,
    generate_ollama,
    refine_segments,
    render_refined_text,
    split_segments,
)
from .repair import repair_dropcaps_in_epub
from .continuity import ContinuityTracker
from .refine_epub import refine_epub
from .resources import (
    assemble_style,
    compile_for_book,
    glossary_to_prompt_dicts,
    load_tree,
    validate_tree,
    write_glossary_json,
    write_style_preset,
)
from .validation import summarize_issues, validate_epub_pair, validate_pair


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _book_from_dict(data: Dict[str, Any]) -> BookRecord:
    allowed = BookRecord.__dataclass_fields__.keys()
    return BookRecord(**{key: value for key, value in data.items() if key in allowed})


def cmd_inventory(args: argparse.Namespace) -> int:
    library = CalibreLibrary(args.library)
    payload = library.write_inventory(
        args.out,
        scan_epubs=args.scan,
        author_filter=args.author or None,
        series_filter=args.series or None,
    )
    summary = {
        "books": payload["book_count"],
        "epubs": payload["epub_count"],
        "words": payload["word_count"],
        "series": len(payload["series"]),
        "issues": len(payload["issues"]),
        "out": os.path.abspath(args.out),
    }
    _print_json(summary)
    return 0


def cmd_resources_validate(args: argparse.Namespace) -> int:
    tree = load_tree(args.root)
    issues = validate_tree(tree)
    _print_json(
        {
            "root": os.path.abspath(args.root),
            "files": len(tree.files),
            "passed": not any(issue.severity in {Severity.ERROR, Severity.CRITICAL} for issue in issues),
            "issues": [issue.to_dict() for issue in issues],
        }
    )
    return 0 if not any(issue.severity in {Severity.ERROR, Severity.CRITICAL} for issue in issues) else 1


def cmd_resources_compile(args: argparse.Namespace) -> int:
    tree = load_tree(args.root)
    compiled = compile_for_book(
        tree,
        author=args.author,
        universe=args.universe,
        subseries=args.subseries or "",
        book=args.book or "",
        book_order=args.order,
    )
    result: Dict[str, Any] = {
        "terms": len(compiled.glossary.terms),
        "series": compiled.series.name if compiled.series else "",
        "book": compiled.book.title if compiled.book else "",
        "issues": [issue.to_dict() for issue in compiled.issues],
    }
    if args.glossary_out:
        write_glossary_json(compiled, args.glossary_out, name=args.name or (compiled.series.name if compiled.series else "literary"))
        result["glossary_out"] = os.path.abspath(args.glossary_out)
    if args.style_out:
        write_style_preset(compiled, args.style_out)
        result["style_out"] = os.path.abspath(args.style_out)
    terms, metadata, forbidden = glossary_to_prompt_dicts(compiled)
    result["prompt_terms"] = len(terms)
    result["forbidden_terms"] = len(forbidden)
    _print_json(result)
    return 0


def cmd_queue_add(args: argparse.Namespace) -> int:
    target = str(args.target or "pt-BR")
    if target not in {"pt-BR", "Portuguese", "Portuguese (Brazil)"}:
        _print_json(
            {
                "error": "this fork only queues English -> Brazilian Portuguese books",
                "target": target,
            }
        )
        return 1
    payload = _read_json(args.inventory)
    books = [_book_from_dict(row) for row in payload.get("books", [])]
    selected = []
    for book in books:
        if not book.is_english:
            continue
        if args.author and args.author.casefold() not in book.author.casefold():
            continue
        if args.series and args.series.casefold() not in book.series.casefold():
            continue
        if args.language and not any(
            str(lang).lower().startswith(args.language.lower()) for lang in book.languages
        ):
            continue
        selected.append(book)
    store = QueueStore(args.db)
    ids = []
    for book in selected:
        estimated_cost = 0.0
        if args.model and args.provider:
            try:
                estimate = estimate_book(
                    word_count=book.word_count,
                    provider=args.provider,
                    model=args.model,
                )
                estimated_cost = estimate.total_cost
            except Exception:
                estimated_cost = 0.0
        ids.append(
            store.add_book(
                book,
                target_language="pt-BR",
                priority=args.priority,
                glossary_scope=args.glossary_scope or "",
                style_scope=args.style_scope or "",
                model=args.model,
                provider=args.provider,
                estimated_cost=estimated_cost,
            )
        )
    _print_json({"queued": len(ids), "book_ids": ids, "db": os.path.abspath(args.db)})
    store.close()
    return 0


def cmd_queue_list(args: argparse.Namespace) -> int:
    store = QueueStore(args.db)
    _print_json({"summary": store.summary(), "books": [book.to_dict() for book in store.list_books(args.status)]})
    store.close()
    return 0


def cmd_queue_next(args: argparse.Namespace) -> int:
    store = QueueStore(args.db)
    book = store.next_pending()
    _print_json(book.to_dict() if book else {"book": None})
    store.close()
    return 0


def cmd_queue_plan(args: argparse.Namespace) -> int:
    from .run_plan import build_run_plan

    book = QueueStore.get_book_readonly(args.db, args.book_id)
    if not book:
        _print_json({"error": "book not found", "book_id": args.book_id})
        return 1
    plan = build_run_plan(
        book,
        resources_root=args.resources,
        refine=not args.no_refine,
        grammar=not args.no_grammar,
        best_of_n=args.best_of_n,
        continuity=not args.no_continuity,
        previous_chapter_text=(
            Path(args.previous_chapter).read_text(encoding="utf-8")
            if args.previous_chapter
            else ""
        ),
        pov=args.pov,
        continuity_notes=args.continuity_notes,
    )
    _print_json(plan)
    return 0


def cmd_queue_run(args: argparse.Namespace) -> int:
    from .queue_runner import active_direct_translation, run_queue_book

    if args.parallel and args.parallel > 1:
        _print_json({"error": "one chunk at a time; --parallel must be 0 or 1"})
        return 1
    exclude = ""
    if args.book_id:
        store = QueueStore(args.db)
        try:
            job = store.latest_job(args.book_id)
            exclude = str((job or {}).get("translation_id") or "")
        finally:
            store.close()
    active = active_direct_translation(
        Path(args.db).with_name("jobs.mirror.db"),
        exclude_translation_id=exclude,
    )
    if active:
        _print_json({
            "error": "another translation is active; one book at a time",
            "translation_id": active,
        })
        return 1
    try:
        result = run_queue_book(
            db_path=args.db,
            book_id=args.book_id,
            resources_root=args.resources,
            refine_limit=args.refine_limit,
            refine=not args.no_refine,
            dry_run=args.dry_run,
            pov=args.pov,
            parallel_workers=args.parallel,
        )
    except Exception as exc:
        _print_json({"error": str(exc)})
        return 1
    _print_json(result)
    return 0


def cmd_queue_run_all(args: argparse.Namespace) -> int:
    from .kindle import build_kindle_library
    from .queue_runner import active_direct_translation, run_queue_book

    if args.max_books != 1:
        _print_json({"error": "one book per run; --max-books must be 1"})
        return 1
    if args.parallel and args.parallel > 1:
        _print_json({"error": "one chunk at a time; --parallel must be 0 or 1"})
        return 1
    results = []
    processed = 0
    last_finished = None
    blocked = False
    while not args.max_books or processed < args.max_books:
        # The web UI and `queue pause` arm this flag. With max_books=1 the
        # runner always stops after this book; the flag is still honoured so
        # the control file does not stay armed.
        if pause_requested(args.db):
            control = honor_pause(args.db, last_finished)
            results.append({
                "paused": "after_book",
                "after": last_finished,
                "control": control,
            })
            break

        store = QueueStore(args.db)
        try:
            book = store.next_pending()
        finally:
            store.close()
        if not book:
            break
        store = QueueStore(args.db)
        try:
            latest = store.latest_job(book.id)
            exclude = str((latest or {}).get("translation_id") or "")
        finally:
            store.close()
        active = active_direct_translation(
            Path(args.db).with_name("jobs.mirror.db"),
            exclude_translation_id=exclude,
        )
        if active:
            results.append({
                "book_id": book.id,
                "title": book.title,
                "error": "another translation is active; one book at a time",
                "translation_id": active,
            })
            blocked = True
            break
        processed += 1
        try:
            result = run_queue_book(
                db_path=args.db,
                book_id=book.id,
                resources_root=args.resources,
                refine_limit=args.refine_limit,
                refine=not args.no_refine,
                dry_run=False,
                pov=args.pov,
                parallel_workers=args.parallel,
            )
            last_finished = {"id": book.id, "title": book.title}
            results.append({"book_id": book.id, "title": book.title, "state": result.get("queue_state"), "report": result})
            if result.get("paused"):
                break
            if args.export_kindle:
                try:
                    build_kindle_library(
                        db_path=args.db,
                        outputs_dir=args.outputs,
                        output_root=args.kindle_out,
                    )
                except Exception as exc:
                    results.append({"book_id": book.id, "kindle_export_error": str(exc)})
            if args.stop_on_review and result.get("queue_state") == "needs_review":
                break
        except Exception as exc:
            results.append({"book_id": book.id, "title": book.title, "error": str(exc)})
            # Mark the book failed before moving on. Without a state change it
            # stays pending and the loop would pick it again forever. Stop the
            # batch if even that write fails.
            try:
                store = QueueStore(args.db)
                try:
                    store.set_book_state(book.id, "failed", f"runner error: {exc}")
                finally:
                    store.close()
            except Exception:
                break
            if args.stop_on_error:
                break

    if last_finished and pause_requested(args.db):
        honor_pause(args.db, last_finished)

    kindle_result = None
    if args.export_kindle:
        kindle_result = build_kindle_library(
            db_path=args.db,
            outputs_dir=args.outputs,
            output_root=args.kindle_out,
        )
    _print_json({"processed": processed, "results": results, "kindle": kindle_result})
    return 1 if blocked else 0


def cmd_queue_pause(args: argparse.Namespace) -> int:
    _print_json(set_pause(args.db, True))
    return 0


def cmd_queue_pause_now(args: argparse.Namespace) -> int:
    _print_json(set_pause_now(args.db, True))
    return 0


def cmd_queue_resume(args: argparse.Namespace) -> int:
    set_pause(args.db, False)
    _print_json(set_pause_now(args.db, False))
    return 0


def cmd_queue_export_kindle(args: argparse.Namespace) -> int:
    from .kindle import build_kindle_library

    try:
        result = build_kindle_library(
            db_path=args.db,
            outputs_dir=args.outputs,
            output_root=args.out,
            include_needs_review=args.include_needs_review,
        )
    except Exception as exc:
        _print_json({"error": str(exc)})
        return 1
    _print_json(result)
    return 0


def cmd_queue_polish(args: argparse.Namespace) -> int:
    from .polish import polish_completed_books

    try:
        result = polish_completed_books(
            db_path=args.db,
            outputs_dir=args.outputs,
            book_id=args.book_id,
            force=args.force,
            run_epubcheck=not args.no_epubcheck,
            kindle_out=args.kindle_out,
        )
    except Exception as exc:
        _print_json({"error": str(exc)})
        return 1
    _print_json(result)
    return 0


def cmd_queue_set_model(args: argparse.Namespace) -> int:
    store = QueueStore(args.db)
    try:
        if not store.update_book_model(args.book_id, args.model, args.provider):
            _print_json({"error": "book not found", "book_id": args.book_id})
            store.close()
            return 1
    except ValueError as exc:
        _print_json({"error": str(exc)})
        store.close()
        return 1
    _print_json(store.get_book(args.book_id).to_dict())
    store.close()
    return 0


def cmd_queue_approve(args: argparse.Namespace) -> int:
    store = QueueStore(args.db)
    book = store.get_book(args.book_id)
    job = store.get_job(args.job_id)
    if not book or not job:
        _print_json({"error": "book or job not found", "book_id": args.book_id, "job_id": args.job_id})
        store.close()
        return 1
    try:
        store.set_job_state(args.job_id, "completed", args.message or "human review approved")
        store.set_book_state(args.book_id, "completed", args.message or "human review approved")
        store.mark_reviewed(args.book_id, args.message or "human review approved")
        store.add_event(
            args.message or "human review approved",
            book_id=args.book_id,
            job_id=args.job_id,
        )
    except ValueError as exc:
        _print_json({"error": str(exc)})
        store.close()
        return 1
    _print_json({"book": store.get_book(args.book_id).to_dict(), "job": store.get_job(args.job_id)})
    store.close()
    return 0


def cmd_queue_state(args: argparse.Namespace) -> int:
    store = QueueStore(args.db)
    store.set_book_state(args.book_id, args.state, message=args.message or "")
    book = store.get_book(args.book_id)
    _print_json(book.to_dict() if book else {"book": None})
    store.close()
    return 0


def cmd_queue_reset(args: argparse.Namespace) -> int:
    store = QueueStore(args.db)
    _print_json({"reset": store.reset_in_progress()})
    store.close()
    return 0


def cmd_queue_start(args: argparse.Namespace) -> int:
    store = QueueStore(args.db)
    book = store.get_book(args.book_id)
    if not book:
        _print_json({"error": "book not found", "book_id": args.book_id})
        store.close()
        return 1
    job_id = store.create_job(book.id, total_chapters=args.total_chapters)
    try:
        store.set_book_state(book.id, "preparing", "book preparing")
        store.set_job_state(job_id, "preparing")
        store.add_event("queue job created", book_id=book.id, job_id=job_id)
    except ValueError as exc:
        _print_json({"error": str(exc), "job_id": job_id})
        store.close()
        return 1
    _print_json({"job_id": job_id, "book": store.get_book(book.id).to_dict()})
    store.close()
    return 0


def cmd_queue_jobs(args: argparse.Namespace) -> int:
    store = QueueStore(args.db)
    _print_json({"jobs": store.list_jobs(args.limit)})
    store.close()
    return 0


def cmd_queue_attach(args: argparse.Namespace) -> int:
    store = QueueStore(args.db)
    try:
        store.attach_translation_id(args.job_id, args.translation_id)
    except ValueError as exc:
        _print_json({"error": str(exc)})
        store.close()
        return 1
    _print_json({"job": store.get_job(args.job_id)})
    store.close()
    return 0


def cmd_queue_sync(args: argparse.Namespace) -> int:
    store = QueueStore(args.db)
    report = store.sync_from_upstream(args.checkpoint_db)
    _print_json(report)
    store.close()
    return 0 if not report.get("error") else 1


def cmd_db_snapshot(args: argparse.Namespace) -> int:
    """Write a compact, consistent snapshot of the live jobs DB."""
    import re
    import sqlite3
    from datetime import datetime, timezone

    live = Path(os.getenv("JOBS_DB_PATH", "data/jobs.db"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    label = re.sub(r"[^a-z0-9]+", "-", (args.label or "").strip().lower()).strip("-")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"jobs-{label + '-' if label else ''}{stamp}.db"
    out = out_dir / name

    src = sqlite3.connect(f"file:{live.as_posix()}?mode=ro", uri=True, timeout=30)
    dst = sqlite3.connect(str(out))
    try:
        src.backup(dst)
        dst.commit()
        integrity = str(dst.execute("PRAGMA quick_check").fetchone()[0])
    finally:
        dst.close()
        src.close()
    _print_json({
        "path": str(out),
        "size": out.stat().st_size,
        "integrity": integrity,
        "label": label,
        "timestamp": stamp,
    })
    return 0 if integrity.lower() == "ok" else 1


def cmd_db_health(args: argparse.Namespace) -> int:
    """Report the live jobs DB integrity and journal mode without writing."""
    import sqlite3

    live = Path(os.getenv("JOBS_DB_PATH", "data/jobs.db"))
    con = sqlite3.connect(f"file:{live.as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        integrity = str(con.execute("PRAGMA quick_check").fetchone()[0])
        journal = str(con.execute("PRAGMA journal_mode").fetchone()[0])
        jobs = int(con.execute("SELECT COUNT(*) FROM translation_jobs").fetchone()[0])
    finally:
        con.close()
    _print_json({
        "path": str(live),
        "integrity": integrity,
        "journal_mode": journal,
        "jobs": jobs,
    })
    return 0 if integrity.lower() == "ok" else 1


def cmd_checkpoint_status(args: argparse.Namespace) -> int:
    """Report the live checkpoint state from inside the app container."""
    import os
    from pathlib import Path

    from src.persistence.checkpoint_manager import CheckpointManager

    db_path = os.getenv("JOBS_DB_PATH", "data/jobs.db")
    manager = CheckpointManager(db_path=db_path)
    try:
        if args.reconcile:
            manager.reconcile_job(args.id)
        job = manager.get_job(args.id)
        if not job:
            _print_json({
                "translation_id": args.id,
                "found": False,
                "resumable": False,
            })
            return 1

        stats = manager.db.get_chunk_stats(args.id)
        progress = job.get("progress") or {}
        config = job.get("config") or {}
        file_type = str(job.get("file_type") or "").lower()
        total = int(progress.get("total_chunks") or 0)
        input_path = config.get("preserved_input_path") or config.get("file_path")
        input_exists = bool(input_path and Path(input_path).exists())
        if not input_exists:
            input_exists = (Path("data/uploads") / args.id).exists()
        health = manager.health()
        if file_type == "epub":
            # EPUB checkpoint rows are files; the global chunk count and the
            # unfinished-chunk map live in the progress JSON / xhtml states.
            completed = int(progress.get("completed_chunks") or 0)
            failed = int(progress.get("failed_chunks") or 0)
            unfinished = bool(progress.get("epub_unfinished_units"))
            resumable = (
                input_exists
                and total > 0
                and (completed < total or unfinished)
                and str(job.get("status") or "") != "completed"
            )
        else:
            completed = int(stats["completed"] or 0)
            failed = int(stats["failed"] or 0)
            resumable = (
                input_exists
                and total > 0
                and stats["total"] > 0
                and completed < total
                and str(job.get("status") or "") != "completed"
            )
        _print_json({
            "translation_id": args.id,
            "found": True,
            "status": job.get("status"),
            "file_type": file_type,
            "resumable": resumable,
            "input_exists": input_exists,
            "total_chunks": total,
            "completed_chunks": completed,
            "failed_chunks": failed,
            "chunk_rows": stats["total"],
            "completed_files": stats["completed"],
            "last_index": stats["last_index"],
            "db_integrity": health["integrity"],
            "journal_mode": health["journal_mode"],
        })
        return 0
    finally:
        manager.close()


def cmd_queue_job_state(args: argparse.Namespace) -> int:
    store = QueueStore(args.db)
    try:
        store.set_job_state(args.job_id, args.state)
    except ValueError as exc:
        _print_json({"error": str(exc)})
        store.close()
        return 1
    if args.message:
        job = store.get_job(args.job_id)
        store.add_event(
            args.message,
            book_id=job["book_id"] if job else None,
            job_id=args.job_id,
        )
    _print_json({"job": store.get_job(args.job_id)})
    store.close()
    return 0


def cmd_refine(args: argparse.Namespace) -> int:
    with open(args.source, "r", encoding="utf-8") as handle:
        source_text = handle.read()
    with open(args.draft, "r", encoding="utf-8") as handle:
        draft_text = handle.read()

    compiled = None
    style = ""
    if args.author and args.universe:
        tree = load_tree(args.root)
        compiled = compile_for_book(
            tree,
            args.author,
            args.universe,
            args.subseries,
            args.book,
        )
        style = assemble_style(compiled.style).get("refinement", "")

    source_segments = split_segments(source_text)
    draft_segments = split_segments(draft_text)
    flagged = find_flagged_segments(
        source_segments, draft_segments, compiled=compiled
    )
    if args.dry_run:
        _print_json(
            {
                "source_segments": len(source_segments),
                "draft_segments": len(draft_segments),
                "flagged": [segment.to_report() for segment in flagged],
            }
        )
        return 0

    def generate(messages):
        return generate_ollama(
            messages,
            model=args.model,
            endpoint=args.endpoint,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )

    replacements, report = refine_segments(
        flagged,
        generate,
        compiled=compiled,
        style=style,
        limit=args.limit,
    )
    output = render_refined_text(draft_text, replacements)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(output)
    report.update(
        {
            "source_segments": len(source_segments),
            "draft_segments": len(draft_segments),
            "out": os.path.abspath(args.out),
        }
    )
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
    _print_json(report)
    return 0


def cmd_refine_epub(args: argparse.Namespace) -> int:
    compiled = None
    style = ""
    tracker = None
    if args.author and args.universe:
        tree = load_tree(args.root)
        compiled = compile_for_book(
            tree,
            args.author,
            args.universe,
            args.subseries,
            args.book,
        )
        style = assemble_style(compiled.style).get("refinement", "")
        tracker = ContinuityTracker.from_compiled(compiled, pov=args.pov)
    report = refine_epub(
        args.source,
        args.target,
        args.out,
        model=args.model,
        compiled=compiled,
        style=style,
        continuity=tracker,
        endpoint=args.endpoint,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        num_ctx=args.num_ctx,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    if args.report:
        Path(args.report).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    _print_json(report)
    return 0


def cmd_repair_dropcaps(args: argparse.Namespace) -> int:
    report = repair_dropcaps_in_epub(args.source, args.out)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
    _print_json(report)
    return 0


def cmd_estimate(args: argparse.Namespace) -> int:
    books: List[Dict[str, Any]] = []
    if args.inventory:
        payload = _read_json(args.inventory)
        books = payload.get("books", [])
        if args.calibre_id:
            books = [book for book in books if int(book.get("calibre_id", 0)) == args.calibre_id]
        if args.series:
            books = [book for book in books if args.series.casefold() in str(book.get("series", "")).casefold()]
        if args.author:
            books = [book for book in books if args.author.casefold() in str(book.get("author", "")).casefold()]
        if args.language:
            books = [book for book in books if any(str(lang).lower().startswith(args.language.lower()) for lang in book.get("languages", []))]
        if not books:
            _print_json({"error": "no books matched the filters", "inventory": args.inventory})
            return 1
        result = estimate_series(books, scenarios=args.scenarios)
        _print_json(result)
        return 0
    if args.words is None:
        _print_json({"error": "provide --words or --inventory"})
        return 1
    if args.all_scenarios:
        scenarios = list(SCENARIOS.keys())
        _print_json({scenario: estimate_scenario(args.words, scenario) for scenario in scenarios})
        return 0
    estimate = estimate_book(
        word_count=args.words,
        provider=args.provider,
        model=args.model,
        passes=args.passes,
        retry_rate=args.retry_rate,
        batch=args.batch,
        offpeak=args.offpeak,
        judge=args.judge,
    )
    _print_json(estimate.to_dict())
    return 0


def cmd_validate_epub(args: argparse.Namespace) -> int:
    if args.target:
        payload = validate_epub_pair(args.source, args.target, expected_language=args.language)
    else:
        issues = validate_epub_structure(args.source)
        payload = {"issues": [issue.to_dict() for issue in issues], **summarize_issues(issues)}
    _print_json(payload)
    return 0 if payload.get("passed", False) else 1


def cmd_validate_text(args: argparse.Namespace) -> int:
    with open(args.source, "r", encoding="utf-8") as handle:
        source = handle.read()
    with open(args.target, "r", encoding="utf-8") as handle:
        target = handle.read()
    compiled = None
    if args.author and args.universe and args.root:
        tree = load_tree(args.root)
        compiled = compile_for_book(tree, args.author, args.universe, args.subseries or "", args.book or "")
    issues = validate_pair(source, target, compiled=compiled)
    payload = summarize_issues(issues)
    _print_json(payload)
    return 0 if payload["passed"] else 1


def cmd_metadata_apply(args: argparse.Namespace) -> int:
    result = update_opf_metadata(
        args.source,
        args.output,
        title=args.title,
        language=args.language,
        identifier=args.identifier,
        series=args.series,
        series_index=args.series_index,
    )
    _print_json({"output": os.path.abspath(result)})
    return 0


def cmd_pricing(args: argparse.Namespace) -> int:
    pricing = get_pricing(args.provider, args.model)
    _print_json(
        {
            "provider": pricing.provider,
            "model": pricing.model,
            "input_per_m": pricing.input_per_m,
            "output_per_m": pricing.output_per_m,
            "cache_read_per_m": pricing.cache_read_per_m,
            "batch_multiplier": pricing.batch_multiplier,
            "offpeak_multiplier": pricing.offpeak_multiplier,
            "context_window": pricing.context_window,
            "data_policy": pricing.data_policy,
            "source": pricing.source,
            "notes": pricing.notes,
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.literary.cli", description="Literary translation infrastructure")
    sub = parser.add_subparsers(dest="command", required=True)

    inventory = sub.add_parser("inventory", help="Read-only Calibre inventory")
    inventory.add_argument("--library", required=True)
    inventory.add_argument("--out", required=True)
    inventory.add_argument("--scan", action="store_true", help="Read every EPUB for title/language/word count")
    inventory.add_argument("--author", action="append", help="Restrict to an author substring; repeatable")
    inventory.add_argument("--series", action="append", help="Restrict to a series substring; repeatable")
    inventory.set_defaults(func=cmd_inventory)

    resources = sub.add_parser("resources", help="Validate or compile hierarchical resources")
    resources_sub = resources.add_subparsers(dest="resources_command", required=True)
    validate = resources_sub.add_parser("validate")
    validate.add_argument("--root", default="literary-resources")
    validate.set_defaults(func=cmd_resources_validate)
    compile_parser = resources_sub.add_parser("compile")
    compile_parser.add_argument("--root", default="literary-resources")
    compile_parser.add_argument("--author", required=True)
    compile_parser.add_argument("--universe", required=True)
    compile_parser.add_argument("--subseries", default="")
    compile_parser.add_argument("--book", default="")
    compile_parser.add_argument("--order", type=float)
    compile_parser.add_argument("--name", default="")
    compile_parser.add_argument("--glossary-out")
    compile_parser.add_argument("--style-out")
    compile_parser.set_defaults(func=cmd_resources_compile)

    queue = sub.add_parser("queue", help="Persistent book queue")
    queue_sub = queue.add_subparsers(dest="queue_command", required=True)
    add = queue_sub.add_parser("add")
    add.add_argument("--db", default="data/literary_queue.db")
    add.add_argument("--inventory", required=True)
    add.add_argument("--author", default="")
    add.add_argument("--series", default="")
    add.add_argument("--language", default="")
    add.add_argument("--target", default="pt-BR")
    add.add_argument("--priority", type=int, default=0)
    add.add_argument("--glossary-scope", default="")
    add.add_argument("--style-scope", default="")
    add.add_argument("--model", default="")
    add.add_argument("--provider", default="")
    add.set_defaults(func=cmd_queue_add)
    list_parser = queue_sub.add_parser("list")
    list_parser.add_argument("--db", default="data/literary_queue.db")
    list_parser.add_argument("--status")
    list_parser.set_defaults(func=cmd_queue_list)
    next_parser = queue_sub.add_parser("next")
    next_parser.add_argument("--db", default="data/literary_queue.db")
    next_parser.set_defaults(func=cmd_queue_next)
    plan_parser = queue_sub.add_parser("plan", help="Resolve model, glossary, style and gates for a book")
    plan_parser.add_argument("--db", default="data/literary_queue.db")
    plan_parser.add_argument("--book-id", type=int, required=True)
    plan_parser.add_argument("--resources", default="literary-resources")
    plan_parser.add_argument("--best-of-n", type=int, default=1)
    plan_parser.add_argument("--no-refine", action="store_true")
    plan_parser.add_argument("--no-grammar", action="store_true")
    plan_parser.add_argument("--no-continuity", action="store_true")
    plan_parser.add_argument("--previous-chapter", default="", help="Optional UTF-8 text file with the previous chapter")
    plan_parser.add_argument("--pov", default="", help="Narrator/person note for the continuity block")
    plan_parser.add_argument("--continuity-notes", default="", help="Extra continuity/address rules")
    plan_parser.set_defaults(func=cmd_queue_plan)
    approve_parser = queue_sub.add_parser("approve", help="Mark a needs_review book/job as completed after human review")
    approve_parser.add_argument("--db", default="data/literary_queue.db")
    approve_parser.add_argument("--book-id", type=int, required=True)
    approve_parser.add_argument("--job-id", type=int, required=True)
    approve_parser.add_argument("--message", default="human review approved")
    approve_parser.set_defaults(func=cmd_queue_approve)
    set_model_parser = queue_sub.add_parser("set-model", help="Change model/provider for a pending book")
    set_model_parser.add_argument("--db", default="data/literary_queue.db")
    set_model_parser.add_argument("--book-id", type=int, required=True)
    set_model_parser.add_argument("--model", required=True)
    set_model_parser.add_argument("--provider", default="ollama")
    set_model_parser.set_defaults(func=cmd_queue_set_model)
    run_parser = queue_sub.add_parser("run", help="Translate the next pending book end to end and stop at needs_review")
    run_parser.add_argument("--db", default="data/literary_queue.db")
    run_parser.add_argument("--book-id", type=int, default=0, help="0 = next pending book")
    run_parser.add_argument("--resources", default="literary-resources")
    run_parser.add_argument("--refine-limit", type=int, default=0, help="0 = refine every flagged segment")
    run_parser.add_argument("--no-refine", action="store_true")
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--pov", default="", help="Narrator/POV note for refinement")
    run_parser.add_argument(
        "--parallel", type=int, default=1,
        help="One chunk at a time; only 0/1 are accepted",
    )
    run_parser.set_defaults(func=cmd_queue_run)
    export_parser = queue_sub.add_parser("export-kindle", help="Build a standardized Kindle folder from queue artifacts")
    export_parser.add_argument("--db", default="data/literary_queue.db")
    export_parser.add_argument("--outputs", default="translated_files")
    export_parser.add_argument("--out", default="translated_files/kindle")
    export_parser.add_argument("--include-needs-review", action="store_true")
    export_parser.add_argument("--completed-only", action="store_true", help=argparse.SUPPRESS)
    export_parser.set_defaults(func=cmd_queue_export_kindle)
    polish_parser = queue_sub.add_parser(
        "polish",
        help="Apply the reader repair to completed Sun Eater books and refresh the Kindle folder",
    )
    polish_parser.add_argument("--db", default="data/literary_queue.db")
    polish_parser.add_argument("--outputs", default="translated_files")
    polish_parser.add_argument("--kindle-out", default="translated_files/kindle")
    polish_parser.add_argument("--book-id", type=int, default=0)
    polish_parser.add_argument("--force", action="store_true")
    polish_parser.add_argument("--no-epubcheck", action="store_true")
    polish_parser.set_defaults(func=cmd_queue_polish)
    run_all_parser = queue_sub.add_parser(
        "run-all",
        help="Translate exactly one pending book and stop at the review gate",
    )
    run_all_parser.add_argument("--db", default="data/literary_queue.db")
    run_all_parser.add_argument("--resources", default="literary-resources")
    run_all_parser.add_argument("--refine-limit", type=int, default=0)
    run_all_parser.add_argument("--no-refine", action="store_true")
    run_all_parser.add_argument("--pov", default="")
    run_all_parser.add_argument(
        "--parallel", type=int, default=1,
        help="One chunk at a time; only 0/1 are accepted",
    )
    run_all_parser.add_argument(
        "--max-books", type=int, default=1,
        help="Must be 1; this fork never batches books",
    )
    run_all_parser.add_argument("--stop-on-review", action="store_true")
    run_all_parser.add_argument("--stop-on-error", action="store_true")
    run_all_parser.add_argument("--export-kindle", action="store_true")
    run_all_parser.add_argument("--outputs", default="translated_files")
    run_all_parser.add_argument("--kindle-out", default="translated_files/kindle")
    run_all_parser.set_defaults(func=cmd_queue_run_all)
    pause_parser = queue_sub.add_parser(
        "pause", help="Ask run-all to stop after the current book"
    )
    pause_parser.add_argument("--db", default="data/literary_queue.db")
    pause_parser.set_defaults(func=cmd_queue_pause)
    pause_now_parser = queue_sub.add_parser(
        "pause-now", help="Stop the book currently being translated"
    )
    pause_now_parser.add_argument("--db", default="data/literary_queue.db")
    pause_now_parser.set_defaults(func=cmd_queue_pause_now)
    resume_parser = queue_sub.add_parser(
        "resume", help="Cancel a pending pause request"
    )
    resume_parser.add_argument("--db", default="data/literary_queue.db")
    resume_parser.set_defaults(func=cmd_queue_resume)
    state_parser = queue_sub.add_parser("set-state")
    state_parser.add_argument("--db", default="data/literary_queue.db")
    state_parser.add_argument("--book-id", type=int, required=True)
    state_parser.add_argument("--state", required=True)
    state_parser.add_argument("--message", default="")
    state_parser.set_defaults(func=cmd_queue_state)
    reset_parser = queue_sub.add_parser("reset")
    reset_parser.add_argument("--db", default="data/literary_queue.db")
    reset_parser.set_defaults(func=cmd_queue_reset)

    start_parser = queue_sub.add_parser("start", help="Create a queue job for a book")
    start_parser.add_argument("--db", default="data/literary_queue.db")
    start_parser.add_argument("--book-id", type=int, required=True)
    start_parser.add_argument("--total-chapters", type=int, default=0)
    start_parser.set_defaults(func=cmd_queue_start)

    jobs_parser = queue_sub.add_parser("jobs", help="List queue jobs and upstream links")
    jobs_parser.add_argument("--db", default="data/literary_queue.db")
    jobs_parser.add_argument("--limit", type=int, default=50)
    jobs_parser.set_defaults(func=cmd_queue_jobs)

    attach_parser = queue_sub.add_parser("attach", help="Link a job to an upstream translation_id")
    attach_parser.add_argument("--db", default="data/literary_queue.db")
    attach_parser.add_argument("--job-id", type=int, required=True)
    attach_parser.add_argument("--translation-id", required=True)
    attach_parser.set_defaults(func=cmd_queue_attach)

    sync_parser = queue_sub.add_parser(
        "sync",
        help="Reconcile with data/jobs.mirror.db (read-only)",
    )
    sync_parser.add_argument("--db", default="data/literary_queue.db")
    sync_parser.add_argument("--checkpoint-db", default="data/jobs.mirror.db")
    sync_parser.set_defaults(func=cmd_queue_sync)

    status_parser = queue_sub.add_parser(
        "checkpoint-status",
        help="Report the live jobs.db checkpoint for one translation",
    )
    status_parser.add_argument("--id", required=True)
    status_parser.add_argument("--reconcile", action="store_true")
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(func=cmd_checkpoint_status)

    snapshot_parser = queue_sub.add_parser(
        "db-snapshot",
        help="Write a consistent snapshot of the live jobs DB",
    )
    snapshot_parser.add_argument("--out-dir", default="/app/data/backups")
    snapshot_parser.add_argument("--label", default="")
    snapshot_parser.add_argument("--json", action="store_true")
    snapshot_parser.set_defaults(func=cmd_db_snapshot)

    health_parser = queue_sub.add_parser(
        "db-health",
        help="Report live jobs DB integrity and journal mode",
    )
    health_parser.add_argument("--json", action="store_true")
    health_parser.set_defaults(func=cmd_db_health)

    job_state_parser = queue_sub.add_parser("set-job-state")
    job_state_parser.add_argument("--db", default="data/literary_queue.db")
    job_state_parser.add_argument("--job-id", type=int, required=True)
    job_state_parser.add_argument("--state", required=True)
    job_state_parser.add_argument("--message", default="")
    job_state_parser.set_defaults(func=cmd_queue_job_state)

    refine_parser = sub.add_parser(
        "refine",
        help="Source-aware selective refinement for paragraph-aligned text",
    )
    refine_parser.add_argument("--source", required=True)
    refine_parser.add_argument("--draft", required=True)
    refine_parser.add_argument("--out", required=True)
    refine_parser.add_argument("--root", default="literary-resources")
    refine_parser.add_argument("--author", default="")
    refine_parser.add_argument("--universe", default="")
    refine_parser.add_argument("--subseries", default="")
    refine_parser.add_argument("--book", default="")
    refine_parser.add_argument("--model", required=True)
    refine_parser.add_argument("--endpoint", default="http://localhost:11434")
    refine_parser.add_argument("--temperature", type=float, default=0.0)
    refine_parser.add_argument("--max-tokens", type=int, default=800)
    refine_parser.add_argument("--limit", type=int, default=0)
    refine_parser.add_argument("--dry-run", action="store_true")
    refine_parser.add_argument("--report", default="")
    refine_parser.set_defaults(func=cmd_refine)

    refine_epub_parser = sub.add_parser(
        "refine-epub",
        help="Source-aware selective refinement for an already translated EPUB",
    )
    refine_epub_parser.add_argument("--source", required=True, help="Source-language EPUB")
    refine_epub_parser.add_argument("--target", required=True, help="Translated draft EPUB")
    refine_epub_parser.add_argument("--out", required=True, help="Output EPUB (never overwrite in place by default)")
    refine_epub_parser.add_argument("--root", default="literary-resources")
    refine_epub_parser.add_argument("--author", default="")
    refine_epub_parser.add_argument("--universe", default="")
    refine_epub_parser.add_argument("--subseries", default="")
    refine_epub_parser.add_argument("--book", default="")
    refine_epub_parser.add_argument("--model", required=True)
    refine_epub_parser.add_argument("--endpoint", default="http://localhost:11434")
    refine_epub_parser.add_argument("--temperature", type=float, default=0.0)
    refine_epub_parser.add_argument("--max-tokens", type=int, default=800)
    refine_epub_parser.add_argument("--num-ctx", type=int, default=8192)
    refine_epub_parser.add_argument("--pov", default="")
    refine_epub_parser.add_argument("--limit", type=int, default=0)
    refine_epub_parser.add_argument("--dry-run", action="store_true")
    refine_epub_parser.add_argument("--report", default="")
    refine_epub_parser.set_defaults(func=cmd_refine_epub)

    repair_parser = sub.add_parser(
        "repair-dropcaps",
        help="Repair unambiguous dropcap corruption in an EPUB",
    )
    repair_parser.add_argument("--source", required=True)
    repair_parser.add_argument("--out", required=True)
    repair_parser.add_argument("--report", default="")
    repair_parser.set_defaults(func=cmd_repair_dropcaps)

    estimate = sub.add_parser("estimate", help="Cost estimate")
    estimate.add_argument("--words", type=int)
    estimate.add_argument("--inventory")
    estimate.add_argument("--calibre-id", type=int)
    estimate.add_argument("--series")
    estimate.add_argument("--author")
    estimate.add_argument("--language")
    estimate.add_argument("--provider", default="deepseek")
    estimate.add_argument("--model", default="deepseek-flash")
    estimate.add_argument("--passes", type=int, default=1)
    estimate.add_argument("--retry-rate", type=float, default=0.10)
    estimate.add_argument("--batch", action="store_true")
    estimate.add_argument("--offpeak", action="store_true")
    estimate.add_argument("--judge", action="store_true")
    estimate.add_argument("--all-scenarios", action="store_true")
    estimate.add_argument("--scenarios", nargs="+", default=None)
    estimate.set_defaults(func=cmd_estimate)

    validate = sub.add_parser("validate", help="Deterministic validation")
    validate_sub = validate.add_subparsers(dest="validate_command", required=True)
    epub = validate_sub.add_parser("epub")
    epub.add_argument("--source", required=True)
    epub.add_argument("--target", default="")
    epub.add_argument("--language", default="pt-BR")
    epub.set_defaults(func=cmd_validate_epub)
    text = validate_sub.add_parser("text")
    text.add_argument("--source", required=True)
    text.add_argument("--target", required=True)
    text.add_argument("--root", default="literary-resources")
    text.add_argument("--author", default="")
    text.add_argument("--universe", default="")
    text.add_argument("--subseries", default="")
    text.add_argument("--book", default="")
    text.set_defaults(func=cmd_validate_text)

    metadata = sub.add_parser("metadata", help="EPUB metadata operations")
    metadata_sub = metadata.add_subparsers(dest="metadata_command", required=True)
    apply_parser = metadata_sub.add_parser("apply")
    apply_parser.add_argument("--source", required=True)
    apply_parser.add_argument("--output", required=True)
    apply_parser.add_argument("--title")
    apply_parser.add_argument("--language")
    apply_parser.add_argument("--identifier")
    apply_parser.add_argument("--series")
    apply_parser.add_argument("--series-index", type=float)
    apply_parser.set_defaults(func=cmd_metadata_apply)

    pricing = sub.add_parser("pricing", help="Show the recorded price for a model")
    pricing.add_argument("--provider", required=True)
    pricing.add_argument("--model", required=True)
    pricing.set_defaults(func=cmd_pricing)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
