"""Unit tests for the end-to-end release-cut orchestration (no network/git)."""

import prepare_release as pr


VERSION_H = """#define SERVER_NAME "valkey"
#define VALKEY_VERSION "255.255.255"
#define VALKEY_VERSION_NUM 0x00ffffff
#define VALKEY_RELEASE_STAGE "dev"
#define REDIS_VERSION "7.2.4"
"""

NOTES_CLEAN = """preamble

## Unreleased

### Bug Fixes
* Fixed a real crash by @alice (#10)
"""

NOTES_MISCATEGORIZED = """preamble

## Unreleased

### Bug Fixes
* Fixed a real crash by @alice (#10)

### Networking
* Big networking change someone miscategorized by @bob (#11)
"""


def _setup(tmp_path, notes_text):
    (tmp_path / "00-RELEASENOTES").write_text(notes_text)
    (tmp_path / "version.h").write_text(VERSION_H)


def _run(tmp_path, **overrides):
    kwargs = dict(
        version="9.1.0",
        stage="rc1",
        urgency="HIGH",
        date="2026-06-11",
        repo="valkey-io/valkey",
        base_ref="v9.0.0",
        token=None,
        repo_dir=str(tmp_path),
        notes_file="00-RELEASENOTES",
        version_file="version.h",
        security_fixes=None,
        dry_run=True,
    )
    kwargs.update(overrides)
    return pr.run(**kwargs)


def test_dry_run_promotes_notes_and_reports_version(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, NOTES_CLEAN)
    monkeypatch.setattr(pr, "list_contributors", lambda *a, **k: ["Alice A @alice"])
    rc = _run(tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    # Dated section and promoted bullet present in the dry-run output.
    assert "Valkey 9.1.0-rc1" in out
    assert "Fixed a real crash by @alice (#10)" in out
    assert "### Contributors" in out and "* Alice A @alice" in out
    # The promoted release-branch file keeps an emptied ## Unreleased block (for
    # the next stage's backports), but the just-promoted bullet is not left in it.
    notes_out = out.split("===== version.h", 1)[0]
    assert "## Unreleased" in notes_out
    assert "Fixed a real crash by @alice (#10)" not in notes_out.split("## Unreleased", 1)[1]
    # Version macros computed correctly (the bump_version bug-fix path).
    assert "VALKEY_VERSION=9.1.0 VALKEY_VERSION_NUM=0x00090100 VALKEY_RELEASE_STAGE=rc1" in out
    # Dry run must not touch the working files (source still has its block).
    assert "## Unreleased" in (tmp_path / "00-RELEASENOTES").read_text()
    assert '"255.255.255"' in (tmp_path / "version.h").read_text()


def test_dry_run_writes_files_when_not_dry(tmp_path, monkeypatch):
    _setup(tmp_path, NOTES_CLEAN)
    monkeypatch.setattr(pr, "list_contributors", lambda *a, **k: [])
    rc = _run(tmp_path, dry_run=False)
    assert rc == 0
    notes = (tmp_path / "00-RELEASENOTES").read_text()
    version = (tmp_path / "version.h").read_text()
    # Release-branch file: dated section plus an emptied ## Unreleased block at the
    # foot (so the next stage's backports can accumulate); version macros rewritten.
    assert "Valkey 9.1.0-rc1" in notes
    assert "## Unreleased" in notes
    assert notes.index("Valkey 9.1.0-rc1") < notes.index("## Unreleased")
    assert '#define VALKEY_VERSION "9.1.0"' in version
    assert "#define VALKEY_VERSION_NUM 0x00090100" in version
    assert '#define VALKEY_RELEASE_STAGE "rc1"' in version


def test_reset_unreleased_only_empties_block_no_version_bump(tmp_path, monkeypatch):
    # The companion unstable PR: empty the ## Unreleased block (clearing the
    # just-released bullets) without cutting a dated section or touching version.h.
    _setup(tmp_path, NOTES_CLEAN)
    monkeypatch.setattr(pr, "list_contributors", lambda *a, **k: [])
    rc = _run(tmp_path, dry_run=False, reset_unreleased_only=True)
    assert rc == 0
    notes = (tmp_path / "00-RELEASENOTES").read_text()
    version = (tmp_path / "version.h").read_text()
    # Block kept but emptied; the released bullet is gone; no dated section cut.
    assert "## Unreleased" in notes
    assert "Fixed a real crash by @alice (#10)" not in notes
    assert "Valkey 9.1.0-rc1" not in notes
    # version.h is untouched on this path.
    assert '#define VALKEY_VERSION "255.255.255"' in version


def test_reset_unreleased_only_dry_run_does_not_write(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, NOTES_CLEAN)
    monkeypatch.setattr(pr, "list_contributors", lambda *a, **k: [])
    rc = _run(tmp_path, reset_unreleased_only=True)  # dry_run=True by default
    out = capsys.readouterr().out
    assert rc == 0
    assert "reset Unreleased" in out
    # Source untouched: the bullet is still there on disk.
    assert "Fixed a real crash by @alice (#10)" in (tmp_path / "00-RELEASENOTES").read_text()


def test_miscategorized_note_warns_but_still_promotes(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, NOTES_MISCATEGORIZED)
    monkeypatch.setattr(pr, "list_contributors", lambda *a, **k: [])
    rc = _run(tmp_path)
    captured = capsys.readouterr()
    assert rc == 0
    # Non-blocking warning surfaced on stderr and as an Actions annotation,
    # naming the offending category.
    assert "Networking" in captured.err
    assert "::warning::" in captured.out
    # The miscategorized bullet is still promoted verbatim -- nothing dropped.
    assert "Big networking change someone miscategorized by @bob (#11)" in captured.out


def test_miscategorized_note_appended_to_job_summary(tmp_path, monkeypatch):
    _setup(tmp_path, NOTES_MISCATEGORIZED)
    monkeypatch.setattr(pr, "list_contributors", lambda *a, **k: [])
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    rc = _run(tmp_path)
    assert rc == 0
    text = summary.read_text()
    assert "Release notes warnings" in text
    assert "Networking" in text
    assert "Big networking change someone miscategorized by @bob (#11)" in text


def test_clean_notes_emit_no_warning(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, NOTES_CLEAN)
    monkeypatch.setattr(pr, "list_contributors", lambda *a, **k: [])
    _run(tmp_path)
    captured = capsys.readouterr()
    assert "::warning::" not in captured.out
    assert "Release notes warnings" not in captured.err


NOTES_RESERVED = """preamble

## Unreleased

### Bug Fixes
* Fixed a real crash by @alice (#10)

### Contributors
* I Added Myself @sneaky

### Security Fixes
* (CVE-2026-9) hand-added by someone (#11)
"""


def test_reserved_section_dropped_and_warned(tmp_path, monkeypatch, capsys):
    # Hand-added Security Fixes / Contributors sections are generated at release
    # time, so promotion drops them. The dry-run output must not contain the stray
    # bullets, and a warning must name both reserved sections.
    _setup(tmp_path, NOTES_RESERVED)
    monkeypatch.setattr(pr, "list_contributors", lambda *a, **k: ["Real Gen @gen"])
    rc = _run(tmp_path)
    captured = capsys.readouterr()
    assert rc == 0
    # The dry run prints the promoted file (a dated section) then the reset
    # ## Unreleased block (whose guidance comment now names the reserved
    # sections). Scope header counts to the promoted section only.
    promoted = captured.out.split("## Unreleased", 1)[0]
    # Stray bullets dropped, generated contributor used instead.
    assert "I Added Myself @sneaky" not in promoted
    assert "(CVE-2026-9) hand-added by someone" not in promoted
    assert "Real Gen @gen" in promoted
    # Exactly one Contributors header in the promoted section (no duplicate).
    assert promoted.count("### Contributors") == 1
    # The hand-added Security Fixes section was dropped, not promoted.
    assert "### Security Fixes" not in promoted
    # Warning names both reserved sections (annotation on stdout, detail on stderr).
    assert "::warning::Reserved release-note section" in captured.out
    assert "Contributors" in captured.err and "Security Fixes" in captured.err


def test_reserved_section_warning_in_job_summary(tmp_path, monkeypatch):
    _setup(tmp_path, NOTES_RESERVED)
    monkeypatch.setattr(pr, "list_contributors", lambda *a, **k: [])
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    rc = _run(tmp_path)
    assert rc == 0
    text = summary.read_text()
    assert "Release notes warnings" in text
    assert "not** promoted" in text or "not promoted" in text.replace("**", "")
    assert "(CVE-2026-9) hand-added by someone" in text


def test_drain_mode_writes_frozen_destination_and_bumps_its_version(tmp_path, monkeypatch):
    # Drain mode: --prior-notes-file points at the destination (release branch)
    # changelog. Bullets come from the source notes file; the destination is written
    # frozen (no ## Unreleased) and its version.h is bumped. The source file is left
    # untouched by promotion (emptied separately via --reset-unreleased-only).
    monkeypatch.setattr(pr, "list_contributors", lambda *a, **k: [])
    src = tmp_path / "src_notes"
    dst = tmp_path / "dst_notes"
    ver = tmp_path / "dst_version.h"
    src.write_text("Preamble.\n\n## Unreleased\n\n### Bug Fixes\n* Backport C by @carol (#30)\n")
    dst.write_text(
        "Valkey 9.1 release notes\n========================\n\n"
        "Valkey 9.1.0-rc1  -  Released Mon 01 June 2026\n"
        "---------------------------------------------\n\n"
        "Upgrade urgency LOW: This is the first release candidate of Valkey 9.1.0.\n\n"
        "### New Features and Enhanced Behavior\n* rc1 feature by @alice (#10)\n"
    )
    ver.write_text(VERSION_H)

    rc = pr.run(
        version="9.1.0", stage="rc2", urgency="LOW", date="2026-04-28",
        repo="valkey-io/valkey", base_ref="v9.0.0", token=None,
        repo_dir=str(tmp_path), notes_file=str(src),
        prior_notes_file=str(dst), version_file=str(ver),
        security_fixes=None, dry_run=False,
    )
    assert rc == 0
    dst_text = dst.read_text()
    # Destination: frozen, rc2 prepended above retained rc1.
    assert "Backport C by @carol (#30)" in dst_text
    assert dst_text.index("Valkey 9.1.0-rc2") < dst_text.index("Valkey 9.1.0-rc1")
    assert "## Unreleased" not in dst_text
    # Destination version bumped.
    assert '#define VALKEY_VERSION "9.1.0"' in ver.read_text()
    assert '#define VALKEY_RELEASE_STAGE "rc2"' in ver.read_text()
    # Source notes file untouched by promotion.
    assert "Backport C by @carol (#30)" in src.read_text()
    assert "## Unreleased" in src.read_text()


NOTES_BAD_BULLETS = """preamble

## Unreleased

### Behavior Changes
* malformed ref by @BChan-0 (#idk)

### Bug Fixes
* good one by @alice (#42)
* missing ref entirely by @bob
* no attribution at all (#43)
"""


def test_bad_bullets_warn_but_still_promote(tmp_path, monkeypatch, capsys):
    # Bullets with a missing/malformed (#N) or a missing `by @handle` are promoted
    # as-is, but a non-blocking warning flags them (a second line of defence past
    # the PR-time checks). The fully valid (#42) bullet is not flagged.
    _setup(tmp_path, NOTES_BAD_BULLETS)
    monkeypatch.setattr(pr, "list_contributors", lambda *a, **k: [])
    rc = _run(tmp_path)
    captured = capsys.readouterr()
    assert rc == 0  # non-blocking
    # Annotation on stdout, per-bullet detail on stderr.
    assert "::warning::" in captured.out
    assert "missing/malformed PR reference or attribution" in captured.out
    # Malformed PR ref flagged with that reason.
    assert "(#idk)" in captured.err and "missing/malformed PR ref" in captured.err
    # Missing attribution flagged with that reason.
    assert "no attribution at all (#43)  -- missing `by @handle` attribution" in captured.err
    # The fully valid bullet must not be flagged.
    assert "good one by @alice (#42)" not in captured.err
    # Still promoted (drained into the dated section).
    promoted = captured.out.split("## Unreleased", 1)[0]
    assert "malformed ref by @BChan-0 (#idk)" in promoted


def test_bad_bullet_reports_both_reasons_for_one_bullet(tmp_path, monkeypatch, capsys):
    # A bullet missing BOTH a PR ref and an attribution is reported once with both.
    _setup(tmp_path, "p\n\n## Unreleased\n\n### Bug Fixes\n* totally bare bullet\n")
    monkeypatch.setattr(pr, "list_contributors", lambda *a, **k: [])
    _run(tmp_path)
    err = capsys.readouterr().err
    assert "totally bare bullet" in err
    assert "missing/malformed PR ref" in err and "missing `by @handle` attribution" in err


def test_bad_bullet_warning_in_job_summary(tmp_path, monkeypatch):
    _setup(tmp_path, NOTES_BAD_BULLETS)
    monkeypatch.setattr(pr, "list_contributors", lambda *a, **k: [])
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    rc = _run(tmp_path)
    assert rc == 0
    text = summary.read_text()
    assert "missing or malformed PR reference" in text
    assert "(#idk)" in text


def test_clean_bullets_emit_no_warning(tmp_path, monkeypatch, capsys):
    _setup(tmp_path, NOTES_CLEAN)  # bullet is "* Fixed a real crash by @alice (#10)"
    monkeypatch.setattr(pr, "list_contributors", lambda *a, **k: [])
    _run(tmp_path)
    captured = capsys.readouterr()
    assert "missing/malformed PR reference or attribution" not in captured.out
    assert "missing/malformed PR ref" not in captured.err
