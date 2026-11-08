"""Chapter-to-chapter continuity context for literary translation.

The benchmark corpus measures isolated excerpts. A novel needs the opposite:
the next chapter must remember the previous chapter's ending, the narrator's
person and gender, the established names and the forms of address. This module
builds a compact, deterministic block that can be injected into a refinement
prompt without another model call.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import CompiledResources


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> List[str]:
    return [part.strip() for part in _SENTENCE_RE.split(text or "") if part.strip()]


def extractive_summary(text: str, max_sentences: int = 4) -> str:
    """Keep the opening and closing sentences, which carry setup and turn."""
    sentences = split_sentences(text)
    if not sentences:
        return ""
    if len(sentences) <= max_sentences:
        return " ".join(sentences)
    first_count = max(1, max_sentences // 2)
    last_count = max(1, max_sentences - first_count)
    return " ".join(sentences[:first_count] + sentences[-last_count:])


def chapter_tail(text: str, max_chars: int = 1200) -> str:
    """Return the ending of a chapter, preserving the last sentences."""
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    tail = text[-max_chars:]
    # Start at a sentence boundary when one is available.
    match = re.search(r"(?<=[.!?])\s+", tail)
    if match and len(tail) - match.end() > max_chars // 2:
        tail = tail[match.end() :]
    return tail.strip()


@dataclass
class Character:
    name: str
    gender: str = ""
    aliases: List[str] = field(default_factory=list)
    forms_of_address: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "gender": self.gender,
            "aliases": list(self.aliases),
            "forms_of_address": self.forms_of_address,
            "notes": self.notes,
        }


def characters_from_compiled(compiled: Optional[CompiledResources]) -> List[Character]:
    """Derive the character sheet from glossary terms already curated."""
    if compiled is None:
        return []
    characters: Dict[str, Character] = {}
    for term in compiled.glossary.terms:
        if term.category != "character":
            continue
        key = term.source.casefold()
        current = characters.get(key)
        if current is None:
            current = Character(
                name=term.target or term.source,
                gender=term.gender,
                aliases=list(term.aliases),
                notes=term.notes,
            )
            characters[key] = current
        else:
            current.gender = current.gender or term.gender
            for alias in term.aliases:
                if alias not in current.aliases:
                    current.aliases.append(alias)
            current.notes = current.notes or term.notes
    return sorted(characters.values(), key=lambda item: item.name.casefold())


@dataclass
class ContinuityTracker:
    characters: List[Character] = field(default_factory=list)
    pov: str = ""
    notes: str = ""
    previous_summary: str = ""
    previous_tail: str = ""

    @classmethod
    def from_compiled(
        cls,
        compiled: Optional[CompiledResources],
        *,
        pov: str = "",
        notes: str = "",
    ) -> "ContinuityTracker":
        return cls(
            characters=characters_from_compiled(compiled),
            pov=pov,
            notes=notes,
        )

    def update(self, chapter_text: str) -> None:
        self.previous_summary = extractive_summary(chapter_text)
        self.previous_tail = chapter_tail(chapter_text)

    def block(self) -> str:
        return build_continuity_block(
            characters=self.characters,
            pov=self.pov,
            notes=self.notes,
            previous_summary=self.previous_summary,
            previous_tail=self.previous_tail,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "characters": [character.to_dict() for character in self.characters],
            "pov": self.pov,
            "notes": self.notes,
            "previous_summary": self.previous_summary,
            "previous_tail": self.previous_tail,
        }


def build_continuity_block(
    *,
    characters: Optional[List[Character]] = None,
    pov: str = "",
    notes: str = "",
    previous_summary: str = "",
    previous_tail: str = "",
) -> str:
    """Return a compact Markdown continuity block, or an empty string."""
    sections: List[str] = []
    if pov.strip():
        sections.append(f"### Point of view\n\n{pov.strip()}")
    if characters:
        lines = []
        for character in characters:
            detail = character.name
            if character.gender:
                detail += f" ({character.gender})"
            if character.aliases:
                detail += f"; aliases: {', '.join(character.aliases)}"
            if character.forms_of_address:
                detail += f"; address: {character.forms_of_address}"
            if character.notes:
                detail += f". {character.notes.strip()}"
            lines.append(f"- {detail}")
        sections.append("### Characters\n\n" + "\n".join(lines))
    if notes.strip():
        sections.append(f"### Continuity notes\n\n{notes.strip()}")
    if previous_summary.strip():
        sections.append(f"### Previous chapter\n\n{previous_summary.strip()}")
    if previous_tail.strip():
        sections.append(f"### End of previous chapter\n\n{previous_tail.strip()}")
    if not sections:
        return ""
    return "## Continuity\n\n" + "\n\n".join(sections) + "\n"
