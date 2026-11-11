# Terminology decisions

This is the human-readable series bible. The machine-readable source of truth
is `literary-resources/christopher-ruocchio/sun-eater/` (the glossary and
worldbuilding files); the audit and the translation prompt read the compiled
JSON produced from it.

## Authority

1. The official Brazilian edition, when it exists, wins. For Sun Eater that is
   *Império do Silêncio* (Aleph, Calibre 436) for book 1; books 2-7 have no
   official PT edition yet, so their terms are editorial decisions recorded
   here.
2. A term is frozen in the glossary before a book starts. The model never
   chooses a form per occurrence.
3. Changing a frozen form requires a series-wide pass and a new glossary
   version; a local edit in one book is not allowed.

## Three tiers

- **Keep** opaque names, places, ships, invented species and in-world Latin or
  technical coinages. Examples: Hadrian, Valka, Emesh, Vorgossos, Cielcin
  (`cielcin` lowercase), Mericanii, Tavrosi, Imperium.
- **Naturalize** common nouns and titles that have a Portuguese form.
  Examples: Homunculus -> homúnculo, Scholiast -> escoliasta, Palatine ->
  palatino, Halfmortal -> Semimortal, animalcule -> animalculo.
- **Translate** descriptive epithets and transparent institutions whose meaning
  carries the narrative. Examples: The Painted Man -> O Homem Pintado, Red
  Company -> Companhia Vermelha, The Exalted -> Os Exaltados, Chantry ->
  Chantria, Sollan Empire -> Império Sollano.

## Frozen decisions (2026-11-11)

| Source | Target | Policy | Evidence |
| --- | --- | --- | --- |
| Imperium | Imperium | keep | Official edition: Imperium 32x, Império 107x. The proper name stays Latin; "império" is the common noun and "Império Sollano" the full name. |
| Quiet | Quieto | translate | Official edition uses "os Quietos" capitalized. Do not use the English word or the ordinary noun "silêncio". |
| Fugue | fuga | translate | Official edition uses lowercase "fuga". Keep "fuga criônica" for the cryonic state. |
| Homunculus | homúnculo | translate | Official edition uses lowercase "homúnculo". |
| Chantry | Chantria | translate | Official edition: Chantria 258x, Chantry 0x. Never keep the English word. |
| Sollan Empire | Império Sollano | translate | Official edition: Império Sollano 22x. |
| Cielcin | cielcin | transliterate | Official edition uses lowercase "cielcin" 335x. |
| datasphere | esfera de dados | translate | No official occurrence. Books 2-3 use "esfera de dados" consistently; freeze it for the series and forbid "datasphere" and "dataesfera" unless a series-wide pass changes it. |
| animalcule | animalculo | adapt | No official occurrence. Portuguese common noun; Howling Dark left one English occurrence. |
| knight-tribune | tribuna-cavaleira | translate | No official occurrence. Raine Smythe is a woman; keep the feminine compound. For a male holder use "tribuno-cavaleiro". |

## Known deviations in shipped books

- **Howling Dark** and **Demon in White** were translated before the Imperium
  freeze. They use "Império" for the polity (Howling Dark: 188 Império, 4
  Imperium). They are not retrofitted: "Império" vs "Imperium" is
  context-sensitive, and a mechanical pass would misclassify the common noun.
  Apply the freeze from the next book.
- Howling Dark has one `animalcule` left in English and one `TIVAMOS NOSSO
  CARON` typo, fixed manually to `TÍNHAMOS NOSSO CARONTE`. The next book uses
  `animalculo` from the start.

## Change process

1. Edit the YAML under `literary-resources/christopher-ruocchio/sun-eater/`.
2. Run `python -m src.literary.cli resources validate` and compile the glossary
   for the next book.
3. Record the decision in this file and in the term's `notes`,
   `source_reference`, `confidence` and `approved` fields.
4. Do not edit the glossary while a book is running: the final audit compares
   the snapshot from the start of the book with the current YAML and fails on
   any drift. Freeze before the run starts.
