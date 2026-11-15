"""The owner-supplied mark stays consistent across the packaged and browser surfaces."""

import re
from importlib.resources import files
from pathlib import Path
from xml.etree import ElementTree

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
STATIC = files("etl_craft.core").joinpath("static")
NS = {"svg": "http://www.w3.org/2000/svg"}


def luminance(value):
    channels = [int(value[n : n + 2], 16) / 255 for n in (1, 3, 5)]
    values = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
    return sum(v * w for v, w in zip(values, (0.2126, 0.7152, 0.0722), strict=True))


def contrast(first, second):
    a, b = luminance(first), luminance(second)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def test_the_page_and_react_marks_draw_the_owner_supplied_path():
    source = ElementTree.parse(REPO / "brand/mark/etl-craft-mark.svg").getroot()
    partial = ElementTree.fromstring(STATIC.joinpath("mark.html").read_text())
    react = (REPO / "ui/src/components/logo.tsx").read_text()
    for svg in (source, partial):
        assert svg.attrib["viewBox"] == "0 0 512 512"
        assert [node.tag for node in svg] == [f"{{{NS['svg']}}}path"]
        assert svg[0].attrib["fill-rule"] == "evenodd"
    assert partial[0].attrib["d"] == source[0].attrib["d"]
    assert partial[0].attrib["fill"] == "currentColor"
    assert partial.attrib["aria-hidden"] == "true"
    assert partial.attrib["focusable"] == "false"
    assert 'viewBox="0 0 512 512"' in react
    assert re.findall(r'<path\b[^>]*\bd="([^"]+)"', react) == [source[0].attrib["d"]]
    assert len(re.findall(r"<path\b", react)) == 1
    assert 'fillRule="evenodd"' in react and 'fill="currentColor"' in react
    assert not re.search(r"<(?:rect|defs|linearGradient|radialGradient)\b", react)


def test_the_favicon_is_the_owner_supplied_theme_aware_pixel_mark():
    favicon = STATIC.joinpath("favicon.svg").read_text()
    assert favicon == (REPO / "brand/favicon/favicon-32.svg").read_text()
    svg = ElementTree.fromstring(favicon)
    assert svg.attrib["viewBox"] == "0 0 32 32"
    assert svg.attrib["width"] == svg.attrib["height"] == "32"
    assert len(svg.findall("svg:path", NS)) == 1
    assert svg.find("svg:path", NS).attrib["fill-rule"] == "evenodd"
    css = re.sub(r"\s+", "", svg.find("svg:style", NS).text)
    assert css == "path{fill:#1B7694}@media(prefers-color-scheme:dark){path{fill:#5BBFDF}}"


def test_the_stylesheet_colours_the_mark_for_both_themes():
    css = re.sub(r"\s+", "", STATIC.joinpath("catalog.css").read_text())
    assert "--mark:light-dark(#1b7694,#5bbfdf);" in css
    assert re.search(r"\.product-mark\{[^}]*\bcolor:var\(--mark\)[;} ]", css)


def test_no_obsolete_mark_tokens_remain_in_either_interface():
    for directory in (REPO / "ui/src", REPO / "src/etl_craft/core/static"):
        for path in directory.rglob("*"):
            if path.is_file():
                assert not re.search(rb"--mark-(?:a|b|glyph)\b", path.read_bytes()), str(path)


@pytest.mark.parametrize(
    ("colour", "pages"),
    [("#1b7694", ("#eef2f6", "#edf1f5")), ("#5bbfdf", ("#151b23", "#0d1117"))],
    ids=["light", "dark"],
)
def test_the_mark_stands_out_from_the_page_in_each_theme(colour, pages):
    assert colour in STATIC.joinpath("catalog.css").read_text()
    for page in pages:
        assert contrast(colour, page) >= 3
