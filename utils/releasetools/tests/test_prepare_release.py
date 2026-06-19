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
    # Version macros computed correctly (the bump_version bug-fix path).
    assert "VALKEY_VERSION=9.1.0 VALKEY_VERSION_NUM=0x00090100 VALKEY_RELEASE_STAGE=rc1" in out
    # Dry run must not touch the working files.
    assert "## Unreleased" in (tmp_path / "00-RELEASENOTES").read_text()
    assert '"255.255.255"' in (tmp_path / "version.h").read_text()


def test_dry_run_writes_files_when_not_dry(tmp_path, monkeypatch):
    _setup(tmp_path, NOTES_CLEAN)
    monkeypatch.setattr(pr, "list_contributors", lambda *a, **k: [])
    rc = _run(tmp_path, dry_run=False)
    assert rc == 0
    notes = (tmp_path / "00-RELEASENOTES").read_text()
    version = (tmp_path / "version.h").read_text()
    # Notes promoted and Unreleased reset; version macros rewritten.
    assert "Valkey 9.1.0-rc1" in notes
    assert '#define VALKEY_VERSION "9.1.0"' in version
    assert "#define VALKEY_VERSION_NUM 0x00090100" in version
    assert '#define VALKEY_RELEASE_STAGE "rc1"' in version


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
