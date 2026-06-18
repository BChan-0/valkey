"""Unit tests for release_notes parsing, rendering, and promotion."""

import release_notes as rn


SAMPLE = """Hello! placeholder text.

## Unreleased

<!-- a comment
spanning lines -->

### Behavior Changes
* Changed the default of foo by @alice (#100)

### New Features and Enhanced Behavior

### Bug Fixes
* Fixed a crash in bar by @bob (#101)
* Fixed a leak in baz by @carol (#102)
"""


def test_parse_unreleased_collects_bullets_by_category():
    notes = rn.parse_unreleased(SAMPLE)
    assert notes["Behavior Changes"] == ["* Changed the default of foo by @alice (#100)"]
    assert notes["Bug Fixes"] == [
        "* Fixed a crash in bar by @bob (#101)",
        "* Fixed a leak in baz by @carol (#102)",
    ]
    # Empty category is present but has no bullets.
    assert notes["New Features and Enhanced Behavior"] == []


def test_parse_unreleased_skips_html_comments():
    notes = rn.parse_unreleased(SAMPLE)
    # The multi-line comment must not leak into any category.
    for bullets in notes.values():
        for bullet in bullets:
            assert "comment" not in bullet


def test_parse_unreleased_missing_block_returns_empty():
    assert rn.parse_unreleased("no block here") == {}


def test_count_and_empty_helpers():
    notes = rn.parse_unreleased(SAMPLE)
    assert rn.count_bullets(notes) == 3
    assert not rn.is_unreleased_empty(notes)
    assert rn.is_unreleased_empty({"Bug Fixes": []})


def test_parse_version_valid_and_range():
    assert rn.parse_version("9.1.0") == (9, 1, 0)
    assert rn.parse_version(" 255.255.255 ") == (255, 255, 255)


def test_parse_version_rejects_bad_input():
    import pytest

    for bad in ["9.1", "9.1.0.0", "x.y.z", "9.1.256", "300.0.0"]:
        with pytest.raises(ValueError):
            rn.parse_version(bad)


def test_render_version_section_ga_structure():
    notes = rn.parse_unreleased(SAMPLE)
    section = rn.render_version_section(
        "9.1.0", "ga", "high", "2026-06-11", notes,
        contributors=["Alice A @alice", "Bob B @bob"],
    )
    assert "Valkey 9.1.0 GA  -  Released Thu 11 June 2026" in section
    assert "Upgrade urgency HIGH: This is the first stable release of Valkey 9.1." in section
    assert "### Behavior Changes" in section
    assert "### Bug Fixes" in section
    # Empty category dropped.
    assert "### New Features and Enhanced Behavior" not in section
    # Contributors rendered as bullets.
    assert "### Contributors" in section
    assert "* Alice A @alice" in section


def test_render_version_section_rc_wording():
    section = rn.render_version_section(
        "9.1.0", "rc2", "MODERATE", "2026-06-11", {"Bug Fixes": ["* x (#1)"]},
    )
    assert "Valkey 9.1.0-rc2" in section
    assert "second release candidate of Valkey 9.1.0" in section


def test_render_version_section_security_first():
    section = rn.render_version_section(
        "9.1.0", "ga", "SECURITY", "2026-06-11",
        {"Bug Fixes": ["* a fix (#1)"]},
        security_fixes=["(CVE-2026-1) bad thing"],
    )
    sec_idx = section.index("### Security Fixes")
    bug_idx = section.index("### Bug Fixes")
    assert sec_idx < bug_idx
    assert "* (CVE-2026-1) bad thing" in section


SAMPLE_UNRECOGNIZED = """preamble

## Unreleased

### Bug Fixes
* Fixed a real crash by @alice (#10)

### Networking
* Big networking change someone miscategorized by @bob (#11)

### Bug Fix
* Typo'd the category header, singular by @carol (#12)
"""


def test_unrecognized_categories_lists_only_noncanonical_with_bullets():
    notes = rn.parse_unreleased(SAMPLE_UNRECOGNIZED)
    # Networking and the singular "Bug Fix" typo are non-canonical and carry
    # bullets; the canonical "Bug Fixes" is excluded.
    assert rn.unrecognized_categories(notes) == ["Networking", "Bug Fix"]


def test_unrecognized_categories_excludes_canonical_and_security():
    notes = {
        "Bug Fixes": ["* x (#1)"],
        rn.SECURITY_CATEGORY: ["* (CVE-2026-1) y"],
        "Empty Weird": [],  # non-canonical but no bullets -> ignored
    }
    assert rn.unrecognized_categories(notes) == []


def test_render_keeps_unrecognized_category_verbatim_after_canonical():
    notes = rn.parse_unreleased(SAMPLE_UNRECOGNIZED)
    section = rn.render_version_section("9.1.0", "ga", "HIGH", "2026-06-11", notes)
    # Nothing is dropped: every miscategorized bullet survives.
    assert "Big networking change someone miscategorized by @bob (#11)" in section
    assert "Typo'd the category header, singular by @carol (#12)" in section
    assert "### Networking" in section
    # Canonical category renders before the non-canonical ones.
    assert section.index("### Bug Fixes") < section.index("### Networking")


def test_promote_keeps_miscategorized_notes():
    out = rn.promote(
        SAMPLE_UNRECOGNIZED, version="9.1.0", stage="rc1", urgency="LOW", date="2026-06-11",
    )
    assert "Big networking change someone miscategorized by @bob (#11)" in out
    # And the Unreleased block is still reset afterwards.
    tail = out.split("## Unreleased", 1)[1]
    assert "Big networking change" not in tail


def test_render_invalid_urgency_and_stage():
    import pytest

    with pytest.raises(ValueError):
        rn.render_version_section("9.1.0", "ga", "NOPE", "2026-06-11", {})
    with pytest.raises(ValueError):
        rn.render_version_section("9.1.0", "beta", "LOW", "2026-06-11", {})


def test_render_empty_unreleased_has_all_categories():
    block = rn.render_empty_unreleased()
    assert block.startswith("## Unreleased")
    for category in rn.CATEGORIES:
        assert "### {}".format(category) in block
    # No real bullets under any category (the guidance comment may contain "* ").
    assert rn.is_unreleased_empty(rn.parse_unreleased(block))


def test_reset_unreleased_clears_bullets_preserves_preamble():
    reset = rn.reset_unreleased(SAMPLE)
    assert reset.startswith("Hello! placeholder text.")
    assert rn.is_unreleased_empty(rn.parse_unreleased(reset))
    assert "Changed the default of foo" not in reset


def test_promote_builds_dated_section_and_resets_block():
    out = rn.promote(
        SAMPLE, version="9.1.0", stage="ga", urgency="HIGH", date="2026-06-11",
        contributors=["Alice A @alice"],
    )
    # Header + legend present.
    assert out.startswith("Valkey 9.1 release notes")
    assert "Upgrade urgency levels:" in out
    # Dated section with the promoted notes.
    assert "Valkey 9.1.0 GA" in out
    assert "Changed the default of foo by @alice (#100)" in out
    # Unreleased block reset to empty at the end.
    tail = out.split("## Unreleased", 1)[1]
    assert "Changed the default of foo" not in tail
    assert rn.is_unreleased_empty(rn.parse_unreleased(out))


def test_promote_preserves_prior_dated_sections():
    existing = (
        "Valkey 9.1 release notes\n"
        "========================\n\n"
        + rn.URGENCY_LEGEND
        + "\n\n"
        "Valkey 9.1.0-rc1  -  Released Mon 01 June 2026\n"
        "---------------------------------------------\n\n"
        "Upgrade urgency LOW: This is the first release candidate of Valkey 9.1.0.\n\n"
        "### Bug Fixes\n* Old fix (#1)\n\n"
        "## Unreleased\n\n### Bug Fixes\n* New fix by @dev (#2)\n"
    )
    out = rn.promote(
        existing, version="9.1.0", stage="ga", urgency="LOW", date="2026-06-11",
    )
    assert "New fix by @dev (#2)" in out  # promoted
    assert "Old fix (#1)" in out  # prior section retained
    # New GA section appears before the older rc1 section.
    assert out.index("Valkey 9.1.0 GA") < out.index("Valkey 9.1.0-rc1")
