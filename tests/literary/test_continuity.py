"""Tests for chapter continuity context."""
from __future__ import annotations

from src.literary.continuity import (
    ContinuityTracker,
    build_continuity_block,
    chapter_tail,
    characters_from_compiled,
    extractive_summary,
)
from src.literary.models import CompiledResources, GlossaryBundle, Term


def _compiled() -> CompiledResources:
    return CompiledResources(
        glossary=GlossaryBundle(
            terms=[
                Term(
                    source="Hadrian Marlowe",
                    target="Hadrian Marlowe",
                    category="character",
                    gender="male",
                    aliases=["Hadrian", "Marlowe"],
                    notes="First-person narrator.",
                ),
                Term(
                    source="Valka",
                    target="Valka",
                    category="character",
                    gender="female",
                ),
                Term(source="Fugue", target="Fuga", category="concept"),
            ]
        )
    )


def test_extractive_summary_keeps_opening_and_turn():
    text = "First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence."
    summary = extractive_summary(text, max_sentences=4)
    assert summary.startswith("First sentence.")
    assert summary.endswith("Fifth sentence.")
    assert "Third sentence." not in summary


def test_chapter_tail_respects_limit_and_keeps_ending():
    text = "\n\n".join(f"Sentence number {index}." for index in range(200))
    tail = chapter_tail(text, max_chars=200)
    assert len(tail) <= 200
    assert tail.endswith("Sentence number 199.")


def test_characters_are_derived_from_glossary_metadata():
    characters = characters_from_compiled(_compiled())
    by_name = {character.name: character for character in characters}
    assert by_name["Hadrian Marlowe"].gender == "male"
    assert by_name["Hadrian Marlowe"].aliases == ["Hadrian", "Marlowe"]
    assert by_name["Valka"].gender == "female"
    assert "Fugue" not in by_name


def test_continuity_block_contains_pov_characters_and_previous_chapter():
    block = build_continuity_block(
        characters=characters_from_compiled(_compiled()),
        pov="First person, retrospective, male narrator.",
        notes="Use você between peers; preserve military titles.",
        previous_summary="Hadrian left the ship.",
        previous_tail="The door closed behind him.",
    )
    assert "## Continuity" in block
    assert "First person" in block
    assert "Hadrian Marlowe (male)" in block
    assert "The door closed behind him." in block
    assert "Use você" in block


def test_empty_continuity_block_is_empty():
    assert build_continuity_block() == ""


def test_tracker_updates_summary_and_tail():
    tracker = ContinuityTracker.from_compiled(_compiled(), pov="First person, male.")
    tracker.update("Opening line. Middle line. Closing line.")
    assert tracker.previous_summary == "Opening line. Middle line. Closing line."
    assert tracker.previous_tail == "Opening line. Middle line. Closing line."
    assert "Hadrian Marlowe" in tracker.block()
    assert tracker.to_dict()["pov"] == "First person, male."
