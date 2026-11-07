# Literary resources

This directory holds the persistent editorial layer for long-form translation.
It is deliberately plain YAML so it can be reviewed in a diff and edited by hand.

## Layout

```
global/                                  # conventions shared by every project
<author>/<universe>/                     # author and universe/saga
  series.yaml                            # book order, PT titles, status
  glossary.yaml                          # non-character terms
  characters.yaml                        # character terms and gender
  worldbuilding.yaml                     # places, factions, technologies
  style.yaml                             # universe-level style base
  <subseries>/                            # optional subseries override
    style.yaml
    glossary.yaml
    <book>/                               # optional book override
      glossary.yaml
      style.yaml
```

Precedence is `global < author < universe < subseries < book`. A higher scope
overrides a target or a style field. Aliases and forbidden renderings are
merged, never silently dropped.

Only create a file when it carries information. An empty file is noise.

## Term fields

```yaml
source: "Original term"
target: "Preferred rendering"
category: character | location | organization | item | title | concept | other
scope: series
policy: translate | keep | adapt | transliterate | contextual
aliases: []
forbidden: []
gender: male | female
number: singular | plural
notes: "Why this choice; context; uncertainty"
source_reference: "Edition, ISBN or URL used to verify it"
confidence: confirmed | reviewed | provisional
first_appearance: book-slug
approved: true
```

`first_appearance` prevents a term introduced in book 3 from being injected
into book 1. The compiler also uses it for spoiler control.

## Evidence policy

1. Official Brazilian edition terminology, when verified in the actual text.
2. Author/editor documentation.
3. Official translations of related works.
4. Reliable secondary sources.
5. Community wikis, checked against a primary source.
6. Our own editorial decision, marked `confidence: provisional`.

Never label a fan translation as an official edition. Never invent an official
rendering. When a term is uncertain, leave `approved: false` and say what is
missing in `notes`.
