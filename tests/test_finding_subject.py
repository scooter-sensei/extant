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


def _run(repo, *args):
    import subprocess
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout


def test_a_backticked_dead_sha_names_its_token(git_repo) -> None:
    import extant_collect as hc
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")

    findings = hc.validate_references(repo, f"Shipped in `{DEAD}`.\n")
    assert findings, "the fixture must produce a finding or this proves nothing"
    assert findings[0].kind == "dead-sha", findings[0]
    assert findings[0].subject == DEAD, findings[0]


def test_a_bare_dead_sha_names_its_token(git_repo) -> None:
    import extant_collect as hc
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")

    findings = hc.validate_references(repo, f"Shipped in {DEAD} last week.\n")
    bare = [f for f in findings if f.kind == "bare-dead-sha"]
    assert bare, f"the fixture produced {[f.kind for f in findings]}"
    assert bare[0].subject == DEAD, bare[0]


def test_every_document_scoped_claim_carries_a_subject(
        git_repo, reconfigure) -> None:
    """The coverage gate, and the reason it is a single test rather than one
    per rule.

    `--deleted-since` can only look for a claim whose token it knows, so a rule
    that omits `subject` is invisible to it. Measured before this was closed:
    a document with four false claims across four rules produced ONE reported
    deletion and two skips. The mode said so in its denominator, which is
    honest, and it still meant the headline feature reached a fraction of what
    it sounded like.

    Repository-scoped rules are exempt and named explicitly. `inconsistent-
    artifact` and `raw-lfs-blob` are facts about the repository rather than
    claims in a document, so no edit to prose can withdraw one and there is
    nothing for this mode to look for.
    """
    import extant_collect as hc
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    _run(repo, "checkout", "-q", "-b", "side")
    sha = commit("side.md", "# side\n", "feat: work")
    _run(repo, "checkout", "-q", "main")

    text = (
        "# Status\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
        f"Merged to `main` at `{sha}`.\n"
        f"Shipped in `{DEAD}`.\n"
        "Released in v9.9 already.\n"
        "Work continues on `feature/ghost`.\n"
        "Work is NOT yet merged on `feature/ghost`.\n"
        "**Design:** `docs/nope.md`\n"
        "See [the plan](docs/gone.md).\n"
        "Jump to [it](#no-such-heading).\n"
        "\n## 1. Ref\n"
    )
    # `dead-release-tag`'s never-tagged branch is opt-in, and this fixture
    # needs it to reach eight rule kinds. The denominator assertion below is
    # what would otherwise turn that into a quietly weaker test.
    # Through `reconfigure`, which writes the built Config as well as the
    # module global. Setting the global alone stopped reaching the rule the
    # moment it became extant/rules/release_tag.py and started reading
    # `ctx.config` - and the failure was visible only because of the
    # denominator assertion below, which fell from 8 kinds to 7. Without that
    # assertion this test would have gone on passing over a rule it no longer
    # exercised.
    #
    # `monkeypatch` undoes it, which is what stops the setting leaking into
    # every test that runs after this one in the same process - under xdist,
    # which of those saw it depended on scheduling.
    reconfigure(release_claims_are_ours=True)
    findings = hc.validate(repo, text)
    document_scoped = [f for f in findings
                       if f.kind not in ("inconsistent-artifact", "raw-lfs-blob")]

    # THE DENOMINATOR. Without it this passes just as happily on a fixture that
    # stopped producing findings, which is the shape of failure this project is
    # about: "no rule is missing a subject" and "no rule ran" read identically.
    exercised = sorted({f.kind for f in document_scoped})
    assert len(exercised) >= 8, (
        f"the fixture exercised only {len(exercised)} rule kind(s) - "
        f"{exercised} - so it cannot speak for the rest"
    )
    missing = sorted({f.kind for f in document_scoped if f.subject is None})
    assert not missing, (
        f"these rules produce findings with no subject, so --deleted-since "
        f"cannot see them: {missing}"
    )
    # And the subject must be the token, not the whole sentence.
    for finding in document_scoped:
        assert finding.subject in finding.detail, (
            f"{finding.kind}: subject {finding.subject!r} does not appear in "
            f"its own detail, so it is unlikely to be the claim's token"
        )


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
