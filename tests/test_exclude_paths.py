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

from conftest import _install_into

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
    from extant import session as hc
    from extant import exclusions
    return exclusions.excluded_documents(list(PATHS), tuple(patterns))


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


# What `git check-ignore --no-index` (2.53.0, `core.ignorecase=false`)
# answered for each pattern over STAR_PATHS, recorded rather than reasoned:
# an expectation written from the rule would prove the rule's paraphrase.
STAR_PATHS = ["a", "ab", "axb", "xa", "a/b", "a/a", "aa/a", "aaa", "a/xb",
              "a/x/b", "a/x/yb", "a/x/y/b", "b", "x/b", "b/a", "fixtures/x.md",
              "a/fixtures/b.md", "docs/a/fixtures", "docs/fixtures"]
GIT_STAR_RUNS = {
    # A run of stars no separator bounds is ONE `*` to git.
    "a/**b": {"a/b", "a/xb"},
    "a**b": {"ab", "axb"},
    "a**/a": {"a/a", "aa/a"},
    "aa**/a": {"aa/a"},
    "/**a": {"a", "xa", "a/b", "a/a", "aa/a", "aaa", "a/xb", "a/x/b",
             "a/x/yb", "a/x/y/b", "a/fixtures/b.md"},
    # A bounded run of three is `**`.
    "***/b": {"b", "x/b", "a/b", "a/x/b", "a/x/y/b", "b/a"},
    "a/***/b": {"a/b", "a/x/b", "a/x/y/b"},
    # The bounded shapes the matcher always read right, held beside them.
    "**/fixtures/**": {"fixtures/x.md", "a/fixtures/b.md"},
    "a/**": {"a/b", "a/a", "a/xb", "a/x/b", "a/x/yb", "a/x/y/b",
             "a/fixtures/b.md"},
    "docs/**/fixtures": {"docs/a/fixtures", "docs/fixtures"},
    "**": set(STAR_PATHS),
}


def test_a_star_run_spans_segments_only_where_git_says_it_does() -> None:
    """`**` crosses separators only as a whole segment - `**/`, `/**/`, a
    trailing `/**` - and is a plain `*` anywhere else, as in gitignore.

    This matcher let every `**` cross them: `a/**b` took `a/x/b`, `a**/a`
    missed `a/a`, `aa**/a` was wrong both ways - it took `aaa` and missed
    `aa/a` - and a bounded `***` was read as `**` followed by `*`. Seven of
    the eleven patterns below disagreed with git, one cause, found by
    holding the matcher beside `git check-ignore` in tests/test_properties.py
    (Phase 62). None was in any configuration the project knows of.
    """
    from extant import exclusions
    wrong = {}
    for pattern, expected in GIT_STAR_RUNS.items():
        regex = exclusions._exclusion_regex(pattern)
        assert regex is not None, pattern
        ours = {path for path in STAR_PATHS if regex.match(path)}
        if ours != expected:
            wrong[pattern] = (sorted(ours - expected), sorted(expected - ours))
    print(f"checked {len(GIT_STAR_RUNS)} patterns over {len(STAR_PATHS)} paths")
    assert not wrong, wrong


def test_an_anchored_pattern_is_rooted_at_the_repository() -> None:
    """`docs/guide.md` is that file, not any `guide.md` anywhere."""
    kept, counts = _split(["docs/guide.md"])
    assert counts["docs/guide.md"] == 1
    assert "docs/guide.md" not in kept
    assert "docs/sub/deep.md" in kept


def test_a_trailing_slash_means_a_directory_and_not_a_file_of_that_name() -> None:
    """`docs/` is gitignore's spelling for "the directory docs", and a FILE
    named `docs` is not it. The matcher took both, and git's own matcher
    does not: fed every tracked path of the 152 visible corpus clones, the
    two disagreed on exactly five paths, all of them Debian packaging files
    called `docs` or `vendor` (`pkg/debian/docs`, `hack/validate/vendor`).
    None was a document - a document carries a suffix - so
    `excluded_documents` could never have reached the difference; it is
    closed anyway, so the matcher agrees with git on every shape it claims.
    Everything under the directory is still taken."""
    from extant import exclusions
    directory = exclusions._exclusion_regex("docs/")
    assert directory is not None
    assert directory.match("docs/guide.md")
    assert directory.match("a/docs/guide.md")
    assert not directory.match("docs"), "a file named docs is not the directory"
    assert not directory.match("pkg/debian/docs")
    # Without the slash the name is a segment, file or directory, as before.
    segment = exclusions._exclusion_regex("docs")
    assert segment is not None
    assert segment.match("pkg/debian/docs")
    assert segment.match("docs/guide.md")


def test_nothing_is_excluded_by_default() -> None:
    """A skip-list that ships with entries is a skip-list nobody audits, and
    this project already shipped a lint whose defaults excluded every file it
    was meant to scan."""
    from extant import session as hc
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
    from extant import session as hc
    from extant import exclusions
    assert exclusions._exclusion_regex("") is None
    assert exclusions._exclusion_regex("   ") is None
    assert exclusions._exclusion_regex("# a comment") is None
    # And the guard has not swallowed a legitimate pattern on its way past.
    assert exclusions._exclusion_regex("testdata") is not None


def test_negation_and_character_classes_are_named_unusable() -> None:
    """Catches `!` and `[` escaped into literals and passed off as patterns.

    gitignore reads a leading `!` as NEGATION and `[` as a character class;
    this matcher escaped both into literal characters, so `!docs/keep.md`
    matched only a path beginning with `!` and `docs/[a-z]*.md` matched a
    directory literally called `[a-z]` - each a pattern that silently meant
    something else. Named rather than supported (no configuration here or in
    a known install uses either), and named WHY, because "matched nothing, so
    it may be stale" is the wrong diagnosis for a pattern that never could.
    """
    from extant import exclusions
    assert exclusions.unusable_exclusion("!docs/keep.md") == "negation is not supported"
    assert (exclusions.unusable_exclusion("docs/[a-z]*.md")
            == "a character class is not supported")
    assert exclusions._exclusion_regex("!docs/keep.md") is None
    assert exclusions._exclusion_regex("docs/[a-z]*.md") is None
    # `!` is special only where gitignore says it is: at the start.
    assert exclusions.unusable_exclusion("docs/a!b.md") is None
    assert exclusions._exclusion_regex("docs/a!b.md") is not None
    assert exclusions.unusable_exclusion("testdata") is None


def test_a_comment_is_not_named_an_unusable_pattern() -> None:
    """Catches the diagnosis reading an entry the matcher never reads.

    `_exclusion_regex` sets a `#` line and an empty entry aside as comments
    before anything else, so neither is a pattern. The unusable verdict was
    asked of every configured entry, and named `# drafts [old]` as an
    unsupported character class - a diagnosis of a comment. Found by the
    review of the built tranche, 2026-09-29.
    """
    from extant import exclusions
    for comment in ("# drafts [old]", "#!keep", "  # [x]", ""):
        assert exclusions.unusable_exclusion(comment) is None, repr(comment)
    assert exclusions.unusable_note(["# drafts [old]", "drafts/**"]) is None


def test_the_sweep_names_an_unusable_pattern_and_why(git_repo) -> None:
    """Printed beside the counts, and kept OUT of the "may be stale" line,
    which would send the reader to look for the directory rather than at the
    pattern."""
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    commit(".extant.toml",
           'exclude_paths = ["!docs/keep.md", "docs/[a-z]*.md", "vendor/**"]\n',
           "config")

    code, output = _sweep(repo)
    unusable = next((ln for ln in output.splitlines() if "unusable" in ln), "")
    assert "!docs/keep.md (negation is not supported)" in unusable, output
    assert ("docs/[a-z]*.md (a character class is not supported)"
            in unusable), output
    stale = next(ln for ln in output.splitlines() if "matched nothing" in ln)
    assert "vendor/**" in stale and "!docs" not in stale and "[a-z]" not in stale, stale


def test_introduced_since_names_an_unusable_pattern_too(git_repo) -> None:
    """The second caller of the same exclusions, which the plan's first
    version of this item did not name."""
    import subprocess
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    commit(".extant.toml", 'exclude_paths = ["docs/[a-z]*.md"]\n', "config")
    commit("docs/guide.md", "Words.\n", "docs: guide")
    tools = _install_into(repo)
    done = subprocess.run(
        [sys.executable, str(tools / "extant_collect.py"),
         "--introduced-since", "HEAD~1"],
        cwd=str(repo), capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    output = done.stdout + done.stderr
    assert ("docs/[a-z]*.md (a character class is not supported)"
            in output), output


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
    import subprocess
    tools = _install_into(repo)
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
