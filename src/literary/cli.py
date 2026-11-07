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
from typing import Any, Dict, List, Optional

from .calibre import CalibreLibrary
from .cost import SCENARIOS, estimate_book, estimate_scenario, estimate_series, get_pricing
from .epub import read_epub, update_opf_metadata, validate_epub_structure
from .models import BookRecord, Severity
from .queue import QueueStore
from .refine_runner import (
    find_flagged_segments,
    generate_ollama,
    refine_segments,
    render_refined_text,
    split_segments,
)
from .repair import repair_dropcaps_in_epub
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
    payload = _read_json(args.inventory)
    books = [_book_from_dict(row) for row in payload.get("books", [])]
    selected = []
    for book in books:
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
                target_language=args.target,
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

    sync_parser = queue_sub.add_parser("sync", help="Reconcile with data/jobs.db (read-only)")
    sync_parser.add_argument("--db", default="data/literary_queue.db")
    sync_parser.add_argument("--checkpoint-db", default="data/jobs.db")
    sync_parser.set_defaults(func=cmd_queue_sync)

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
