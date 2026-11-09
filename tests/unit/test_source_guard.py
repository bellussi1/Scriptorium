"""Tests for the best-effort English/Portuguese source-language guard."""
from __future__ import annotations

from src.utils.source_guard import check_text, extract_text

ENGLISH = (
    "The old lighthouse keeper climbed the narrow stairs every evening before "
    "sunset. He carried a small lantern and a notebook in which he wrote down "
    "the weather, the ships he had seen during the day, and the names of the "
    "birds that rested on the rocks. Nobody in the village remembered when he "
    "had first arrived, but everyone agreed that the light had never failed."
) * 3

FRENCH = (
    "Le vieux gardien de phare montait les escaliers étroits chaque soir avant "
    "le coucher du soleil. Il portait une petite lanterne et un carnet dans "
    "lequel il notait le temps, les navires qu'il avait vus pendant la journée "
    "et les noms des oiseaux posés sur les rochers. Personne dans le village "
    "ne se rappelait son arrivée, mais tous convenaient que la lumière n'avait "
    "jamais manqué."
) * 3

PORTUGUESE = (
    "O velho faroleiro subia as escadas estreitas todas as noites antes do "
    "pôr do sol. Levava uma pequena lanterna e um caderno no qual anotava o "
    "tempo, os navios que tinha visto durante o dia e os nomes das aves que "
    "descansavam nas rochas. Ninguém na aldeia se lembrava de quando ele "
    "chegara, mas todos concordavam que a luz nunca falhara."
) * 3


def test_english_source_passes_translate_guard():
    result = check_text(ENGLISH, expected="en")
    assert result["status"] == "ok"
    assert result["language"] == "en"


def test_french_source_is_rejected_for_translate():
    result = check_text(FRENCH, expected="en")
    assert result["status"] == "rejected"
    assert result["language"] == "fr"
    assert result["language_name"] == "French"


def test_portuguese_source_passes_refine_guard():
    result = check_text(PORTUGUESE, expected="pt")
    assert result["status"] == "ok"
    assert result["language"] == "pt"


def test_english_source_is_rejected_for_refine():
    result = check_text(ENGLISH, expected="pt")
    assert result["status"] == "rejected"
    assert result["language"] == "en"


def test_short_text_is_unknown_not_rejected():
    result = check_text("Hello world.", expected="en")
    assert result["status"] == "unknown"


def test_srt_extraction_ignores_timestamps_and_indices():
    srt = b"""1
00:00:01,000 --> 00:00:04,000
The old lighthouse keeper climbed the narrow stairs.

2
00:00:05,000 --> 00:00:08,000
He carried a small lantern and a notebook.
"""
    text = extract_text(srt, "chapter.srt")
    assert "-->" not in text
    assert "lighthouse keeper" in text
    assert not text.startswith("1 ")
