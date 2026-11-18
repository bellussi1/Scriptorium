import hashlib
import zipfile
from pathlib import Path

from src.literary.source_prep import (
    inspect_source_epub,
    prepare_source_epub,
    prepared_source_path,
)


def _write_epub(path: Path, entries: dict[str, bytes | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        if "mimetype" in entries:
            data = entries["mimetype"]
            zf.writestr(
                "mimetype",
                data if isinstance(data, bytes) else data.encode("utf-8"),
                compress_type=zipfile.ZIP_STORED,
            )
        for name, data in entries.items():
            if name == "mimetype":
                continue
            zf.writestr(
                name,
                data if isinstance(data, bytes) else data.encode("utf-8"),
                compress_type=zipfile.ZIP_DEFLATED,
            )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_clean_epub_is_not_rewritten(tmp_path: Path):
    src = tmp_path / "clean.epub"
    _write_epub(
        src,
        {
            "mimetype": "application/epub+zip",
            "content.opf": (
                '<package unique-identifier="uid" version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">'
                '<metadata><dc:identifier id="uid">abc-123</dc:identifier></metadata>'
                '<manifest><item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
                '<item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/></manifest>'
                '<spine toc="ncx"><itemref idref="c1"/><itemref idref="c2"/></spine></package>'
            ),
            "toc.ncx": (
                "<ncx><docTitle><text>Clean</text></docTitle><navMap>"
                '<navPoint id="n1" playOrder="1"><navLabel><text>1</text></navLabel><content src="ch1.xhtml"/></navPoint>'
                '<navPoint id="n2" playOrder="2"><navLabel><text>2</text></navLabel><content src="ch2.xhtml"/></navPoint>'
                '<navPoint id="n3" playOrder="3"><navLabel><text>3</text></navLabel><content src="ch2.xhtml#end"/></navPoint>'
                "</navMap></ncx>"
            ),
            "ch1.xhtml": '<html><head><title>Clean</title></head><body><p>Hello world.</p><img src="a.jpg" alt="map"/></body></html>',
            "ch2.xhtml": '<html><head><title>Clean</title></head><body><p id="end">Bye.</p></body></html>',
        },
    )

    prepared_dir = tmp_path / "prepared"
    res = prepare_source_epub("Clean Book", src, prepared_dir=prepared_dir)
    assert res["prepared"] is False
    assert res["reason"] == "clean"
    assert res["path"] == str(src)
    assert not prepared_source_path("Clean Book", prepared_dir).exists()


def test_pdftohtml_source_prep_sanitizes_without_modifying_original(tmp_path: Path):
    src = tmp_path / "Ship of Magic.epub"
    header_repeats = "\n".join(
        f'<p class="calibre1">Hobb, Robin - Ship of Magic</p>\n'
        f'<p class="calibre1">Sentence end {i}.</p>'
        for i in range(12)
    )
    doc0 = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" lang="" xml:lang=""><head>'
        '<title>file:///C|/Books/Ship.html</title>'
        '<meta name="generator" content="pdftohtml 0.36"/>'
        '</head><body>'
        '<p class="calibre1"><img src="cover.jpg" class="c2"/></p>'
        '<p class="calibre1"><a name="1"></a><a name="anchor_ok"></a>First line.</p>'
        '<p class="calibre1"><b class="b1">CHAPTER ONE - OF PRIESTS AND </b></p>'
        '<p class="calibre1"><b class="b1">PIRATES</b></p>'
        '<p class="calibre1">In return file:///C|/Documents/Ship.html (81 of 1064)12/11/2005</p>'
        '<p class="calibre1">Hobb, Robin - Ship of Magic</p>'
        '<p class="calibre1"></p>'
        '<p class="calibre1">for the Satrap granting them this, they kept peace.</p>'
        '<p class="calibre1">Complete sentence. file:///C|/Documents/Ship.html (82 of 1064)12/11/2005</p>'
        '<p class="calibre1">Hobb, Robin - Ship of Magic</p>'
        '<p class="calibre1">New paragraph after break.</p>'
        '<p class="calibre1"><b class="b1">CHAPTER TWO - LIVESHIPS</b></p>'
        '<p class="calibre1"><b class="b1">CHAPTER THREE - </b></p>'
        '<p class="calibre1"><b class="b1">CONSEQUENCES AND REFLECTIONS</b></p>'
        '<p class="calibre1">More text.</p>'
        + header_repeats
        + "</body></html>"
    )
    doc_outline = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head><body>'
        '<p class="calibre1"><h1 id="calibre_pb_0">Document Outline</h1>'
        '<ul><li>Local Disk <ul><li><a href="index_split_000.html#1">Ship</a></li></ul></li></ul></p>'
        "</body></html>"
    )
    opf = (
        '<opf:package xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf" '
        'unique-identifier="uuid_id" version="2.0">'
        '<opf:metadata>'
        '<dc:identifier id="isbn">0553575635</dc:identifier>'
        '<dc:identifier id="kre-calibre-uuid" opf:scheme="calibre">fffe-1111</dc:identifier>'
        '<opf:meta id="col" property="belongs-to-collection">Realm</opf:meta>'
        '<opf:meta refines="#col" property="group-position">4</opf:meta>'
        '</opf:metadata>'
        '<opf:manifest>'
        '<opf:item href="index_split_000.html" id="id12" media-type="application/xhtml+xml"/>'
        '<opf:item href="index_split_001.html" id="id11" media-type="application/xhtml+xml"/>'
        '<opf:item href="toc.ncx" id="ncx" media-type="application/x-dtbncx+xml"/>'
        '</opf:manifest>'
        '<opf:spine toc="ncx"><opf:itemref idref="id12"/><opf:itemref idref="id11"/></opf:spine>'
        '<opf:guide />'
        "</opf:package>"
    )
    ncx = (
        '<ncx><head><meta content="old-uuid-000" name="dtb:uid"/></head>'
        '<docTitle><text>file:///C|/Books/Ship.txt</text></docTitle><navMap>'
        '<navPoint id="np0" playOrder="0"><navLabel><text>file:///C|/</text></navLabel>'
        '<content src="index_split_000.html#1"/></navPoint>'
        "</navMap></ncx>"
    )
    _write_epub(
        src,
        {
            "mimetype": "application/epub+zip",
            "content.opf": opf,
            "toc.ncx": ncx,
            "index_split_000.html": doc0,
            "index_split_001.html": doc_outline,
        },
    )
    before_sha = _sha256(src)
    prepared_dir = tmp_path / "prepared"

    res = prepare_source_epub("Ship of Magic", src, prepared_dir=prepared_dir)
    assert res["prepared"] is True
    assert res["cached"] is False
    assert _sha256(src) == before_sha

    dest = Path(res["path"])
    assert dest == prepared_dir / "ship-of-magic.epub"

    with zipfile.ZipFile(dest) as zf:
        names = zf.namelist()
        assert names[0] == "mimetype"
        assert "index_split_001.html" not in names
        cleaned_doc = zf.read("index_split_000.html").decode("utf-8")
        assert 'lang="en" xml:lang="en"' in cleaned_doc
        assert "<title>Ship of Magic</title>" in cleaned_doc
        assert "file:///" not in cleaned_doc
        assert "Hobb, Robin - Ship of Magic" not in cleaned_doc
        assert 'alt=""' in cleaned_doc
        assert 'name="1"' not in cleaned_doc
        assert 'id="anchor_ok"' in cleaned_doc
        assert "CHAPTER ONE - OF PRIESTS AND PIRATES" in cleaned_doc
        assert "CHAPTER THREE - CONSEQUENCES AND REFLECTIONS" in cleaned_doc
        assert "In return for the Satrap granting them this, they kept peace." in cleaned_doc
        assert "Complete sentence.</p>" in cleaned_doc
        assert "<p class=\"calibre1\">New paragraph after break.</p>" in cleaned_doc

        cleaned_opf = zf.read("content.opf").decode("utf-8")
        assert 'unique-identifier="kre-calibre-uuid"' in cleaned_opf
        assert "belongs-to-collection" not in cleaned_opf
        assert "<opf:guide" not in cleaned_opf
        assert "index_split_001.html" not in cleaned_opf
        assert 'idref="id11"' not in cleaned_opf

        cleaned_ncx = zf.read("toc.ncx").decode("utf-8")
        assert 'content="fffe-1111"' in cleaned_ncx
        assert "<text>Ship of Magic</text>" in cleaned_ncx
        assert 'playOrder="0"' not in cleaned_ncx
        assert 'playOrder="1"' in cleaned_ncx
        assert 'playOrder="2"' in cleaned_ncx
        assert "CHAPTER ONE - OF PRIESTS AND PIRATES" in cleaned_ncx
        assert "CHAPTER TWO - LIVESHIPS" in cleaned_ncx
        assert "CHAPTER THREE - CONSEQUENCES AND REFLECTIONS" in cleaned_ncx
        assert "#ch_001" in cleaned_ncx
        assert "#ch_002" in cleaned_ncx
        assert "#ch_003" in cleaned_ncx

    post = inspect_source_epub(dest)
    assert post["needs_prep"] is False


def test_toc_r1_rebuilds_ncx_with_relative_paths(tmp_path: Path):
    src = tmp_path / "The Golden Fool.epub"
    _write_epub(
        src,
        {
            "mimetype": "application/epub+zip",
            "content.opf": (
                '<package unique-identifier="uid" version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">'
                '<metadata><dc:identifier id="uid">gf-1</dc:identifier></metadata>'
                '<manifest>'
                '<item id="toc" href="OEBPS/Text/book_toc_r1.htm" media-type="application/xhtml+xml"/>'
                '<item id="prl" href="OEBPS/Text/book_prl_r1.htm" media-type="application/xhtml+xml"/>'
                '<item id="c01" href="OEBPS/Text/book_c01_r1.htm" media-type="application/xhtml+xml"/>'
                '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
                '</manifest>'
                '<spine toc="ncx"><itemref idref="toc"/><itemref idref="prl"/><itemref idref="c01"/></spine>'
                "</package>"
            ),
            "toc.ncx": (
                "<ncx><docTitle><text>The Golden Fool</text></docTitle><navMap>"
                '<navPoint id="np1" playOrder="1"><navLabel><text>Start</text></navLabel>'
                '<content src="OEBPS/Text/book_toc_r1.htm"/></navPoint>'
                "</navMap></ncx>"
            ),
            "OEBPS/Text/book_toc_r1.htm": (
                '<html><body>'
                '<a href="../Text/book_prl_r1.htm#prologue">Prologue</a>'
                '<a href="../Text/book_c01_r1.htm#missing">Chapter 1</a>'
                "</body></html>"
            ),
            "OEBPS/Text/book_prl_r1.htm": '<html><body><h1 id="prologue">Prologue</h1></body></html>',
            "OEBPS/Text/book_c01_r1.htm": "<html><body><h1>Chapter 1</h1></body></html>",
        },
    )

    res = prepare_source_epub("The Golden Fool", src, prepared_dir=tmp_path / "prepared")
    assert res["prepared"] is True
    with zipfile.ZipFile(res["path"]) as zf:
        ncx = zf.read("toc.ncx").decode("utf-8")
        assert 'src="OEBPS/Text/book_prl_r1.htm#prologue"' in ncx
        assert 'src="OEBPS/Text/book_c01_r1.htm"' in ncx
        assert "#missing" not in ncx
        assert 'playOrder="2"' in ncx
