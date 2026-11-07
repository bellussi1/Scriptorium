"""Validate every style profile and compile it through the resource tree.

Run from the repository root:
    python scripts/literary/validate_styles.py
"""
from pathlib import Path
import sys
import types
import yaml
import importlib.util

sys.path.insert(0, str(Path(".").resolve()))

# Load the lint module without importing src.core.__init__ (which pulls runtime deps).
import src  # safe: only __version__
core = types.ModuleType("src.core"); core.__path__ = []
style = types.ModuleType("src.core.style"); style.__path__ = []
dims = types.ModuleType("src.core.style.dimensions")
dims.ALLOWED_DIMENSIONS = (
    "register", "narrative_voice", "sentence_rhythm", "lexicon",
    "imagery", "dialogue", "punctuation", "formatting", "other",
)
sys.modules["src.core"] = core
sys.modules["src.core.style"] = style
sys.modules["src.core.style.dimensions"] = dims
spec = importlib.util.spec_from_file_location("src.core.style.lint", "src/core/style/lint.py")
lint_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lint_mod)
lint_instruction = lint_mod.lint_instruction

from src.literary.resources import load_tree, validate_tree, compile_for_book

ROOT = Path("literary-resources")
files = sorted(ROOT.rglob("style.yaml"))
print("FILES", len(files))
ok = True
for path in files:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    print("\n" + str(path))
    missing = [k for k in ("description", "mode", "context", "rules") if k not in data]
    if missing:
        ok = False
        print(" MISSING", missing)
    rules = data.get("rules") or []
    print(" mode:", data.get("mode"), "| context:", len(data.get("context", "")), "chars | rules:", len(rules))
    if data.get("mode") != "source":
        ok = False; print(" BAD MODE")
    if not 6 <= len(rules) <= 10:
        ok = False; print(" BAD RULE COUNT")
    if len(data.get("context", "")) > 600:
        ok = False; print(" CONTEXT TOO LONG")
    dims_list = [r.get("dimension") for r in rules]
    dup = sorted({d for d in dims_list if dims_list.count(d) > 1})
    if dup:
        ok = False; print(" DUPLICATE DIMS", dup)
    for i, rule in enumerate(rules, 1):
        if rule.get("dimension") not in dims.ALLOWED_DIMENSIONS:
            ok = False; print(" BAD DIM", i, rule.get("dimension"))
        text = rule.get("instruction", "")
        if len(text) > 500:
            ok = False; print(" INSTRUCTION TOO LONG", i)
        flags = lint_instruction(text)
        if flags:
            ok = False
            print(" LINT", i, rule.get("dimension"), flags)
            print("   ", text)
    print(" notes:", data.get("notes", "(none)"))

tree = load_tree(ROOT)
print("\nTREE files:", len(tree.files))
issues = validate_tree(tree)
for issue in issues:
    print("ISSUE", issue.code, issue.severity, issue.message, issue.location)

for args in [
    ("larry-mcmurtry", "lonesome-dove", "", ""),
    ("robin-hobb", "realm-of-the-elderlings", "", ""),
    ("robin-hobb", "realm-of-the-elderlings", "farseer", ""),
    ("robin-hobb", "realm-of-the-elderlings", "liveship-traders", ""),
    ("robin-hobb", "realm-of-the-elderlings", "tawny-man", ""),
    ("robin-hobb", "realm-of-the-elderlings", "rain-wild-chronicles", ""),
    ("robin-hobb", "realm-of-the-elderlings", "fitz-and-the-fool", ""),
    ("christopher-ruocchio", "sun-eater", "", ""),
]:
    compiled = compile_for_book(tree, *args)
    print("COMPILED", args, "->", len(compiled.style.get("rules", [])), [r.get("dimension") for r in compiled.style.get("rules", [])])

print("\nOK" if ok else "\nFAILED")
