"""Tests for the deterministic PT-BR checks."""
from __future__ import annotations

from src.literary.ptbr import check_text, check_with_languagetool, merge_issues
from src.literary.refine_runner import flags_for_segment


def _codes(text: str) -> set[str]:
    return {issue.code for issue in check_text(text)}


def test_known_pilot_verb_errors_are_caught_with_suggestions():
    issues = check_text("Convinci-me de que era verdade. Convinquei-me depois.")
    by_code = [issue for issue in issues if issue.code == "ptbr.verb_convencer"]

    assert len(by_code) == 2
    assert by_code[0].severity == "error"
    assert "Convenci-me" in by_code[0].suggestions
    assert "Convenci-me" in by_code[1].suggestions
    text = "Convinci-me de que era verdade."
    issue = next(item for item in check_text(text) if item.code == "ptbr.verb_convencer")
    assert text[issue.start:issue.end] == "Convinci-me"


def test_correct_forms_are_not_flagged():
    clean = (
        "Convenci-me de que era verdade. Convém esperar. Ela tem menos medo. "
        "De repente, atravessou a rua. Ele foi para eu terminar o trabalho."
    )
    assert _codes(clean) == set()


def test_contractions_and_pronoun_case():
    assert "ptbr.contraction_do" in _codes("Ele saiu de o carro.")
    assert "ptbr.contraction_nos" in _codes("Pensou em os amigos.")
    assert "ptbr.contraction_pelo" in _codes("Passou por o portão.")
    assert "ptbr.pronoun_para_eu" in _codes("Isso é para mim fazer.")
    assert "ptbr.pronoun_entre_mim" in _codes("Entre eu e ela, prefiro o silêncio.")


def test_impersonal_haver_and_existir_agreement():
    assert "ptbr.haver_impessoal" in _codes("Houveram muitos problemas.")
    assert "ptbr.haver_impessoal" in _codes("Haviam muitos problemas.")
    assert "ptbr.existir_concordancia" in _codes("Existe muitos motivos.")
    assert "ptbr.fazer_tempo" in _codes("Fazem dois anos que parti.")


def test_mas_mais_and_final_por_que():
    assert "ptbr.mas_mais" in _codes("Ele chegou, mais eu não estava lá.")
    assert "ptbr.por_que_final" in _codes("Você fez isso por que?")
    assert "ptbr.por_que_final" not in _codes("Por que você fez isso?")


def test_accent_and_spelling_rules():
    assert "ptbr.accent_convem" in _codes("Convem esperar.")
    assert "ptbr.menos" in _codes("Ela tem menas medo.")
    assert "ptbr.subjuntivo_seja" in _codes("Espero que seje assim.")
    assert "ptbr.de_repente" in _codes("Derrepente, tudo mudou.")
    assert "ptbr.com_certeza" in _codes("Concerteza ele vem.")
    assert "ptbr.accent_atraves" in _codes("Passou atraves da porta.")
    assert "ptbr.accent_ha" in _codes("Ha dois anos que parti.")


def test_repeated_word_is_a_warning_not_an_error():
    issues = [issue for issue in check_text("Ele disse que que era tarde.") if issue.code == "ptbr.repeated_word"]
    assert len(issues) == 1
    assert issues[0].severity == "warning"


def test_empty_text_has_no_issues():
    assert check_text("") == []


def test_languagetool_matches_are_normalized(monkeypatch):
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "matches": [
                    {
                        "offset": 4,
                        "length": 6,
                        "message": "possible agreement error",
                        "rule": {"id": "AGREEMENT", "issueType": "grammar"},
                        "replacements": [{"value": "correta"}],
                    }
                ]
            }

    calls = {}

    def _post(url, data, timeout):
        calls["url"] = url
        calls["data"] = data
        return _Response()

    monkeypatch.setattr("src.literary.ptbr.requests.post", _post)
    issues = check_with_languagetool("um texto", endpoint="http://localhost:8010")

    assert calls["url"] == "http://localhost:8010/v2/check"
    assert calls["data"]["language"] == "pt-BR"
    assert issues[0].code == "languagetool.AGREEMENT"
    assert issues[0].severity == "error"
    assert issues[0].start == 4
    assert issues[0].end == 10
    assert issues[0].suggestions == ["correta"]


def test_merge_issues_deduplicates_same_span():
    first = check_text("Ele saiu de o carro.")
    second = check_text("Ele saiu de o carro.")
    merged = merge_issues(first, second)
    assert len(merged) == len({(item.code, item.start, item.end) for item in merged})


def test_refinement_flags_include_ptbr_issues():
    issues = flags_for_segment(
        "I convinced myself that it was true.",
        "Convinci-me de que era verdade.",
    )
    assert any(issue.code == "ptbr.verb_convencer" for issue in issues)
    # The repeated-word warning is reported by check_text but is not a repair
    # target for the refinement pass.
    repeated = flags_for_segment("He said that that was enough.", "Ele disse que que bastava.")
    assert not any(issue.code == "ptbr.repeated_word" for issue in repeated)
