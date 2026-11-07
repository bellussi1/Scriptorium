"""Print speech-tag and PT-BR variety markers for the editorial samples.

Run from the repository root:
    python scripts/literary/style_markers.py data/editorial_samples
"""
from pathlib import Path
import re
import json
import sys
from collections import Counter

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/editorial_samples")
DIRS = ["lonesome_en","lonesome_pt","farseer1_en","farseer1_pt","farseer2_en","farseer2_pt","sun2_en","sun3_en","sun1_pt"]

def text(d):
    return "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in sorted((ROOT/d).glob("chapter_*.txt")))

def count(pat, t, flags=re.I):
    return len(re.findall(pat, t, flags))

def first_n_words(t, n=1000):
    ws = re.findall(r"\S+", t)
    return " ".join(ws[:n])

def sent_stats(t):
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", t) if s.strip()]
    lens = [len(re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ'-]+", s)) for s in sents]
    return len(sents), round(sum(lens)/max(len(lens),1),1), sorted(lens)[int(len(lens)*.9)] if lens else 0

print("=== TAG VERBS ===")
for d in DIRS:
    t = text(d)
    tags = Counter(m.group(0).lower() for m in re.finditer(r"\b(?:said|asked|replied|answered|cried|shouted|muttered|whispered|murmured|snapped|observed|remarked|added|began|continued|explained|admitted|agreed|protested|demanded|suggested|insisted|warned|called|told|spoke)\b", t, re.I))
    if d.endswith("_pt"):
        tags = Counter(m.group(0).lower() for m in re.finditer(r"\b(?:disse|perguntou|respondeu|retrucou|gritou|sussurrou|murmurou|rosnou|observou|comentou|acrescentou|começou|continuou|explicou|admitiu|concordou|protestou|exigiu|sugeriu|insistiu|avisou|chamou|contou|falou)\b", t, re.I))
    print(d, tags.most_common(8))

print("\n=== FIRST 1000 WORDS RHYTHM ===")
for d in DIRS:
    n, avg, p90 = sent_stats(first_n_words(text(d)))
    print(d, "sentences", n, "avg", avg, "p90", p90)

print("\n=== MARKERS ===")
patterns = {
  "retrospective_I": r"\b(?:I (?:remember|recall|did not know|didn't know|would later|was to learn|later)|looking back|years later|now I know|I have since)\b",
  "reader_address": r"\b(?:you|your)\b",
  "free_indirect_q": r"(?<![A-Za-z])(?:Why|How|What|Where|Who)\b[^.!?]{0,80}\?",
  "italics_or_caps": r"\b[A-Z]{3,}\b",
  "one_word_para": r"(?m)^[A-Za-zÀ-ÖØ-öø-ÿ'-]{1,20}\s*$",
  "short_para_under_8": r"(?m)^(?:[^\n]{1,60})\n",
}
for d in DIRS:
    t = text(d)
    para = [p.strip() for p in t.splitlines() if p.strip()]
    print(d, "paras", len(para), "one_word_paras", sum(1 for p in para if len(re.findall(r"\S+", p)) == 1),
          "paras<=5w", sum(1 for p in para if len(re.findall(r"\S+", p)) <= 5),
          "retro_markers", count(patterns["retrospective_I"], t),
          "caps", count(r"\b[A-Z]{3,}\b", t))

print("\n=== PT REGIONAL / NORMATIVE MARKERS ===")
for d in ["lonesome_pt","farseer1_pt","farseer2_pt","sun1_pt"]:
    t = text(d)
    markers = {
      "a_minha": count(r"\ba minha\b", t),
      "minha": count(r"\bminha\b", t),
      "tu": count(r"\btu\b", t),
      "voce": count(r"\bvoc[êe]\b", t),
      "a_gente": count(r"\ba gente\b", t),
      "nos": count(r"\bn[óo]s\b", t),
      "gerund": count(r"\b\w+ndo\b", t),
      "a_inf": count(r"\b(?:est[áa]|estava|est[ãa]o|andava|ficou|come[çc]ou)\s+\w+ndo\b", t),
      "pra": count(r"\bpr[ao]\b", t),
      "para": count(r"\bpara\b", t),
      "enclisis": count(r"\b\w+(?:-se|-me|-lhe|-lhes|-nos|-vos|-o|-a|-os|-as|-lo|-la|-los|-las)\b", t),
      "mesoclisis": count(r"\b\w+-(?:se|me|lhe|nos|vos)-?(?:ia|á|á|ei|emos|iam)\b", t),
      "ora": count(r"\bOra\b", t),
      "com certeza": count(r"\bcom certeza\b", t),
      "de fato": count(r"\bde fato\b", t),
      "realmente": count(r"\brealmente\b", t),
    }
    print(d, markers)

print("\n=== EN CONTRACTIONS / DIALECT ===")
for d in ["lonesome_en","farseer1_en","farseer2_en","sun2_en","sun3_en"]:
    t = text(d)
    print(d, "ain't", count(r"\bain['’]t\b", t), "nonstandard_you_was", count(r"\byou was\b", t),
          "gonna", count(r"\bgonna\b", t), "git", count(r"\bgit\b", t),
          "tis", count(r"\b(?:'|’)tis\b", t), "nowt", count(r"\bnowt\b", t))
