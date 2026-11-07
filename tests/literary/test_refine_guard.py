from src.literary.models import CompiledResources, GlossaryBundle, Term
from src.literary.refine import (
    RefinementIssue,
    apply_guard,
    build_source_aware_messages,
    refine_with_guard,
)


def _compiled() -> CompiledResources:
    return CompiledResources(
        glossary=GlossaryBundle(
            terms=[
                Term(
                    source="FitzChivalry Farseer",
                    target="FitzChivalry Farseer",
                    category="character",
                    aliases=["Fitz"],
                    alias_targets={"Fitz": "Fitz"},
                    forbidden=["Fitz Chivalry"],
                    gender="male",
                    confidence="confirmed",
                )
            ]
        )
    )


def test_prompt_includes_source_draft_issue_and_glossary():
    messages = build_source_aware_messages(
        "Fitz rode for 3 days.",
        "Fitz Chivalry cavalgou por 3 dias.",
        [RefinementIssue("glossary.forbidden", "forbidden rendering 'Fitz Chivalry'")],
        compiled=_compiled(),
    )
    assert messages[0]["role"] == "system"
    assert "ENGLISH SOURCE" in messages[1]["content"]
    assert "PORTUGUESE DRAFT" in messages[1]["content"]
    assert "glossary.forbidden" in messages[1]["content"]
    assert "Fitz Chivalry" in messages[1]["content"]
    assert "never:" in messages[1]["content"]


def test_guard_accepts_small_repair():
    guard = apply_guard(
        "Fitz rode for 3 days.",
        "Fitz Chivalry cavalgou por 3 dias.",
        "Fitz cavalgou por 3 dias.",
        compiled=_compiled(),
    )
    assert guard.ok, guard.reasons


def test_guard_rejects_omission_number_and_forbidden():
    guard = apply_guard(
        "Fitz rode for 3 days.",
        "Fitz Chivalry cavalgou por 3 dias.",
        "Ele viajou por três dias.",
        compiled=_compiled(),
    )
    assert not guard.ok
    assert any("numbers" in reason for reason in guard.reasons) or any("forbidden" in reason for reason in guard.reasons)

    guard2 = apply_guard(
        "Fitz rode for 3 days.",
        "Fitz Chivalry cavalgou por 3 dias.",
        "Fitz Chivalry cavalgou por 3 dias.",
        compiled=_compiled(),
    )
    assert not guard2.ok
    assert any("forbidden" in reason for reason in guard2.reasons)


def test_refine_with_guard_keeps_draft_when_rewrite_is_too_large():
    def generate(_messages):
        return "Ele viajou por três dias e nunca mais voltou."

    result = refine_with_guard(
        "Fitz rode for 3 days.",
        "Fitz cavalgou por 3 dias.",
        [RefinementIssue("style", "sentence rhythm")],
        generate,
        compiled=_compiled(),
    )
    assert result.accepted is False
    assert result.text == "Fitz cavalgou por 3 dias."


def test_refine_with_guard_accepts_small_repair():
    def generate(_messages):
        return "Fitz cavalgou por 3 dias."

    result = refine_with_guard(
        "Fitz rode for 3 days.",
        "Fitz Chivalry cavalgou por 3 dias.",
        [RefinementIssue("glossary.forbidden", "forbidden rendering")],
        generate,
        compiled=_compiled(),
    )
    assert result.accepted is True
    assert result.text == "Fitz cavalgou por 3 dias."
