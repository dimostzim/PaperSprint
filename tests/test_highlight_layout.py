from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]


def css_rule(styles: str, selector: str) -> str:
    start = styles.index(f"{selector} {{")
    end = styles.index("}\n", start)
    return styles[start:end]


def test_highlight_navigation_stays_fixed_below_independently_scrolling_story():
    template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
    section = BeautifulSoup(template, "html.parser").select_one(".highlights-section")
    direct_children = [child for child in section.children if getattr(child, "name", None)]

    list_position = next(index for index, child in enumerate(direct_children) if child.get("id") == "highlight-list")
    navigation_position = next(index for index, child in enumerate(direct_children) if "highlight-navigation" in child.get("class", []))

    assert navigation_position > list_position
    assert "overflow: hidden" in css_rule(styles, ".library-panel")
    assert "display: flex" in css_rule(styles, ".highlights-section")
    assert "min-height: 0" in css_rule(styles, ".highlights-section")
    assert "overflow: hidden" in css_rule(styles, ".highlights-section")
    assert "flex: 1 1 auto" in css_rule(styles, ".highlight-list")
    assert "overflow-y: auto" in css_rule(styles, ".highlight-list")
    assert "flex: 0 0 auto" in css_rule(styles, ".highlight-navigation")
