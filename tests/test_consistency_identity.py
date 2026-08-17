"""A consistency block reaching one file by two routes compares nothing.

The guard in `extant/config.py` is a STRING comparison at config-load time. It
normalises `docs/x.md` and `docs/./x.md` to one key and rejects the block. It
cannot normalise a symlink, a hardlink, or a case variant on a case-insensitive
filesystem, because it never touches the filesystem - so such a block passes
forever while appearing to compare two things.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))

VERSION = re.compile(r'"version": "([^"]+)"')


def test_two_routes_to_one_file_are_reported(git_repo, monkeypatch) -> None:
    """A symlink is a genuinely different route to the same bytes."""
    from extant import session as hc
    from extant.rules import consistency as rule_consistency
    from extant.rules import consistency as rule
    repo, commit = git_repo
    commit("version.json", '{"version": "1.2.3"}\n', "chore: init")
    link = repo / "alias.json"
    try:
        link.symlink_to(repo / "version.json")
    except (OSError, NotImplementedError):
        pytest.skip("this platform does not permit symlink creation here")

    monkeypatch.setattr(rule, "_consistency_for", lambda _ctx: {
        "version": (("version.json", VERSION), ("alias.json", VERSION)),
    })

    details = [f.detail for f in rule_consistency.check(hc.context(repo), "")]
    assert any("the same file" in d for d in details), (
        "a block comparing a file with itself must say so: " + str(details)
    )


def _case_insensitive(directory: Path) -> bool:
    """Does this filesystem reach one file by two spellings of its name?"""
    probe = directory / "CaseProbe.tmp"
    probe.write_text("x", encoding="utf-8")
    try:
        return (directory / "caseprobe.tmp").is_file()
    finally:
        probe.unlink(missing_ok=True)


def test_a_case_variant_reaches_the_same_file(git_repo, monkeypatch) -> None:
    """The route that exists on Windows and macOS, where symlinks often do not.

    `os.path.normpath` does not fold case, so the string guard at config load
    accepts `version.json` and `VERSION.JSON` as two files. On a
    case-insensitive filesystem they are one, and the check agrees with itself
    forever.
    """
    from extant import session as hc
    from extant.rules import consistency as rule_consistency
    from extant.rules import consistency as rule
    repo, commit = git_repo
    commit("version.json", '{"version": "1.2.3"}\n', "chore: init")
    if not _case_insensitive(repo):
        pytest.skip("this filesystem is case-sensitive; the symlink test covers it")

    monkeypatch.setattr(rule, "_consistency_for", lambda _ctx: {
        "version": (("version.json", VERSION), ("VERSION.JSON", VERSION)),
    })

    details = [f.detail for f in rule_consistency.check(hc.context(repo), "")]
    assert any("the same file" in d for d in details), (
        "two case spellings of one file on a case-insensitive filesystem must "
        "be reported as one: " + str(details)
    )


def test_two_genuinely_different_files_are_not_reported(git_repo, monkeypatch) -> None:
    """The control.

    Without it an identity function returning a constant would satisfy the test
    above and report every consistency block in every project as
    self-comparing, which is a false positive on every run.
    """
    from extant import session as hc
    from extant.rules import consistency as rule_consistency
    from extant.rules import consistency as rule
    repo, commit = git_repo
    commit("a.json", '{"version": "1.2.3"}\n', "chore: a")
    commit("b.json", '{"version": "1.2.3"}\n', "chore: b")

    monkeypatch.setattr(rule, "_consistency_for", lambda _ctx: {
        "version": (("a.json", VERSION), ("b.json", VERSION)),
    })

    details = [f.detail for f in rule_consistency.check(hc.context(repo), "")]
    assert not any("the same file" in d for d in details), details


def test_a_real_disagreement_is_still_reported(git_repo, monkeypatch) -> None:
    """The second control. The new check sits in front of the comparison and
    `continue`s past it, so getting the guard wrong would silence the rule's
    actual job rather than merely adding noise."""
    from extant import session as hc
    from extant.rules import consistency as rule_consistency
    from extant.rules import consistency as rule
    repo, commit = git_repo
    commit("a.json", '{"version": "1.2.3"}\n', "chore: a")
    commit("b.json", '{"version": "9.9.9"}\n', "chore: b")

    monkeypatch.setattr(rule, "_consistency_for", lambda _ctx: {
        "version": (("a.json", VERSION), ("b.json", VERSION)),
    })

    details = [f.detail for f in rule_consistency.check(hc.context(repo), "")]
    assert any("disagree" in d for d in details), details


def test_identity_discriminates_before_it_is_trusted(tmp_path) -> None:
    """`st_ino` is 0 on FAT32 and on some network shares.

    Keyed naively on `(st_dev, st_ino)` every file on such a volume compares
    equal, and the check would report self-comparison on every configuration -
    a false positive on every run, which is worse than the hole it closes.
    """
    from extant import session as hc
    from extant.rules import consistency as rule_consistency
    from extant.rules import consistency as rule
    one = tmp_path / "one.txt"
    two = tmp_path / "two.txt"
    one.write_text("1\n", encoding="utf-8")
    two.write_text("2\n", encoding="utf-8")

    assert rule_consistency._file_identity(one) != rule_consistency._file_identity(two), (
        "the identity function cannot tell two different files apart, so every "
        "result built on it is meaningless"
    )
    assert rule_consistency._file_identity(one) == rule_consistency._file_identity(one)
