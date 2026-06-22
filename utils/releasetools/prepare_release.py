#!/usr/bin/env python3
"""Orchestrate a release cut: promote notes, bump version, list contributors.

Invoked by .github/workflows/prepare-release.yml. Given a target version,
release stage, urgency, and date, it:

1. promotes the ``## Unreleased`` block of 00-RELEASENOTES into a dated section,
   re-emptying the block at the foot of the file so the next stage's backports
   (rc2, rc3, ... GA, all cut from the release branch) can accumulate there,
2. injects a generated ``### Contributors`` list into that new section, and
3. sets the version macros in src/version.h.

It only edits files; the workflow handles branch/commit/PR. Use ``--dry-run``
to print the would-be results without writing.
"""

from __future__ import annotations

import argparse
import datetime
import os
import subprocess
import sys
from typing import List, Optional

try:  # Allow both `python -m` and direct-script execution.
    from bump_version import set_version, version_num
    from gen_contributors import list_contributors
    from release_notes import (
        parse_unreleased,
        promote,
        reserved_sections_present,
        reset_unreleased,
        unrecognized_categories,
    )
except ImportError:  # pragma: no cover - import shim
    from utils.releasetools.bump_version import set_version, version_num  # type: ignore
    from utils.releasetools.gen_contributors import list_contributors  # type: ignore
    from utils.releasetools.release_notes import (  # type: ignore
        parse_unreleased,
        promote,
        reserved_sections_present,
        reset_unreleased,
        unrecognized_categories,
    )


def _last_tag(repo_dir: str) -> Optional[str]:
    """Return the most recent tag reachable from HEAD, or None."""
    try:
        return subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=repo_dir,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _warn_unrecognized(notes_text: str, notes_file: str) -> None:
    """Warn (non-blocking) about problematic sections in the ``## Unreleased`` block.

    Two distinct cases, both surfaced three ways: stderr (workflow logs / local
    runs), GitHub Actions ``::warning::`` annotations, and the job summary,
    mirroring check_release_notes._emit_summary:

    * Non-canonical categories: authors sometimes typo a header (``### Bug Fix``
      for ``### Bug Fixes``) or invent one (``### Networking``). Those bullets are
      still promoted *verbatim* by :func:`release_notes.promote` so nothing is
      lost, but a maintainer should recategorize them.
    * Reserved sections (``Security Fixes`` / ``Contributors``): these are
      generated at release time, so a hand-added one in the block is *dropped* by
      promotion. Warn loudly so the maintainer knows the stray bullets did not
      ship and removes the section.
    """
    notes = parse_unreleased(notes_text)
    unknown = unrecognized_categories(notes)
    reserved = reserved_sections_present(notes)
    if not unknown and not reserved:
        return

    summary_lines: List[str] = []
    if unknown:
        summary_lines += [
            "⚠️ {} release note(s) sit under a category that is not one of the standard "
            "headers in {}. They were promoted verbatim under that header -- please move "
            "them to a standard `### Category` while reviewing this PR:".format(
                sum(len(notes[c]) for c in unknown), notes_file
            ),
            "",
        ]
        for category in unknown:
            summary_lines.append("- **{}**".format(category))
            for bullet in notes[category]:
                summary_lines.append("  {}".format(bullet.strip()))
            # One concise annotation per offending category for the Actions UI.
            print(
                "::warning::Unrecognized release-note category {!r} in {} "
                "(promoted verbatim; please recategorize).".format(category, notes_file)
            )

    if reserved:
        if summary_lines:
            summary_lines.append("")
        summary_lines += [
            "⚠️ {} bullet(s) sit under a section that is generated automatically at "
            "release time ({}) in {}. These were **not** promoted -- they are dropped "
            "by the release cut. Move the content into the right place (CVEs via the "
            "embargo list, contributors are auto-collected) and remove the section:".format(
                sum(len(notes[c]) for c in reserved),
                ", ".join("`{}`".format(c) for c in reserved),
                notes_file,
            ),
            "",
        ]
        for category in reserved:
            summary_lines.append("- **{}**".format(category))
            for bullet in notes[category]:
                summary_lines.append("  {}".format(bullet.strip()))
            print(
                "::warning::Reserved release-note section {!r} in {} was hand-added "
                "and dropped (it is generated at release time).".format(category, notes_file)
            )

    for line in summary_lines:
        print(line, file=sys.stderr)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as fh:
                fh.write("\n".join(["## Release notes warnings", ""] + summary_lines) + "\n")
        except OSError:
            pass


def run(
    *,
    version: str,
    stage: str,
    urgency: str,
    date: Optional[str],
    repo: str,
    base_ref: Optional[str],
    token: Optional[str],
    repo_dir: str,
    notes_file: str,
    version_file: str,
    security_fixes: Optional[List[str]],
    dry_run: bool,
    reset_unreleased_only: bool = False,
    prior_notes_file: Optional[str] = None,
) -> int:
    # Unstable path: don't cut a dated section or bump the version, just empty the
    # ## Unreleased block so the bullets that were just promoted onto the release
    # branch are cleared from unstable's running changelog and not promoted twice
    # when the next minor line forks. (The default path below, via promote(), also
    # re-empties the block on the release branch -- see promote()'s docstring --
    # so reset-only differs by skipping the dated section and the version bump.)
    if reset_unreleased_only:
        notes_text = _read(os.path.join(repo_dir, notes_file))
        new_notes = reset_unreleased(notes_text)
        if dry_run:
            print("\n===== {} (reset Unreleased, dry run) =====\n".format(notes_file))
            print(new_notes)
            return 0
        _write(os.path.join(repo_dir, notes_file), new_notes)
        print("Reset the ## Unreleased block in {}.".format(notes_file))
        return 0

    if not date:
        date = datetime.date.today().isoformat()

    # Contributor range: explicit --base-ref, else the most recent tag.
    base = base_ref or _last_tag(repo_dir)
    contributors: List[str] = []
    if base:
        contributors = list_contributors(repo, base, "HEAD", token, repo_dir=repo_dir)
        print("Collected {} contributor(s) over {}..HEAD".format(len(contributors), base))
    else:
        print("No base ref or tag found; skipping contributor generation.", file=sys.stderr)

    notes_text = _read(os.path.join(repo_dir, notes_file))
    # Non-blocking: flag any notes under typo'd/invented categories. They are
    # still promoted verbatim below, so the release is never blocked on them.
    _warn_unrecognized(notes_text, notes_file)

    # Drain mode: bullets come from the source file (notes_file, the base/feature
    # branch's block) while prior dated sections come from the destination changelog
    # (prior_notes_file, the running pre-release branch). The promoted changelog is
    # frozen -- no ## Unreleased block -- and written to the destination path. The
    # base branch's block is emptied separately via --reset-unreleased-only. Without
    # prior_notes_file this stays single-file (legacy) in-place promotion.
    prior_text: Optional[str] = None
    out_notes_file = notes_file
    if prior_notes_file:
        prior_text = _read(os.path.join(repo_dir, prior_notes_file))
        out_notes_file = prior_notes_file

    new_notes = promote(
        notes_text,
        version=version,
        stage=stage,
        urgency=urgency,
        date=date,
        contributors=contributors,
        security_fixes=security_fixes,
        prior_text=prior_text,
    )

    version_text = _read(os.path.join(repo_dir, version_file))
    new_version = set_version(version_text, version, stage)

    print(
        "version.h -> VALKEY_VERSION={} VALKEY_VERSION_NUM={} VALKEY_RELEASE_STAGE={}".format(
            version, version_num(version), stage.strip().lower()
        )
    )

    if dry_run:
        print("\n===== {} (dry run) =====\n".format(out_notes_file))
        print(new_notes)
        print("\n===== {} (dry run) =====\n".format(version_file))
        print(new_version)
        return 0

    _write(os.path.join(repo_dir, out_notes_file), new_notes)
    _write(os.path.join(repo_dir, version_file), new_version)
    print("Wrote {} and {}.".format(out_notes_file, version_file))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a Valkey release: notes + version bump.")
    parser.add_argument("--version", required=True, help="Target version, e.g. 9.1.0")
    parser.add_argument("--stage", required=True, help="Release stage: rc1..rcN or ga")
    parser.add_argument(
        "--urgency",
        required=True,
        help="Upgrade urgency: LOW, MODERATE, HIGH, CRITICAL, or SECURITY",
    )
    parser.add_argument(
        "--date", default=None, help="Release date YYYY-MM-DD (default: today)"
    )
    parser.add_argument("--repo", required=True, help="owner/name, e.g. valkey-io/valkey")
    parser.add_argument(
        "--base-ref",
        default=None,
        help="Contributor range start (default: most recent tag reachable from HEAD)",
    )
    parser.add_argument(
        "--token", default=os.environ.get("GITHUB_TOKEN"), help="GitHub token ($GITHUB_TOKEN)"
    )
    parser.add_argument("--repo-dir", default=".", help="Repository checkout dir (default: .)")
    parser.add_argument("--notes-file", default="00-RELEASENOTES")
    parser.add_argument(
        "--prior-notes-file",
        default=None,
        help="Destination changelog to prepend the new dated section to (the running "
        "pre-release branch's 00-RELEASENOTES). When set, bullets are drained from "
        "--notes-file (the base branch) into this file, written frozen (no ## Unreleased "
        "block). Omit for in-place single-file promotion.",
    )
    parser.add_argument("--version-file", default="src/version.h")
    parser.add_argument(
        "--security-fix",
        action="append",
        default=None,
        dest="security_fixes",
        help="A Security Fixes bullet (repeatable), e.g. '(CVE-2026-12345) ...'",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print results without writing files"
    )
    parser.add_argument(
        "--reset-unreleased-only",
        action="store_true",
        help="Only empty the ## Unreleased block (no dated section or version bump). "
        "Used to prepare the companion PR that clears the just-released notes on the "
        "unstable branch.",
    )
    args = parser.parse_args(argv)

    try:
        return run(
            version=args.version,
            stage=args.stage,
            urgency=args.urgency,
            date=args.date,
            repo=args.repo,
            base_ref=args.base_ref,
            token=args.token,
            repo_dir=args.repo_dir,
            notes_file=args.notes_file,
            version_file=args.version_file,
            security_fixes=args.security_fixes,
            dry_run=args.dry_run,
            reset_unreleased_only=args.reset_unreleased_only,
            prior_notes_file=args.prior_notes_file,
        )
    except ValueError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
