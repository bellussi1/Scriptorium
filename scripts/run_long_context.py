"""Long-context/chunking runner for the three Farseer chapters.

This uses the production ``TokenChunker`` (450 tokens, paragraph/sentence
boundaries) and the benchmark prompt adapters, then reassembles the chunks.
It is the long-context complement to ``benchmark_fase_d.py``; it must run where
``tiktoken`` is installed (the app container) and Ollama is reachable.

Dry run (no GPU, prints chunk counts):
    docker compose -f docker-compose.dev.yml exec -T app python \
      scripts/run_long_context.py --dry-run

Real run (GPU; wait for the queue to be idle):
    docker compose -f docker-compose.dev.yml exec -T app python \
      scripts/run_long_context.py --models hy-mt2-7b index-translate-9b \
      --endpoint http://host.docker.internal:11434
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmark.literary.adapters import MODELS, build_prompt, generate_ollama  # noqa: E402
from benchmark.literary.metrics import chrf  # noqa: E402
from src.core.chunking.token_chunker import TokenChunker  # noqa: E402
from src.literary.resources import (  # noqa: E402
    _target_groups,
    assemble_style,
    compile_for_book,
    load_tree,
)

DEFAULT_CORPUS = ROOT / "data" / "benchmark" / "literary" / "long_chapters_farseer.jsonl"


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _resources(
    book_slug: str,
    author: str = "robin-hobb",
    universe: str = "realm-of-the-elderlings",
    subseries: str = "farseer",
    book_order: float | None = None,
) -> tuple[Dict[str, str], str]:
    tree = load_tree(str(ROOT / "literary-resources"))
    compiled = compile_for_book(
        tree,
        author,
        universe,
        subseries,
        book_slug,
        book_order=book_order,
    )
    glossary: Dict[str, str] = {}
    for term in compiled.glossary.terms:
        for target, forms in _target_groups(term):
            for form in forms:
                glossary[form] = target
    style = assemble_style(compiled.style).get("translation", "") if compiled.style else ""
    return glossary, style


def _join_chunks(chunks: List[Dict[str, Any]], outputs: List[str]) -> str:
    parts = []
    for chunk, output in zip(chunks, outputs):
        separator = str(chunk.get("join_with") or "")
        parts.append(separator + output.strip())
    return "".join(parts).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--models", nargs="+", default=["hy-mt2-7b", "index-translate-9b"])
    parser.add_argument("--endpoint", default="http://localhost:11434")
    parser.add_argument("--out-root", type=Path, default=ROOT / "data" / "benchmark" / "long-context")
    parser.add_argument("--max-tokens", type=int, default=450)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resource-author", default="robin-hobb")
    parser.add_argument("--resource-universe", default="realm-of-the-elderlings")
    parser.add_argument("--resource-subseries", default="farseer")
    parser.add_argument("--resource-book-order", type=float)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    chapters = _read_jsonl(args.corpus)
    if args.limit:
        chapters = chapters[: args.limit]
    chunker = TokenChunker(max_tokens=args.max_tokens)
    args.out_root.mkdir(parents=True, exist_ok=True)
    summaries: Dict[str, Any] = {}

    for chapter in chapters:
        glossary, style = _resources(
            chapter["book_slug"],
            args.resource_author,
            args.resource_universe,
            args.resource_subseries,
            args.resource_book_order,
        )
        chunks = chunker.chunk_text(chapter["text"])
        print(
            f"{chapter['id']}: {len(chunks)} chunks, "
            f"{chapter['word_count']} words, {sum(chunker.count_tokens(c['main_content']) for c in chunks)} tokens",
            flush=True,
        )
        for model in args.models:
            if model not in MODELS:
                raise SystemExit(f"unknown model key: {model}")
            spec = MODELS[model]
            print(f"  {model}: {len(chunks)} calls", flush=True)
            if args.dry_run:
                continue
            started = time.time()
            outputs: List[str] = []
            errors = []
            for index, chunk in enumerate(chunks, start=1):
                messages = build_prompt(
                    spec,
                    chunk["main_content"],
                    glossary=glossary,
                    style=style,
                )
                generation = generate_ollama(
                    spec,
                    messages,
                    endpoint=args.endpoint,
                    max_tokens=1200,
                    timeout=900,
                )
                if generation.error:
                    errors.append({"chunk": index, "error": generation.error})
                    outputs.append(chunk["main_content"])
                else:
                    outputs.append(generation.text)
                print(f"    {index}/{len(chunks)}", flush=True)
            text_out = _join_chunks(chunks, outputs)
            expected = chapter.get("expected_terms") or []
            term_hits = sum(
                1
                for term in expected
                if term.get("target") and term["target"].casefold() in text_out.casefold()
            )
            row = {
                "id": chapter["id"],
                "model": model,
                "book_slug": chapter["book_slug"],
                "chapter_title": chapter.get("chapter_title", ""),
                "chunks": len(chunks),
                "source_words": chapter.get("word_count"),
                "reference_words": chapter.get("reference_word_count"),
                "text": text_out,
                "reference_pt": chapter.get("reference_pt", ""),
                "chrf": chrf(chapter.get("reference_pt", ""), text_out),
                "term_total": len(expected),
                "term_hit": term_hits,
                "term_compliance": round(term_hits / len(expected), 4) if expected else None,
                "latency_s": round(time.time() - started, 2),
                "errors": errors,
            }
            out_path = args.out_root / f"{chapter['id']}-{model}.jsonl"
            out_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            summaries.setdefault(model, []).append(
                {
                    "id": chapter["id"],
                    "chunks": len(chunks),
                    "chrf": row["chrf"],
                    "term_compliance": row["term_compliance"],
                    "latency_s": row["latency_s"],
                    "errors": len(errors),
                }
            )
            print(
                f"    done in {row['latency_s']}s, chrF {row['chrf']}, terms {row['term_compliance']}",
                flush=True,
            )

    if not args.dry_run:
        summary_path = args.out_root / "summary.json"
        summary_path.write_text(
            json.dumps(summaries, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"summary": str(summary_path), "models": summaries}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
