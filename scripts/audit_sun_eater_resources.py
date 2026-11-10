"""Audit Sun Eater term first appearances against the actual book text.

The resource files were seeded with later-book terms and some targets that do
not match the official PT-BR edition. This script counts each source form in the
English book and each target form in the official Portuguese book, then reports
terms that are present in book 1 but still marked with a later
``first_appearance``.

With ``--apply`` it promotes the verified terms to ``empire-of-silence`` and
fixes the two known English targets. It edits the YAML text in place, keeping
the existing layout.

Usage:
    python scripts/audit_sun_eater_resources.py
    python scripts/audit_sun_eater_resources.py --apply
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.literary.epub import count_words, iter_spine_documents  # noqa: E402

RESOURCES = ROOT / "literary-resources" / "christopher-ruocchio" / "sun-eater"
EN_BOOK = Path(
    r"C:\Users\Bellussi\Downloads\Livros e leitura\Sun Eater\Empire of Silence - Christopher Ruocchio.epub"
)
PT_BOOK = Path(
    r"C:\Users\Bellussi\Biblioteca do calibre\Christopher Ruocchio\Imperio do Silencio (436)\Imperio do Silencio - Christopher Ruocchio.epub"
)
FILES = ("glossary.yaml", "characters.yaml", "worldbuilding.yaml")
# Common words that are also later-book proper nouns. They need context review,
# not a blind promotion based on case-insensitive counts.
DENYLIST = {"Watchers"}


def _text(path: Path) -> str:
    return "\n".join(
        doc.get("text") or ""
        for doc in iter_spine_documents(str(path))
        if count_words(doc.get("text") or "") >= 900
    )


def _norm(value: str) -> str:
    return unicodedata.normalize("NFC", str(value or ""))


def _hits(forms: Iterable[str], text: str) -> int:
    total = 0
    for form in forms:
        form = _norm(form).strip()
        if not form:
            continue
        total += len(re.findall(r"(?<!\w)" + re.escape(form) + r"(?!\w)", text, re.IGNORECASE))
    return total


def _terms() -> List[Tuple[str, Dict[str, Any]]]:
    rows = []
    for filename in FILES:
        payload = yaml.safe_load((RESOURCES / filename).read_text(encoding="utf-8")) or {}
        for term in payload.get("terms") or []:
            if isinstance(term, dict) and term.get("source"):
                rows.append((filename, term))
    return rows


def _source_forms(term: Dict[str, Any]) -> List[str]:
    return [_norm(term.get("source"))] + [_norm(item) for item in term.get("aliases") or []]


def _target_forms(term: Dict[str, Any]) -> List[str]:
    targets = [_norm(term.get("target"))]
    targets.extend(_norm(value) for value in (term.get("alias_targets") or {}).values())
    return [item for item in targets if item]


def _promote(text: str, promoted: set[str], target_fixes: Dict[str, str]) -> str:
    parts = text.split("\n  - source: ")
    output = [parts[0]]
    for part in parts[1:]:
        source = _norm(part.split("\n", 1)[0].strip())
        if source in promoted:
            part = re.sub(
                r"^(\s*first_appearance:\s*).*$",
                r"\g<1>empire-of-silence",
                part,
                count=1,
                flags=re.MULTILINE,
            )
        if source in target_fixes:
            part = re.sub(
                r"^(\s*target:\s*).*$",
                r"\g<1>" + target_fixes[source],
                part,
                count=1,
                flags=re.MULTILINE,
            )
        output.append(part)
    return "\n  - source: ".join(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not EN_BOOK.exists() or not PT_BOOK.exists():
        raise SystemExit("English or Portuguese source book is missing")
    en_text = _text(EN_BOOK)
    pt_text = _text(PT_BOOK)
    rows = _terms()
    promoted: set[str] = set()
    report = []
    for filename, term in rows:
        source = _norm(term.get("source"))
        source_hits = _hits(_source_forms(term), en_text)
        target_hits = _hits(_target_forms(term), pt_text)
        current = _norm(term.get("first_appearance"))
        should_promote = (
            source_hits > 0
            and target_hits > 0
            and source not in DENYLIST
            and current != "empire-of-silence"
        )
        if should_promote:
            promoted.add(source)
        report.append(
            {
                "file": filename,
                "source": source,
                "target": term.get("target"),
                "first_appearance": current,
                "source_hits": source_hits,
                "target_hits": target_hits,
                "promote": should_promote,
            }
        )
    for row in report:
        marker = "PROMOTE" if row["promote"] else ""
        print(
            f"{row['source']:24s} -> {str(row['target']):24s} "
            f"first={str(row['first_appearance']):20s} "
            f"en={row['source_hits']:4d} pt={row['target_hits']:4d} {marker}"
        )
    print(f"\n{len(promoted)} terms can be promoted to empire-of-silence")
    if not args.apply:
        print("dry run; pass --apply to edit the resource files")
        return 0
    target_fixes = {"Gibson of Syracuse": "Gibson de Siracusa"}
    for filename in FILES:
        path = RESOURCES / filename
        text = path.read_text(encoding="utf-8")
        updated = _promote(text, promoted, target_fixes)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            print(f"updated {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
