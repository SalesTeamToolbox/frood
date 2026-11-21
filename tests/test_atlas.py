"""
tests/test_atlas.py — Resolves every reference in docs/ATLAS.md.

Asserts:
- Every route has a handler and decides field.
- Every sibling-trap route exists in the atlas.
- Every referenced topic file exists under docs/atlas/.

Run: python -m pytest tests/test_atlas.py -q
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ATLAS_PATH = ROOT / "docs" / "ATLAS.md"
ATLAS_DIR = ROOT / "docs" / "atlas"

_SECTION_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
_FIELD_RE = re.compile(r"^(\w+):\s*(.*)$", re.MULTILINE)


def _parse_atlas(text: str) -> dict[str, dict[str, str | list[str]]]:
    """Parse ATLAS.md into {route: {handler, decides, sibling_traps, topic}}."""
    routes: dict[str, dict[str, str | list[str]]] = {}
    # Split on route headers; each chunk is one section.
    chunks = _SECTION_RE.split(text)
    # chunks[0] is preamble before the first ### header.
    for i in range(1, len(chunks), 2):
        route = chunks[i].strip()
        # Skip placeholder schema examples (e.g. "### <route>").
        if "<" in route or ">" in route:
            continue
        body = chunks[i + 1] if i + 1 < len(chunks) else ""
        # Stop the body at the next route header (already split, so body is
        # everything until end of this section).
        fields: dict[str, str | list[str]] = {}
        for line in body.splitlines():
            line = line.rstrip()
            if not line.strip():
                continue
            m = _FIELD_RE.match(line.strip())
            if not m:
                continue
            key, value = m.group(1).strip(), m.group(2).strip()
            if key == "sibling traps":
                fields["sibling_traps"] = [t.strip() for t in value.split(",") if t.strip()]
            else:
                fields[key] = value
        routes[route] = fields
    return routes


def _atlas_text() -> str:
    return ATLAS_PATH.read_text(encoding="utf-8")


@pytest.fixture
def atlas() -> dict[str, dict[str, str | list[str]]]:
    return _parse_atlas(_atlas_text())


class TestAtlasRouteFields:
    """Every route declares handler and decides."""

    def test_every_route_has_handler(self, atlas):
        for route, fields in atlas.items():
            assert "handler" in fields, f"route {route!r} missing handler"
            assert fields["handler"], f"route {route!r} handler is empty"

    def test_every_route_has_decides(self, atlas):
        for route, fields in atlas.items():
            assert "decides" in fields, f"route {route!r} missing decides"
            assert fields["decides"], f"route {route!r} decides is empty"


class TestAtlasSiblingTraps:
    """Every sibling-trap route exists in the atlas."""

    def test_sibling_traps_exist(self, atlas):
        known = set(atlas)
        for route, fields in atlas.items():
            for trap in fields.get("sibling_traps", []):
                assert trap in known, f"route {route!r} references unknown sibling trap {trap!r}"


class TestAtlasTopicFiles:
    """Every referenced topic file exists."""

    def test_topic_files_exist(self, atlas):
        for route, fields in atlas.items():
            topic = fields.get("topic")
            if not topic:
                continue
            topic_path = ROOT / topic
            assert (
                topic_path.exists()
            ), f"route {route!r} references missing topic {topic!r} ({topic_path})"

    def test_at_least_one_topic_file(self):
        """At least one topic file must exist and be referenced (M6)."""
        topic_files = list(ATLAS_DIR.glob("*.md"))
        assert topic_files, "no topic files under docs/atlas/"
        # At least one route must reference a topic file.
        text = _atlas_text()
        assert "topic:" in text, "ATLAS.md references no topic file"
