"""Checks that the README's local images exist and that the SVGs are valid XML."""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _local_images() -> set[str]:
    # Matches src="docs/..." in <img> tags and ![alt](docs/...) in Markdown.
    html = re.findall(r'src="([^"]+)"', README)
    md = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", README)
    return {p for p in html + md if not p.startswith(("http://", "https://"))}


def test_readme_images_exist() -> None:
    images = _local_images()
    assert images  # the banner must be referenced
    for rel in images:
        assert (ROOT / rel).is_file(), f"README points to missing file: {rel}"


def test_svgs_are_valid_xml() -> None:
    for svg in (ROOT / "docs" / "assets").glob("*.svg"):
        root = ET.parse(svg).getroot()  # raises if the XML is broken
        assert root.tag.endswith("svg")
        assert "viewBox" in root.attrib, f"{svg.name} has no viewBox"


def test_readme_internal_links_point_to_real_files() -> None:
    # Links like (DECISIONS.md#anchor): the file must exist.
    for target in re.findall(r"\]\(([A-Z]+\.md)(?:#[^)]*)?\)", README):
        assert (ROOT / target).is_file(), f"missing {target}"


def test_decision_anchors_exist() -> None:
    # Each DECISIONS.md#anchor in the README must match a real heading.
    decisions = (ROOT / "DECISIONS.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## (.+)$", decisions, flags=re.MULTILINE)
    # GitHub anchors: lowercase, drop punctuation, spaces to hyphens.
    anchors = {
        re.sub(r"[^a-z0-9 -]", "", h.lower()).replace(" ", "-") for h in headings
    }
    for anchor in re.findall(r"DECISIONS\.md#([a-z0-9-]+)", README):
        assert anchor in anchors, f"no such DECISIONS.md heading: {anchor}"
