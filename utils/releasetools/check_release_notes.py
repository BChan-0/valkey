#!/usr/bin/env python3
"""CI check: enforce release-notes labelling and Unreleased edits on PRs.

Runs from .github/workflows/release-notes-check.yml for PRs targeting the
``unstable`` branch. Three rules:

1. A PR must carry exactly one of the labels ``release-notes`` or
   ``no-release-notes``. Zero labels or both is a failure.
2. If labelled ``release-notes``, the PR must add at least one new bullet to
   the ``## Unreleased`` block of 00-RELEASENOTES (compared against its merge
   base), so a user-facing change cannot ship without a note. Conversely, if
   labelled ``no-release-notes`` it must add *no* new bullet, since the label
   claims there is nothing to release-note yet prepare-release.yml would still
   promote any bullet it finds. (The net-new check needs a base to diff
   against, so it is only enforced when BASE_SHA is supplied, as it always is
   in CI.)
3. A net-new bullet whose trailing ``(#N)`` references a PR number other than
   this PR's is a mislabel and fails the check. A bullet that credits a handle
   other than the PR author is only a warning, since release notes may
   legitimately credit a co-author or proxy contributor.

Inputs come from the environment so the workflow can pass GitHub Actions
context directly:

    PR_LABELS         JSON array of label names (toJSON(... .labels.*.name))
    BASE_SHA          merge-base SHA to diff 00-RELEASENOTES against (rule 2)
    PR_NUMBER         this PR's number; used to suggest appending "(#N)" to a
                      new bullet that lacks a PR reference (optional)
    PR_AUTHOR         this PR's author login; used to suggest appending
                      "by @handle" to a new bullet that lacks one (optional)
    RELEASE_NOTES_FILE  path to the notes file (default: 00-RELEASENOTES)
    GITHUB_STEP_SUMMARY path the job-summary markdown is appended to (optional)

Exits 0 when both rules pass, 1 on any violation, 2 on unexpected error.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter
from typing import Dict, List, Optional, Tuple

try:  # Allow both `python -m` and direct-script execution.
    from release_notes import count_bullets, parse_unreleased
except ImportError:  # pragma: no cover - import shim
    from utils.releasetools.release_notes import count_bullets, parse_unreleased  # type: ignore

RELEASE_LABEL = "release-notes"
NO_RELEASE_LABEL = "no-release-notes"
DEFAULT_FILE = "00-RELEASENOTES"

# Matches a "(#123)" PR reference anywhere in a bullet. The capturing group
# yields the bare number so we can both detect references (truthy `search`) and
# extract them (`findall`) to compare against this PR's number.
_PR_REF_RE = re.compile(r"\(#(\d+)\)")

# Matches a "by @handle" author attribution anywhere in a bullet. The capturing
# group yields the handle so we can compare it against this PR's author.
_AUTHOR_RE = re.compile(r"by @([\w-]+)")

# Matches a "(#123)" reference only at the END of a bullet. The canonical bullet
# form is "* <desc> by @handle (#N)", so the trailing reference is the bullet's
# own PR number; a mid-text "(#N)" is a cross-reference to another PR and must
# not be mistaken for a mislabel. Used to validate the number against this PR.
_TRAILING_PR_REF_RE = re.compile(r"\(#(\d+)\)\s*$")


def parse_labels(raw: Optional[str]) -> List[str]:
    """Parse the PR_LABELS env value (a JSON array) into a list of names."""
    if not raw or not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Be lenient: accept a comma-separated fallback.
        return [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(data, list):
        return [str(item).strip() for item in data if str(item).strip()]
    return []


def _git_show(ref_path: str, repo_dir: str) -> Optional[str]:
    """Return ``git show <ref:path>`` content, or None if it does not exist."""
    try:
        return subprocess.run(
            ["git", "show", ref_path],
            cwd=repo_dir,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _all_bullets(notes: "Dict[str, List[str]]") -> List[str]:
    """Flatten a parsed Unreleased map into a single list of bullet strings."""
    bullets: List[str] = []
    for category_bullets in notes.values():
        bullets.extend(category_bullets)
    return bullets


def _new_bullets(head_text: str, base_text: Optional[str]) -> List[str]:
    """Return bullets present in *head_text* but not in *base_text*.

    Compared as a multiset so an added duplicate still counts as new, while
    bullets carried over from the base are not re-suggested. When there is no
    base text (new file or unknown base) every head bullet is considered new.
    """
    head = _all_bullets(parse_unreleased(head_text))
    if base_text is None:
        return head
    base_counts = Counter(_all_bullets(parse_unreleased(base_text)))
    new: List[str] = []
    for bullet in head:
        if base_counts.get(bullet, 0) > 0:
            base_counts[bullet] -= 1
        else:
            new.append(bullet)
    return new


def _suggest_pr_refs(new_bullets: List[str], pr_number: Optional[str]) -> List[str]:
    """Build "suggested edit" lines for new bullets that lack a ``(#N)`` ref.

    Returns markdown lines (possibly empty) prompting the contributor to append
    this PR's number to each net-new bullet that does not already reference one.
    """
    if not pr_number:
        return []
    needing = [b for b in new_bullets if not _PR_REF_RE.search(b)]
    if not needing:
        return []
    lines = [
        "",
        "ℹ️ Suggested edit: append this PR's number to your new bullet(s) so the "
        "note links back here. Update {} to:".format(DEFAULT_FILE),
        "",
    ]
    for bullet in needing:
        lines.append("    {} (#{})".format(bullet.rstrip(), pr_number))
    return lines


def _suggest_authors(new_bullets: List[str], pr_author: Optional[str]) -> List[str]:
    """Build "suggested edit" lines for new bullets that lack a ``by @handle``.

    Returns markdown lines (possibly empty) prompting the contributor to append
    this PR author's handle to each net-new bullet that does not already carry
    an attribution, keeping the canonical ``* ... by @handle`` bullet format.
    """
    if not pr_author:
        return []
    needing = [b for b in new_bullets if not _AUTHOR_RE.search(b)]
    if not needing:
        return []
    lines = [
        "",
        "ℹ️ Suggested edit: append the author handle to your new bullet(s) so the "
        "note credits the contributor. Update {} to:".format(DEFAULT_FILE),
        "",
    ]
    attribution = "by @{}".format(pr_author)
    for bullet in needing:
        text = bullet.rstrip()
        # Keep the canonical "* description by @handle (#N)" order: when a PR
        # reference is already present, insert the attribution before it rather
        # than after.
        ref_match = _PR_REF_RE.search(text)
        if ref_match:
            suggestion = "{} {} {}".format(
                text[: ref_match.start()].rstrip(), attribution, text[ref_match.start() :]
            )
        else:
            suggestion = "{} {}".format(text, attribution)
        lines.append("    {}".format(suggestion))
    return lines


def _check_pr_refs(new_bullets: List[str], pr_number: Optional[str]) -> List[str]:
    """Return failure lines for new bullets whose trailing ``(#N)`` is wrong.

    The canonical bullet form ends with this PR's own number, so a trailing
    ``(#N)`` that does not match *pr_number* is a mislabel (e.g. a copy/pasted
    bullet still pointing at another PR). Mid-text ``(#N)`` cross-references are
    ignored. Returns ``[]`` when nothing is wrong or *pr_number* is unknown.
    """
    if not pr_number:
        return []
    wrong: List[Tuple[str, str]] = []
    for bullet in new_bullets:
        match = _TRAILING_PR_REF_RE.search(bullet)
        if match and match.group(1) != pr_number:
            wrong.append((bullet.rstrip(), match.group(1)))
    if not wrong:
        return []
    lines = [
        "❌ {} new bullet(s) reference a PR number that is not this PR "
        "(#{}). Fix the trailing `(#N)` to match this PR:".format(len(wrong), pr_number),
        "",
    ]
    for text, found in wrong:
        lines.append("    {}  ← says (#{}), expected (#{})".format(text, found, pr_number))
    return lines


def _check_authors(new_bullets: List[str], pr_author: Optional[str]) -> List[str]:
    """Return warning lines for new bullets crediting someone other than the author.

    Release notes may legitimately credit a co-author or proxy contributor, so a
    mismatch is a *warning*, not a failure: it surfaces the likely-wrong handle
    without blocking. Returns ``[]`` when nothing is suspect or *pr_author* is
    unknown.
    """
    if not pr_author:
        return []
    suspect: List[Tuple[str, List[str]]] = []
    for bullet in new_bullets:
        handles = _AUTHOR_RE.findall(bullet)
        if handles and pr_author not in handles:
            suspect.append((bullet.rstrip(), handles))
    if not suspect:
        return []
    lines = [
        "",
        "⚠️ {} new bullet(s) credit a handle other than this PR's author "
        "(@{}). This is allowed (e.g. crediting a co-author), but double-check "
        "the attribution is intentional:".format(len(suspect), pr_author),
        "",
    ]
    for text, handles in suspect:
        credited = ", ".join("@{}".format(h) for h in handles)
        lines.append("    {}  ← credits {}, not @{}".format(text, credited, pr_author))
    return lines


def evaluate(
    labels: List[str],
    *,
    base_sha: Optional[str],
    notes_file: str = DEFAULT_FILE,
    repo_dir: str = ".",
    pr_number: Optional[str] = None,
    pr_author: Optional[str] = None,
) -> Tuple[bool, List[str]]:
    """Apply both rules. Return ``(ok, messages)``.

    *messages* always carries human-readable lines describing the outcome
    (failures and the passing summary) for the job summary.
    """
    messages: List[str] = []
    has_release = RELEASE_LABEL in labels
    has_no_release = NO_RELEASE_LABEL in labels

    # Rule 1: exactly one of the two labels.
    if has_release and has_no_release:
        messages.append(
            "❌ PR has both `{}` and `{}` labels. Keep exactly one.".format(
                RELEASE_LABEL, NO_RELEASE_LABEL
            )
        )
        return False, messages
    if not has_release and not has_no_release:
        messages.append(
            "❌ PR is missing a release-notes decision. Add either the `{}` label "
            "(and a note under `## Unreleased` in {}) or the `{}` label.".format(
                RELEASE_LABEL, notes_file, NO_RELEASE_LABEL
            )
        )
        return False, messages

    # A `no-release-notes` PR with no base to diff against can't be attributed
    # any bullets (the Unreleased block already carries earlier PRs' entries),
    # so there is nothing to enforce -- pass without reading the file.
    if has_no_release and not base_sha:
        messages.append(
            "✅ PR is labelled `{}`; no release note required.".format(NO_RELEASE_LABEL)
        )
        return True, messages

    # Both remaining rules need to know what this PR added to the Unreleased
    # block, so read the file and diff bullets against the base once, up front.
    try:
        with open(os.path.join(repo_dir, notes_file), "r", encoding="utf-8") as fh:
            head_text = fh.read()
    except OSError as exc:
        messages.append("❌ Could not read {}: {}".format(notes_file, exc))
        return False, messages

    head_count = count_bullets(parse_unreleased(head_text))

    base_text: Optional[str] = None
    base_count = 0
    if base_sha:
        base_text = _git_show("{}:{}".format(base_sha, notes_file), repo_dir)
        if base_text is not None:
            base_count = count_bullets(parse_unreleased(base_text))

    if has_no_release:
        # The label says there is nothing to note, but prepare-release.yml would
        # still promote any new entry, so a net-new bullet contradicts the label.
        if head_count > base_count:
            messages.append(
                "❌ PR is labelled `{}` but adds {} new entry/entries to the "
                "`## Unreleased` block of {}. Either drop the new bullet(s) or "
                "switch to the `{}` label.".format(
                    NO_RELEASE_LABEL, head_count - base_count, notes_file, RELEASE_LABEL
                )
            )
            return False, messages
        messages.append(
            "✅ PR is labelled `{}`; no release note required.".format(NO_RELEASE_LABEL)
        )
        return True, messages

    # Rule 2: release-notes label requires a new Unreleased bullet.
    if head_count <= base_count:
        messages.append(
            "❌ PR is labelled `{}` but adds no new entry to the `## Unreleased` block "
            "of {} (found {} bullet(s), base had {}). Add a bullet under the matching "
            "`### Category`, e.g. `* My change by @handle`. Once your PR is open you "
            "can edit the bullet to add its number, e.g. `(#1234)`.".format(
                RELEASE_LABEL, notes_file, head_count, base_count
            )
        )
        return False, messages

    new_bullets = _new_bullets(head_text, base_text)

    # A net-new bullet that references the wrong PR number is a
    # mislabel, so block on it before reporting success.
    wrong_ref_lines = _check_pr_refs(new_bullets, pr_number)
    if wrong_ref_lines:
        return False, wrong_ref_lines

    messages.append(
        "✅ PR is labelled `{}` and adds {} new release-note bullet(s).".format(
            RELEASE_LABEL, head_count - base_count
        )
    )
    messages.extend(_suggest_pr_refs(new_bullets, pr_number))
    messages.extend(_suggest_authors(new_bullets, pr_author))
    # Crediting a different handle is allowed; surface it as a warning only.
    messages.extend(_check_authors(new_bullets, pr_author))
    return True, messages


def _emit_summary(ok: bool, messages: List[str]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = ["## Release notes check", ""]
    lines.extend(messages)
    try:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        pass


def main(argv=None) -> int:
    labels = parse_labels(os.environ.get("PR_LABELS"))
    base_sha = os.environ.get("BASE_SHA") or None
    notes_file = os.environ.get("RELEASE_NOTES_FILE", DEFAULT_FILE)
    pr_number = os.environ.get("PR_NUMBER") or None
    pr_author = os.environ.get("PR_AUTHOR") or None

    try:
        ok, messages = evaluate(
            labels,
            base_sha=base_sha,
            notes_file=notes_file,
            pr_number=pr_number,
            pr_author=pr_author,
        )
    except Exception as exc:  # noqa: BLE001 - surface any unexpected failure clearly
        print("error: {}".format(exc), file=sys.stderr)
        return 2

    for message in messages:
        print(message)
    _emit_summary(ok, messages)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
