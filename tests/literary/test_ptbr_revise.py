"""Tests for the European-Portuguese revision pass (source-free, per paragraph)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from src.literary.ptbr_revise import guard, pt_pt_issues, revise_epub


def _codes(text: str) -> set[str]:
    return {issue.code for issue in pt_pt_issues(text)}


def test_detects_european_second_person_and_forms():
    assert "ptbr.pt_tu_preterito" in _codes("Compreendes o que fizeste?")
    assert "ptbr.pt_tu_futuro" in _codes("Tu garantirás o apoio.")
    assert "ptbr.pt_estar_a" in _codes("Estamos a construir naves.")
    assert "ptbr.pt_ammos" in _codes("Encontrámos o colar.")
    assert "ptbr.pt_demonio" in _codes("O demónio cornudo.")


def test_does_not_flag_brazilian_forms():
    assert _codes("Este homem, deste lado, no oeste, e estavam aqui.") == set()
    assert _codes("Ela chegou atrás do muro e estávamos sós.") == set()


def test_guard_accepts_a_clean_conversion():
    draft = "Tu garantirás o apoio deles."
    revised = "Você garantirá o apoio deles."
    ok, reasons = guard(draft, revised, pt_pt_issues(draft))
    assert ok, reasons


def test_guard_rejects_changes_outside_the_flagged_forms():
    draft = "Vós falais com demónios."
    revised = "Vocês falam com demônios."
    ok, reasons = guard(draft, revised, pt_pt_issues(draft))
    assert not ok
    assert any("outside the flagged forms" in reason for reason in reasons)


def test_guard_rejects_a_revision_that_keeps_european_forms():
    draft = "Estamos a construir naves."
    revised = "Estamos a construir naves."
    ok, reasons = guard(draft, revised, pt_pt_issues(draft))
    assert not ok
    assert any("still European" in reason for reason in reasons)


def test_guard_rejects_lost_names_and_changed_numbers():
    draft = "Lorian disse 3 palavras ao Magnarca."
    revised = "Ele disse 4 palavras ao Magnarca."
    ok, reasons = guard(draft, revised, [])
    assert not ok
    assert any("numbers changed" in reason for reason in reasons)


def test_revise_epub_writes_only_accepted_paragraphs(tmp_path: Path):
    source = tmp_path / "in.epub"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr(
            "OEBPS/ch.xhtml",
            "<html><body><p>Tu garantirás o apoio deles.</p>"
            "<p>Estamos a construir naves.</p></body></html>",
        )
    output = tmp_path / "out.epub"

    def stub(messages):
        user = messages[-1]["content"]
        if "garantirás" in user:
            return "Você garantirá o apoio deles."
        return "Vocês falam com demônios."  # unrequested change: the guard must refuse it

    report = revise_epub(str(source), str(output), generate=stub)

    assert report["flagged"] == 2
    assert report["accepted"] == 1
    assert report["rejected"] == 1
    with zipfile.ZipFile(output) as archive:
        xhtml = archive.read("OEBPS/ch.xhtml").decode("utf-8")
        assert archive.infolist()[0].filename == "mimetype"
    assert "Você garantirá o apoio deles." in xhtml
    assert "Estamos a construir naves." in xhtml
    segments = json.loads(json.dumps(report["segments"]))
    assert {s["accepted"] for s in segments} == {True, False}


def test_safe_swaps_need_no_model():
    from src.literary.ptbr_revise import revise_paragraph

    def never(messages):
        raise AssertionError("the model must not be called for word swaps")

    result = revise_paragraph("O demónio falou de facto com a tua gente.", never)
    assert result["method"] == "swap"
    assert result["accepted"], result["reasons"]
    assert result["after"] == "O demônio falou de fato com a sua gente."


def test_guard_accepts_a_verb_person_change_within_the_same_stem():
    draft = "Esperas encontrar algum registo de contacto."
    revised = "Espera encontrar algum registro de contato."
    ok, reasons = guard(draft, revised, pt_pt_issues(draft))
    assert ok, reasons
