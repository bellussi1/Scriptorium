from pathlib import Path

import yaml

from src.literary.glossary import build_glossary_block, select_terms
from src.literary.resources import (
    compile_for_book,
    glossary_to_prompt_dicts,
    load_tree,
    validate_tree,
    write_glossary_json,
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_compile_hierarchy_overrides_and_first_appearance(tmp_path: Path):
    root = tmp_path / "literary-resources"
    _write(
        root / "robin-hobb" / "realm-of-the-elderlings" / "series.yaml",
        {
            "name": "Realm of the Elderlings",
            "books": [
                {"slug": "assassins-apprentice", "title": "Assassin's Apprentice", "order": 1},
                {"slug": "royal-assassin", "title": "Royal Assassin", "order": 2},
            ],
        },
    )
    _write(
        root / "robin-hobb" / "realm-of-the-elderlings" / "glossary.yaml",
        {
            "terms": [
                {
                    "source": "Fitz",
                    "target": "Fitz",
                    "category": "character",
                    "policy": "keep",
                    "aliases": ["FitzChivalry"],
                    "first_appearance": "assassins-apprentice",
                    "confidence": "confirmed",
                    "approved": True,
                },
                {
                    "source": "Skill",
                    "target": "Habilidade",
                    "category": "concept",
                    "first_appearance": "royal-assassin",
                },
            ],
        },
    )
    _write(
        root / "robin-hobb" / "realm-of-the-elderlings" / "farseer" / "style.yaml",
        {
            "mode": "source",
            "context": "A pre-industrial kingdom.",
            "rules": [{"dimension": "register", "instruction": "Keep the introspective first person."}],
        },
    )
    _write(
        root / "robin-hobb" / "realm-of-the-elderlings" / "farseer" / "assassins-apprentice" / "glossary.yaml",
        {"terms": [{"source": "Fitz", "target": "FitzChivalry", "first_appearance": "assassins-apprentice"}]},
    )
    tree = load_tree(root)
    assert not validate_tree(tree)
    compiled = compile_for_book(tree, "robin-hobb", "realm-of-the-elderlings", "farseer", "assassins-apprentice")
    terms = {term.source: term for term in compiled.glossary.terms}
    assert terms["Fitz"].effective_target() == "FitzChivalry"
    assert "FitzChivalry" in terms["Fitz"].aliases
    assert "Skill" not in terms
    assert compiled.series.name == "Realm of the Elderlings"
    assert compiled.book.order == 1
    assert compiled.style["context"] == "A pre-industrial kingdom."


def test_glossary_selection_alias_and_forbidden(tmp_path: Path):
    root = tmp_path / "literary-resources"
    _write(
        root / "author" / "universe" / "glossary.yaml",
        {
            "terms": [
                {
                    "source": "FitzChivalry Farseer",
                    "target": "FitzChivalry Farseer",
                    "category": "character",
                    "aliases": ["Fitz"],
                    "forbidden": ["Fitz Chivalry", "Fitz, o Farseer"],
                    "confidence": "confirmed",
                }
            ]
        },
    )
    tree = load_tree(root)
    compiled = compile_for_book(tree, "author", "universe")
    chunk = "Fitz walked into the room. FitzChivalry Farseer said nothing."
    selected = select_terms(chunk, compiled)
    assert len(selected) == 1
    block = build_glossary_block(selected)
    assert "FitzChivalry Farseer" in block
    assert "do not use" in block.lower() or "forbidden" in block.lower()
    terms, metadata, forbidden = glossary_to_prompt_dicts(compiled)
    assert any("Fitz" in key for key in terms)
    assert forbidden


def test_select_terms_uses_alias_specific_target(tmp_path: Path):
    root = tmp_path / "literary-resources"
    _write(
        root / "a" / "u" / "glossary.yaml",
        {
            "terms": [
                {
                    "source": "FitzChivalry Farseer",
                    "target": "FitzChivalry Farseer",
                    "aliases": ["Fitz"],
                    "alias_targets": {"Fitz": "Fitz"},
                }
            ]
        },
    )
    compiled = compile_for_book(load_tree(root), "a", "u")
    selected = select_terms("Fitz walked into the room.", compiled)
    assert len(selected) == 1
    assert selected[0].term.effective_target() == "Fitz"


def test_alias_targets_compile_to_separate_entries(tmp_path: Path):
    root = tmp_path / "literary-resources"
    _write(
        root / "a" / "u" / "glossary.yaml",
        {
            "terms": [
                {
                    "source": "FitzChivalry Farseer",
                    "target": "FitzChivalry Farseer",
                    "aliases": ["Fitz"],
                    "alias_targets": {"Fitz": "Fitz"},
                }
            ]
        },
    )
    compiled = compile_for_book(load_tree(root), "a", "u")
    term = compiled.glossary.terms[0]
    assert term.target_for_form("Fitz") == "Fitz"
    terms, metadata, _ = glossary_to_prompt_dicts(compiled)
    assert terms["FitzChivalry Farseer"] == "FitzChivalry Farseer"
    assert terms["Fitz"] == "Fitz"
    assert metadata["Fitz"]["category"] == "other"


def test_write_glossary_json_shape(tmp_path: Path):
    root = tmp_path / "literary-resources"
    _write(root / "a" / "u" / "glossary.yaml", {"terms": [{"source": "Keep", "target": "Manter"}]})
    compiled = compile_for_book(load_tree(root), "a", "u")
    out = tmp_path / "glossary.json"
    write_glossary_json(compiled, str(out))
    import json

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["terms"][0]["source"] == "Keep"
    assert payload["terms"][0]["target"] == "Manter"
