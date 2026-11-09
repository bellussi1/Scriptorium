"""Tests for resolving a queue book into a reproducible run plan."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.literary.run_plan import build_run_plan, infer_scopes


def _resource_file(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _book(**overrides):
    values = {
        "id": 7,
        "calibre_id": 700,
        "title": "Test Book",
        "author": "Test Author",
        "series": "Test Universe",
        "series_index": 1.0,
        "status": "pending",
        "word_count": 1200,
        "source_path": "/library/Test Author/Test Book (700)/Test Book.epub",
        "target_language": "pt-BR",
        "glossary_scope": "",
        "style_scope": "",
        "model": "test-model:Q6_K",
        "provider": "ollama",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_infer_scopes_for_known_series():
    ruocchio = _book(author="Christopher Ruocchio", series="The Sun Eater", title="Howling Dark")
    assert infer_scopes(ruocchio).to_dict() == {
        "author": "christopher-ruocchio",
        "universe": "sun-eater",
        "subseries": "",
        "book": "howling-dark",
    }

    hobb = _book(author="Robin Hobb", series="The Liveship Traders", title="Ship of Magic")
    assert infer_scopes(hobb).to_dict() == {
        "author": "robin-hobb",
        "universe": "realm-of-the-elderlings",
        "subseries": "liveship-traders",
        "book": "ship-of-magic",
    }


def test_infer_scopes_for_shared_worlds():
    malice = _book(author="John Gwynne", series="The Faithful and the Fallen", title="Malice")
    assert infer_scopes(malice).to_dict() == {
        "author": "john-gwynne",
        "universe": "the-banished-lands",
        "subseries": "the-faithful-and-the-fallen",
        "book": "malice",
    }

    dread = _book(author="John Gwynne", series="Of Blood and Bone", title="A Time of Dread")
    assert infer_scopes(dread).to_dict() == {
        "author": "john-gwynne",
        "universe": "the-banished-lands",
        "subseries": "of-blood-and-bone",
        "book": "a-time-of-dread",
    }

    hatred = _book(author="Joe Abercrombie", series="The Age of Madness", title="A Little Hatred")
    assert infer_scopes(hatred).to_dict() == {
        "author": "joe-abercrombie",
        "universe": "the-first-law",
        "subseries": "the-age-of-madness",
        "book": "a-little-hatred",
    }


def test_compiled_glossary_path_is_not_treated_as_scope_coordinates():
    book = _book(
        author="Christopher Ruocchio",
        series="The Sun Eater",
        title="Howling Dark",
        glossary_scope="data/compiled/sun-eater-2-glossary.json",
    )
    scopes = infer_scopes(book)
    assert scopes.author == "christopher-ruocchio"
    assert scopes.universe == "sun-eater"


def test_explicit_scope_path_wins():
    book = _book(glossary_scope="robin-hobb/realm-of-the-elderlings/liveship-traders")
    scopes = infer_scopes(book)
    assert scopes.author == "robin-hobb"
    assert scopes.universe == "realm-of-the-elderlings"
    assert scopes.subseries == "liveship-traders"


def test_build_run_plan_compiles_glossary_and_style(tmp_path: Path):
    root = tmp_path / "literary-resources"
    _resource_file(
        root,
        "test-author/test-universe/glossary.yaml",
        """
version: 1
scope: universe
source_language: en
target_language: pt-BR
terms:
  - source: Test Term
    target: Termo Teste
    category: concept
    policy: translate
    confidence: confirmed
    approved: true
  - source: Test Character
    target: Test Character
    category: character
    policy: keep
    gender: female
    aliases: [Test]
    confidence: confirmed
    approved: true
""".lstrip(),
    )
    _resource_file(
        root,
        "test-author/test-universe/style.yaml",
        """
description: Test style
mode: source
context: A test setting.
rules:
  - dimension: register
    instruction: Keep the prose formal and precise.
""".lstrip(),
    )

    plan = build_run_plan(
        _book(),
        resources_root=str(root),
        previous_chapter_text="The ship left. The door closed.",
    )

    assert plan["model"] == "test-model:Q6_K"
    assert plan["provider"] == "ollama"
    assert plan["glossary"]["terms"] == 2
    assert plan["glossary"]["preview"][0]["target"] == "Termo Teste"
    assert plan["continuity"]["characters"][0]["name"] == "Test Character"
    assert plan["continuity"]["characters"][0]["gender"] == "female"
    assert "The door closed." in plan["continuity"]["block"]
    assert "Keep the prose formal and precise." in plan["style"]["translation"]
    assert plan["pipeline"] == {
        "refine": True,
        "grammar": True,
        "best_of_n": 1,
        "continuity": True,
    }
    assert plan["issues"] == []


def test_pipeline_flags_can_be_overridden(tmp_path: Path):
    plan = build_run_plan(
        _book(),
        resources_root=str(tmp_path / "missing"),
        refine=False,
        grammar=False,
        best_of_n=3,
        continuity=False,
    )
    assert plan["pipeline"] == {
        "refine": False,
        "grammar": False,
        "best_of_n": 3,
        "continuity": False,
    }
