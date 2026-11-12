"""Deterministic Brazilian Portuguese checks for literary drafts.

The rules here are deliberately conservative: they only flag patterns that are
wrong in running prose, so they can feed the source-aware refinement queue
without turning every stylistic choice into an "error". LanguageTool is an
optional second opinion; it is never required for the local pipeline.

This module does not replace a human editor. It catches known error classes
(verb forms, contractions, pronoun case, impersonal *haver*, repeated words)
and exposes spans so a report can point at the exact text.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

import requests


@dataclass
class PtBrIssue:
    code: str
    message: str
    severity: str = "warning"  # warning | error
    start: int = -1
    end: int = -1
    suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "start": self.start,
            "end": self.end,
            "suggestions": list(self.suggestions),
        }


@dataclass(frozen=True)
class _Rule:
    pattern: re.Pattern
    replacement: str
    code: str
    message: str
    severity: str = "warning"


def _rule(pattern: str, replacement: str, code: str, message: str, severity: str = "warning") -> _Rule:
    return _Rule(
        pattern=re.compile(pattern, re.IGNORECASE | re.UNICODE),
        replacement=replacement,
        code=code,
        message=message,
        severity=severity,
    )


# High-confidence errors seen in the PT-BR pilot or in common Portuguese prose.
_RULES: List[_Rule] = [
    _rule(
        r"\bconvinci(-me)?\b",
        r"convenci\1",
        "ptbr.verb_convencer",
        "Forma verbal incorreta de convencer: use 'convenci'.",
        "error",
    ),
    _rule(
        r"\bconvinquei(-me)?\b",
        r"convenci\1",
        "ptbr.verb_convencer",
        "Forma verbal incorreta de convencer: use 'convenci'.",
        "error",
    ),
    _rule(r"\bconvem\b", "convém", "ptbr.accent_convem", "Falta acento em 'convém'.", "error"),
    _rule(r"\bmenas\b", "menos", "ptbr.menos", "Use 'menos', não 'menas'.", "error"),
    _rule(r"\bseje\b", "seja", "ptbr.subjuntivo_seja", "Use 'seja', não 'seje'.", "error"),
    _rule(r"\bsejem\b", "sejam", "ptbr.subjuntivo_sejam", "Use 'sejam', não 'sejem'.", "error"),
    _rule(r"\bderrepente\b", "de repente", "ptbr.de_repente", "Escreva 'de repente' separado.", "error"),
    _rule(r"\bconcerteza\b", "com certeza", "ptbr.com_certeza", "Escreva 'com certeza'.", "error"),
    _rule(r"\batraves\b", "através", "ptbr.accent_atraves", "Falta acento em 'através'.", "error"),
    _rule(r"\bde o\b", "do", "ptbr.contraction_do", "Contraia 'de o' em 'do'.", "warning"),
    _rule(r"\bde os\b", "dos", "ptbr.contraction_dos", "Contraia 'de os' em 'dos'.", "warning"),
    _rule(r"\bem o\b", "no", "ptbr.contraction_no", "Contraia 'em o' em 'no'.", "warning"),
    _rule(r"\bem os\b", "nos", "ptbr.contraction_nos", "Contraia 'em os' em 'nos'.", "warning"),
    _rule(r"\bpor o\b", "pelo", "ptbr.contraction_pelo", "Contraia 'por o' em 'pelo'.", "warning"),
    _rule(r"\bpor os\b", "pelos", "ptbr.contraction_pelos", "Contraia 'por os' em 'pelos'.", "warning"),
    _rule(
        r"\bpara mim\s+(fazer|ver|ir|dizer|pensar|saber|entender|escrever|ler|traduzir|terminar|começar)\b",
        r"para eu \1",
        "ptbr.pronoun_para_eu",
        "Antes de verbo no infinitivo, use 'para eu', não 'para mim'.",
        "error",
    ),
    _rule(
        r"\bentre eu e\b",
        "entre mim e",
        "ptbr.pronoun_entre_mim",
        "Use 'entre mim e', não 'entre eu e'.",
        "error",
    ),
    _rule(
        r"\bhouveram\b",
        "houve",
        "ptbr.haver_impessoal",
        "O verbo haver é impessoal: use 'houve' para existência.",
        "warning",
    ),
    _rule(
        r"\bhaviam\s+(muitos|muitas|vários|várias|alguns|algumas|dois|duas|três)\b",
        r"havia \1",
        "ptbr.haver_impessoal",
        "O verbo haver é impessoal: use 'havia' para existência.",
        "warning",
    ),
    _rule(
        r"\bexiste\s+(muitos|muitas|vários|várias|alguns|algumas|dois|duas|três)\b",
        r"existem \1",
        "ptbr.existir_concordancia",
        "Concorde o verbo existir com o sujeito plural.",
        "error",
    ),
    _rule(
        r"\bfazem\s+(\d+|dois|duas|três|tres|quatro|cinco|seis|sete|oito|nove|dez|muitos|muitas)\s+(anos|meses|dias|horas)\b",
        r"faz \1 \2",
        "ptbr.fazer_tempo",
        "Para tempo decorrido, use 'faz', não 'fazem'.",
        "error",
    ),
    _rule(
        r"\bmais\s+(eu|ele|ela|eles|elas|nós|você)\b",
        r"mas \1",
        "ptbr.mas_mais",
        "Aqui o sentido é adversativo: use 'mas', não 'mais'.",
        "warning",
    ),
    _rule(
        r"\bpor que\s*([?.!]|$)",
        r"por quê\1",
        "ptbr.por_que_final",
        "No fim da frase, use 'por quê' com acento.",
        "error",
    ),
    _rule(
        r"\bha\s+(\d+|dois|duas|três|tres|quatro|cinco|seis|sete|oito|nove|dez|muitos|muitas)\s+(anos|meses|dias|horas)\b",
        r"há \1 \2",
        "ptbr.accent_ha",
        "Falta acento em 'há' (tempo decorrido).",
        "error",
    ),
    # European Portuguese forms. A Brazilian edition uses the forms below. Rules
    # with an empty replacement describe a change of verb person or tense: the
    # model has to conjugate the whole clause, so no single-word suggestion is
    # offered.
    _rule(r"\bde facto\b", "de fato", "ptbr.pt_de_facto", "Português europeu: use 'de fato'.", "error"),
    _rule(r"\bcontact(o|os)\b", r"contat\1", "ptbr.pt_contacto", "Português europeu: use 'contato'.", "error"),
    _rule(r"\bdemónio(s?)\b", r"demônio\1", "ptbr.pt_demonio", "Português europeu: use 'demônio'.", "error"),
    _rule(r"\bprémio(s?)\b", r"prêmio\1", "ptbr.pt_premio", "Português europeu: use 'prêmio'.", "error"),
    _rule(r"\bconvosco\b", "com vocês", "ptbr.pt_convosco", "Português europeu: use 'com vocês'.", "error"),
    _rule(r"\b(\w+)ámos\b", r"\1amos", "ptbr.pt_ammos", "Pretérito europeu: 'amos' sem acento.", "error"),
    _rule(
        r"\b(estou|estás|está|estamos|estão|estava|estavam) a (?=\w+r\b)",
        "",
        "ptbr.pt_estar_a",
        "Português europeu 'estar a + infinitivo'. Use 'estar + gerúndio' (ex.: 'estamos construindo').",
        "error",
    ),
    _rule(
        r"\b(?!(?:este|deste|neste|oeste|leste|teste|peste|agreste|nordeste|sudeste)\b)\w+(?:aste|este|iste)\b",
        "",
        "ptbr.pt_tu_preterito",
        "Segunda pessoa do português europeu. Troque por 'você' e conjugue o verbo na 3.ª pessoa do pretérito.",
        "error",
    ),
    _rule(
        r"\b\w+(?:irás|erás|arás)\b",
        "",
        "ptbr.pt_tu_futuro",
        "Segunda pessoa do futuro. Troque por 'você' e use o futuro na 3.ª pessoa.",
        "error",
    ),
    _rule(
        r"\b(és|tens|queres|sabes|podes|vês|dizes|fazes|dás|vens)\b",
        "",
        "ptbr.pt_tu_presente",
        "Segunda pessoa do presente do português europeu. Use 'você' e a 3.ª pessoa.",
        "error",
    ),
    _rule(r"\btu\b", "você", "ptbr.pt_tu", "Português europeu: use 'você' e a 3.ª pessoa do verbo.", "error"),
    _rule(r"\bteu(s?)\b", r"seu\1", "ptbr.pt_teu", "Possessivo de 'tu': use 'seu' com 'você'.", "error"),
    _rule(r"\btua(s?)\b", r"sua\1", "ptbr.pt_tua", "Possessivo de 'tu': use 'sua' com 'você'.", "error"),
]

_REPEATED_WORD = re.compile(r"\b([A-Za-zÀ-ÖØ-öø-ÿ]{3,})\s+\1\b", re.IGNORECASE | re.UNICODE)


def _match_case(original: str, replacement: str) -> str:
    if not replacement:
        return replacement
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def check_text(text: str) -> List[PtBrIssue]:
    """Return conservative PT-BR issues with exact character spans."""
    if not text:
        return []
    issues: List[PtBrIssue] = []
    for rule in _RULES:
        for match in rule.pattern.finditer(text):
            suggestion = _match_case(match.group(0), match.expand(rule.replacement))
            issues.append(
                PtBrIssue(
                    code=rule.code,
                    message=rule.message,
                    severity=rule.severity,
                    start=match.start(),
                    end=match.end(),
                    suggestions=[suggestion] if rule.replacement else [],
                )
            )

    for match in _REPEATED_WORD.finditer(text):
        word = match.group(1)
        # Deliberate repetition is a literary device; report it as a warning
        # rather than assuming it is a typo.
        issues.append(
            PtBrIssue(
                code="ptbr.repeated_word",
                message=f"Palavra repetida em sequência: '{word}'.",
                severity="warning",
                start=match.start(),
                end=match.end(),
                suggestions=[word],
            )
        )

    # One span can match more than one rule (e.g. repeated-word plus a
    # contraction); keep the first occurrence per code/span.
    deduped: List[PtBrIssue] = []
    seen = set()
    for issue in sorted(issues, key=lambda item: (item.start, item.code)):
        key = (issue.code, issue.start, issue.end)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped


def languagetool_endpoint() -> str:
    return os.getenv("LANGUAGETOOL_URL", "").strip()


def check_with_languagetool(
    text: str,
    *,
    endpoint: Optional[str] = None,
    language: str = "pt-BR",
    timeout: int = 30,
) -> List[PtBrIssue]:
    """Query a local LanguageTool server and normalize its matches.

    The caller should catch ``requests.RequestException`` and fall back to
    :func:`check_text`; this module never starts a server by itself.
    """
    endpoint = (endpoint or languagetool_endpoint()).rstrip("/")
    if not endpoint:
        return []
    response = requests.post(
        f"{endpoint}/v2/check",
        data={"text": text, "language": language, "enabledOnly": "false"},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    issues: List[PtBrIssue] = []
    for match in payload.get("matches", []):
        rule = match.get("rule") or {}
        issue_type = str(rule.get("issueType") or "").lower()
        severity = "error" if issue_type in {"grammar", "misspelling"} else "warning"
        offset = int(match.get("offset") or 0)
        length = int(match.get("length") or 0)
        suggestions = [
            str(item.get("value"))
            for item in (match.get("replacements") or [])[:5]
            if item.get("value")
        ]
        issues.append(
            PtBrIssue(
                code=f"languagetool.{rule.get('id') or 'match'}",
                message=str(match.get("message") or rule.get("description") or "LanguageTool match"),
                severity=severity,
                start=offset,
                end=offset + length,
                suggestions=suggestions,
            )
        )
    return issues


def merge_issues(*groups: Iterable[PtBrIssue]) -> List[PtBrIssue]:
    """Merge deterministic and LanguageTool issues without duplicate spans."""
    merged: List[PtBrIssue] = []
    seen = set()
    for group in groups:
        for issue in group:
            key = (issue.code, issue.start, issue.end)
            if key in seen:
                continue
            seen.add(key)
            merged.append(issue)
    return sorted(merged, key=lambda item: (item.start, item.code))
