"""
Tests for glossary gender support (issue #250).

The feature exists because a source language that does not mark gender —
Chinese, Japanese, Korean — lets a model default every character to "he".
The load-bearing behavior is therefore NOT that a gender renders nicely, but
that it reaches the prompt for a chunk in which the character is never named:
that chunk is precisely where the model would otherwise guess.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.core.glossary.cli_loader import load_glossary_from_file
from src.core.glossary.injector import build_cast_block, build_glossary_block
from src.core.glossary.models import GlossaryTerm, normalize_gender
from src.core.glossary.ner import parse_ner_response
from src.core.glossary.store import GlossaryStore
from src.core.translator import _build_chunk_glossary_block


@pytest.fixture
def store():
    db = os.path.join(
        tempfile.gettempdir(),
        f"glossary_gender_test_{os.getpid()}_{id(object())}.db",
    )
    if os.path.exists(db):
        os.remove(db)
    s = GlossaryStore(db_path=db)
    try:
        yield s
    finally:
        s.close()
        try:
            os.remove(db)
        except OSError:
            pass


class TestNormalizeGender:
    """Only male/female survive; everything else means 'no information'."""

    @pytest.mark.parametrize("raw,expected", [
        ("male", "male"),
        ("MALE", "male"),
        ("  Male  ", "male"),
        ("m", "male"),
        ("man", "male"),
        ("masculine", "male"),
        ("female", "female"),
        ("F", "female"),
        ("woman", "female"),
        ("feminine", "female"),
    ])
    def test_recognized_values(self, raw, expected):
        assert normalize_gender(raw) == expected

    @pytest.mark.parametrize("raw", [
        None, "", "   ", "unknown", "n/a", "other", "nonbinary", "?", "attack helicopter",
    ])
    def test_unrecognized_values_become_none(self, raw):
        """'unknown' is not stored: it carries nothing for the prompt."""
        assert normalize_gender(raw) is None

    def test_term_normalizes_on_construction(self):
        assert GlossaryTerm("李凡", "Li Fan", "character", "MALE").gender == "male"
        assert GlossaryTerm("沈青", "Shen Qing", "character", "unknown").gender is None


class TestCastBlock:
    """The cast block is the part that is NOT chunk-filtered."""

    def test_no_metadata_yields_nothing(self):
        block, capped = build_cast_block({"李凡": "Li Fan"})
        assert block == ""
        assert capped is False

    def test_glossary_without_any_gender_yields_nothing(self):
        """Guarantees byte-identical prompts for every pre-existing glossary."""
        block, capped = build_cast_block(
            {"李凡": "Li Fan", "青玄宗": "Qingxuan Sect"},
            term_metadata={
                "李凡": {"category": "character"},
                "青玄宗": {"category": "organization"},
            },
        )
        assert block == ""
        assert capped is False

    def test_lists_only_gendered_entries(self):
        block, _ = build_cast_block(
            {"林月": "Lin Yue", "李凡": "Li Fan", "青玄宗": "Qingxuan Sect"},
            term_metadata={
                "林月": {"category": "character", "gender": "female"},
                "李凡": {"category": "character", "gender": "male"},
                "青玄宗": {"category": "organization"},
            },
        )
        assert "林月 (Lin Yue) — female" in block
        assert "李凡 (Li Fan) — male" in block
        assert "Qingxuan Sect" not in block

    def test_instructs_against_masculine_default(self):
        """The bug is a masculine default, so the block must name it."""
        block, _ = build_cast_block(
            {"林月": "Lin Yue"},
            term_metadata={"林月": {"gender": "female"}},
        )
        assert "CAST" in block
        assert "MANDATORY" in block
        assert "masculine" in block.lower()

    def test_uses_first_alternative_as_canonical_form(self):
        """Declined variants stay in the glossary block, not in the cast list."""
        block, _ = build_cast_block(
            {"Москва|Москве|Москвы": "Moscou"},
            term_metadata={"Москва|Москве|Москвы": {"gender": "female"}},
        )
        assert "Москва (Moscou) — female" in block
        assert "Москве" not in block

    def test_identical_source_and_target_is_not_duplicated(self):
        block, _ = build_cast_block(
            {"Anna": "Anna"},
            term_metadata={"Anna": {"gender": "female"}},
        )
        assert "  - Anna — female" in block
        assert "Anna (Anna)" not in block

    def test_cap_truncates_and_reports(self):
        terms = {f"C{i}": f"Char {i}" for i in range(10)}
        metadata = {f"C{i}": {"gender": "female"} for i in range(10)}
        block, capped = build_cast_block(terms, metadata, max_entries=4)
        assert capped is True
        assert block.count(" — female") == 4

    def test_block_is_stable_across_calls(self):
        """A cast that reordered per chunk would break prompt caching and could
        flip a character's gender mid-book."""
        terms = {"林月": "Lin Yue", "李凡": "Li Fan"}
        metadata = {"林月": {"gender": "female"}, "李凡": {"gender": "male"}}
        first, _ = build_cast_block(terms, metadata)
        second, _ = build_cast_block(terms, metadata)
        assert first == second


class TestGlossaryBlockGenderHint:
    def test_gender_appended_to_bracketed_hint(self):
        block = build_glossary_block(
            {"林月": "Lin Yue"},
            term_metadata={"林月": {"category": "character", "gender": "female"}},
        )
        assert "林月 -> Lin Yue  [character, female]" in block

    def test_gender_alone_renders_without_category(self):
        block = build_glossary_block(
            {"林月": "Lin Yue"},
            term_metadata={"林月": {"gender": "female"}},
        )
        assert "林月 -> Lin Yue  [female]" in block

    def test_unrecognized_gender_is_dropped_from_hint(self):
        block = build_glossary_block(
            {"沈青": "Shen Qing"},
            term_metadata={"沈青": {"category": "character", "gender": "unknown"}},
        )
        assert "沈青 -> Shen Qing  [character]" in block


class TestChunkPromptSection:
    """End-to-end at the point where the prompt section is assembled."""

    PROMPT_OPTIONS = {
        "glossary_terms": {"林月": "Lin Yue", "李凡": "Li Fan"},
        "glossary_term_metadata": {
            "林月": {"category": "character", "gender": "female"},
            "李凡": {"category": "character", "gender": "male"},
        },
    }

    def test_gender_reaches_a_chunk_that_names_nobody(self):
        """The issue #250 regression test.

        This Chinese chunk omits the subject entirely — no glossary term
        matches it — yet it is exactly the passage where a model invents "he".
        """
        section = _build_chunk_glossary_block("她低下头，没有回答。", self.PROMPT_OPTIONS)
        assert "CAST" in section
        assert "Lin Yue) — female" in section
        # No term matched, so the glossary block itself must stay absent.
        assert "GLOSSARY - REQUIRED TRANSLATIONS" not in section

    def test_both_blocks_when_a_term_matches(self):
        section = _build_chunk_glossary_block("林月走了进来。", self.PROMPT_OPTIONS)
        assert "CAST" in section
        assert "GLOSSARY - REQUIRED TRANSLATIONS" in section
        assert section.index("CAST") < section.index("GLOSSARY - REQUIRED")

    def test_genderless_glossary_is_unchanged(self):
        """No gender anywhere means no cast block and no behavior change."""
        options = {
            "glossary_terms": {"林月": "Lin Yue"},
            "glossary_term_metadata": {"林月": {"category": "character"}},
        }
        section = _build_chunk_glossary_block("林月走了进来。", options)
        assert "CAST" not in section
        assert "GLOSSARY - REQUIRED TRANSLATIONS" in section

    def test_no_match_and_no_gender_yields_empty(self):
        options = {
            "glossary_terms": {"林月": "Lin Yue"},
            "glossary_term_metadata": {"林月": {"category": "character"}},
        }
        assert _build_chunk_glossary_block("天气很好。", options) == ""

    def test_english_source_filters_cast_to_surrounding_context(self):
        """English marks pronouns explicitly, so unrelated universe entities stay out of CAST."""
        options = {
            "glossary_terms": {
                "Malta": "Malta",
                "Althea": "Althea",
                "Kennit": "Kennit",
            },
            "glossary_term_metadata": {
                "Malta": {"category": "character", "gender": "female"},
                "Althea": {"category": "character", "gender": "female"},
                "Kennit": {"category": "character", "gender": "male"},
            },
        }
        section = _build_chunk_glossary_block(
            "She asked Malta to wait on deck.",
            options,
            source_language="English",
            context_text="Althea stood by the rail.",
        )
        # Malta is already in the chunk glossary with [character, female], so not repeated in CAST.
        assert "Malta -> Malta  [character, female]" in section
        # Althea appeared only in surrounding context, so she stays in CAST for pronoun continuity.
        assert "  - Althea — female" in section
        # Kennit appeared in neither the chunk nor surrounding context.
        assert "Kennit" not in section
        assert "Malta — female" not in section



class TestStoreGender:
    def test_roundtrip(self, store):
        g = store.create_glossary("g", "Chinese", "English")
        store.bulk_add_terms(g.id, [
            GlossaryTerm("林月", "Lin Yue", "character", "female"),
            GlossaryTerm("李凡", "Li Fan", "character", "male"),
            GlossaryTerm("青玄宗", "Qingxuan Sect", "organization", None),
        ])
        terms = {t.source_term: t.gender for t in store.get_glossary(g.id).terms}
        assert terms == {"林月": "female", "李凡": "male", "青玄宗": None}

    def test_terms_metadata_omits_absent_fields(self, store):
        g = store.create_glossary("g")
        store.bulk_add_terms(g.id, [
            GlossaryTerm("林月", "Lin Yue", "character", "female"),
            GlossaryTerm("青玄宗", "Qingxuan Sect", None, None),
        ])
        assert store.get_glossary(g.id).terms_metadata == {
            "林月": {"category": "character", "gender": "female"},
        }

    def test_update_term_sets_and_clears(self, store):
        g = store.create_glossary("g")
        term = store.add_term(g.id, GlossaryTerm("林月", "Lin Yue", "character"))
        assert store.update_term(term.id, gender="female").gender == "female"
        assert store.update_term(term.id, gender="").gender is None

    def test_update_term_without_gender_leaves_it_alone(self, store):
        g = store.create_glossary("g")
        term = store.add_term(g.id, GlossaryTerm("林月", "Lin Yue", "character", "female"))
        updated = store.update_term(term.id, translated_term="Lin Yueh")
        assert updated.translated_term == "Lin Yueh"
        assert updated.gender == "female"

    def test_bulk_set_gender(self, store):
        g = store.create_glossary("g")
        store.bulk_add_terms(g.id, [
            GlossaryTerm("A", "A"),
            GlossaryTerm("B", "B"),
        ])
        ids = [t.id for t in store.get_glossary(g.id).terms]
        assert store.bulk_set_gender(g.id, ids, "female") == 2
        assert all(t.gender == "female" for t in store.get_glossary(g.id).terms)
        assert store.bulk_set_gender(g.id, ids, "unknown") == 2
        assert all(t.gender is None for t in store.get_glossary(g.id).terms)

    def test_duplicate_glossary_carries_gender(self, store):
        g = store.create_glossary("g")
        store.add_term(g.id, GlossaryTerm("林月", "Lin Yue", "character", "female"))
        copy = store.duplicate_glossary(g.id)
        assert copy.terms[0].gender == "female"

    def test_bulk_replace_carries_gender(self, store):
        g = store.create_glossary("g")
        store.bulk_replace_terms(g.id, [
            GlossaryTerm("林月", "Lin Yue", "character", "female"),
        ])
        assert store.get_glossary(g.id).terms[0].gender == "female"

    def test_migration_adds_column_to_a_pre_gender_database(self):
        """A database created before this field must open, not crash."""
        import sqlite3

        db = os.path.join(
            tempfile.gettempdir(),
            f"glossary_legacy_{os.getpid()}_{id(object())}.db",
        )
        if os.path.exists(db):
            os.remove(db)
        conn = sqlite3.connect(db)
        conn.executescript("""
            CREATE TABLE glossaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                source_language TEXT NOT NULL DEFAULT '',
                target_language TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE glossary_terms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                glossary_id INTEGER NOT NULL,
                source_term TEXT NOT NULL,
                translated_term TEXT NOT NULL,
                category TEXT,
                FOREIGN KEY (glossary_id) REFERENCES glossaries(id) ON DELETE CASCADE,
                UNIQUE (glossary_id, source_term)
            );
            INSERT INTO glossaries (name) VALUES ('legacy');
            INSERT INTO glossary_terms (glossary_id, source_term, translated_term, category)
                VALUES (1, '林月', 'Lin Yue', 'character');
        """)
        conn.commit()
        conn.close()

        s = GlossaryStore(db_path=db)
        try:
            glossary = s.get_glossary_by_name("legacy")
            assert glossary is not None
            assert glossary.terms[0].source_term == "林月"
            assert glossary.terms[0].gender is None
            # And the column is writable after the migration.
            assert s.update_term(glossary.terms[0].id, gender="female").gender == "female"
        finally:
            s.close()
            try:
                os.remove(db)
            except OSError:
                pass


class TestNerGenderParsing:
    def test_gender_is_parsed(self):
        raw = """<NER_JSON>
        [
          {"source": "林月", "target": "Lin Yue", "category": "character", "gender": "female"},
          {"source": "李凡", "target": "Li Fan", "category": "character", "gender": "male"}
        ]
        </NER_JSON>"""
        candidates, _ = parse_ner_response(raw)
        assert {c["source"]: c["gender"] for c in candidates} == {
            "林月": "female", "李凡": "male",
        }

    def test_unknown_gender_becomes_empty_string(self):
        raw = ('<NER_JSON>[{"source": "沈青", "target": "Shen Qing", '
               '"category": "character", "gender": "unknown"}]</NER_JSON>')
        candidates, _ = parse_ner_response(raw)
        assert candidates[0]["gender"] == ""

    def test_bogus_gender_is_discarded_not_stored(self):
        """A confidently wrong gender would ship silently; a blank is reviewed."""
        raw = ('<NER_JSON>[{"source": "X", "target": "X", '
               '"category": "character", "gender": "probably male?"}]</NER_JSON>')
        candidates, _ = parse_ner_response(raw)
        assert candidates[0]["gender"] == ""

    def test_missing_gender_key_is_tolerated(self):
        """Older models and smaller ones will omit the field entirely."""
        raw = '<NER_JSON>[{"source": "林月", "target": "Lin Yue", "category": "character"}]</NER_JSON>'
        candidates, _ = parse_ner_response(raw)
        assert candidates[0]["gender"] == ""


class TestCliLoaderGender:
    def test_json_gender(self, tmp_path):
        import json

        p = tmp_path / "g.json"
        p.write_text(json.dumps({"terms": [
            {"source": "林月", "target": "Lin Yue", "category": "character", "gender": "female"},
            {"source": "青玄宗", "target": "Qingxuan Sect", "category": "organization"},
        ]}), encoding="utf-8")
        terms, metadata = load_glossary_from_file(str(p))
        assert terms == {"林月": "Lin Yue", "青玄宗": "Qingxuan Sect"}
        assert metadata["林月"] == {"category": "character", "gender": "female"}
        assert metadata["青玄宗"] == {"category": "organization"}

    def test_csv_gender_column(self, tmp_path):
        p = tmp_path / "g.csv"
        p.write_text(
            "source,target,category,gender\n"
            "林月,Lin Yue,character,female\n"
            "李凡,Li Fan,character,M\n"
            "青玄宗,Qingxuan Sect,organization,\n",
            encoding="utf-8",
        )
        _terms, metadata = load_glossary_from_file(str(p))
        assert metadata["林月"]["gender"] == "female"
        assert metadata["李凡"]["gender"] == "male"
        assert "gender" not in metadata["青玄宗"]

    def test_csv_without_gender_column_still_loads(self, tmp_path):
        p = tmp_path / "g.csv"
        p.write_text("source,target,category\n林月,Lin Yue,character\n", encoding="utf-8")
        _terms, metadata = load_glossary_from_file(str(p))
        assert metadata["林月"] == {"category": "character"}
