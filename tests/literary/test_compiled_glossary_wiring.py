from pathlib import Path

from src.core.glossary.cli_loader import load_glossary_from_file
from src.core.translator import _build_chunk_glossary_block
from src.literary.resources import compile_for_book, load_tree, write_glossary_json


def test_compiled_glossary_reaches_upstream_prompt_with_forbidden(tmp_path: Path):
    root = tmp_path / "literary-resources"
    folder = root / "robin-hobb" / "realm-of-the-elderlings"
    folder.mkdir(parents=True)
    (folder / "glossary.yaml").write_text(
        """
terms:
  - source: FitzChivalry Farseer
    target: FitzChivalry Farseer
    category: character
    aliases: [Fitz]
    forbidden: ["Fitz Chivalry"]
    gender: male
    confidence: confirmed
""",
        encoding="utf-8",
    )
    compiled = compile_for_book(load_tree(root), "robin-hobb", "realm-of-the-elderlings")
    out = tmp_path / "glossary.json"
    write_glossary_json(compiled, str(out))
    terms, metadata = load_glossary_from_file(str(out))
    block = _build_chunk_glossary_block(
        "Fitz walked into the room.",
        {"glossary_terms": terms, "glossary_term_metadata": metadata},
    )
    assert "FitzChivalry Farseer" in block
    assert "forbidden" in block.lower()
    assert "Fitz Chivalry" in block
