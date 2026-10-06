"""What a zero means: every rule that examined nothing says why.

A zero in the `examined:` line has five causes, and the tool printed one
sentence for all of them - "either no document makes such claims, or the
pattern does not match how this project writes them". Measured over the 139
de-duplicated corpus sweeps on 2026-09-29, that NOTE named 1,115 zeros:

  - 642 were rules keyed on a TOKEN SHAPE, which read no pattern anybody
    sets, so "the pattern is wrong" could not be the reason;
  - 334 were rules keyed on a PHRASE, running on the shipped default because
    no `.extant.toml` set one - the reason, and the lever, went unnamed;
  - 139 were `inconsistent-artifact`, which is off until a check is
    configured - neither explanation was true of it.

And the installer, run over the 39 visible benchmark rows, left at least
three of the five pattern keys undetermined in all 39 while saying "Rules
with no pattern check nothing" - every one of them ran on the default.

The fix states the cause. A rule declares the settings its vocabulary comes
from (`Rule.settings`); the loaded settings record which keys the file sets
and which it switches off; an empty pattern is a real OFF rather than the
crash or the silent widening it was; and one classifier words every zero,
for the text output and the SARIF alike.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import GitRepo
from extant import session
from extant.config import DEFAULTS, DISABLEABLE, Config, StatusConfig, load_config
from extant.report import format_sarif
from extant.session import UNRUN_NOTE, ZERO_DEFAULT, ZERO_SET, ZERO_SHAPE

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / "plugin" / "skills" / "extant" / "payload"
PACKAGE = PAYLOAD / "extant"
COLLECTOR = PAYLOAD / "extant_collect.py"

# The settings that decide WHICH TEXT IS A CLAIM - a rule's vocabulary. The
# others a rule may read decide how a claim is JUDGED (`trunk`, the release
# opt-in, a timeout) and are not what a zero is about.
VOCABULARY = frozenset({"merge_claim", "live_phrases", "branch_token",
                        "path_pointer", "release_tag", "consistency"})
PATTERNS = sorted(VOCABULARY - {"consistency"})

ENTRY = "# Status\n\n## Phase 1 - the work (complete, 2026-09-29)\n\n{}\n"
# One of each claim the five patterns read, for the empty-pattern tests.
EVERY_CLAIM = ("Work on `feature/demo` is NOT yet merged.\n"
               "Merged to `main` at `0123abc`.\n"
               "**Design:** `docs/absent.md`\n"
               "Released in v9.9.9.\n")


def run(repo: Path, *args: str, stdin: str | None = None
        ) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(COLLECTOR), "--repo", str(repo), *args],
        cwd=repo, capture_output=True, text=True, encoding="utf-8",
        errors="replace", input=stdin)


def line_with(result: subprocess.CompletedProcess[str], phrase: str) -> str:
    """The first output line holding `phrase` - and a failure when none does.

    A filter that finds no line passes every negative assertion made of it,
    which is how `test_fuzz_findings.py` could have gone vacuous the day the
    NOTE was reworded. So the line is asserted to exist first.
    """
    combined = result.stdout + result.stderr
    found = [ln for ln in combined.splitlines() if phrase in ln]
    assert found, f"no output line holds {phrase!r}:\n{combined}"
    return found[0]


def lines_with(result: subprocess.CompletedProcess[str], phrase: str) -> str:
    combined = result.stdout + result.stderr
    return "\n".join(ln for ln in combined.splitlines() if phrase in ln)


def _vocabulary_read(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in VOCABULARY}


def _settings(tmp_path: Path, toml: str | None = None) -> StatusConfig:
    root = tmp_path / "settings"
    (root / ".git").mkdir(parents=True, exist_ok=True)
    if toml is not None:
        (root / ".extant.toml").write_text(toml, encoding="utf-8")
    return load_config(root)


# --- 1. a rule states where its vocabulary comes from ----------------------

def test_the_vocabulary_is_the_patterns_that_decide_what_a_claim_is() -> None:
    assert VOCABULARY <= set(DEFAULTS)
    # Every one of them can be switched off, or a zero under it could not be
    # made to mean "off" by the project that wants it to.
    assert set(PATTERNS) <= DISABLEABLE


def test_every_setting_a_rule_declares_is_a_configuration_key() -> None:
    declared = {key for rule in session.RULES for key in rule.settings}
    assert declared, "no rule declares a setting; this would pass vacuously"
    assert declared <= set(DEFAULTS), sorted(declared - set(DEFAULTS))


def test_a_rule_declares_exactly_the_vocabulary_its_module_reads() -> None:
    """Catches a declaration that drifts from the code it describes.

    `settings` is what the zero NOTE names as the lever to pull; a rule that
    reads `merge_claim` and declares nothing would have its zero blamed on a
    token shape, and one declaring a key it never reads would send a reader
    to set something that changes nothing.
    """
    checked = 0
    for rule in session.RULES:
        module = sys.modules[rule.check.__module__]
        reads = _vocabulary_read(Path(str(module.__file__)))
        assert set(rule.settings) == reads, (
            f"{rule.kind} declares {rule.settings} and its module reads "
            f"{sorted(reads)}")
        checked += 1
    assert checked == len(session.RULES) == 13


def test_vocabulary_read_outside_the_rules_is_a_recorded_decision() -> None:
    """The shared machinery that reads a rule's vocabulary, named.

    Each reads it on behalf of rules that declare the key: the commit batch
    finds the merge claims `false-merge-claim` judges (and `dead-sha` batches
    with, which is why `merge_claim = ''` used to take `dead-sha` down too);
    the patch generator re-reads `path_pointer`; the probes read the branch
    token for the two entry rules. A new reader is a visible decision here.
    """
    found = {path.name: _vocabulary_read(path)
             for path in sorted(PACKAGE.glob("*.py"))
             if path.name != "config.py"}
    found = {name: keys for name, keys in found.items() if keys}
    assert found == {"commits.py": {"merge_claim"},
                     "patches.py": {"path_pointer"},
                     "probes.py": {"branch_token"}}


# --- 2. where each setting came from ----------------------------------------

def test_the_settings_say_which_keys_the_file_sets(tmp_path: Path) -> None:
    assert _settings(tmp_path).configured == frozenset()
    status = _settings(tmp_path, "trunk = 'develop'\nretain_entries = 5\n")
    assert status.configured == {"trunk", "retain_entries"}
    assert Config.build(status).configured == status.configured


@pytest.mark.parametrize("key", PATTERNS)
def test_an_empty_pattern_switches_its_setting_off(tmp_path: Path,
                                                   key: str) -> None:
    status = _settings(tmp_path, f"{key} = ''\n")
    assert key in status.off
    assert key in Config.build(status).off
    pattern = getattr(status, key)
    # Never matches, and keeps the default's group count, so shared
    # machinery that branches on `pattern.groups` behaves as for any pattern.
    assert pattern.search(EVERY_CLAIM) is None
    assert pattern.groups == re.compile(str(DEFAULTS[key])).groups


def test_nothing_is_off_that_the_file_did_not_switch_off(tmp_path: Path) -> None:
    assert _settings(tmp_path).off == {"consistency"}


def test_consistency_is_off_until_a_check_is_configured(tmp_path: Path) -> None:
    status = _settings(tmp_path, (
        "[extant.consistency.version]\n"
        "\"a.txt\" = 'v(\\d+)'\n"
        "\"b.txt\" = 'v(\\d+)'\n"))
    assert "consistency" not in status.off


# --- 3. a pattern that cannot mean anything is refused at load ---------------

@pytest.mark.parametrize("key,pattern", [
    ("path_pointer", "(x)?"),
    ("live_phrases", "(pending)*"),
    ("merge_claim", "(m)?"),
    # Empty only in context, which `match("")` never saw: after a word
    # boundary, or behind a space - 24 examined on a 7-line document.
    ("path_pointer", "\\b([\\w/.-]*)"),
    ("branch_token", "(?<=\\s)(\\S*)"),
])
def test_a_pattern_that_matches_the_empty_string_is_refused(
        tmp_path: Path, key: str, pattern: str) -> None:
    """`path_pointer = ''` reported 256 examined on a 14-line document, and
    `live_phrases = ''` made every branch token in the newest entry a live
    claim. The empty string is now OFF; any other pattern that matches
    nothing-at-all does the same damage and is refused, naming the key."""
    with pytest.raises(ValueError, match=f"{key}.*empty string"):
        _settings(tmp_path, f"{key} = '{pattern}'\n")


@pytest.mark.parametrize("key,pattern", [
    ("branch_token", "`feature/x`"),
    ("path_pointer", "see `(a)(b)`"),
    ("release_tag", "released"),
    ("merge_claim", "merged (a) (b) (c)"),
])
def test_a_pattern_with_the_wrong_number_of_groups_is_refused(
        tmp_path: Path, key: str, pattern: str) -> None:
    """Each of these raised `IndexError: no such group` inside the rule on
    every run, which never exits 0 but names the rule rather than the key."""
    with pytest.raises(ValueError, match=f"{key}.*group"):
        _settings(tmp_path, f"{key} = '{pattern}'\n")


@pytest.mark.parametrize("key,pattern", [
    ("branch_token", "`((feature|fix)/[^`]+)`"),
    ("release_tag", "released in (v(\\d+)\\.\\d+)"),
])
def test_a_rule_reading_group_one_takes_more_groups(tmp_path: Path, key: str,
                                                    pattern: str) -> None:
    """These rules read group 1 and nothing past it, so a nested group was a
    working configuration before the refusal, and must stay one: refused, it
    stopped every mode at load, not only its rule."""
    assert getattr(_settings(tmp_path, f"{key} = '{pattern}'\n"), key).groups == 2


def test_merge_claim_keeps_both_of_its_shapes(tmp_path: Path) -> None:
    one = _settings(tmp_path, "merge_claim = 'merged at ([0-9a-f]{7,40})'\n")
    assert one.merge_claim.groups == 1
    two = _settings(tmp_path,
                    "merge_claim = 'merged to (\\S+) at ([0-9a-f]{7,40})'\n")
    assert two.merge_claim.groups == 2


def test_every_known_configuration_still_loads() -> None:
    """The refusals above refuse nothing that exists: the defaults and this
    repository's own settings. (The 39 installer outputs were checked by
    extant-hardening/m21_pattern_shapes.py: 0 refused.)"""
    assert load_config(ROOT).source.endswith(".extant.toml")


# --- 4. off is a state, and the run says so ----------------------------------

def test_a_switched_off_rule_does_not_run_and_the_run_says_so(git_repo: GitRepo) -> None:
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format("**Design:** `docs/absent.md`"),
           "docs: status")
    # The positive control: the claim IS reported while the rule is on.
    before = run(repo, "--verify")
    assert "[dead-path-pointer]" in before.stdout + before.stderr

    commit(".extant.toml", "path_pointer = ''\n", "chore: switch it off")
    after = run(repo, "--verify")
    assert "[dead-path-pointer]" not in after.stdout + after.stderr
    unrun = line_with(after, UNRUN_NOTE)
    assert "dead-path-pointer read nothing" in unrun, unrun
    assert "`path_pointer`" in unrun, unrun
    assert after.returncode == 0, after.stdout + after.stderr


@pytest.mark.parametrize("key", PATTERNS)
def test_an_empty_pattern_never_crashes_a_rule_or_widens_one(
        git_repo: GitRepo, key: str) -> None:
    """Before: three keys raised (`merge_claim` took `dead-sha` with it), and
    two failed silently - `path_pointer` reported 256 examined on a 14-line
    document, `live_phrases` turned every branch token into a live claim."""
    repo, commit = git_repo
    commit(".extant.toml", f"{key} = ''\n", "chore: config")
    commit("NEXT_SESSION.md", ENTRY.format(EVERY_CLAIM), "docs: status")
    result = run(repo, "--verify")
    combined = result.stdout + result.stderr
    assert "ERRORED" not in combined, combined
    readers = [rule.kind for rule in session.RULES if key in rule.settings]
    assert readers
    unrun = line_with(result, UNRUN_NOTE)
    checked = line_with(result, "checked NEXT_SESSION.md")
    for kind in readers:
        assert kind in unrun, unrun
        assert f"{kind} 0" in checked, checked
        assert f"[{kind}]" not in combined, combined


def test_the_sweep_does_not_run_a_repository_rule_that_is_off(git_repo: GitRepo) -> None:
    """The sweep's repository pass ran every repository rule directly, so an
    off rule still ran there and was counted among those that ran once."""
    repo, commit = git_repo
    commit("README.md", "# Project\n\nNothing claimed.\n", "docs: readme")
    result = run(repo, "--sweep")
    assert "1 repository-wide rule(s) ran once" in result.stdout, result.stdout
    unrun = line_with(result, UNRUN_NOTE)
    assert "inconsistent-artifact read nothing" in unrun, unrun
    assert "`consistency`" in unrun, unrun


def test_selftest_reports_a_switched_off_rule_as_not_run(git_repo: GitRepo) -> None:
    """Counted as silent before, because `silent` was every rule that did not
    fire, find nothing to probe or raise - so an off rule failed the run."""
    repo, commit = git_repo
    commit(".extant.toml", "path_pointer = ''\n", "chore: config")
    commit("NEXT_SESSION.md", ENTRY.format("**Design:** `docs/absent.md`"),
           "docs: status")
    result = run(repo, "--selftest")
    line = line_with(result, "dead-path-pointer")
    assert "NOT RUN" in line and "`path_pointer`" in line, line
    # And the other rule off in any repository without a consistency check.
    line = line_with(result, "inconsistent-artifact")
    assert "NOT RUN" in line and "`consistency`" in line, line
    assert "0 stayed silent" in result.stdout, result.stdout
    assert "2 not run here" in result.stdout, result.stdout
    assert result.returncode == 0, result.stdout + result.stderr


def test_selftest_does_not_probe_a_rule_the_document_is_not_read_by(
        git_repo: GitRepo) -> None:
    """The owed item: `--selftest` ignored `rule_applies`, so it probed the
    entry rules on a document holding no entry, and markdown rules on rst."""
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# Status\n\nNothing dated here.\n",
           "docs: status")
    result = run(repo, "--selftest")
    line = line_with(result, "stale-live-claim")
    assert "NOT RUN" in line and "which has none" in line, line


# --- 5. every zero that ran is worded by its cause ---------------------------

def test_a_zero_no_pattern_could_explain_is_not_blamed_on_one(git_repo: GitRepo) -> None:
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format("Plain prose."), "docs: status")
    result = run(repo, "--verify")
    shape = line_with(result, ZERO_SHAPE)
    for kind in ("dead-pinned-ref", "raw-lfs-blob", "dead-sha"):
        assert kind in shape, shape
    default = line_with(result, ZERO_DEFAULT)
    for named in ("stale-live-claim (live_phrases, branch_token)",
                  "unknown-branch (branch_token)",
                  "false-merge-claim (merge_claim)",
                  "dead-path-pointer (path_pointer)",
                  "dead-release-tag (release_tag)"):
        assert named in default, default
    assert "dead-pinned-ref" not in default, default
    assert not lines_with(result, ZERO_SET)
    # Off, not "matched nothing": no consistency check is configured.
    assert "inconsistent-artifact" not in shape + default
    assert "inconsistent-artifact" in line_with(result, UNRUN_NOTE)


def test_a_zero_under_a_pattern_the_project_set_keeps_both_reasons(
        git_repo: GitRepo) -> None:
    repo, commit = git_repo
    commit(".extant.toml",
           "merge_claim = 'landed on (`[^`]+`) at ([0-9a-f]{7,40})'\n",
           "chore: config")
    commit("NEXT_SESSION.md", ENTRY.format("Plain prose."), "docs: status")
    result = run(repo, "--verify")
    chosen = line_with(result, ZERO_SET)
    assert "false-merge-claim (merge_claim)" in chosen, chosen
    assert "the pattern does not match" in chosen, chosen
    assert "false-merge-claim" not in lines_with(result, ZERO_DEFAULT)


def test_an_entry_rule_on_a_document_with_no_entry_read_nothing(
        git_repo: GitRepo) -> None:
    """25 of the 39 installed primary documents hold no entry, and --verify
    said the entry rules "matched nothing" there."""
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# Status\n\nNothing dated here.\n",
           "docs: status")
    result = run(repo, "--verify")
    unrun = line_with(result, UNRUN_NOTE)
    assert ("stale-live-claim, unknown-branch read only the newest entry of "
            "the primary document, which has none") in unrun, unrun
    # And the lever, since 23 of the 25 measured were entries headed some
    # other way than the shipped `## Phase `.
    assert "shipped default `entry_prefix` '## Phase '" in unrun, unrun
    zeros = lines_with(result, "NOTE: these rules matched nothing")
    assert "stale-live-claim" not in zeros and "unknown-branch" not in zeros


def test_a_set_entry_prefix_is_not_named_as_the_lever(git_repo: GitRepo) -> None:
    repo, commit = git_repo
    commit(".extant.toml", "entry_prefix = '## Step '\n", "chore: config")
    commit("NEXT_SESSION.md", "# Status\n\nNothing dated here.\n",
           "docs: status")
    unrun = line_with(run(repo, "--verify"), UNRUN_NOTE)
    assert "which has none" in unrun and "entry_prefix" not in unrun, unrun


def test_a_markdown_rule_on_an_rst_primary_read_nothing(git_repo: GitRepo) -> None:
    repo, commit = git_repo
    commit(".extant.toml", "primary_doc = 'STATUS.rst'\n", "chore: config")
    # A link-shaped token, which the markdown rule counted although it did
    # not run: its count and the NOTE saying it read nothing, side by side.
    commit("STATUS.rst", "Status\n======\n\nSee [the notes](docs/notes.md).\n",
           "docs: status")
    result = run(repo, "--verify")
    unrun = line_with(result, UNRUN_NOTE)
    assert "dead-md-link" in unrun and "markdown" in unrun, unrun
    assert "dead-md-link" not in lines_with(result, "NOTE: these rules matched")
    assert "dead-md-link 0," in line_with(result, "checked STATUS.rst")


def test_check_text_words_its_zeros_the_same_way(git_repo: GitRepo) -> None:
    repo, _commit = git_repo
    result = run(repo, "--check-text", stdin="# Draft\n\nNothing dated.\n")
    assert "which has none" in line_with(result, UNRUN_NOTE)
    assert "dead-pinned-ref" in line_with(result, ZERO_SHAPE)


# --- 6. SARIF says what the text says ----------------------------------------

def _notes(result: subprocess.CompletedProcess[str]) -> list[str]:
    return [ln.strip()[len("NOTE: "):]
            for ln in result.stderr.splitlines()
            if ln.strip().startswith("NOTE: these rules")]


def test_sarif_carries_the_same_zero_notes_as_the_text(git_repo: GitRepo) -> None:
    """It computed its own list from every zero, so it never learned the
    split the text NOTE has had since Phase 57, and named rules that read
    no document as rules that examined nothing."""
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# Status\n\nNothing dated here.\n",
           "docs: status")
    result = run(repo, "--verify", "--format=sarif")
    notes = _notes(result)
    assert notes, result.stderr
    invocation = json.loads(result.stdout)["runs"][0]["invocations"][0]
    sent = [n["message"]["text"]
            for key in ("toolExecutionNotifications",
                        "toolConfigurationNotifications")
            for n in invocation.get(key, [])]
    for note in notes:
        assert note in sent, (note, sent)
    assert not [text for text in sent if text.startswith("examined nothing")]


def test_sarif_names_a_switched_off_rule_as_disabled(git_repo: GitRepo) -> None:
    repo, commit = git_repo
    commit(".extant.toml", "path_pointer = ''\n", "chore: config")
    commit("NEXT_SESSION.md", ENTRY.format("Plain prose."), "docs: status")
    result = run(repo, "--verify", "--format=sarif")
    run_ = json.loads(result.stdout)["runs"][0]
    overrides = run_["invocations"][0]["ruleConfigurationOverrides"]
    disabled = [o for o in overrides
                if o["descriptor"]["id"] == "dead-path-pointer"]
    assert disabled and disabled[0]["configuration"] == {"enabled": False}
    # Every reference resolves: an off rule has no result to be listed by,
    # so it is listed for the override, at the index the override names.
    rules = run_["tool"]["driver"]["rules"]
    for override in overrides:
        ref = override["descriptor"]
        assert rules[ref["index"]]["id"] == ref["id"], (ref, rules)


def test_sarif_reports_a_rule_that_raised_as_a_failed_execution() -> None:
    """`executionSuccessful` was hard-coded true, so a SARIF consumer saw a
    successful run while the exit code said a rule could not look."""
    document = json.loads(format_sarif(
        [], None, examined={"dead-sha": 0},
        errors=[("dead-sha", "ValueError: boom")]))
    invocation = document["runs"][0]["invocations"][0]
    assert invocation["executionSuccessful"] is False
    raised = [n for n in invocation["toolExecutionNotifications"]
              if n["level"] == "error"]
    assert raised and raised[0]["associatedRule"]["id"] == "dead-sha"
    rules = document["runs"][0]["tool"]["driver"]["rules"]
    assert rules[raised[0]["associatedRule"]["index"]]["id"] == "dead-sha"
    assert "ValueError: boom" in raised[0]["exception"]["message"]


def test_deleted_since_sarif_says_it_examined_no_document(git_repo: GitRepo) -> None:
    """SARIF stopped working out its own zeros, and this mode handed it none:
    a range that changed no document lost the warning it had."""
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format("Plain prose."), "docs: status")
    result = run(repo, "--deleted-since", "HEAD", "--format=sarif")
    invocation = json.loads(result.stdout)["runs"][0]["invocations"][0]
    assert invocation["executionSuccessful"] is True
    sent = [n["message"]["text"]
            for n in invocation["toolExecutionNotifications"]]
    assert any("no changed document was examined" in text for text in sent), sent


# --- 7. the newest entry has one reader -------------------------------------

def test_a_branch_probe_corrupts_the_token_the_rule_reads(git_repo: GitRepo) -> None:
    """The probe split the RAW text, so the first branch token it found could
    sit in a fence the rule never reads: corrupted there, the rule stayed
    silent on a claim it would have caught - a false DID NOT FIRE."""
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format(
        "```\n`feature/in-a-fence`\n```\n\nWork on `feature/demo` continues."),
        "docs: status")
    # The prose token names a branch that exists, so only the probe's
    # corruption of it can make the rule fire.
    subprocess.run(["git", "branch", "feature/demo"], cwd=repo, check=True,
                   capture_output=True)
    result = run(repo, "--selftest")
    line = line_with(result, "unknown-branch")
    assert "FIRED" in line and "DID NOT" not in line, result.stdout
