---
name: EPUB Quality
description: Validate and repair translated EPUBs in this repository, including OPF/NCX metadata, TOC labels, EPUBCheck, reader repair, dropcaps and Kindle export. Use after a translation finishes, when a book is stuck in needs_review, or when an EPUB opens with wrong metadata or chapter labels.
---

# EPUB Quality

A translated EPUB is not done because the translation process exited. It is done
when the package is valid and the reader sees the right title, series, chapter
labels and text.

## Non-negotiables

- **Never rewrite literary text to fix metadata.** Metadata work is metadata
  work; if the prose is wrong, that is a separate editorial pass.
- Keep a backup of the original EPUB before any repair.
- Run EPUBCheck after every change to the OPF, NCX, spine or TOC.
- Explain every remaining warning; zero errors is the gate.

## Validation

```bash
python -m src.literary.cli validate epub \
  --source "<source.epub>" --target "<translated.epub>" --language pt-BR
```

EPUBCheck is the hard gate. The repository helper is
`src.literary.queue_runner._epubcheck`; it runs the official `epubcheck.jar` in a
throwaway JRE container. For a manual run:

```bash
docker run --rm \
  -v "<repo>/tools/epubcheck:/epubcheck:ro" \
  -v "<dir-with-epub>:/books:ro" \
  eclipse-temurin:17-jre java -jar /epubcheck/epubcheck.jar \
  "/books/<file>.epub"
```

The path passed to the container must be absolute; a relative directory makes
Docker create an empty mount and EPUBCheck reports "File not found".

## OPF rules

- An EPUB2 package (`version="2.0"`) uses `dc:` elements and `opf:meta
  name/content`. It must **not** contain EPUB3 `property`/`refines`
  attributes.
- An EPUB3 package uses `meta property` and `meta refines`; do not mix the
  two dialects.
- `package unique-identifier` must point to an existing `dc:identifier` id.
- The NCX `<meta name="dtb:uid">` must match the OPF identifier.
- Remove duplicate `<meta name="cover">` entries.
- A translated EPUB may gain one attribution page; a spine gain larger than
  that is a warning worth investigating.
- Metadata translation must not change the package version or insert EPUB3
  metadata into an EPUB2 file.

## TOC rules

- Chapter labels must be chapter labels. A TOC where every entry is the book
  title is broken even if EPUBCheck passes.
- Use the source `toc.ncx` order and `content src` to map labels. Translate
  "Chapter I" -> "Capítulo I"; preserve front matter and attribution entries.
- Fix obvious roman-numeral typos (`Xll` -> `XII`) but do not invent chapter
  titles that are not in the source.
- The NCX `docTitle` should be the translated book title, not the source title.

## Reader repair and Kindle export

The Sun Eater path runs a reader repair after `fixed-v2`: join chunk seams,
normalize dialogue, and re-run validation/EPUBCheck before accepting the
repaired file. Do not skip it for Sun Eater.

```bash
python -m src.literary.cli queue approve --book-id <id> --job-id <id>
python -m src.literary.cli queue export-kindle
```

`queue approve` records `reviewed_at`; without it the Kindle export skips the
book as "not reviewed". The export embeds series, index, language, translator
role and tags in the OPF.

## Fool's Errand reference case

The repaired book had:

- EPUB3 `collection`/`role` meta inside an EPUB2 package;
- duplicate cover meta;
- `unique-identifier="uuid_id"` with no `dc:identifier id="uuid_id"`;
- NCX `dtb:uid` different from the OPF identifier;
- every TOC label replaced by the book title.

The repair kept the prose untouched, changed the package identifier to the
existing `kre-calibre-uuid`, converted the role to `opf:role="trl"`, removed the
duplicate cover, aligned the NCX uid, and restored `Capítulo I…XXIX`. EPUBCheck
then reported 0/0/0.

## Checklist

1. Backup the EPUB.
2. Inspect `content.opf` and `toc.ncx` from the zip.
3. Check package version vs metadata dialect.
4. Check `unique-identifier` and NCX uid.
5. Check TOC labels against the source TOC.
6. Check spine/document count; explain any extra.
7. Run EPUBCheck 0/0/0.
8. Run `validate epub`; explain warnings.
9. Open the result in the reader and check the TOC, title and first/last
   paragraphs.
10. Approve and export to Kindle.
