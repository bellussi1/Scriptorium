"""Tests for the targeted repair of forbidden forms and pt-PT blocking forms."""

from __future__ import annotations

import zipfile
from pathlib import Path

from src.literary.targeted_fix import (
    ForbiddenRule,
    fix_epub,
    fix_paragraph,
    find_failures,
)

RULES = [ForbiddenRule(source="animalcule", target="criatura", form="animalcule")]
CLEAN = "O monstro rastejou pelo piso quebrado da velha capela enquanto os sinos tocavam ao longe."
FORBIDDEN = "O animalcule rastejou pelo piso quebrado da velha capela enquanto os sinos tocavam ao longe."
PT_PT = "Estamos a construir a ponte e o contacto é importante para todos nós aqui na aldeia."


def _fixed_forbidden(text: str) -> str:
    return text.replace("animalcule", "criatura")


def test_clean_paragraph_has_no_failure():
    assert find_failures(CLEAN, RULES) == []


def test_forbidden_form_is_detected_with_instruction():
    failures = find_failures(FORBIDDEN, RULES)
    assert [f.code for f in failures] == ["forbidden"]
    assert "criatura" in failures[0].instruction


def test_pt_pt_block_is_detected():
    assert "pt_pt_block" in [f.code for f in find_failures(PT_PT, RULES)]


def test_repair_is_accepted_when_failure_is_gone():
    calls = []

    def generate(messages):
        calls.append(messages)
        return _fixed_forbidden(FORBIDDEN)

    result = fix_paragraph(FORBIDDEN, RULES, generate)
    assert result["accepted"] is True
    assert result["after"] == _fixed_forbidden(FORBIDDEN)
    assert result["attempts"] == 1
    assert "criatura" in calls[0][1]["content"]


def test_reply_that_keeps_the_failure_is_rejected():
    result = fix_paragraph(FORBIDDEN, RULES, lambda messages: FORBIDDEN)
    assert result["accepted"] is False
    assert any(r.startswith("failure remains") for r in result["reasons"])


def test_numbers_changed_is_rejected():
    text = "Em 1842 o animalcule atravessou a ponte e chegou à cidade antes do amanhecer."
    changed = _fixed_forbidden(text).replace("1842", "1824")
    result = fix_paragraph(text, RULES, lambda messages: changed)
    assert result["accepted"] is False
    assert "numbers changed" in result["reasons"]


def test_rewrite_that_is_too_short_is_rejected():
    result = fix_paragraph(FORBIDDEN, RULES, lambda messages: "criatura.")
    assert result["accepted"] is False


def test_provider_error_keeps_the_draft():
    def generate(messages):
        raise RuntimeError("offline")

    result = fix_paragraph(FORBIDDEN, RULES, generate)
    assert result["accepted"] is False
    assert result["after"] == FORBIDDEN
    assert result["reasons"][0].startswith("error:")


def _write_sample_epub(path: Path, paragraph: str) -> None:
    body = f"<html><body><p>{paragraph}</p><p>{CLEAN}</p></body></html>"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("OEBPS/ch1.xhtml", body)


def test_fix_epub_writes_repaired_paragraph_and_keeps_other_text(tmp_path):
    source = tmp_path / "in.epub"
    output = tmp_path / "out.epub"
    _write_sample_epub(source, FORBIDDEN)

    report = fix_epub(str(source), str(output), rules=RULES, generate=lambda m: _fixed_forbidden(FORBIDDEN))

    assert report["accepted"] == 1
    assert report["by_code"] == {"forbidden": 1}
    with zipfile.ZipFile(output) as archive:
        text = archive.read("OEBPS/ch1.xhtml").decode("utf-8")
    assert "criatura" in text and "animalcule" not in text
    assert CLEAN in text


def test_fix_epub_dry_run_changes_nothing(tmp_path):
    source = tmp_path / "in.epub"
    output = tmp_path / "out.epub"
    _write_sample_epub(source, FORBIDDEN)

    report = fix_epub(str(source), str(output), rules=RULES, generate=lambda m: "x", dry_run=True)

    assert report["flagged"] == 1
    assert report["attempted"] == 0
    assert not output.exists()


PAGAR = 'Estamos a pagar aos guardas o dobro do valor combinado todos os dias da semana inteira.'


def test_content_word_swap_is_rejected():
    revised = PAGAR.replace('pagar', 'construindo')
    result = fix_paragraph(PAGAR, RULES, lambda messages: revised)
    assert result['accepted'] is False
    assert any('unexpected word change: pagar' in r for r in result['reasons'])


def test_related_form_is_accepted():
    draft = 'Podia entrar em contacto com o vosso mestre, sacerdote, e pedir uma audiência com ele antes do fim do dia.'
    revised = draft.replace('Podia', 'Poderia').replace('contacto', 'contato')
    result = fix_paragraph(draft, RULES, lambda messages: revised)
    assert result['accepted'] is True
