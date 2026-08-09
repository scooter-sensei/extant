"""`exclude_paths`: the one setting that can make a repository look clean.

Some documents are INPUT TO A TEST rather than a promise to a reader, and no
rule can tell the difference. A held-out corpus put 18 findings in `testdata/`
and `test/fixtures/` trees, and one of the targets was
`../assets/does-not-exist.jpg` - a fixture DELIBERATELY naming a missing file
to exercise error handling. Nothing git or the filesystem can answer separates
that from a real defect.

Which directories hold fixtures is a project's own convention, so this is
configuration rather than a rule. That makes it the most dangerous setting
here: a skip-list fails silently in BOTH directions, by removing more than
intended and by containing patterns that match nothing. Both are pinned below,
and both are printed at runtime.
"""
from __future__ import annotations

import sys
from pathlib import Path

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))

PATHS = [
    "README.md",
    "docs/guide.md",
    "docs/sub/deep.md",
    "hugolib/testdata/what-is-markdown.md",
    "packages/app/test/fixtures/content/entry.mdx",
    "notes/testdata.md",
]


def _split(patterns):
    import extant_collect as hc
    return hc.excluded_documents(list(PATHS), tuple(patterns))


# --------------------------------------------------------------------------
# What the patterns mean
# --------------------------------------------------------------------------

def test_a_bare_name_matches_a_segment_at_any_depth() -> None:
    """`testdata` covers `hugolib/testdata/x.md` without anybody discovering
    that `**/testdata/**` was required. This is the shape the corpus actually
    needs, so it is the shape that must be easy to write."""
    kept, counts = _split(["testdata"])
    assert counts["testdata"] == 1
    assert "hugolib/testdata/what-is-markdown.md" not in kept


def test_a_bare_name_does_not_match_half_a_segment() -> None:
    """`notes/testdata.md` is a document called testdata, not a directory of
    fixtures. A substring match would take it and nobody would notice one
    fewer file."""
    kept, _ = _split(["testdata"])
    assert "notes/testdata.md" in kept


def test_a_star_does_not_cross_a_separator() -> None:
    """Deliberately not `fnmatch`, whose `*` spans `/`. `docs/*.md` means the
    markdown directly in docs; under fnmatch it would silently take the whole
    tree, and the only evidence would be a smaller number."""
    kept, counts = _split(["docs/*.md"])
    assert counts["docs/*.md"] == 1
    assert "docs/guide.md" not in kept
    assert "docs/sub/deep.md" in kept


def test_a_matched_directory_takes_its_contents() -> None:
    """The other half of gitignore's behaviour, pinned because it surprises
    people the first time: `docs/*` matches `docs/sub`, and excluding a
    directory excludes what is in it."""
    kept, counts = _split(["docs/*"])
    assert counts["docs/*"] == 2
    assert kept == ["README.md", "hugolib/testdata/what-is-markdown.md",
                    "packages/app/test/fixtures/content/entry.mdx",
                    "notes/testdata.md"]


def test_a_double_star_spans_segments() -> None:
    kept, counts = _split(["**/fixtures/**"])
    assert counts["**/fixtures/**"] == 1
    assert "packages/app/test/fixtures/content/entry.mdx" not in kept


def test_an_anchored_pattern_is_rooted_at_the_repository() -> None:
    """`docs/guide.md` is that file, not any `guide.md` anywhere."""
    kept, counts = _split(["docs/guide.md"])
    assert counts["docs/guide.md"] == 1
    assert "docs/guide.md" not in kept
    assert "docs/sub/deep.md" in kept


def test_nothing_is_excluded_by_default() -> None:
    """A skip-list that ships with entries is a skip-list nobody audits, and
    this project already shipped a lint whose defaults excluded every file it
    was meant to scan."""
    import extant_collect as hc
    assert hc.CONFIG.exclude_paths == ()
    kept, counts = _split([])
    assert kept == PATHS and counts == {}


# --------------------------------------------------------------------------
# The two silent failure modes
# --------------------------------------------------------------------------

def test_a_pattern_matching_nothing_is_counted_as_zero() -> None:
    """Dead configuration reads exactly like a working exclusion and survives
    every run until somebody counts. The count is what the sweep prints, so
    the zero has to reach it."""
    _, counts = _split(["vendor/**", "testdata"])
    assert counts == {"vendor/**": 0, "testdata": 1}


def test_every_pattern_reports_its_own_count() -> None:
    """Per pattern, not a total. A total cannot distinguish one pattern doing
    all the work from every pattern pulling its weight, and the first case is
    where an over-broad entry hides."""
    _, counts = _split(["testdata", "**/fixtures/**", "README.md"])
    assert counts == {"testdata": 1, "**/fixtures/**": 1, "README.md": 1}


def test_a_path_is_attributed_to_the_first_pattern_that_matches() -> None:
    """Overlapping patterns must not inflate the arithmetic past the number of
    files that exist, AND attribution goes to the first match in reading
    order.

    The total alone does not pin this: dropping the `break` leaves the count
    correct and moves the attribution to the LAST matching pattern, which
    silently rewrites the per-pattern report the whole feature exists to
    print. The mutation survived a version of this test that checked only the
    sum.
    """
    kept, counts = _split(["testdata", "hugolib/**"])
    assert sum(counts.values()) + len(kept) == len(PATHS)
    assert counts == {"testdata": 1, "hugolib/**": 0}


def test_the_unusable_pattern_guard_is_a_contract() -> None:
    """Pinned on the function, because no document can observe it.

    An empty pattern compiles to a regex matching only the empty string, so
    removing the guard changes no verdict on any path - the mutation for it
    survived every behavioural test. That is the signal to state the contract
    instead of hunting for a document that would notice.
    """
    import extant_collect as hc
    assert hc._exclusion_regex("") is None
    assert hc._exclusion_regex("   ") is None
    assert hc._exclusion_regex("# a comment") is None
    # And the guard has not swallowed a legitimate pattern on its way past.
    assert hc._exclusion_regex("testdata") is not None


def test_an_unusable_pattern_excludes_nothing_rather_than_everything() -> None:
    """An empty or commented entry is ignored. Compiling it to an empty regex
    would match every path, which is the worst available failure."""
    kept, counts = _split(["", "   ", "# a comment"])
    assert kept == PATHS
    assert set(counts.values()) == {0}


# --------------------------------------------------------------------------
# End to end, through the sweep
# --------------------------------------------------------------------------

def _sweep(repo):
    """Run the INSTALLED shape, which is the only one that reads the target's
    own configuration.

    Settings are discovered relative to the script, so a collector run from
    this source tree against a temporary repository reads THIS project's
    `.extant.toml` and says so on stderr. The first version of these tests did
    exactly that and asserted against extant's own settings without noticing -
    the tool's own diagnostic is what caught it.
    """
    import shutil
    import subprocess
    tools = Path(repo) / "tools"
    tools.mkdir(exist_ok=True)
    for name in ("extant_collect.py", "extant_config.py"):
        shutil.copyfile(PAYLOAD / name, tools / name)
    done = subprocess.run(
        [sys.executable, str(tools / "extant_collect.py"), "--sweep"],
        cwd=str(repo), capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    return done.returncode, done.stdout + done.stderr


def test_the_sweep_prints_what_it_excluded(git_repo) -> None:
    """A count nobody sees is the same as no count. This is the setting that
    can make a repository look clean by not looking at it, so what it removed
    is printed beside what was read."""
    repo, commit = git_repo
    commit("README.md", "See [gone](nowhere.md).\n", "seed")
    commit("testdata/spec.md", "See [also gone](nope.md).\n", "fixture")
    commit(".extant.toml", 'exclude_paths = ["testdata"]\n', "config")

    code, output = _sweep(repo)
    # Two TRACKED MARKDOWN files, not three committed ones: `.extant.toml` is
    # config, not a document. The denominator counts what the sweep would
    # otherwise have read.
    assert "excluded 1 of 2 tracked file(s)" in output, output
    assert "1 testdata" in output, output
    # The kept document is still checked: excluding must not mean not looking.
    assert "nowhere.md" in output, output
    assert "nope.md" not in output, output


def test_the_sweep_names_a_pattern_that_matched_nothing(git_repo) -> None:
    """The failure that survives forever otherwise."""
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    commit(".extant.toml", 'exclude_paths = ["vendor/**"]\n', "config")

    code, output = _sweep(repo)
    assert "matched nothing" in output, output
    assert "vendor/**" in output, output


def test_excluding_a_configured_document_is_refused(git_repo) -> None:
    """One setting says gate on this file and another says never read it.
    Reported rather than resolved, because either answer silently overrides
    something the author wrote - and the dangerous direction is quietly
    dropping a document somebody asked to gate on."""
    repo, commit = git_repo
    commit("STATUS.md", "x\n", "seed")
    commit(".extant.toml",
           'primary_doc = "STATUS.md"\nexclude_paths = ["STATUS.md"]\n', "config")

    code, output = _sweep(repo)
    assert code == 1, output
    assert "CONFLICT" in output, output
    assert "STATUS.md" in output, output


def test_excluding_everything_says_so(git_repo) -> None:
    """Zero documents swept because a pattern removed them all is a different
    fact from zero documents tracked, and they printed identically."""
    repo, commit = git_repo
    commit("docs/a.md", "x\n", "seed")
    commit(".extant.toml", 'exclude_paths = ["**"]\n', "config")

    code, output = _sweep(repo)
    assert "removed all" in output, output
    assert code == 0, output
