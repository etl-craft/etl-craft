"""One theme-aware tile mark for the console, sign-in, offline catalog, favicon and new interface."""

from importlib.resources import files
from xml.etree import ElementTree

import pytest

pytestmark = pytest.mark.unit

# The tile's gradient ends and the glyph drawn on it, in each theme.
LIGHT = {"tile": ("#3a6cf7", "#1b44c4"), "glyph": "#ffffff", "page": ("#eef2f6", "#edf1f5")}
DARK = {"tile": ("#9dbaff", "#6d93f2"), "glyph": "#0c1426", "page": ("#151b23", "#0d1117")}


def luminance(value):
    channels = [int(value[n : n + 2], 16) / 255 for n in (1, 3, 5)]
    values = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
    return sum(v * w for v, w in zip(values, (0.2126, 0.7152, 0.0722), strict=True))


def contrast(first, second):
    a, b = luminance(first), luminance(second)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def test_the_page_mark_and_the_favicon_draw_the_same_tile_and_glyph():
    root = files("etl_craft.core").joinpath("static")
    partial = ElementTree.fromstring(root.joinpath("mark.html").read_text())
    favicon = ElementTree.fromstring(root.joinpath("favicon.svg").read_text())
    ns = {"svg": "http://www.w3.org/2000/svg"}
    assert partial.attrib["viewBox"] == favicon.attrib["viewBox"] == "0 0 32 32"

    def shapes(svg):
        return [node.attrib["d"] for node in svg.findall(".//svg:path", ns)]

    def tile(svg):
        node = svg.find("svg:rect", ns)
        return node.attrib["width"], node.attrib["height"], node.attrib["rx"]

    assert shapes(partial) == shapes(favicon)
    assert len(shapes(partial)) == 4
    assert tile(partial) == tile(favicon) == ("32", "32", "8")
    assert partial.attrib["aria-hidden"] == "true"
    group = partial.find("svg:g", ns)
    assert group.attrib["stroke-linecap"] == group.attrib["stroke-linejoin"] == "round"
    assert "prefers-color-scheme: dark" in root.joinpath("favicon.svg").read_text()


@pytest.mark.parametrize("theme", [LIGHT, DARK], ids=["light", "dark"])
def test_the_glyph_reads_on_the_tile_and_the_tile_stands_out_from_the_page(theme):
    for tile in theme["tile"]:
        assert contrast(theme["glyph"], tile) >= 3
        for page in theme["page"]:
            assert contrast(tile, page) >= 1.5 or contrast(theme["glyph"], tile) >= 4.5


def test_the_stylesheet_and_the_favicon_use_the_same_tile_colours():
    root = files("etl_craft.core").joinpath("static")
    css = root.joinpath("catalog.css").read_text()
    favicon = root.joinpath("favicon.svg").read_text()
    for colour in (*LIGHT["tile"], LIGHT["glyph"], *DARK["tile"], DARK["glyph"]):
        assert colour in css and colour in favicon
