"""A cited line number that is past the end of the file it cites.

Derived from a 39-repository corpus measured 2026-08-04: 7,775 candidate
sites, 6,525 outside a code block, 51 naming a file the repository tracks, and
3 citing a line past its end. All three were real - plan documents telling an
implementer to modify a line of a file that had since shrunk.

The two big filters are why it is usable. Code blocks are excluded, and so are
the 6,474 pointers naming something the repository does not track: those are
pasted stack traces and third-party paths, and whether a path exists is
already `dead-path-pointer`'s question.

Each test names the wrong implementation it would catch.
"""
from __future__ import annotations

import sys
from pathlib import Path

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))


def _reset():
    from extant import session as hc
    hc._SCOPE = hc.RunScope()
    hc._DOC = hc.DocScope()


def _check(repo, text: str):
    from extant import session as hc
    from extant.rules import line_pointer as rule_line_pointer
    _reset()
    return rule_line_pointer.check(hc.context(repo), text)


def _examined(repo, text: str) -> int:
    from extant import session as hc
    from extant.rules import line_pointer as rule_line_pointer
    _reset()
    return len(rule_line_pointer._line_pointer_sites(hc.context(repo), text))


# --- the claim itself --------------------------------------------------

def test_a_line_past_the_end_is_reported(git_repo) -> None:
    """The corpus case: a plan says modify line 211 of a 167-line file.

    Catches a rule that only checks the path and never counts the lines.
    """
    repo, commit = git_repo
    commit("src/app.py", "".join(f"line {n}\n" for n in range(1, 41)),
           "feat: app")
    findings = _check(repo, "**Modify:** `src/app.py:123`\n")
    assert [f.kind for f in findings] == ["dead-line-pointer"]
    assert "40 lines" in findings[0].detail
    assert findings[0].subject == "src/app.py:123"


def test_a_line_inside_the_file_is_silent(git_repo) -> None:
    """Catches a rule that fires on every pointer it can parse."""
    repo, commit = git_repo
    commit("src/app.py", "".join(f"line {n}\n" for n in range(1, 41)),
           "feat: app")
    assert _check(repo, "See `src/app.py:40` for the detail.\n") == []


def test_the_last_line_is_inside_the_file(git_repo) -> None:
    """An off-by-one here reports every pointer at the final line.

    Catches `cited < total` where `cited <= total` is meant.
    """
    repo, commit = git_repo
    commit("src/app.py", "a\nb\nc\n", "feat: app")
    assert _check(repo, "See `src/app.py:3`.\n") == []
    assert len(_check(repo, "See `src/app.py:4`.\n")) == 1


def test_a_one_line_file_reads_as_singular(git_repo) -> None:
    """Prose detail, and the only place a plural is computed."""
    repo, commit = git_repo
    commit("one.py", "solo\n", "feat: one")
    assert "has 1 line" in _check(repo, "See `one.py:9`.\n")[0].detail


# --- what it refuses to judge -----------------------------------------

def test_a_pointer_inside_a_fence_is_not_read(git_repo) -> None:
    """A pasted traceback is a record of what was true when captured.

    Catches dropping `_prose`, which is what keeps stack traces out.
    """
    repo, commit = git_repo
    commit("src/app.py", "a\nb\n", "feat: app")
    text = ("```\n"
            'File "src/app.py", line 99\n'
            "src/app.py:99 in handler\n"
            "```\n")
    assert _check(repo, text) == []


def test_a_pointer_inside_an_rst_literal_block_is_not_read(git_repo) -> None:
    """reStructuredText code blocks are INDENTATION, not fences.

    The corpus harness missed this and reported a pytest transcript as a
    finding; the real rule did not, because `_prose` is format aware. Catches
    a rule that assumes every code block is fenced.
    """
    from extant import session as hc
    from extant.rules import line_pointer as rule_line_pointer
    repo, commit = git_repo
    commit("conftest.py", "a\nb\nc\nd\n", "feat: conftest")
    text = ("then you will see this:\n\n"
            ".. code-block:: pytest\n\n"
            "    SKIPPED [2] conftest.py:13: cannot run on platform linux\n")
    _reset()
    hc.set_document(doc_format="rst")
    try:
        assert rule_line_pointer.check(hc.context(repo), text) == []
    finally:
        hc.set_document(doc_format="markdown")


def test_a_path_the_repository_does_not_track_is_not_judged(git_repo) -> None:
    """6,474 of 6,525 corpus pointers were this: third-party paths and
    transcripts. Whether a path exists is `dead-path-pointer`'s question, and
    asking it again here reports one fault twice under two names.

    Catches a rule that treats "cannot read it" as "zero lines".
    """
    repo, commit = git_repo
    commit("README.md", "# x\n", "docs: readme")
    assert _check(repo, "See `vendor/other/thing.py:900`.\n") == []


def test_a_time_or_a_port_is_not_a_pointer(git_repo) -> None:
    """`localhost:8080` and `12:30` share the shape and are not pointers.

    Catches a pattern without the extension requirement or the boundaries.
    """
    repo, commit = git_repo
    commit("README.md", "# x\n", "docs: readme")
    text = ("Run on localhost:8080 at 12:30, ratio 3:1, see "
            "https://example.com:443/x and note: this is prose.\n")
    assert _check(repo, text) == []
    assert _examined(repo, text) == 0


def test_a_wrong_case_path_is_not_judged(git_repo) -> None:
    """Resolution is case-correct, and only that guard rejects this.

    On a case-insensitive filesystem `is_file()` says yes to `src/app.py`
    when the file is `src/App.py`, so counting its lines succeeds and the
    pointer would be judged against a file the document did not name. Only
    `_resolve_reference` catches it, which is why the case matters here and
    the ordinary missing-path case does not isolate the guard.
    """
    repo, commit = git_repo
    commit("src/App.py", "a\nb\n", "feat: app")
    assert _check(repo, "See `src/app.py:99`.\n") == []


def test_a_directory_is_not_counted_as_a_file(git_repo) -> None:
    """A path can resolve and still be uncountable.

    `pkg.d` exists, so resolution passes; it is not a file, so counting
    returns None. Catches treating "cannot count it" as zero lines, which
    would report every directory as a pointer past the end.
    """
    repo, commit = git_repo
    commit("pkg.d/keep.md", "x\n", "feat: a directory that looks like a file")
    assert _check(repo, "See `pkg.d:99`.\n") == []
    assert _examined(repo, "See `pkg.d:99`.\n") == 0


def test_an_extensionless_name_is_not_a_pointer(git_repo) -> None:
    """`Makefile:99` is not read, and that is a deliberate narrowing.

    The pattern requires an extension because the corpus form is
    `path/to/file.ext:line`. Extensionless files are real, and admitting them
    would also admit every `word:number` in prose. Catches relaxing the
    extension requirement, which nothing else in this file would notice.
    """
    repo, commit = git_repo
    commit("Makefile", "a\nb\n", "feat: makefile")
    assert _examined(repo, "See Makefile:99 for the target.\n") == 0
    assert _check(repo, "See Makefile:99 for the target.\n") == []


def test_a_dotted_suffix_after_the_number_is_not_a_line(git_repo) -> None:
    """`app.py:2.0` names a version, not line 2.

    Asserted on the DENOMINATOR rather than on findings: without the trailing
    boundary the pointer is examined and simply agrees, so a findings-only
    assertion would pass either way.
    """
    repo, commit = git_repo
    commit("app.py", "a\nb\nc\n", "feat: app")
    assert _examined(repo, "Tested against app.py:2.0 of the spec.\n") == 0


# --- narrowings found by a gap audit, pinned so they stay deliberate ---

def test_a_range_is_read_by_its_start(git_repo) -> None:
    """`app.py:2-9` on a three-line file is SILENT, and that is the choice.

    Lines 4 to 9 do not exist, so a wider rule would report it. Firing only
    when the FIRST cited line is already past the end keeps the claim
    unarguable. Widening to the range end is a separate measurement, and this
    test is what makes the current behaviour visible rather than accidental.
    """
    repo, commit = git_repo
    commit("app.py", "a\nb\nc\n", "feat: app")
    assert _check(repo, "See `app.py:2-9`.\n") == []
    assert len(_check(repo, "See `app.py:8-9`.\n")) == 1


def test_a_line_column_pointer_is_judged_on_its_line(git_repo) -> None:
    """`app.py:2:14` is line 2, column 14, and only the line is checkable."""
    repo, commit = git_repo
    commit("app.py", "a\nb\nc\n", "feat: app")
    assert _check(repo, "See `app.py:2:14`.\n") == []
    assert len(_check(repo, "See `app.py:9:14`.\n")) == 1


def test_line_zero_is_not_a_line(git_repo) -> None:
    """Catches counting `:0` as a pointer, which every file would fail."""
    repo, commit = git_repo
    commit("app.py", "a\nb\nc\n", "feat: app")
    assert _examined(repo, "See `app.py:0`.\n") == 0


def test_a_seven_digit_line_is_not_examined(git_repo) -> None:
    """The digit cap, pinned. Without it the pattern would match the first
    six digits and judge a line the document never cited."""
    repo, commit = git_repo
    commit("app.py", "a\nb\nc\n", "feat: app")
    assert _examined(repo, "See `app.py:1234567`.\n") == 0


def test_an_empty_file_has_no_first_line(git_repo) -> None:
    """0 lines is a real count, not a failure to count."""
    repo, commit = git_repo
    commit("empty.py", "", "feat: empty")
    assert "has 0 lines" in _check(repo, "See `empty.py:1`.\n")[0].detail


def test_a_file_without_a_trailing_newline_counts_its_last_line(git_repo) -> None:
    """`a\\nb` is two lines. Counting newlines rather than lines would say one
    and report the final line of every such file as missing."""
    repo, commit = git_repo
    commit("notrail.py", "a\nb", "feat: no trailing newline")
    assert _check(repo, "See `notrail.py:2`.\n") == []
    assert len(_check(repo, "See `notrail.py:3`.\n")) == 1


# --- the denominator ---------------------------------------------------

def test_a_resolvable_pointer_is_counted_even_when_it_is_fine(git_repo) -> None:
    """Catches a denominator that counts findings rather than candidates."""
    repo, commit = git_repo
    commit("src/app.py", "a\nb\nc\n", "feat: app")
    assert _examined(repo, "See `src/app.py:2`.\n") == 1


def test_an_undecidable_pointer_is_not_counted_as_examined(git_repo) -> None:
    """Coverage the rule does not have must not be claimed.

    Catches counting every `path:line` match, which on the corpus would have
    reported 6,525 examined where the rule could decide 51.
    """
    repo, commit = git_repo
    commit("README.md", "# x\n", "docs: readme")
    assert _examined(repo, "See `nowhere/absent.py:5`.\n") == 0


def test_count_examined_exposes_the_rule(git_repo) -> None:
    """The registry's denominator must reach the reported one."""
    from extant import session as hc
    repo, commit = git_repo
    commit("src/app.py", "a\nb\n", "feat: app")
    _reset()
    assert hc.count_examined(repo, "See `src/app.py:1`.\n")[
        "dead-line-pointer"] == 1


# --- probe -------------------------------------------------------------

def test_the_probe_makes_a_clean_document_fire(git_repo) -> None:
    """A rule that cannot say how to make itself fire cannot be shown to work."""
    from extant import session as hc
    from extant.rules import line_pointer as rule_line_pointer
    repo, commit = git_repo
    commit("src/app.py", "a\nb\nc\n", "feat: app")
    text = "See `src/app.py:2` for the detail.\n"
    assert _check(repo, text) == []
    _reset()
    probed = rule_line_pointer.probe(hc.context(repo), text)
    assert probed is not None
    _reset()
    assert len(rule_line_pointer.check(hc.context(repo), probed)) == 1


def test_the_probe_declines_when_there_is_nothing_to_corrupt(git_repo) -> None:
    """None is the honest answer, and `--selftest` reports it as NO PROBE."""
    from extant import session as hc
    from extant.rules import line_pointer as rule_line_pointer
    repo, commit = git_repo
    commit("README.md", "# x\n", "docs: readme")
    _reset()
    assert rule_line_pointer.probe(hc.context(repo), "Nothing cited here.\n") is None


# --- the gate in front of the scan -------------------------------------

def _sites_without_the_gate(ctx, text: str):
    """`_line_pointer_sites_uncached` as it stood at 7c51c2f.

    A deliberate second copy, with the same maintenance contract the bare-SHA
    equivalence test in tests/test_held_out_narrowings.py carries: a change to
    the real function has to be made here too, and this goes red until it is.
    """
    from extant.rules.line_pointer import _LINE_POINTER, _line_count
    from extant.sites import resolve_reference
    from extant.text import prose
    sites = []
    for number, line in enumerate(prose(ctx.doc, text).splitlines(), start=1):
        for match in _LINE_POINTER.finditer(line):
            raw, cited = match.group(1), int(match.group(2))
            if cited < 1:
                continue
            exists, _actual = resolve_reference(ctx, ctx.repo, raw)
            if not exists:
                continue
            total = _line_count(ctx, raw)
            if total is None:
                continue
            sites.append((number, raw, cited, total))
    return sites


def test_the_colon_gate_finds_every_pointer_the_ungated_scan_finds(
        git_repo) -> None:
    """A line with no colon is skipped, and nothing else is.

    `_LINE_POINTER` opens with a lookbehind and a nested
    `(?:[\\w.\\-]+[/\\\\])*`, so it cannot skip ahead on a literal and every
    line cost a full backtracking scan. Measured over 58,067 lines from two
    repositories, 18 hold a pointer and 9.1 per cent hold a colon: 8.63 ms per
    document became 1.26.

    The gate is sound because the pattern carries a literal `:` between its
    two groups with nothing optional around it. This checks that claim by
    running the REAL function against a copy of the one it replaced, over a
    document mixing genuine pointers into this repository's own prose as
    noise, so a gate narrowed to something the pattern does not require - a
    `.py:` prefix, say, or a colon followed by a space - shows up as sites
    that go missing. That is how this optimisation goes wrong: silently, by
    finding fewer pointers and reporting a clean document.
    """
    import subprocess
    from extant import session as hc
    from extant.rules import line_pointer as rule_line_pointer

    _reset()
    repo, commit = git_repo
    commit("core/engine.py", "x\n" * 40, "seed")
    commit("docs/plan.md", "y\n" * 12, "plan")
    commit("a.py", "z\n", "one line")

    body = [
        "See core/engine.py:123 for the detail.",
        "Edit docs/plan.md:4 next.",
        "And docs\\plan.md:9 with a backslash.",
        "A range core/engine.py:211-215 is read by its start.",
        "A column a.py:1:34 is judged on its line.",
        "Meeting at 10:30 in room 4.",
        "http://localhost:8080/x is a port.",
        "core/engine.py:40 is the last line.",
        "core/engine.py:41 is one past it.",
        "docs/plan.md:12 and docs/plan.md:13 on one line.",
        "No pointer at all on this line.",
    ]
    # Real prose as NOISE: thousands of lines the gate must skip, carrying
    # every colon this project happens to write, so the comparison is over
    # something harder than eleven crafted lines.
    root = Path(__file__).resolve().parent.parent
    listed = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True,
                            text=True, encoding="utf-8", errors="replace",
                            check=True)
    for relative in listed.stdout.splitlines():
        if not relative.lower().endswith((".md", ".mdx", ".rst")):
            continue
        try:
            with open(root / relative, encoding="utf-8", newline="") as fh:
                body.extend(fh.read().splitlines())
        except (OSError, UnicodeDecodeError):
            continue
    text = "\n".join(body) + "\n"

    ctx = hc.context(repo)
    want = _sites_without_the_gate(ctx, text)
    got = rule_line_pointer._line_pointer_sites_uncached(ctx, text)
    print(f"compared {len(body)} lines: {len(want)} pointer sites without the "
          f"gate, {len(got)} with it")
    assert len(want) >= 8, (
        f"only {len(want)} sites in the whole document, so agreement here "
        f"would prove nothing; the fixture or the checkout is wrong")
    assert got == want, (
        "the colon gate skipped a line the pattern would have matched, so the "
        "rule finds fewer pointers and says nothing about it")


def test_the_line_pointer_pattern_cannot_match_without_a_colon(git_repo) -> None:
    """The property `b5308b1`'s gate rests on, pinned against the pattern.

    `_line_pointer_sites_uncached` skips any line with no `:` in it before
    running `_LINKED_POINTER_UNUSED`. Its whole safety argument is that
    `_LINE_POINTER` carries a literal `:` between its two groups, with no
    alternation and nothing optional around it, so a colon-free line cannot
    match. A tighter gate that duplicated a fragment of the pattern was
    rejected on purpose, and that was the right call - but it leaves the gate
    sound only while the property holds. Make the colon optional or alternate
    it, and the gate starts skipping lines the pattern would have matched: the
    rule finds fewer pointers, reports a clean document, and nothing fails.

    Asserted against the COMPILED pattern by feeding it strings, never against
    its source text. A source-text assertion breaks when somebody reformats the
    pattern and passes when somebody changes what it means, which is the wrong
    way round on both counts.

    Three populations, because each catches a different edit:

    * Every real pointer this file uses, with its colons replaced by each other
      printable ASCII character and by nothing at all. This is the one that
      catches an ALTERNATION: alternate `:` with `#` and `a.py#1` starts
      matching, and it is in here.
    * The same shapes assembled from a path, a separator and a line number,
      including multi-character separators and the empty one. The empty
      separator is what catches the colon being made OPTIONAL.
    * Every colon-free line of this repository's own documents, which is the
      population the gate actually skips in production - about nine lines in
      ten of everything it reads.

    Observed failing against both edits before being trusted; the report beside
    this change records the two outputs.
    """
    import re
    import subprocess

    from extant.rules.line_pointer import _LINE_POINTER

    matching = [
        "core/engine.py:123",
        "a.py:1",
        r"docs\plan.md:4",
        "SKILL.md:211-215",
        "a.py:1:34",
        "deep/nested/dir/file.tsx:999999",
        "x.c:7",
        "See tests/test_line_pointers.py:12 for it.",
    ]
    for seed in matching:
        assert _LINE_POINTER.search(seed) is not None, (
            f"the seed {seed!r} does not match at all, so removing its colon "
            f"proves nothing; the fixture or the pattern moved")

    # Everything printable that is not a colon, plus a tab and three colon
    # LOOK-ALIKES - a pattern widened by pasting one of those in is a real way
    # for this to go wrong and they are not `:`.
    replacements = [chr(code) for code in range(0x20, 0x7F)
                    if chr(code) != ":"]
    replacements += ["\t", "\u2236", "\uFF1A", "\u0589", ""]
    # Separators longer than one character, which the substitution above
    # cannot reach.
    separators = list(replacements) + [
        "  ", " line ", "#L", "->", " L", "::", ", line ", " at "]
    separators = [s for s in separators if ":" not in s]

    probed = 0
    for seed in matching:
        for replacement in replacements:
            candidate = seed.replace(":", replacement)
            assert ":" not in candidate
            probed += 1
            assert _LINE_POINTER.search(candidate) is None, (
                f"{candidate!r} matched with no colon in it, so the gate in "
                f"`_line_pointer_sites_uncached` now skips lines this pattern "
                f"would have matched and the rule goes quiet")

    for separator in separators:
        for path in ("core/engine.py", "a.py", r"docs\plan.md", "x.md",
                     "deep/nested/file.tsx"):
            for number in ("1", "123", "999999"):
                candidate = f"{path}{separator}{number}"
                assert ":" not in candidate
                probed += 1
                assert _LINE_POINTER.search(candidate) is None, (
                    f"{candidate!r} matched with no colon in it, so the gate "
                    f"in `_line_pointer_sites_uncached` now skips lines this "
                    f"pattern would have matched and the rule goes quiet")

    root = Path(__file__).resolve().parent.parent
    listed = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True,
                            text=True, encoding="utf-8", errors="replace",
                            check=True)
    documents = 0
    real_lines = 0
    for relative in listed.stdout.splitlines():
        if not relative.lower().endswith((".md", ".mdx", ".rst")):
            continue
        try:
            with open(root / relative, encoding="utf-8", newline="") as fh:
                body = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        documents += 1
        for line in body.splitlines():
            if ":" in line:
                continue
            real_lines += 1
            assert _LINE_POINTER.search(line) is None, (
                f"{relative}: {line!r} matched with no colon in it, so the "
                f"gate skips a line this pattern would have matched")

    print(f"checked {probed} constructed strings and {real_lines} colon-free "
          f"lines from {documents} documents against the compiled pattern")
    assert probed >= 500 and real_lines >= 500 and documents >= 5, (
        f"only {probed} constructed strings and {real_lines} real lines from "
        f"{documents} documents; a pass here would prove nothing, so the "
        f"checkout or the generators are wrong")
    # The gate's own condition, stated as code rather than as prose: this is
    # the test `re` would have to break for the skip to become unsound.
    assert re.search(r"[^:]*", "") is not None      # sanity: re is not stubbed
