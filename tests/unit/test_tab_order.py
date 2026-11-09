"""The primary tab strip has a fixed, intentional order."""
from __future__ import annotations

import re
from pathlib import Path

TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "web"
    / "templates"
    / "translation_interface.html"
)


def test_top_tabs_follow_the_daily_workflow_order():
    html = TEMPLATE.read_text(encoding="utf-8")
    nav = html.split('id="topTabNav"', 1)[1].split("</div>", 1)[0]
    order = re.findall(r'data-tab="([^"]+)"', nav)
    assert order == [
        "translate",
        "queue",
        "files",
        "glossaries",
        "styles",
        "sample",
        "settings",
    ]
