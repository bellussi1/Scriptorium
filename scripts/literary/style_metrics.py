"""Compute the style metrics used in docs/project/EDITORIAL_PROFILES.md.

Run from the repository root:
    python scripts/literary/style_metrics.py data/editorial_samples
"""
from pathlib import Path
import re
import statistics
import json
import sys

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/editorial_samples")
SAMPLE_DIRS = [
    "lonesome_en", "lonesome_pt",
    "farseer1_en", "farseer1_pt",
    "farseer2_en", "farseer2_pt",
    "sun2_en", "sun3_en", "sun1_pt",
]
EN_CONTRACTIONS = re.compile(r"\b(?:[A-Za-z]+['\u2019](?:t|s|re|ve|ll|d|m)|(?:ain|can|don|won|isn|aren|wasn|weren|didn|doesn|hadn|hasn|haven|couldn|wouldn|shouldn|mustn|needn)['\u2019]t)\b", re.I)
DIALOGUE_EN = re.compile(r"^\s*[\u201c\"']")
DIALOGUE_PT = re.compile(r"^\s*(?:[-\u2013\u2014\u2015]\s*|[\u201c\"'])")
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'\u201c\u2018A-ZÀ-Ý0-9])")


def paragraphs(text: str):
    return [p.strip() for p in text.splitlines() if p.strip()]


def sentences(text: str):
    out = []
    for p in paragraphs(text):
        for s in SENT_SPLIT.split(p):
            s = s.strip()
            if s:
                out.append(s)
    return out


def words(text: str):
    return re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ\u2019'-]+", text)


def metrics(text: str, lang: str):
    paras = paragraphs(text)
    sents = sentences(text)
    ws = words(text)
    wl = [len(words(s)) for s in sents]
    pl = [len(words(p)) for p in paras]
    sents_sorted = sorted(wl)
    p90 = sents_sorted[int(len(sents_sorted) * 0.9)] if sents_sorted else 0
    dlg = DIALOGUE_PT if lang == "pt" else DIALOGUE_EN
    dlg_paras = sum(1 for p in paras if dlg.match(p))
    starts_and = sum(1 for s in sents if re.match(r"(?i)^(and|but|so|because|or)\b", s.strip()))
    # fragments: short sentence with no obvious finite verb (rough, English)
    fragment = 0
    if lang == "en":
        finite = re.compile(r"\b(?:is|are|was|were|am|be|been|being|have|has|had|do|does|did|will|would|can|could|shall|should|may|might|must|said|says|went|come|came|know|knew|think|thought|saw|see|look|looked|stood|stand|sat|sit|lay|lie|put|took|take|gave|give|made|make|get|got|go|goes|felt|feel|seemed|seem|left|leave|found|find|told|tell|asked|ask)\b|['\u2019](?:s|re|ve|ll|d|m|t)\b", re.I)
        fragment = sum(1 for s in sents if len(words(s)) <= 7 and not finite.search(s) and not s.endswith("?"))
    semi = text.count(";")
    dash = text.count("—") + text.count("–")
    ell = text.count("...") + text.count("…")
    q = text.count("?")
    excl = text.count("!")
    commas = text.count(",")
    cont = len(EN_CONTRACTIONS.findall(text))
    enclisis = len(re.findall(r"\b\w+(?:-se|-me|-lhe|-lhes|-nos|-vos|-o|-a|-os|-as|-lo|-la|-los|-las)\b", text, re.I))
    ly = len(re.findall(r"\b\w+ly\b", text, re.I))
    mente = len(re.findall(r"\b\w+mente\b", text, re.I))
    return {
        "lang": lang, "chars": len(text), "words": len(ws),
        "paragraphs": len(paras), "sentences": len(sents),
        "avg_sentence": round(len(ws) / max(len(sents), 1), 2),
        "median_sentence": round(statistics.median(wl), 1) if wl else 0,
        "p90_sentence": p90, "max_sentence": max(wl) if wl else 0,
        "avg_paragraph": round(len(ws) / max(len(paras), 1), 2),
        "median_paragraph": round(statistics.median(pl), 1) if pl else 0,
        "p90_paragraph": sorted(pl)[int(len(pl) * 0.9)] if pl else 0,
        "dialogue_para_ratio": round(dlg_paras / max(len(paras), 1), 3),
        "semicolons_1k": round(semi / max(len(ws), 1) * 1000, 2),
        "dashes_1k": round(dash / max(len(ws), 1) * 1000, 2),
        "ellipses_1k": round(ell / max(len(ws), 1) * 1000, 2),
        "questions_1k": round(q / max(len(ws), 1) * 1000, 2),
        "excl_1k": round(excl / max(len(ws), 1) * 1000, 2),
        "commas_per_sentence": round(commas / max(len(sents), 1), 2),
        "and_but_starts_pct": round(starts_and / max(len(sents), 1) * 100, 1),
        "contractions_1k": round(cont / max(len(ws), 1) * 1000, 2),
        "enclisis_1k": round(enclisis / max(len(ws), 1) * 1000, 2),
        "ly_1k": round(ly / max(len(ws), 1) * 1000, 2),
        "mente_1k": round(mente / max(len(ws), 1) * 1000, 2),
        "short_fragments_pct": round(fragment / max(len(sents), 1) * 100, 1) if lang == "en" else "",
    }


def main():
    results = {}
    chapters = {}
    for d in SAMPLE_DIRS:
        files = sorted((ROOT / d).glob("chapter_*.txt"))
        lang = "pt" if d.endswith("_pt") else "en"
        chapter_metrics = []
        for f in files:
            m = metrics(f.read_text(encoding="utf-8", errors="replace"), lang)
            m["file"] = f.name
            chapter_metrics.append(m)
        combined = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in files)
        m = metrics(combined, lang)
        m["files"] = len(files)
        results[d] = m
        chapters[d] = chapter_metrics
    print(json.dumps({"combined": results, "chapters": chapters}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
