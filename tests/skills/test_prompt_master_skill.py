"""Tests for the prompt-master optional skill (ported from nidhinjs/prompt-master)."""

import re
from pathlib import Path

import pytest
import yaml

SKILL_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "optional-skills"
    / "productivity"
    / "prompt-master"
)
SKILL_MD = SKILL_DIR / "SKILL.md"
REFERENCES_DIR = SKILL_DIR / "references"


def _split_skill() -> tuple[dict, str]:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md must start with YAML frontmatter"
    _, fm, body = text.split("---\n", 2)
    return yaml.safe_load(fm), body


@pytest.fixture(scope="module")
def frontmatter() -> dict:
    return _split_skill()[0]


@pytest.fixture(scope="module")
def body() -> str:
    return _split_skill()[1]


def test_skill_file_exists():
    assert SKILL_MD.is_file()


def test_frontmatter_required_fields(frontmatter):
    assert frontmatter["name"] == "prompt-master"
    assert frontmatter["version"] == "0.1.0"
    assert frontmatter["license"] == "MIT"
    assert "nidhinjs" in frontmatter["author"]
    assert "Hermes Agent" in frontmatter["author"]


def test_description_valid(frontmatter):
    desc = frontmatter["description"]
    assert isinstance(desc, str)
    assert len(desc) <= 60, f"description is {len(desc)} chars, max 60"
    assert desc.endswith("."), "description must end with a period"
    assert "\n" not in desc


def test_platforms(frontmatter):
    assert frontmatter["platforms"] == ["linux", "macos", "windows"]


def test_metadata_hermes(frontmatter):
    hermes = frontmatter["metadata"]["hermes"]
    assert hermes["tags"] == ["Prompts", "Prompt-Engineering", "Productivity"]
    assert hermes["related_skills"] == []


def test_body_sections(body):
    for section in (
        "## When to Use",
        "## Procedure",
        "## Tool-Family Formats",
        "## Pitfalls",
        "## Verification",
    ):
        assert section in body, f"missing section: {section}"


def test_no_identity_override_language(body):
    """The Hermes port must not carry upstream persona-overlay framing."""
    assert "PRIMACY" not in body
    banned = [
        "primacy zone",
        "recency zone",
        "middle zone",
        "output lock",
        "success lock",
        "who you are",
        "you are now",
        "hard rules — never violate",
    ]
    lowered = body.lower()
    for phrase in banned:
        assert phrase not in lowered, f"banned identity-override phrase: {phrase!r}"


def test_references_dir_has_expected_files():
    assert REFERENCES_DIR.is_dir()
    names = {p.name for p in REFERENCES_DIR.glob("*.md")}
    assert {"tool-routing.md", "templates.md", "patterns.md"} <= names


def test_mentioned_references_exist(body):
    """Every references/*.md path mentioned in SKILL.md must exist on disk."""
    mentioned = set(re.findall(r"references/[\w.-]+\.md", body))
    assert mentioned, "SKILL.md should reference at least one file in references/"
    for rel in mentioned:
        assert (SKILL_DIR / rel).is_file(), f"referenced file missing: {rel}"


def test_all_reference_files_mentioned(body):
    """Every file in references/ should be discoverable from SKILL.md."""
    for path in REFERENCES_DIR.glob("*.md"):
        assert f"references/{path.name}" in body, f"{path.name} not mentioned in SKILL.md"


def test_core_knowledge_preserved(body):
    """Spot-check the substantive per-tool knowledge survived the port."""
    for marker in ("Midjourney", "Cursor", "code block", "reasoning-native"):
        assert marker.lower() in body.lower(), f"missing knowledge marker: {marker}"
