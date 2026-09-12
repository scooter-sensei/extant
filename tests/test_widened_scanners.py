"""The scanner widenings measured on 2026-09-12, and the shapes they refuse.

Ten widenings were proposed against nine rules. Each was counted on the
visible corpora before anything was written - 132 repositories, the holdout
rows of every manifest excluded - and only the ones with a population AND a
readable set of added findings were built. The measurement is recorded beside
each rule in the source; what is here is the behaviour, one test per shape.

Each test names the wrong implementation it would catch. The refusals matter
more than the positive cases: every widening here is a suppression's mirror
image, and a scanner that admits a shape it cannot settle reports coverage the
rule does not have.
"""
from __future__ import annotations

from pathlib import Path


def _reset():
    from extant import session as hc
    hc._SCOPE = hc.RunScope()
    hc._DOC = hc.DocScope()


def _md_link(repo: Path, text: str, base: Path | None = None):
    from extant import session as hc
    from extant.rules import md_link as rule
    _reset()
    if base is not None:
        hc._DOC = hc.DocScope(link_base=base)
    ctx = hc.context(repo)
    return rule.check(ctx, text), rule.examined(ctx, text)


# --- dead-md-link: reference-style definitions -------------------------------

def test_a_reference_definition_to_a_missing_file_is_reported(git_repo) -> None:
    """`[guide]: docs/setup.md` is a link, and was invisible.

    Catches a scanner that reads only the inline `[text](target)` shape.
    Measured on the visible corpora before it was written: 3,171 definitions
    name a local file, across 75 repositories, and the shape was examined
    zero times.
    """
    repo, commit = git_repo
    commit("README.md", "# x\n", "docs: readme")
    findings, examined = _md_link(
        repo, "Read the [guide].\n\n[guide]: docs/setup.md\n")
    assert [f.kind for f in findings] == ["dead-md-link"]
    assert findings[0].line == 3
    assert findings[0].subject == "docs/setup.md"
    assert examined == 1


def test_a_footnote_definition_is_not_a_link(git_repo) -> None:
    """`[^1]: some text` shares the colon and is a footnote.

    Catches a definition pattern that reads every `[x]:` line. facebook/
    docusaurus keeps footnote fixtures whose text would each be a dead file.
    """
    repo, commit = git_repo
    commit("README.md", "# x\n", "docs: readme")
    findings, examined = _md_link(repo, "A claim[^1].\n\n[^1]: foo\n")
    assert findings == []
    assert examined == 0


def test_a_parenthesised_destination_is_read_literally(git_repo) -> None:
    """`[label]:(file.go)` is a reference definition whose destination is the
    whole parenthesised run - CommonMark keeps balanced parentheses - so
    GitHub links it to a file literally named `(file.go)`, and the link is
    dead whether or not `file.go` exists.

    golang writes 63 such lines in one testdata README, every one naming a
    file since renamed as well. Catches a scanner that strips the
    parentheses and then judges the inner path, which would call the link
    working when it is not.
    """
    repo, commit = git_repo
    commit("cockroach_test.go", "package goker\n", "test: goker")
    findings, examined = _md_link(repo, "[cockroach#10214]:(cockroach_test.go)\n")
    assert [f.subject for f in findings] == ["(cockroach_test.go)"]
    assert examined == 1


def test_an_angle_bracketed_destination_is_read_without_its_brackets(git_repo) -> None:
    """`[doc]: <docs/a b.md>` is CommonMark's spelling for a spaced target.

    Catches a scanner that looks for a file literally named `<docs/...>`.
    """
    repo, commit = git_repo
    commit("docs/a b.md", "# a\n", "docs: spaced")
    findings, examined = _md_link(repo, "[doc]: <docs/a b.md>\n")
    assert findings == []
    assert examined == 1
    findings, _ = _md_link(repo, "[doc]: <docs/gone.md>\n")
    assert [f.subject for f in findings] == ["docs/gone.md"]


def test_a_title_after_the_destination_is_not_part_of_it(git_repo) -> None:
    """`[api]: docs/api.md "The API"` carries a title the file does not.

    Catches a scanner that takes the rest of the line as the target.
    """
    repo, commit = git_repo
    commit("docs/api.md", "# api\n", "docs: api")
    findings, examined = _md_link(repo, '[api]: docs/api.md "The API"\n')
    assert findings == []
    assert examined == 1


def test_an_external_definition_is_never_checked(git_repo) -> None:
    """Catches a definition scanner that skips the refusals inline links get."""
    repo, commit = git_repo
    commit("README.md", "# x\n", "docs: readme")
    findings, examined = _md_link(
        repo, "[docs]: https://example.com/docs\n[frag]: #heading\n"
              "[page]: guide.html\n[macro]: @ref\n")
    assert findings == []
    assert examined == 0


def test_a_definition_inside_a_fence_is_an_example(git_repo) -> None:
    """Catches a scanner reading the raw document rather than the stripped one."""
    repo, commit = git_repo
    commit("README.md", "# x\n", "docs: readme")
    findings, examined = _md_link(repo, "```\n[guide]: docs/gone.md\n```\n")
    assert findings == []
    assert examined == 0


def test_the_patch_generator_sees_a_reference_definition(git_repo) -> None:
    """The second reader of `link_sites`.

    `gate.suggest_renames` patches links to renamed files, and it was moved
    onto the one scanner precisely so it cannot disagree with the rule about
    what a link is. Catches a widening applied to the rule alone.
    """
    from extant.text import link_sites
    from extant import session as hc
    _reset()
    sites = link_sites(hc.DocScope(), "[guide]: docs/old%20guide.md\n")
    assert sites == [(1, "docs/old%20guide.md", "docs/old guide.md", False)]


# --- dead-md-link: raw HTML -------------------------------------------------

def test_an_html_image_source_to_a_missing_file_is_reported(git_repo) -> None:
    """`<img src="assets/arch.png">` in a README is a link GitHub resolves
    against the file, and it was invisible.

    Catches a scanner that reads markdown syntax alone. Measured on the visible
    corpora: 8,488 local `href`/`src` attributes across 86 repositories.
    """
    repo, commit = git_repo
    commit("README.md", "# x\n", "docs: readme")
    findings, examined = _md_link(
        repo, '<p align="center"><img src="assets/arch.png" width="600"></p>\n')
    assert [f.kind for f in findings] == ["dead-md-link"]
    assert findings[0].subject == "assets/arch.png"
    assert examined == 1


def test_an_html_anchor_href_to_an_existing_file_is_silent(git_repo) -> None:
    """Catches a scanner that fires on every tag it can parse."""
    repo, commit = git_repo
    commit("docs/faq.md", "# faq\n", "docs: faq")
    findings, examined = _md_link(repo, '<a href="docs/faq.md">FAQ</a>\n')
    assert findings == []
    assert examined == 1


def test_html_inside_a_generated_site_tree_is_neither_judged_nor_counted(git_repo) -> None:
    """The browser resolves a raw `src` against the page URL, not the file.

    mkdocs/mkdocs writes `<img src="../../img/x.png">` in `docs/user-guide/`
    and the image sits at `docs/img/x.png`: right on the site, missing on
    disk relative to the file. Catches an adapter that counts what the rule
    declines, which prints as coverage never provided.
    """
    repo, commit = git_repo
    commit("docs/mkdocs.yml", "site_name: x\n", "docs: site")
    commit("docs/img/x.png", "png\n", "docs: image")
    commit("docs/user-guide/theme.md", "# theme\n", "docs: page")
    from extant import session as hc
    from extant.rules import md_link as rule
    _reset()
    hc._DOC = hc.DocScope(link_base=repo / "docs" / "user-guide",
                          doc_path="docs/user-guide/theme.md")
    ctx = hc.context(repo)
    text = '<img src="../../img/x.png">\n![x](../../img/x.png)\n'
    assert rule.examined(ctx, text) == 1          # the markdown image only
    assert [f.line for f in rule.check(ctx, text)] == [2]


def test_html_outside_the_site_tree_is_still_judged(git_repo) -> None:
    """A repository with a site under `docs/` still has a README GitHub
    renders. Catches a refusal keyed on the repository rather than the
    document."""
    repo, commit = git_repo
    commit("docs/mkdocs.yml", "site_name: x\n", "docs: site")
    commit("docs/index.md", "# x\n", "docs: page")
    from extant import session as hc
    from extant.rules import md_link as rule
    _reset()
    hc._DOC = hc.DocScope(link_base=repo, doc_path="README.md")
    ctx = hc.context(repo)
    text = '<img src="assets/logo.png">\n'
    assert rule.examined(ctx, text) == 1
    assert [f.subject for f in rule.check(ctx, text)] == ["assets/logo.png"]


def test_a_templated_attribute_names_no_file(git_repo) -> None:
    """`<img src="{{ site.baseurl }}/x.png">` is a Jekyll expression.

    Catches a scanner that resolves the braces as a directory name.
    """
    repo, commit = git_repo
    commit("README.md", "# x\n", "docs: readme")
    findings, examined = _md_link(
        repo, '<img src="{{ site.baseurl }}/x.png">\n<a href="${BASE}/y.md">y</a>\n')
    assert findings == []
    assert examined == 0


def test_html_targets_get_the_refusals_markdown_links_get(git_repo) -> None:
    """External, fragment, data URI, `.html` page. Catches an HTML arm
    wired around `_link_target` instead of through it."""
    repo, commit = git_repo
    commit("README.md", "# x\n", "docs: readme")
    findings, examined = _md_link(
        repo, '<a href="https://example.com/x.md">x</a>\n'
              '<a href="#install">install</a>\n'
              '<img src="data:image/png;base64,AAAA">\n'
              '<a href="guide.html">guide</a>\n')
    assert findings == []
    assert examined == 0


def test_a_data_href_attribute_is_not_an_href(git_repo) -> None:
    """Catches a word boundary that admits `data-href="..."`."""
    repo, commit = git_repo
    commit("README.md", "# x\n", "docs: readme")
    findings, examined = _md_link(repo, '<a data-href="docs/gone.md">x</a>\n')
    assert findings == []
    assert examined == 0


def test_single_quoted_attributes_are_read(git_repo) -> None:
    """Catches a pattern that knows one quote character."""
    repo, commit = git_repo
    commit("README.md", "# x\n", "docs: readme")
    findings, examined = _md_link(repo, "<img src='assets/gone.png' alt=\"x\">\n")
    assert [f.subject for f in findings] == ["assets/gone.png"]
    assert examined == 1


def test_html_inside_a_fence_is_an_example(git_repo) -> None:
    """Catches a scanner reading the raw document rather than the stripped one."""
    repo, commit = git_repo
    commit("README.md", "# x\n", "docs: readme")
    findings, examined = _md_link(repo, '```html\n<img src="gone.png">\n```\n')
    assert findings == []
    assert examined == 0


# --- dead-line-pointer: the end of a range -------------------------------------

def _line_pointer(repo: Path, text: str):
    from extant import session as hc
    from extant.rules import line_pointer as rule
    _reset()
    ctx = hc.context(repo)
    return rule.check(ctx, text), rule.examined(ctx, text)


def test_a_range_whose_end_is_past_the_file_is_reported(git_repo) -> None:
    """`src/a.ts:32-116` against a 94-line file cites 22 lines that are not
    there, and was read by its start alone.

    The corpus case: lobehub/lobe-chat, a `**Location**:` citation in an
    agent-written README. Catches a rule that judges only the first number.
    Measured on the visible corpora: 27 ranges name a tracked file, 4 begin
    past the end (already reported), 1 ends past it, and the other 22 are
    inside the file.
    """
    repo, commit = git_repo
    commit("src/a.ts", "".join(f"line {n}\n" for n in range(1, 95)), "feat: a")
    findings, examined = _line_pointer(repo, "**Location**: `src/a.ts:32-116`\n")
    assert examined == 1
    assert [f.subject for f in findings] == ["src/a.ts:32-116"]
    assert "94 lines" in findings[0].detail


def test_a_range_inside_the_file_is_silent(git_repo) -> None:
    """Catches an end check written `>=` where `>` is meant."""
    repo, commit = git_repo
    commit("src/a.ts", "a\nb\nc\n", "feat: a")
    findings, examined = _line_pointer(repo, "See `src/a.ts:1-3`.\n")
    assert findings == []
    assert examined == 1


def test_a_line_and_column_is_not_a_range(git_repo) -> None:
    """`src/a.ts:10:80` is line 10, column 80 - the form every compiler and
    editor prints - and 69 of the 73 such citations on the corpora carry a
    second number below the first.

    Catches a separator class of `[:-]`, which would report column 80 of a
    50-line file as a line past its end.
    """
    repo, commit = git_repo
    commit("src/a.ts", "".join(f"line {n}\n" for n in range(1, 51)), "feat: a")
    findings, examined = _line_pointer(repo, "error at `src/a.ts:10:80`\n")
    assert findings == []
    assert examined == 1


def test_a_range_ending_below_its_start_is_read_by_its_start(git_repo) -> None:
    """`src/a.ts:40-2` names no range. Catches a rule that reports 2 > total
    as impossible, or one that refuses the site outright."""
    repo, commit = git_repo
    commit("src/a.ts", "a\nb\nc\n", "feat: a")
    findings, examined = _line_pointer(repo, "See `src/a.ts:40-2`.\n")
    assert examined == 1
    assert [f.subject for f in findings] == ["src/a.ts:40"]


# --- dead-sha: a range inside one backtick pair ------------------------------

def _dead_sha(repo: Path, text: str):
    from extant import session as hc
    from extant.rules import sha as rule
    _reset()
    ctx = hc.context(repo)
    return rule.check(ctx, text), rule.examined(ctx, text)


def test_both_ends_of_a_backticked_range_are_resolved(git_repo) -> None:
    """`` `7d6ec08..7499537` `` names two commits and was read as none.

    The corpus case is a session log recording a fast-forward push whose
    both ends a later force-push rewrote away. Catches a scanner that tests
    the whole backticked token for the SHA shape and drops it on the dots.
    """
    repo, commit = git_repo
    real = commit("a.py", "a = 1\n", "feat: a")
    dead = "deadbee" + "0" * 33
    findings, examined = _dead_sha(repo, f"Pushed `main` (`{real[:7]}..{dead}`).\n")
    assert examined == 2
    assert [f.subject for f in findings] == [dead]
    assert findings[0].kind == "dead-sha"


def test_the_three_dot_spelling_is_a_range_too(git_repo) -> None:
    """`a...b` is git's symmetric-difference range. Catches a splitter that
    knows two dots and reads the third as part of a token."""
    repo, commit = git_repo
    real = commit("a.py", "a = 1\n", "feat: a")
    dead = "deadbee" + "0" * 33
    findings, examined = _dead_sha(repo, f"Compare `{dead}...{real[:7]}`.\n")
    assert examined == 2
    assert [f.subject for f in findings] == [dead]


def test_a_range_that_is_link_text_belongs_to_the_link(git_repo) -> None:
    """`` [`a..b`](.../compare/a..b) `` says whose commits these are.

    helix's changelog writes it, and the first commit of the pair is one a
    rebase left unreachable while GitHub's compare page still serves it.
    Catches a range splitter wired around `_LINKED_SHA` instead of through
    the same span check a single linked SHA gets.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    dead = "deadbee" + "0" * 33
    text = (f"- Overhaul ([`{dead}..4080341`]"
            f"(https://github.com/helix-editor/helix/compare/{dead}..4080341))\n")
    findings, examined = _dead_sha(repo, text)
    assert findings == []
    assert examined == 0


def test_a_command_holding_a_range_is_not_a_range(git_repo) -> None:
    """`` `git log abc1234..def5678` `` is a command; the token is not two
    commits joined by dots. Catches a splitter that searches inside the
    backticks instead of matching the whole token."""
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    dead = "deadbee" + "0" * 33
    findings, examined = _dead_sha(repo, f"Run `git log {dead}..{dead}`.\n")
    assert findings == []
    assert examined == 0


def test_the_rewriter_translates_both_ends_of_a_range() -> None:
    """Detection and repair must read the same tokens, or the class this
    rule reports becomes one `--sha-map` cannot fix. Catches a range admitted
    to the scanner and not to `translate_shas`."""
    from extant.commits import translate_shas
    old_a, old_b = "a1a1a1a" + "1" * 33, "b2b2b2b" + "2" * 33
    new_a, new_b = "c3c3c3c" + "3" * 33, "d4d4d4d" + "4" * 33
    text = f"Pushed (`{old_a[:7]}..{old_b[:7]}`) and `{old_a[:7]}` alone.\n"
    out, count = translate_shas(text, {old_a: new_a, old_b: new_b})
    assert count == 3
    assert out == f"Pushed (`{new_a[:7]}..{new_b[:7]}`) and `{new_a[:7]}` alone.\n"


def test_a_range_starting_past_the_end_keeps_its_old_fingerprint(git_repo) -> None:
    """`app.py:8-9` on a three-line file was reported as `app.py:8` before
    ranges were read, and `detail` is the baseline fingerprint.

    Catches a finding that spells every range as a range, which would
    re-raise every such finding a project's baseline had already forgiven.
    """
    repo, commit = git_repo
    commit("app.py", "a\nb\nc\n", "feat: app")
    findings, _ = _line_pointer(repo, "See `app.py:8-9`.\n")
    assert [f.subject for f in findings] == ["app.py:8"]
    assert "`app.py:8`" in findings[0].detail


def test_html_tag_and_attribute_names_are_case_insensitive(git_repo) -> None:
    """`<IMG SRC="...">` is the same element. Catches a pattern compiled
    without `re.I`, which would read only lower-case HTML and say nothing
    about the rest."""
    repo, commit = git_repo
    commit("README.md", "# x\n", "docs: readme")
    findings, examined = _md_link(repo, '<IMG SRC="assets/gone.png">\n')
    assert [f.subject for f in findings] == ["assets/gone.png"]
    assert examined == 1


def test_the_html_scan_is_not_quadratic() -> None:
    """A line of a hundred thousand unclosed tags must not hang the scan.

    A single bounded pattern over the whole line costs every tag start its
    full 4096-character walk, which measured 12.5 seconds on a 96 KB line of
    `<a ` - the same shape that once cost `MD_LINK` three minutes. The scan
    walks the line ONCE, tag by tag, and a tag with no `>` after it is not a
    tag. The budget is loose on purpose: this guards against catastrophic
    growth, not a benchmark.
    """
    import time
    from extant.text import _html_references
    worst = 0.0
    for line in ("<a " * 32000,
                 '<a href="' * 32000,
                 "<a " * 32000 + ">",
                 ("<img " + "x" * 4000 + ">") * 30,
                 "<" * 120000):
        started = time.perf_counter()
        _html_references(line)
        worst = max(worst, time.perf_counter() - started)
    assert worst < 1.0, f"slowest line took {worst:.1f}s; the scan is quadratic"


def test_the_html_scan_still_reads_a_real_tag() -> None:
    """The speed fix must not have been achieved by matching nothing."""
    from extant.text import _html_references
    line = ('<p align="center"><a href="docs/faq.md"><img src=\'assets/logo.png\''
            ' width="600" /></a> <A HREF="x.md" data-href="no.md"></A></p>')
    assert _html_references(line) == ["docs/faq.md", "assets/logo.png", "x.md"]


def test_the_rewriter_repairs_the_end_it_can_read_beside_one_it_cannot() -> None:
    """`` `7d6ec08..7499537` ``: the scanner reads the first end and refuses
    the second as all digits, and the rewriter has to reach exactly what the
    scanner reported. Catches a rewriter that refuses the whole range when one
    end fails the shape test, which would leave a reported finding no
    `--sha-map` can fix."""
    from extant.commits import translate_shas
    old = "7d6ec08" + "a" * 33
    new = "9e9e9e9" + "b" * 33
    out, count = translate_shas("Pushed (`7d6ec08..7499537`).\n", {old: new})
    assert count == 1
    assert out == "Pushed (`9e9e9e9..7499537`).\n"
