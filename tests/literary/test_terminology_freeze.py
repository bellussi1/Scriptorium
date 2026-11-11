"""Guard the frozen Sun Eater terminology decisions."""
from __future__ import annotations

from pathlib import Path

from src.literary.resources import compile_for_book, load_tree

ROOT = Path(__file__).resolve().parents[2]


def _sun_eater_terms():
    tree = load_tree(str(ROOT / "literary-resources"))
    compiled = compile_for_book(
        tree,
        "christopher-ruocchio",
        "sun-eater",
        "",
        "",
        book_order=4,
    )
    return {term.source: term for term in compiled.glossary.terms}


def test_imperium_stays_a_latin_proper_name():
    term = _sun_eater_terms()["Imperium"]
    assert term.target == "Imperium"
    assert term.policy == "keep"


def test_invented_terms_are_frozen():
    terms = _sun_eater_terms()
    assert terms["datasphere"].target == "esfera de dados"
    assert "dataesfera" in terms["datasphere"].forbidden
    assert terms["animalcule"].target == "animalculo"
    assert terms["knight-tribune"].target == "tribuna-cavaleira"
    assert "knight-tribune" in terms["knight-tribune"].forbidden


def test_official_forms_are_not_reverted():
    terms = _sun_eater_terms()
    assert terms["Chantry"].target == "Chantria"
    assert terms["Cielcin"].target == "cielcin"
    assert terms["Sollan Empire"].target == "Império Sollano"
    assert terms["Quiet"].target == "Quieto"
    assert terms["Fugue"].target == "fuga"
