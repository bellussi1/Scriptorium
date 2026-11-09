"""Best-effort source-language guard for the fork's English -> pt-BR scope.

This is deliberately a guard, not a language picker: the UI has one fixed
pair. Uploads are checked so a French/Spanish/... source cannot be silently
translated as if it were English, and refine/term-fix uploads are checked so
they actually contain an already-translated Portuguese file.

The check is advisory when the text is too short or the detector is not
confident; a confident mismatch is rejected by the routes.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Optional, Tuple

MIN_CHARS = 80
CONFIDENCE_THRESHOLD = 0.80
MAX_SAMPLE_CHARS = 12000

LANGUAGE_NAMES = {
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "ru": "Russian",
    "pl": "Polish",
    "sv": "Swedish",
    "da": "Danish",
    "no": "Norwegian",
    "fi": "Finnish",
    "cs": "Czech",
    "el": "Greek",
    "tr": "Turkish",
    "ar": "Arabic",
    "he": "Hebrew",
    "fa": "Persian",
    "hi": "Hindi",
    "zh-cn": "Chinese",
    "zh-tw": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "uk": "Ukrainian",
    "ro": "Romanian",
    "hu": "Hungarian",
    "ca": "Catalan",
}


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ""


def _strip_srt(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.isdigit() or "-->" in stripped:
            continue
        lines.append(stripped)
    return " ".join(lines)


def _text_from_epub(data: bytes) -> str:
    try:
        from lxml import html as lhtml
    except Exception:
        return ""
    parts = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for name in archive.namelist():
                if not name.lower().endswith((".xhtml", ".html", ".htm")):
                    continue
                try:
                    tree = lhtml.fromstring(archive.read(name))
                    text = tree.text_content()
                except Exception:
                    continue
                if text.strip():
                    parts.append(text)
                if sum(len(part) for part in parts) >= MAX_SAMPLE_CHARS:
                    break
    except Exception:
        return ""
    return " ".join(parts)


def _text_from_docx(data: bytes) -> str:
    try:
        from lxml import etree
    except Exception:
        return ""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml = archive.read("word/document.xml")
        root = etree.fromstring(xml)
        return " ".join(text for text in root.itertext() if text.strip())
    except Exception:
        return ""


def _text_from_pdf(data: bytes) -> str:
    try:
        from src.core.pdf import extract_pdf_text

        return extract_pdf_text(data, hard_cap=MAX_SAMPLE_CHARS)
    except Exception:
        return ""


def extract_text(data: bytes, filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".epub"):
        text = _text_from_epub(data)
    elif lower.endswith(".docx"):
        text = _text_from_docx(data)
    elif lower.endswith(".pdf"):
        text = _text_from_pdf(data)
    else:
        text = _decode_text(data)
        if lower.endswith(".srt"):
            text = _strip_srt(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_SAMPLE_CHARS]


def detect_language(text: str) -> Tuple[Optional[str], float]:
    sample = re.sub(r"\s+", " ", text or "").strip()
    if len(sample) < MIN_CHARS:
        return None, 0.0
    try:
        from langdetect import LangDetectException, detect_langs

        probabilities = detect_langs(sample[:MAX_SAMPLE_CHARS])
    except Exception:
        return None, 0.0
    if not probabilities:
        return None, 0.0
    best = max(probabilities, key=lambda item: item.prob)
    return str(best.lang).lower(), float(best.prob)


def _result(status: str, language: Optional[str], confidence: float) -> dict:
    base = str(language or "").split("-")[0]
    return {
        "status": status,
        "language": language or "",
        "language_name": LANGUAGE_NAMES.get(language or "", LANGUAGE_NAMES.get(base, language or "")),
        "confidence": round(confidence, 3),
    }


def check_text(text: str, *, expected: str = "en") -> dict:
    language, confidence = detect_language(text)
    if not language:
        return _result("unknown", None, 0.0)
    if confidence < CONFIDENCE_THRESHOLD:
        return _result("uncertain", language, confidence)
    matches = language.startswith("en") if expected == "en" else language.startswith("pt")
    return _result("ok" if matches else "rejected", language, confidence)


def check_file(path: str | Path, *, expected: str = "en") -> dict:
    try:
        data = Path(path).read_bytes()
    except Exception:
        return _result("unknown", None, 0.0)
    return check_text(extract_text(data, str(path)), expected=expected)
