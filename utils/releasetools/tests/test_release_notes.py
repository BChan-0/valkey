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


def test_render_security_fixes_arg_wins_over_notes_no_duplicate_header():
    # A contributor hand-added a Security Fixes section AND the release cut supplies
    # the embargo CVE list. Only the supplied list renders, under a single header --
    # the hand-added one is ignored, never duplicated.
    notes = {
        rn.SECURITY_CATEGORY: ["* (CVE-2026-2) hand-added in the block (#5)"],
        "Bug Fixes": ["* a fix (#1)"],
    }
    section = rn.render_version_section(
        "9.1.0", "ga", "SECURITY", "2026-06-11", notes,
        security_fixes=["(CVE-2026-1) from the embargo list"],
    )
    assert section.count("### Security Fixes") == 1
    assert "(CVE-2026-1) from the embargo list" in section
    assert "(CVE-2026-2) hand-added in the block" not in section


def test_render_contributors_arg_wins_over_notes_no_duplicate_header():
    # Same for a hand-added Contributors section: the generated list is the source
    # of truth, the hand-added section is dropped, and there is one header.
    notes = {
        "Bug Fixes": ["* a fix (#1)"],
        rn.CONTRIBUTORS_SECTION: ["* I Added Myself @sneaky"],
    }
    section = rn.render_version_section(
        "9.1.0", "ga", "LOW", "2026-06-11", notes,
        contributors=["Real Generated @gen"],
    )
    assert section.count("### Contributors") == 1
    assert "Real Generated @gen" in section
    assert "I Added Myself @sneaky" not in section


def test_reserved_sections_present_reports_bullet_bearing_only():
    notes = {
        "Bug Fixes": ["* x (#1)"],
        rn.SECURITY_CATEGORY: ["* (CVE-2026-1) y"],
        rn.CONTRIBUTORS_SECTION: [],  # present but empty -> not reported
    }
    assert rn.reserved_sections_present(notes) == [rn.SECURITY_CATEGORY]


def test_unrecognized_categories_excludes_reserved_sections():
    # Reserved sections with bullets are handled by reserved_sections_present, not
    # flagged as "miscategorized" (which would promote them verbatim).
    notes = {
        rn.SECURITY_CATEGORY: ["* (CVE-2026-1) y"],
        rn.CONTRIBUTORS_SECTION: ["* Me @me"],
        "Networking": ["* invented (#2)"],
    }
    assert rn.unrecognized_categories(notes) == ["Networking"]


def test_normalize_stage_rejects_rc_zero_and_leading_zeros():
    import pytest

    for good, num in [("rc1", 1), ("rc2", 2), ("rc12", 12)]:
        assert rn._normalize_stage(good) == good
        assert "{} release candidate".format(rn.ordinal(num)) in rn._urgency_sentence(
            "9.1.0", good, "LOW"
        )
    for bad in ["rc0", "rc01", "rc007", "rc", "rcx"]:
        with pytest.raises(ValueError):
            rn._normalize_stage(bad)


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
    # Promoted into the dated section exactly once (not also left under the
    # re-emptied Unreleased block, which carries no bullets).
    assert out.count("Big networking change someone miscategorized by @bob (#11)") == 1


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


def test_promote_builds_dated_section_with_emptied_unreleased_block():
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
    # The release branch keeps an *emptied* ## Unreleased block at the foot so the
    # next stage's backports have somewhere to accumulate; the promoted bullets
    # are gone from it (they now live in the dated section above).
    assert "## Unreleased" in out
    assert rn.is_unreleased_empty(rn.parse_unreleased(out))
    assert "Changed the default of foo" not in out.split("## Unreleased", 1)[1]
    # The emptied block sits below the dated section, not above it.
    assert out.index("Valkey 9.1.0 GA") < out.index("## Unreleased")


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
    # ...and the re-emptied Unreleased block trails the dated sections.
    assert out.index("Valkey 9.1.0-rc1") < out.index("## Unreleased")
    assert rn.is_unreleased_empty(rn.parse_unreleased(out))


def test_promote_chains_rc_to_ga():
    """rc1 (from unstable) -> backport -> rc2 (from release branch) must work.

    Regression for the bug where promote() dropped the Unreleased block, so every
    stage after rc1 -- cut from the release branch, which then had no block --
    rendered an empty dated section. Keeping an emptied block at the foot lets
    backported PRs accumulate between cuts and be promoted into the next stage.
    """
    unstable = (
        "placeholder\n\n## Unreleased\n\n"
        "### New Features and Enhanced Behavior\n* rc1 feature by @alice (#100)\n"
    )
    rc1 = rn.promote(unstable, version="9.1.0", stage="rc1", urgency="LOW", date="2026-03-17")
    assert "rc1 feature by @alice (#100)" in rc1
    assert rn.is_unreleased_empty(rn.parse_unreleased(rc1))

    # A backport merges to the release branch, adding a bullet under the block.
    backported = rc1.replace(
        "## Unreleased\n",
        "## Unreleased\n\n### Bug Fixes\n* Backported fix by @bob (#200)\n",
        1,
    )
    rc2 = rn.promote(backported, version="9.1.0", stage="rc2", urgency="LOW", date="2026-04-28")

    # The backport lands in the rc2 section; rc1's bullet is preserved once, below.
    assert "Backported fix by @bob (#200)" in rc2
    assert rc2.count("rc1 feature by @alice (#100)") == 1
    assert rc2.index("Valkey 9.1.0-rc2") < rc2.index("Valkey 9.1.0-rc1")
    # The block is re-emptied for the next stage and the backport is no longer in it.
    assert rn.is_unreleased_empty(rn.parse_unreleased(rc2))
    assert "Backported fix by @bob (#200)" not in rc2.split("## Unreleased", 1)[1]
