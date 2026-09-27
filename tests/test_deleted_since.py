"""Claims removed while still false are reported, and never gate.

The mechanism is one idea: take each configured document as it stood at `ref`
and validate it against TODAY's git. Every finding that survives is a claim
which is false right now, so there is no separate "is it still false" step.

This mode does not gate, and that is a design decision rather than caution.
Whether a deletion is evasion or repair is a question about intent, and git
cannot settle it - a document that deletes a false claim now tells the truth,
which is the tool's whole purpose. Reporting the fact is falsifiable. Judging
it is not, so a human does that.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))

DEAD = "dead" + "0" * 36
OTHER = "beef" + "1" * 36
ENTRY = "# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n{}\n\n## 1. Ref\n"


def _run(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout


def test_a_deleted_false_claim_is_reported(git_repo) -> None:
    from extant import session as hc
    from extant import deleted_since
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format(f"Merged at `{DEAD}`."), "docs: claim")
    commit("NEXT_SESSION.md", ENTRY.format("Nothing to see here."), "docs: remove")

    gone, examined, _skipped, _bad = deleted_since.deleted_claims(repo, "HEAD~1")
    assert examined == 1, f"examined {examined} documents"
    assert [f for f in gone if f.finding.subject == DEAD], [f.finding for f in gone]


def test_a_claim_that_became_true_is_not_reported(git_repo) -> None:
    """The mechanism's whole point, and the reason there is no separate
    still-false check. Validating the OLD text against TODAY's git means a
    claim whose underlying fact was fixed produces no finding to begin with."""
    from extant import session as hc
    from extant import deleted_since
    repo, commit = git_repo
    commit("NEXT_SESSION.md",
           ENTRY.format("Work continues on `feature/pending`."), "docs: claim")
    commit("NEXT_SESSION.md", ENTRY.format("Done."), "docs: remove")
    # The branch now exists, so the old text's claim is true today.
    _run(repo, "branch", "feature/pending")

    gone, _examined, _skipped, _bad = deleted_since.deleted_claims(repo, "HEAD~1")
    assert not [f for f in gone if "feature/pending" in f.finding.detail], (
        [f.finding.detail for f in gone]
    )


def test_relocating_to_the_archive_is_not_a_deletion(git_repo) -> None:
    """`--archive` moves entries out of the live document by design. The token
    stays findable, so archiving must not look like hiding."""
    from extant import session as hc
    from extant import deleted_since
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format(f"Merged at `{DEAD}`."), "docs: claim")
    commit("docs/status-archive.md",
           f"# Archive\n\n## Phase 1 - x (shipped, 2026-01-01)\n\nMerged at `{DEAD}`.\n",
           "docs: archive it")
    commit("NEXT_SESSION.md", ENTRY.format("Moved to the archive."), "docs: relocate")

    gone, _examined, _skipped, _bad = deleted_since.deleted_claims(repo, "HEAD~1")
    assert not [f for f in gone if f.finding.subject == DEAD], (
        "the token is still findable in the archive: " + str([f.finding for f in gone])
    )


def test_moving_a_claim_into_a_fence_is_a_deletion(git_repo) -> None:
    """Fenced code is exempt from every claim rule, so a fence silences them
    all. Without prose-scoping on the haystack it would silence this too."""
    from extant import session as hc
    from extant import deleted_since
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format(f"Merged at `{DEAD}`."), "docs: claim")
    commit("NEXT_SESSION.md",
           ENTRY.format(f"```\nMerged at `{DEAD}`.\n```"), "docs: hide it")

    gone, _examined, _skipped, _bad = deleted_since.deleted_claims(repo, "HEAD~1")
    assert [f for f in gone if f.finding.subject == DEAD], (
        "a claim moved into a fence is still a claim withdrawn from prose"
    )


def test_an_unchanged_document_is_not_re_read(git_repo) -> None:
    """Cost, and correctness. A document that did not change cannot have lost
    a claim, so skipping it is not merely an optimisation."""
    from extant import session as hc
    from extant import deleted_since
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format(f"Merged at `{DEAD}`."), "docs: claim")
    commit("other.txt", "unrelated\n", "chore: touch something else")

    _gone, examined, _skipped, _bad = deleted_since.deleted_claims(repo, "HEAD~1")
    assert examined == 0, "the document did not change; it must not be re-read"


def test_the_mode_never_gates(git_repo, capsys) -> None:
    from extant import session as hc
    from extant import deleted_since
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format(f"Merged at `{DEAD}`."), "docs: claim")
    commit("NEXT_SESSION.md", ENTRY.format("Gone."), "docs: remove")

    assert deleted_since.run_deleted_since(repo, "HEAD~1", "text") == 0
    printed = capsys.readouterr()
    assert "examined" in printed.out + printed.err, "the denominator must print"


def test_a_rule_that_raises_is_named_even_though_the_mode_never_gates(
        git_repo, capsys, monkeypatch) -> None:
    """The gap `run_sweep` and `--validate` already closed, missing here.

    `deleted_claims` calls `session.validate()` once per changed document, the
    same call `cli.main()` makes for `--validate` and `run_sweep` makes per
    swept file - and both of those name a crashed rule in their output, beside
    the denominator, per registry.py's RULE_ERRORS contract. This mode never
    reported it: `session.validate()` still records the failure in
    RULE_ERRORS, but nothing here ever called `session.report_rule_errors`, so
    a rule that failed to look printed no differently from a rule that looked
    and found nothing.

    Non-gating is correct and deliberate here - see the module docstring - so
    this does NOT assert a non-zero exit, unlike the equivalent test in
    test_rule_contract.py. It only asserts the failure is SAID.
    """
    from extant import session as hc
    from extant import deleted_since

    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format(f"Merged at `{DEAD}`."), "docs: claim")
    commit("NEXT_SESSION.md", ENTRY.format("Gone."), "docs: remove")

    def explode(ctx, text):
        raise RuntimeError("deliberate")

    import dataclasses

    broken = dataclasses.replace(hc.RULES[0], check=explode)
    monkeypatch.setattr(hc, "RULES", (broken,) + hc.RULES[1:])

    code = deleted_since.run_deleted_since(repo, "HEAD~1", "text")
    printed = capsys.readouterr()
    combined = printed.out + printed.err

    assert code == 0, (
        "this mode must never gate, crashed rule or not - see the module "
        "docstring on why intent is not this tool's to judge")
    assert "ERRORED" in combined and broken.kind in combined, (
        f"the crashed rule was not named in the output, so its silence is "
        f"indistinguishable from a clean run finding nothing to report:\n"
        f"{combined}")
    assert "RuntimeError: deliberate" in combined, (
        f"the exception was recorded without saying what it was:\n{combined}")


def test_a_missing_ref_is_reported_not_crashed(git_repo, capsys) -> None:
    from extant import session as hc
    from extant import deleted_since
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format("x"), "docs: init")

    assert deleted_since.run_deleted_since(repo, "no-such-ref", "text") == 0
    printed = capsys.readouterr()
    assert "examined" in printed.out + printed.err


def test_sarif_stdout_is_a_document_even_with_nothing_to_report(
        git_repo, capsys) -> None:
    """SARIF's contract is that stdout is one valid document, always.

    A machine consumer handed zero bytes fails its upload rather than reading
    "no results", so a clean run looks exactly like a broken one. `--sweep` and
    `--validate` both emit an empty document here; this mode emitted nothing
    at all until it was measured against them.
    """
    import json
    from extant import session as hc
    from extant import deleted_since
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format("Nothing wrong."), "docs: init")

    assert deleted_since.run_deleted_since(repo, "HEAD", "sarif") == 0
    printed = capsys.readouterr()
    parsed = json.loads(printed.out)
    assert parsed["runs"][0]["results"] == [], parsed["runs"][0]["results"]
    assert "examined" in printed.err, (
        "the denominator belongs on stderr in SARIF mode, or it corrupts the "
        "document on stdout"
    )


def test_a_correction_that_swaps_the_token_is_reported(git_repo) -> None:
    """Recorded deliberately, so nobody later 'fixes' it into a heuristic.

    Replacing a dead SHA with a different dead SHA removes the first one, and
    the first one is still dead. From git's side that is indistinguishable
    from hiding it, and guessing which it was is exactly the intent question
    this mode refuses to answer. It reports; the reader decides. This is also
    why it does not gate.
    """
    from extant import session as hc
    from extant import deleted_since
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format(f"Merged at `{DEAD}`."), "docs: claim")
    commit("NEXT_SESSION.md", ENTRY.format(f"Merged at `{OTHER}`."), "docs: swap")

    gone, _examined, _skipped, _bad = deleted_since.deleted_claims(repo, "HEAD~1")
    assert [f for f in gone if f.finding.subject == DEAD], (
        "the removed token is still dead, so it is reported"
    )


# --- 4.10: every previous version in one batch, one scope across them ------
#
# The review's item, and its decider: git processes per run, which was one
# `git show` per changed document. Measured on this repository before the
# change, `--deleted-since v0.26.1` started 10 for 4 documents - the four
# reads, the diff, one SHA batch, and the ref table and trunk index TWICE,
# because `deleted_claims` opened no run scope and `validate()` opened a
# fresh one per old document. The tests below pin both halves.


def _counted(monkeypatch) -> list[str]:
    """Every git command line started, recorded at the subprocess boundary -
    the only vantage that sees the stdin-fed batches as well as the seam."""
    spawns: list[str] = []
    real = subprocess.run

    def counted(cmd, *a, **kw):
        if cmd and str(cmd[0]) == "git":
            spawns.append(" ".join(str(c) for c in cmd[1:]))
        return real(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "run", counted)
    return spawns


def test_every_changed_document_is_read_in_one_batch(git_repo, monkeypatch) -> None:
    """Three changed documents, ONE `cat-file --batch`, and no `git show`.

    Fails the moment a read goes back to one process per document, which is
    the shape this replaced: N documents cost N spawns of about 25 ms each,
    on a mode whose whole population is one configured status document and
    its extras.
    """
    from extant import session as hc
    from extant import deleted_since
    repo, commit = git_repo
    commit(".extant.toml", 'extra_docs = ["A.md", "B.md"]\n', "chore: config")
    commit("NEXT_SESSION.md", ENTRY.format(f"Merged at `{DEAD}`."), "docs: claim")
    commit("A.md", f"# A\n\nSee `docs/gone-a.md` and `{DEAD}`.\n", "docs: a")
    commit("B.md", f"# B\n\nSee `docs/gone-b.md` and `{OTHER}`.\n", "docs: b")
    commit("NEXT_SESSION.md", ENTRY.format("Nothing."), "docs: remove")
    commit("A.md", "# A\n\nNothing.\n", "docs: a2")
    commit("B.md", "# B\n\nNothing.\n", "docs: b2")
    hc.reload_config(repo)
    spawns = _counted(monkeypatch)

    gone, examined, _skipped, unreadable = deleted_since.deleted_claims(repo, "HEAD~3")

    assert (examined, unreadable) == (3, 0), (examined, unreadable)
    subjects = {f.finding.subject for f in gone}
    assert {DEAD, OTHER, "docs/gone-a.md", "docs/gone-b.md"} <= subjects, subjects
    shows = [c for c in spawns if c.startswith("show ")]
    batches = [c for c in spawns if c == "cat-file --batch"]
    print(f"{len(spawns)} git spawns: {spawns}")
    assert not shows, f"a previous version was read one process at a time: {shows}"
    assert len(batches) == 1, (
        f"{len(batches)} `cat-file --batch` for three documents; the previous "
        f"versions are read in ONE batch, in the order the documents are "
        f"configured")


def test_the_ref_table_is_built_once_across_the_documents_it_reads(
        git_repo, monkeypatch) -> None:
    """Two old documents both make a merge claim; the ref table and the
    trunk index are asked ONCE, not once per document.

    `deleted_claims` validates every changed document against today's git
    from one static checkout and writes nothing, which is exactly the promise
    `run_scope()` asks a caller to make - and it never made it, so each
    `validate()` opened a fresh scope and re-asked what the last one learned.
    The deleted `with session.run_scope():` this pins is the same regression
    `test_spawn_budget.py` pins for `--verify`.
    """
    from extant import session as hc
    from extant import deleted_since
    repo, commit = git_repo
    # REAL commits, so the rule resolves the SHA and goes on to ask which
    # branches hold it - a dead SHA is reported before the ref table is
    # needed, and a fixture built on one would count nothing.
    first = commit(".extant.toml", 'extra_docs = ["A.md"]\n', "chore: config")[:9]
    second = commit("NEXT_SESSION.md",
                    ENTRY.format(f"The work was merged to `main` at `{first}`."),
                    "docs: claim")[:9]
    commit("A.md", f"# A\n\nThe fix was merged to `main` at `{second}`.\n", "docs: a")
    commit("NEXT_SESSION.md", ENTRY.format("Nothing."), "docs: remove")
    commit("A.md", "# A\n\nNothing.\n", "docs: a2")
    hc.reload_config(repo)
    spawns = _counted(monkeypatch)

    _gone, examined, _skipped, _bad = deleted_since.deleted_claims(repo, "HEAD~2")

    assert examined == 2, examined
    tables = [c for c in spawns if c.startswith("for-each-ref ")]
    trunk = [c for c in spawns if c.startswith("rev-list -n ")]
    print(f"{len(spawns)} git spawns: {spawns}")
    assert len(tables) == 1, (
        f"the ref table was built {len(tables)} times for 2 documents; one "
        f"run scope spans the loop, so it is built once")
    assert len(trunk) <= 1, (
        f"the trunk index was built {len(trunk)} times; it is memoised per "
        f"run scope, so more than once means the scope is not held")


def test_a_missing_object_beside_a_present_one_counts_one_and_examines_the_other(
        tmp_path) -> None:
    """In a `blob:none` copy the batch answers `missing` for one document's
    old version and hands back the other's, and the two are counted apart.

    A batch that stopped at the first `missing`, or read every answer as the
    first document's, would lose exactly the deleted claim in the document
    whose old blob IS here. The present one is here because its old content
    is byte-identical to a live file the checkout fetched - same content,
    same object - which is the one way an old version's blob reaches a
    partial copy without the transport.
    """
    from conftest import committer, init_repo
    from extant import session as hc
    from extant import deleted_since

    old_extra = "# Extra\n\nSee `docs/vanished.md` for the detail.\n"
    source = tmp_path / "source"
    init_repo(source)
    commit = committer(source)
    commit(".extant.toml", 'extra_docs = ["EXTRA.md"]\n', "chore: config")
    commit("keep.md", old_extra, "docs: keep")
    commit("EXTRA.md", old_extra, "docs: extra")
    commit("NEXT_SESSION.md", ENTRY.format(f"Merged at `{DEAD}`."), "docs: claim")
    commit("EXTRA.md", "# Extra\n\nNothing now.\n", "docs: extra2")
    commit("NEXT_SESSION.md", ENTRY.format("Nothing."), "docs: remove")
    _run(source, "config", "uploadpack.allowFilter", "true")
    partial = tmp_path / "partial"
    subprocess.run(["git", "clone", "-q", "--filter=blob:none",
                    "file://" + source.as_posix(), str(partial)],
                   check=True, capture_output=True)
    hc.reload_config(partial)

    gone, examined, _skipped, unreadable = deleted_since.deleted_claims(
        partial, "HEAD~2")

    print(f"examined={examined} unreadable={unreadable} "
          f"gone={[f.finding.subject for f in gone]}")
    assert (examined, unreadable) == (1, 1), (
        f"one old version is a missing object and one is held: examined "
        f"{examined}, unreadable {unreadable}")
    assert [f for f in gone if f.finding.subject == "docs/vanished.md"], (
        [f.finding for f in gone])


def test_an_undecodable_previous_version_beside_a_valid_one_is_counted_apart(
        git_repo) -> None:
    """One old version is latin-1, the other is valid: examined 1, unreadable
    1, and the valid one's deleted claim is reported. Decoding happens per
    document AFTER the batch, so one bad document cannot take the others
    with it - or, worse, be decoded with replacement into text the file
    never held."""
    from extant import session as hc
    from extant import deleted_since
    repo, commit = git_repo
    commit(".extant.toml", 'extra_docs = ["A.md"]\n', "chore: config")
    commit("NEXT_SESSION.md", ENTRY.format(f"Merged at `{DEAD}`."), "docs: claim")
    (repo / "A.md").write_bytes(b"# A\n\ncaf\xe9 and `docs/gone.md`\n")
    _run(repo, "add", "A.md")
    _run(repo, "commit", "-m", "docs: latin-1")
    commit("NEXT_SESSION.md", ENTRY.format("Nothing."), "docs: remove")
    commit("A.md", "# A\n\nNothing.\n", "docs: a2")
    hc.reload_config(repo)

    gone, examined, _skipped, unreadable = deleted_since.deleted_claims(repo, "HEAD~2")

    assert (examined, unreadable) == (1, 1), (examined, unreadable)
    assert [f for f in gone if f.finding.subject == DEAD], [f.finding for f in gone]


def test_a_directory_at_the_configured_name_is_not_a_document_there(git_repo) -> None:
    """At the ref the configured name was a DIRECTORY. `git show` printed its
    listing and the mode validated that as a document; the batch says
    `tree`, which is not a document, and the name counts as absent then."""
    from extant import session as hc
    from extant import deleted_since
    repo, commit = git_repo
    commit("NEXT_SESSION.md/inner.md", "# Inner\n", "docs: a directory")
    _run(repo, "rm", "-q", "-r", "NEXT_SESSION.md")
    _run(repo, "commit", "-q", "-m", "docs: gone")
    commit("NEXT_SESSION.md", ENTRY.format("Nothing."), "docs: a file")

    _gone, examined, _skipped, unreadable = deleted_since.deleted_claims(repo, "HEAD~2")

    assert (examined, unreadable) == (0, 0), (
        f"a tree at the name is not a previous version of the document: "
        f"examined {examined}, unreadable {unreadable}")


def test_a_name_with_a_space_that_was_absent_at_the_ref_is_absent(git_repo) -> None:
    """The batch echoes a name it could not find - `<spec> missing` - and a
    name holding a space then has a space in the header line too. A parser
    that split the header on spaces and counted three fields read
    `HEAD~1:docs/my doc.md missing` as a blob record whose size was the
    word `missing`, and crashed. The record is read from its END, where the
    type and the size are, so the name may hold whatever the filesystem
    allows short of a newline. Found by the gap audit that closed the
    tranche, not by the corpus, which configures nothing."""
    from extant import session as hc
    from extant import deleted_since
    repo, commit = git_repo
    commit(".extant.toml", 'extra_docs = ["docs/my doc.md"]\n', "chore: config")
    commit("NEXT_SESSION.md", ENTRY.format(f"Merged at `{DEAD}`."), "docs: claim")
    commit("NEXT_SESSION.md", ENTRY.format("Nothing."), "docs: remove")
    commit("docs/my doc.md", "# Mine\n\nNew here.\n", "docs: spaced")
    hc.reload_config(repo)

    gone, examined, _skipped, unreadable = deleted_since.deleted_claims(repo, "HEAD~2")

    assert (examined, unreadable) == (1, 0), (examined, unreadable)
    assert [f for f in gone if f.finding.subject == DEAD], [f.finding for f in gone]


def test_a_name_with_a_space_that_was_present_at_the_ref_is_read(git_repo) -> None:
    """The other half: present, the record for a spaced name is an ordinary
    blob record, and its old claim is read and reported."""
    from extant import session as hc
    from extant import deleted_since
    repo, commit = git_repo
    commit(".extant.toml", 'extra_docs = ["docs/my doc.md"]\n', "chore: config")
    commit("docs/my doc.md", f"# Mine\n\nSee `docs/gone.md` and `{DEAD}`.\n", "docs: spaced")
    commit("docs/my doc.md", "# Mine\n\nNothing.\n", "docs: spaced2")
    hc.reload_config(repo)

    gone, examined, _skipped, unreadable = deleted_since.deleted_claims(repo, "HEAD~1")

    assert (examined, unreadable) == (1, 0), (examined, unreadable)
    assert {f.finding.subject for f in gone} >= {DEAD, "docs/gone.md"}, (
        [f.finding for f in gone])
