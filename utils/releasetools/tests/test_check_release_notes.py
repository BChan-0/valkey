"""Unit tests for the release-notes CI label/edit enforcement."""

import check_release_notes as crn


NOTES_WITH_BULLET = """preamble

## Unreleased

### Bug Fixes
* Fixed a thing by @dev (#1)

### Behavior Changes
"""

NOTES_EMPTY = """preamble

## Unreleased

### Bug Fixes

### Behavior Changes
"""

NOTES_BULLET_NO_REF = """preamble

## Unreleased

### Bug Fixes
* Fixed a thing by @dev

### Behavior Changes
"""

NOTES_BULLET_NO_AUTHOR = """preamble

## Unreleased

### Bug Fixes
* Fixed a thing (#1)

### Behavior Changes
"""


def _write(tmp_path, text):
    path = tmp_path / "00-RELEASENOTES"
    path.write_text(text)
    return path


def test_parse_labels_json_array():
    assert crn.parse_labels('["release-notes", "bug"]') == ["release-notes", "bug"]


def test_parse_labels_empty_and_comma_fallback():
    assert crn.parse_labels("") == []
    assert crn.parse_labels(None) == []
    assert crn.parse_labels("release-notes, bug") == ["release-notes", "bug"]


def test_no_label_fails(tmp_path):
    ok, messages = crn.evaluate([], base_sha=None, repo_dir=str(tmp_path))
    assert not ok
    assert any("missing a release-notes decision" in m for m in messages)


def test_both_labels_fail(tmp_path):
    ok, messages = crn.evaluate(
        ["release-notes", "no-release-notes"], base_sha=None, repo_dir=str(tmp_path)
    )
    assert not ok
    assert any("both" in m for m in messages)


def test_no_release_notes_label_passes(tmp_path):
    ok, messages = crn.evaluate(["no-release-notes"], base_sha=None, repo_dir=str(tmp_path))
    assert ok
    assert any("no release note required" in m for m in messages)


def test_no_release_notes_with_net_new_bullet_fails(tmp_path, monkeypatch):
    # Label claims no note, but the PR adds a bullet the base did not have.
    _write(tmp_path, NOTES_WITH_BULLET)
    monkeypatch.setattr(crn, "_git_show", lambda ref, repo_dir: NOTES_EMPTY)
    ok, messages = crn.evaluate(
        ["no-release-notes"], base_sha="abc123", repo_dir=str(tmp_path)
    )
    assert not ok
    assert any("adds 1 new entry" in m for m in messages)


def test_no_release_notes_with_carried_over_bullet_passes(tmp_path, monkeypatch):
    # The bullet was already in the base, so this PR added nothing -> pass.
    _write(tmp_path, NOTES_WITH_BULLET)
    monkeypatch.setattr(crn, "_git_show", lambda ref, repo_dir: NOTES_WITH_BULLET)
    ok, messages = crn.evaluate(
        ["no-release-notes"], base_sha="abc123", repo_dir=str(tmp_path)
    )
    assert ok
    assert any("no release note required" in m for m in messages)


def test_release_notes_label_with_bullet_passes(tmp_path):
    _write(tmp_path, NOTES_WITH_BULLET)
    ok, messages = crn.evaluate(["release-notes"], base_sha=None, repo_dir=str(tmp_path))
    assert ok
    assert any("adds 1 new release-note" in m for m in messages)


def test_release_notes_label_without_bullet_fails(tmp_path):
    _write(tmp_path, NOTES_EMPTY)
    ok, messages = crn.evaluate(["release-notes"], base_sha=None, repo_dir=str(tmp_path))
    assert not ok
    assert any("adds no new entry" in m for m in messages)


def test_release_notes_missing_file_fails(tmp_path):
    ok, messages = crn.evaluate(["release-notes"], base_sha=None, repo_dir=str(tmp_path))
    assert not ok
    assert any("Could not read" in m for m in messages)


def test_base_count_blocks_when_no_net_new(tmp_path, monkeypatch):
    # Head has one bullet; base (via git show) also has one -> no net-new -> fail.
    _write(tmp_path, NOTES_WITH_BULLET)
    monkeypatch.setattr(crn, "_git_show", lambda ref, repo_dir: NOTES_WITH_BULLET)
    ok, messages = crn.evaluate(
        ["release-notes"], base_sha="abc123", repo_dir=str(tmp_path)
    )
    assert not ok
    assert any("adds no new entry" in m for m in messages)


def test_net_new_against_base_passes(tmp_path, monkeypatch):
    # Head has one bullet; base had none -> net-new -> pass.
    _write(tmp_path, NOTES_WITH_BULLET)
    monkeypatch.setattr(crn, "_git_show", lambda ref, repo_dir: NOTES_EMPTY)
    ok, messages = crn.evaluate(
        ["release-notes"], base_sha="abc123", repo_dir=str(tmp_path)
    )
    assert ok


def test_missing_pr_ref_fails(tmp_path):
    # Net-new bullet has no trailing (#N) -> hard failure.
    _write(tmp_path, NOTES_BULLET_NO_REF)
    ok, messages = crn.evaluate(
        ["release-notes"], base_sha=None, repo_dir=str(tmp_path), pr_number="1234"
    )
    assert not ok
    joined = "\n".join(messages)
    assert "missing this PR's number" in joined
    assert "* Fixed a thing by @dev (#1234)" in joined


def test_correct_ref_and_author_passes(tmp_path):
    # Bullet carries the matching (#1) and an attribution -> clean pass.
    _write(tmp_path, NOTES_WITH_BULLET)  # "* Fixed a thing by @dev (#1)"
    ok, messages = crn.evaluate(
        ["release-notes"], base_sha=None, repo_dir=str(tmp_path), pr_number="1", pr_author="dev"
    )
    assert ok
    assert not any(m.startswith("❌") for m in messages)


def test_pr_ref_not_required_without_pr_number(tmp_path):
    # Without a known PR number the ref check is skipped; the bullet still has
    # an attribution, so the PR passes.
    _write(tmp_path, NOTES_BULLET_NO_REF)
    ok, messages = crn.evaluate(
        ["release-notes"], base_sha=None, repo_dir=str(tmp_path), pr_number=None
    )
    assert ok
    assert not any("missing this PR's number" in m for m in messages)


def test_missing_ref_only_targets_net_new_bullet(tmp_path, monkeypatch):
    # Base already had the @dev bullet; head adds a second, unreferenced one.
    # Only the net-new bullet is held to the rule.
    head = NOTES_BULLET_NO_REF.replace(
        "* Fixed a thing by @dev\n",
        "* Fixed a thing by @dev\n* Added a flag by @newdev\n",
    )
    _write(tmp_path, head)
    monkeypatch.setattr(crn, "_git_show", lambda ref, repo_dir: NOTES_BULLET_NO_REF)
    ok, messages = crn.evaluate(
        ["release-notes"], base_sha="abc123", repo_dir=str(tmp_path), pr_number="1234"
    )
    assert not ok
    joined = "\n".join(messages)
    # Only the net-new bullet is flagged, not the carried-over one.
    assert "* Added a flag by @newdev (#1234)" in joined
    assert "* Fixed a thing by @dev (#1234)" not in joined


def test_missing_author_fails(tmp_path):
    # Net-new bullet has a (#1) but no "by @handle" -> now a hard failure.
    _write(tmp_path, NOTES_BULLET_NO_AUTHOR)
    ok, messages = crn.evaluate(
        ["release-notes"], base_sha=None, repo_dir=str(tmp_path), pr_author="dev"
    )
    assert not ok
    joined = "\n".join(messages)
    assert "missing a contributor attribution" in joined
    # Canonical order: attribution goes before the existing (#N) reference.
    assert "* Fixed a thing by @dev (#1)" in joined


def test_missing_author_fix_when_no_pr_ref_present(tmp_path):
    notes = NOTES_BULLET_NO_AUTHOR.replace("* Fixed a thing (#1)", "* Fixed a thing")
    _write(tmp_path, notes)
    ok, messages = crn.evaluate(
        ["release-notes"], base_sha=None, repo_dir=str(tmp_path), pr_author="dev"
    )
    assert not ok
    assert any("* Fixed a thing by @dev" in m for m in messages)


def test_author_present_does_not_fail_missing_check(tmp_path):
    # An attribution is present (even a different handle), so the *missing*
    # author check must not fire. A wrong-author warning is covered separately
    # in test_wrong_author_warns_but_passes.
    _write(tmp_path, NOTES_BULLET_NO_REF)  # "* Fixed a thing by @dev"
    ok, messages = crn.evaluate(
        ["release-notes"], base_sha=None, repo_dir=str(tmp_path), pr_author="other"
    )
    assert ok
    assert not any("missing a contributor attribution" in m for m in messages)


def test_author_not_required_without_pr_author(tmp_path):
    # Without a known PR author the attribution check is skipped.
    _write(tmp_path, NOTES_BULLET_NO_AUTHOR)
    ok, messages = crn.evaluate(
        ["release-notes"], base_sha=None, repo_dir=str(tmp_path), pr_author=None
    )
    assert ok
    assert not any("missing a contributor attribution" in m for m in messages)


def test_missing_author_only_targets_net_new_bullet(tmp_path, monkeypatch):
    # Base already had an unattributed bullet; head adds a second one. Only the
    # net-new bullet is held to the rule.
    head = NOTES_BULLET_NO_AUTHOR.replace(
        "* Fixed a thing (#1)\n",
        "* Fixed a thing (#1)\n* Added a flag (#2)\n",
    )
    _write(tmp_path, head)
    monkeypatch.setattr(crn, "_git_show", lambda ref, repo_dir: NOTES_BULLET_NO_AUTHOR)
    ok, messages = crn.evaluate(
        ["release-notes"], base_sha="abc123", repo_dir=str(tmp_path), pr_author="dev"
    )
    assert not ok
    joined = "\n".join(messages)
    assert "* Added a flag by @dev (#2)" in joined
    assert "* Fixed a thing by @dev (#1)" not in joined


def test_missing_ref_and_author_reported_together(tmp_path):
    # A bullet lacking both a number and an attribution should surface both
    # failures in one run so the contributor fixes everything at once.
    notes = NOTES_EMPTY.replace("### Bug Fixes\n", "### Bug Fixes\n* Fixed a thing\n")
    _write(tmp_path, notes)
    ok, messages = crn.evaluate(
        ["release-notes"],
        base_sha=None,
        repo_dir=str(tmp_path),
        pr_number="1234",
        pr_author="dev",
    )
    assert not ok
    joined = "\n".join(messages)
    assert "missing this PR's number" in joined
    assert "missing a contributor attribution" in joined


NOTES_WRONG_PR = """preamble

## Unreleased

### Bug Fixes
* Fixed a thing by @dev (#9999)

### Behavior Changes
"""

NOTES_WRONG_AUTHOR = """preamble

## Unreleased

### Bug Fixes
* Fixed a thing by @someoneelse (#1)

### Behavior Changes
"""


def test_wrong_pr_number_fails(tmp_path):
    # New bullet's trailing (#9999) does not match this PR (#1) -> fail.
    _write(tmp_path, NOTES_WRONG_PR)
    ok, messages = crn.evaluate(
        ["release-notes"], base_sha=None, repo_dir=str(tmp_path), pr_number="1"
    )
    assert not ok
    joined = "\n".join(messages)
    assert "not this PR" in joined
    assert "says (#9999), expected (#1)" in joined


def test_correct_pr_number_passes(tmp_path):
    _write(tmp_path, NOTES_WRONG_PR)
    ok, _ = crn.evaluate(
        ["release-notes"], base_sha=None, repo_dir=str(tmp_path), pr_number="9999"
    )
    assert ok


def test_wrong_pr_number_only_checks_net_new(tmp_path, monkeypatch):
    # The wrong-numbered bullet was already in the base, so it is not net-new
    # and must not fail this PR -- only the newly added bullet matters.
    head = NOTES_WRONG_PR.replace(
        "* Fixed a thing by @dev (#9999)\n",
        "* Fixed a thing by @dev (#9999)\n* Added a flag by @dev (#1)\n",
    )
    _write(tmp_path, head)
    monkeypatch.setattr(crn, "_git_show", lambda ref, repo_dir: NOTES_WRONG_PR)
    ok, _ = crn.evaluate(
        ["release-notes"], base_sha="abc123", repo_dir=str(tmp_path), pr_number="1"
    )
    assert ok


def test_mid_text_pr_ref_is_not_treated_as_mislabel(tmp_path):
    # A cross-reference to another PR mid-bullet, with the correct trailing
    # number, is legitimate and must not fail.
    notes = NOTES_WRONG_PR.replace(
        "* Fixed a thing by @dev (#9999)",
        "* Revert the change from (#42) by @dev (#1)",
    )
    _write(tmp_path, notes)
    ok, _ = crn.evaluate(
        ["release-notes"], base_sha=None, repo_dir=str(tmp_path), pr_number="1"
    )
    assert ok


def test_no_pr_check_without_pr_number(tmp_path):
    _write(tmp_path, NOTES_WRONG_PR)
    ok, _ = crn.evaluate(
        ["release-notes"], base_sha=None, repo_dir=str(tmp_path), pr_number=None
    )
    assert ok


def test_wrong_author_warns_but_passes(tmp_path):
    # Bullet credits @someoneelse, PR author is @dev -> warning, still passes.
    _write(tmp_path, NOTES_WRONG_AUTHOR)
    ok, messages = crn.evaluate(
        ["release-notes"], base_sha=None, repo_dir=str(tmp_path), pr_author="dev"
    )
    assert ok
    joined = "\n".join(messages)
    assert "other than this PR's author" in joined
    assert "credits @someoneelse, not @dev" in joined


def test_matching_author_no_warning(tmp_path):
    _write(tmp_path, NOTES_WITH_BULLET)  # credited "by @dev"
    ok, messages = crn.evaluate(
        ["release-notes"], base_sha=None, repo_dir=str(tmp_path), pr_author="dev"
    )
    assert ok
    assert not any("other than this PR's author" in m for m in messages)


def test_author_warning_only_targets_net_new(tmp_path, monkeypatch):
    # The mismatched-author bullet was already in the base -> no warning.
    _write(tmp_path, NOTES_WRONG_AUTHOR)
    monkeypatch.setattr(crn, "_git_show", lambda ref, repo_dir: NOTES_WRONG_AUTHOR)
    # Head == base means no net-new bullet, so rule 2 would block first; add a
    # net-new correctly-attributed bullet so we reach the author check.
    head = NOTES_WRONG_AUTHOR.replace(
        "* Fixed a thing by @someoneelse (#1)\n",
        "* Fixed a thing by @someoneelse (#1)\n* Added a flag by @dev (#2)\n",
    )
    _write(tmp_path, head)
    ok, messages = crn.evaluate(
        ["release-notes"], base_sha="abc123", repo_dir=str(tmp_path), pr_author="dev"
    )
    assert ok
    # Only the carried-over bullet credits @someoneelse, and it is not net-new,
    # so no author warning should fire.
    assert not any("other than this PR's author" in m for m in messages)


def test_main_exit_codes(tmp_path, monkeypatch):
    _write(tmp_path, NOTES_WITH_BULLET)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PR_LABELS", '["no-release-notes"]')
    monkeypatch.delenv("BASE_SHA", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert crn.main([]) == 0

    monkeypatch.setenv("PR_LABELS", "[]")
    assert crn.main([]) == 1
