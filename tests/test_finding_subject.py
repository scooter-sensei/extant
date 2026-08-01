"""Findings carry the token they are about, so a consumer need not parse prose.

`--deleted-since` has to ask "does this claim still appear anywhere". The token
lives inside the detail's English, and scraping backticks out of a sentence is
the reason-about-the-wording trap this project keeps being bitten by. Carrying
it in the data is the fix.
"""
from __future__ import annotations

import sys
from pathlib import Path

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))

DEAD = "dead" + "0" * 36


def test_a_backticked_dead_sha_names_its_token(git_repo) -> None:
    import extant_collect as hc
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")

    findings = hc.validate_shas(repo, f"Shipped in `{DEAD}`.\n")
    assert findings, "the fixture must produce a finding or this proves nothing"
    assert findings[0].kind == "dead-sha", findings[0]
    assert findings[0].subject == DEAD, findings[0]


def test_a_bare_dead_sha_names_its_token(git_repo) -> None:
    import extant_collect as hc
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")

    findings = hc.validate_shas(repo, f"Shipped in {DEAD} last week.\n")
    bare = [f for f in findings if f.kind == "bare-dead-sha"]
    assert bare, f"the fixture produced {[f.kind for f in findings]}"
    assert bare[0].subject == DEAD, bare[0]


def test_subject_defaults_to_none(git_repo) -> None:
    """Optional on purpose. It is populated rule by rule, and the mode that
    consumes it reports how many findings it had to skip - so partial coverage
    stays visible rather than silently narrowing what that mode can see."""
    import extant_collect as hc
    assert hc.Finding(1, "dead-sha", "detail").subject is None


def test_subject_does_not_disturb_the_fingerprint(git_repo) -> None:
    """The baseline keys on (path, kind, detail). Folding a new field in would
    invalidate every recorded baseline in every project that has one."""
    import extant_collect as hc
    without = hc.Finding(1, "dead-sha", "detail")
    with_subject = hc.Finding(1, "dead-sha", "detail", subject="abc1234")
    assert (hc._fingerprint("d.md", without.kind, without.detail)
            == hc._fingerprint("d.md", with_subject.kind, with_subject.detail))
