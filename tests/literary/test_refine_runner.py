"""Tests for source-aware selective refinement."""
from __future__ import annotations

from src.literary.models import CompiledResources, GlossaryBundle, Term
from src.literary.refine import RefinementIssue, apply_guard
from src.literary.validation import numbers_compatible, numeric_tokens, target_present
from src.literary.refine_runner import (
    FlaggedSegment,
    find_flagged_segments,
    flags_for_segment,
    refine_segments,
    render_refined_text,
    split_segments,
)
from src.literary.cli import main as cli_main


def _compiled(*terms: Term) -> CompiledResources:
    return CompiledResources(glossary=GlossaryBundle(terms=list(terms)))


def test_split_segments_uses_blank_lines():
    assert split_segments("A\n\nB\n \nC\n") == ["A", "B", "C"]


def test_clean_pair_has_no_flags():
    compiled = _compiled(Term(source="Fugue", target="Fuga"))
    issues = flags_for_segment(
        "The Fugue ended at dawn.", "A Fuga terminou ao amanhecer.", compiled=compiled
    )
    assert issues == []


def test_flags_missing_number_glossary_and_forbidden():
    compiled = _compiled(
        Term(source="Fugue", target="Fuga"),
        Term(source="Scholiast", target="Escoliasta", forbidden=["erudito"]),
    )
    issues = flags_for_segment(
        "The Fugue lasted 3 days and the Scholiast wrote it.",
        "O episódio durou dois dias e o erudito escreveu.",
        compiled=compiled,
    )
    codes = {issue.code for issue in issues}
    assert "segment.numbers" in codes
    assert "segment.glossary_missing" in codes
    assert "segment.forbidden" in codes


def test_number_words_are_equivalent_to_digits():
    assert flags_for_segment("It lasted 3 days.", "Durou três dias.") == []
    guard = apply_guard("It lasted 3 days.", "Durou três dias.", "Durou três dias.")
    assert guard.ok, guard.reasons


def test_ambiguous_one_does_not_create_numeric_false_positive():
    assert flags_for_segment(
        "There’s no one here but us.", "Não há ninguém aqui além de nós."
    ) == []
    assert flags_for_segment("One of the men arrived.", "Um dos homens chegou.") == []


def test_millions_plural_matches():
    assert numeric_tokens("Millions dead") == numeric_tokens("Milhões mortos")


def test_compound_numbers_are_compatible():
    assert numbers_compatible(
        numeric_tokens("two hundred and fifty meters"),
        numeric_tokens("duzentos e cinquenta metros"),
    )
    assert flags_for_segment(
        "Two hundred and fifty meters.", "Duzentos e cinquenta metros."
    ) == []


def test_coordinate_strings_skip_numeric_comparison():
    assert flags_for_segment(
        "The code is two-nineteen point one-one.",
        "O código é dois-um-nove ponto um-um.",
    ) == []


def test_glossary_target_tolerates_regular_inflection():
    assert target_present("palatino", "a casa palatina")
    assert not target_present("Fuga", "Fugitivo")
    assert flags_for_segment(
        "The palatine house fell.", "A casa palatina caiu."
    ) == []


def test_empty_and_english_drafts_are_flagged():
    assert flags_for_segment("Hello.", "")[0].code == "segment.empty"
    english = (
        "The night was cold and the men were tired, but they had to keep "
        "riding because the river was still far away from the camp."
    )
    issues = flags_for_segment("A noite estava fria.", english)
    assert any(issue.code == "segment.language" for issue in issues)


def test_find_flagged_segments_pairs_by_index_and_flags_missing_draft():
    compiled = _compiled(Term(source="Fugue", target="Fuga"))
    flagged = find_flagged_segments(
        ["The Fugue ended.", "A second paragraph."],
        ["A Fuga terminou."],
        compiled=compiled,
    )
    assert [segment.index for segment in flagged] == [1]
    assert flagged[0].draft == ""
    assert flagged[0].issues[0].code == "segment.empty"


def test_refine_segments_accepts_small_edits_and_rejects_rewrites():
    accepted = FlaggedSegment(
        0,
        "The Fugue ended.",
        "A Fuga terminou.",
        [RefinementIssue("segment.glossary_missing", "test")],
    )
    rejected = FlaggedSegment(
        1,
        "The Fugue ended.",
        "A Fuga terminou.",
        [RefinementIssue("segment.glossary_missing", "test")],
    )
    calls = []

    def generate(messages):
        calls.append(messages)
        if len(calls) == 1:
            return "A Fuga terminou ontem."
        return (
            "Um texto completamente reescrito, com detalhes novos, imagens "
            "diferentes, outra sintaxe e uma extensão muito maior do que o "
            "rascunho original para forçar o guard a rejeitar a proposta."
        )

    replacements, report = refine_segments([accepted, rejected], generate)
    assert replacements == {0: "A Fuga terminou ontem."}
    assert report["accepted"] == 1
    assert report["rejected"] == 1
    assert report["attempted"] == 2


def test_refine_segments_keeps_draft_on_provider_error():
    segment = FlaggedSegment(0, "The Fugue ended.", "A Fuga terminou.", [])

    def generate(messages):
        raise RuntimeError("connection reset")

    replacements, report = refine_segments([segment], generate)
    assert replacements == {}
    assert report["rejected"] == 1
    assert "connection reset" in report["segments"][0]["error"]


def test_empty_draft_is_skipped_without_a_model_call():
    segment = FlaggedSegment(0, "Source.", "", [RefinementIssue("segment.empty", "empty")])
    replacements, report = refine_segments([segment], lambda messages: "should not run")
    assert replacements == {}
    assert report["skipped"] == 1
    assert report["attempted"] == 0


def test_render_refined_text_preserves_paragraph_boundaries():
    draft = "Primeiro parágrafo.\n\nSegundo parágrafo.\n\nTerceiro parágrafo."
    output = render_refined_text(draft, {1: "Segundo parágrafo revisado."})
    assert output == (
        "Primeiro parágrafo.\n\nSegundo parágrafo revisado.\n\nTerceiro parágrafo.\n"
    )


def test_cli_dry_run_reports_flags(tmp_path, capsys):
    source = tmp_path / "source.txt"
    draft = tmp_path / "draft.txt"
    source.write_text("The Fugue lasted 3 days.", encoding="utf-8")
    draft.write_text("O episódio durou dois dias.", encoding="utf-8")

    code = cli_main(
        [
            "refine",
            "--source",
            str(source),
            "--draft",
            str(draft),
            "--out",
            str(tmp_path / "out.txt"),
            "--author",
            "robin-hobb",
            "--universe",
            "realm-of-the-elderlings",
            "--subseries",
            "farseer",
            "--book",
            "assassins-apprentice",
            "--model",
            "unused",
            "--dry-run",
        ]
    )
    assert code == 0
    captured = capsys.readouterr().out
    assert '"flagged"' in captured
    assert "segment.numbers" in captured
