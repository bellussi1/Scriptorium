"""Build a tiny 3-chapter EPUB for the destructive resume test."""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "data/tmp/destructive-test.epub")
OUT.parent.mkdir(parents=True, exist_ok=True)

CHAPTER = (
    "<html xmlns='http://www.w3.org/1999/xhtml'><head><title>{title}</title></head>"
    "<body><h1>{title}</h1>{body}</body></html>"
)
PARAGRAPH = (
    "<p>The lighthouse keeper wrote another line in the log, watching the cold "
    "sea break against the black rocks below the tower. The wind carried salt "
    "and the distant sound of a bell, and the keeper remembered the ships that "
    "never came home. Every night the light turned, and every night the keeper "
    "counted the waves until the horizon grew pale and the gulls returned.</p>"
)


def chapter(title: str, count: int) -> str:
    return CHAPTER.format(title=title, body=PARAGRAPH * count)


with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as archive:
    archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
    archive.writestr(
        "META-INF/container.xml",
        """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""",
    )
    archive.writestr(
        "OEBPS/content.opf",
        """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid" xml:lang="en">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="uid">urn:uuid:11111111-2222-3333-4444-555555555555</dc:identifier>
    <dc:title>Destructive Test Book</dc:title>
    <dc:language>en</dc:language>
    <meta property="dcterms:modified">2026-11-11T00:00:00Z</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch3" href="ch3.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="ch1"/><itemref idref="ch2"/><itemref idref="ch3"/></spine>
</package>""",
    )
    archive.writestr(
        "OEBPS/nav.xhtml",
        """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en">
<head><title>Contents</title></head>
<body><nav epub:type="toc"><ol>
<li><a href="ch1.xhtml">One</a></li><li><a href="ch2.xhtml">Two</a></li><li><a href="ch3.xhtml">Three</a></li>
</ol></nav></body></html>""",
    )
    for index, title in enumerate(("One", "Two", "Three"), start=1):
        archive.writestr(f"OEBPS/ch{index}.xhtml", chapter(title, 8))

print(OUT.resolve())
