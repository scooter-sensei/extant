"""The two hook pipelines that became builtins, against the pipelines they replace.

Shell is the least forgiving material in this repository: no type checker, no
test that reads it as a program, and failures that are quiet. A mis-parsed
`primary_doc` does not crash - it validates the wrong file, or validates
nothing, which is the exact shape this hook has been caught in twice already
(once hardcoding the document name, once hardcoding the Windows virtualenv
path, each time looking perfectly healthy while doing nothing).

So these are divergence tables, and four things about how they are built are
load-bearing, each because an attempt at this got it wrong:

* THE REPLACEMENT IS LIFTED FROM THE SHIPPED FILE, by name, rather than
  retyped. A retyped `sed` pattern was mangled by shell quoting, returned the
  empty string for all nine cases, and the builtin "agreed" with it everywhere
  - a comparison in which neither side did anything, reported as zero
  divergences.
* THE ORACLE CARRIES ITS OWN DENOMINATOR. The pipelines being compared against
  ARE retyped here, because the hook no longer contains them, so each table
  asserts how many of its cases produce a NON-EMPTY result. A mangled oracle
  now fails loudly instead of agreeing with everything.
* COUNT IS USED, NOT PRINTED. The formatter's first implementation ran its loop
  in a pipeline, so the count never left the subshell - and the test missed it
  precisely because the test printed the count rather than using it afterwards
  the way the hook does, in an `if`.
* THE SAMPLES SPAN SIZES. Every formatter sample was under 600 bytes while the
  implementation silently returned nothing above 4 KB, so nine cases reported
  zero divergences and proved only that both sides agreed on small inputs. See
  the note on `OUTPUTS`. A hook prints five lines whatever the output's size,
  which is why size is the dimension nobody thinks to vary.

Both run under `sh` AND under `dash`: CI's /bin/sh is dash, and these
constructs - `[[:space:]]` inside a `case` bracket, `${var%%"$_LF"*}` splitting,
`${#var}` - had only ever been exercised under Git Bash. That was not
belt-and-braces: `dash` is where the size defect above appears and `sh` is
where it does not.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
HOOK = (PACKAGE_ROOT / "plugin" / "skills" / "extant" / "payload" / "hooks"
        / "extant-verify")

# The shells that could actually run this hook, and are present here. `sh` is
# what the shebang names - Git's on Windows, the system one elsewhere - and
# `dash` is what CI's /bin/sh IS, which is the whole reason it is listed
# separately: every construct in these functions had only ever been exercised
# under Git Bash.
#
# `bash` is deliberately NOT in the list. On Windows `shutil.which("bash")`
# finds `C:\Windows\System32\bash.exe`, which is the WSL launcher rather than a
# shell - it cannot open a Windows path at all, so it fails every case here for
# a reason that has nothing to do with the code. Nothing runs this hook through
# it, and a third shell that reports a harness fault as a portability finding
# is worse than two that report neither.
SHELLS = [name for name in ("sh", "dash") if shutil.which(name)]


def shell_function(name: str) -> str:
    """The named function's definition, lifted verbatim out of the shipped hook.

    Anchored on a closing brace in column 0, which is the only place this file
    puts one, so the extraction cannot swallow the rest of the script.
    """
    text = HOOK.read_text(encoding="utf-8")
    match = re.search(r"^%s\(\) \{$.*?^\}$" % re.escape(name), text,
                      re.MULTILINE | re.DOTALL)
    assert match, f"no shell function named {name} in {HOOK}"
    return match.group(0)


def write_exactly(path: Path, text: str) -> None:
    """Write `text` byte for byte, with no line-ending translation.

    `open(..., newline="")` rather than `Path.write_text(newline=...)`, which
    is a 3.10 method against a 3.9 floor - tests/test_packaging.py fails the
    suite over it, and has, because two such calls once shipped in the
    installer. The exactness matters here beyond tidiness: on Windows the
    default translation turns every LF into CRLF, so a .extant.toml written
    that way carries a trailing CR into the value the shipped `sed` reads and
    the comparison stops being about the code.
    """
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def run(shell: str, script: str, *args: str, check: bool = True) -> str:
    """Run `script` under `shell`, from a FILE rather than through `-c`.

    Through `-c` on Windows the script is a single argv element, and the shells
    that ship with Git rebuild their argv from the Windows command line with
    rules that are not quite the MSVCRT ones Python quotes with. A multi-line
    script carrying quotes and backticks came back mangled under `bash` and
    intact under `sh` - which reads as a portability failure in the code, and
    is a failure of the harness. A file has no quoting to get wrong.

    POSIX SPELLINGS OF EVERY PATH, for the second half of the same problem:
    `bash` from Git for Windows drops the backslashes out of a native path
    handed to it as an argument, so a `C:\\Users\\...` script arrives as
    `C:Users...` and is not found. `sh` and `dash` from the same install do
    not. Callers pass their paths through `Path.as_posix()` for the same
    reason, and the sample text the formatter reads comes from a FILE rather
    than from argv so that a finding containing a backslash reaches the shell
    intact under every one of them.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "case.sh"
        write_exactly(path, script)
        done = subprocess.run(
            [shell, path.as_posix(), *args], capture_output=True, text=True,
            encoding="utf-8",
        )
    assert not check or done.returncode == 0, (
        f"{shell} exited {done.returncode}: {done.stderr}\n{script}")
    return done.stdout


# --- the config read ---------------------------------------------------------

# The pipeline being replaced, retyped because the hook no longer carries it.
# Written as a single-quoted Python string holding a double-quoted shell string,
# which is the same quoting the hook used, so what is compared against is what
# the hook ran.
SHIPPED_SED = (
    'sed -n "s/^[[:space:]]*primary_doc[[:space:]]*=[[:space:]]*[\\"\']'
    '\\\\([^\\"\']*\\\\).*/\\\\1/p" "$1" | head -n 1'
)

# Seventeen spellings of a .extant.toml. Twelve name a document; the other five
# are the ways a line can look like the setting and not be one.
CONFIGS = [
    pytest.param('primary_doc = "NEXT_SESSION.md"\n', id="plain"),
    pytest.param("primary_doc = 'NEXT_SESSION.md'\n", id="single-quoted"),
    pytest.param('primary_doc="NEXT_SESSION.md"\n', id="no-spaces"),
    pytest.param('   primary_doc   =   "NEXT_SESSION.md"\n', id="padded"),
    pytest.param('\tprimary_doc = "NEXT_SESSION.md"\n', id="tab-indented"),
    pytest.param('[extant]\nprimary_doc = "docs/STATUS.md"\nother = 1\n',
                 id="inside-a-table"),
    pytest.param('primary_doc = "first.md"\nprimary_doc = "second.md"\n',
                 id="two-values-takes-the-first"),
    pytest.param('primary_doc = "NEXT.md"  # trailing comment\n',
                 id="trailing-comment"),
    pytest.param('primary_doc = "has space.md"\n', id="value-with-a-space"),
    pytest.param("# primary_doc = \"commented.md\"\n", id="commented-out"),
    pytest.param("primary_doc = NEXT_SESSION.md\n", id="unquoted-value"),
    pytest.param("other_primary_doc = \"x.md\"\n", id="a-longer-key"),
    pytest.param("", id="empty-file"),
    pytest.param("[extant]\ntrunk = \"main\"\n", id="no-such-setting"),
    # Terminators, which this project has been caught by three times over. A
    # file with no final newline needs the loop's `|| [ -n "$_line" ]` guard;
    # a CRLF file leaves a CR that must land AFTER the closing quote and not
    # inside the value; a CR-only file is one `read` line to both sides.
    pytest.param('primary_doc = "NOEOL.md"', id="no-trailing-newline"),
    pytest.param('primary_doc = "CRLF.md"\r\nother = 1\r\n', id="crlf"),
    pytest.param('primary_doc = "CRONLY.md"\rother = 1\r', id="cr-only"),
]

NAMED_BY_TWELVE = 12


@pytest.mark.parametrize("config", CONFIGS)
@pytest.mark.parametrize("shell", SHELLS)
def test_the_builtin_config_read_matches_the_pipeline_it_replaced(
        shell, config, tmp_path) -> None:
    path = tmp_path / ".extant.toml"
    write_exactly(path, config)

    piped = run(shell, SHIPPED_SED, path.as_posix()).rstrip("\n")
    builtin = run(
        shell,
        shell_function("extant_primary_doc")
        + '\nextant_primary_doc "$1"\nprintf %s "$EXTANT_PRIMARY_DOC"\n',
        path.as_posix())

    print(f"{shell}: sed={piped!r} builtin={builtin!r}")
    assert builtin == piped


@pytest.mark.parametrize("shell", SHELLS)
def test_the_config_cases_are_not_all_empty(shell, tmp_path) -> None:
    """The denominator. Two implementations that both do nothing agree.

    This is the check the first attempt at this comparison did not have: its
    retyped `sed` was mangled, produced "" for every case, and the builtin
    matched it perfectly.
    """
    answered = 0
    for index, case in enumerate(CONFIGS):
        path = tmp_path / f"c{index}.toml"
        write_exactly(path, case.values[0])
        if run(shell, SHIPPED_SED, path.as_posix()).strip():
            answered += 1
    print(f"{shell}: {answered} of {len(CONFIGS)} cases name a document")
    assert answered == NAMED_BY_TWELVE, (
        f"{answered} non-empty results, expected {NAMED_BY_TWELVE}: the oracle "
        f"is not doing what the hook did, so the comparison proves nothing")


# --- the findings formatter --------------------------------------------------

# The sample arrives as a FILE and is read with `$(cat ...)` on both sides,
# which is not merely a way around argv mangling: it is how the hook gets its
# own OUTPUT, from `$("$PY" "$TOOL" --verify ...)`. Command substitution strips
# trailing newlines, so a comparison fed through argv would be comparing
# something the hook never sees.
_SAMPLE = '_out=$(cat "$1")\n'
SHIPPED_COUNT = _SAMPLE + "printf '%s\\n' \"$_out\" | grep -c '\\['"
SHIPPED_LISTING = _SAMPLE + "printf '%s\\n' \"$_out\" | head -5 | sed 's/^/  /'"

# The samples, including the characters that break a naive here-document, the
# shapes real `--verify` output takes, and - added after the fact - sizes.
#
# THE SIZE CASES ARE THE POINT OF THIS LIST, because their absence is what let
# a silent wrong answer through review. The first implementation read the whole
# output through a here-document, which under the `dash` shipped with Git for
# Windows returns NOTHING above about 4 KB: 2691 bytes read back every line,
# 5491 bytes read back none, so COUNT came out 0 and the listing empty while
# `--verify` had exited 1. Every sample here was under 600 bytes, so the table
# reported zero divergences across nine cases and proved only that the two
# agreed on small inputs. A hook prints five lines whatever the size, which is
# exactly why nobody thinks to test a big one.
OUTPUTS = [
    pytest.param("", id="empty"),
    pytest.param("NEXT_SESSION.md:12 [dead-sha] `abc1234` does not resolve",
                 id="one-finding"),
    pytest.param("\n".join(f"NEXT_SESSION.md:{n} [dead-sha] gone" for n in range(1, 4)),
                 id="three-findings"),
    pytest.param("\n".join(f"NEXT_SESSION.md:{n} [dead-md-link] gone"
                           for n in range(1, 13)),
                 id="twelve-findings"),
    pytest.param("checked NEXT_SESSION.md: dead-sha 39, dead-md-link 4\n"
                 "NEXT_SESSION.md:8 [dead-sha] `deadbee` does not resolve",
                 id="denominator-line-then-a-finding"),
    pytest.param("NEXT.md:3 [dead-path-pointer] points at `a\\b\\c.md`",
                 id="backslashes"),
    pytest.param("NEXT.md:4 [dead-md-link] 100% of the links are dead",
                 id="percent-signs"),
    pytest.param("NEXT.md:5 [dead-sha] $HOME and `date` and $(id) are literal",
                 id="dollars-and-backticks"),
    pytest.param("no findings at all, and no bracket anywhere", id="no-brackets"),
    # 300 findings is about 8 KB, which is the smallest of these that crosses
    # the ~4 KB boundary where the here-document version began returning
    # nothing. This is the regression guard; the one below it is the evidence
    # that the replacement's cost does not grow with the input.
    pytest.param("\n".join(f"NEXT_SESSION.md:{n} [dead-sha] `abc{n:04d}` is gone"
                           for n in range(1, 301)),
                 id="three-hundred-findings"),
    pytest.param("\n".join(f"NEXT_SESSION.md:{n} [dead-md-link] `docs/p{n}.md`"
                           for n in range(1, 1501)),
                 id="fifteen-hundred-findings"),
]


@pytest.mark.parametrize("output", OUTPUTS)
@pytest.mark.parametrize("shell", SHELLS)
def test_the_builtin_formatter_matches_the_pipeline_it_replaced(
        shell, output, tmp_path) -> None:
    sample = tmp_path / "verify-output.txt"
    write_exactly(sample, output)

    # `grep -c` exits 1 when it counts nothing, and the hook read it inside
    # `$(...)` where that status is discarded. The oracle discards it too, or
    # this harness fails on precisely the empty case it exists to cover.
    piped_count = run(shell, SHIPPED_COUNT, sample.as_posix(),
                      check=False).strip()
    piped_listing = run(shell, SHIPPED_LISTING, sample.as_posix())

    # COUNT is USED here, in an `if`, exactly as the hook uses it after the
    # listing - not merely printed. The implementation this caught ran its loop
    # in a pipeline, so COUNT was set in a subshell and the parent saw nothing.
    builtin = run(
        shell,
        shell_function("extant_findings_summary")
        + "\n" + _SAMPLE
        + 'extant_findings_summary "$_out"\n'
        + 'printf %s "$LISTING"\n'
        + 'if [ "$COUNT" -gt 5 ]; then printf "MANY:%s\\n" "$COUNT"\n'
        + 'else printf "FEW:%s\\n" "$COUNT"; fi\n',
        sample.as_posix())
    marker, _, builtin_count = builtin.rsplit("\n", 2)[-2].partition(":")
    builtin_listing = builtin[:len(builtin) - len(builtin.rsplit("\n", 2)[-2]) - 1]

    print(f"{shell}: count pipeline={piped_count} builtin={builtin_count} "
          f"({marker})")
    assert builtin_count == piped_count
    assert builtin_listing == piped_listing
    assert marker == ("MANY" if int(piped_count) > 5 else "FEW"), (
        "COUNT did not survive into the parent shell, where the hook uses it")


@pytest.mark.parametrize("shell", SHELLS)
def test_the_formatter_cases_are_not_all_empty(shell, tmp_path) -> None:
    """The same denominator, for the same reason."""
    counted = []
    for index, case in enumerate(OUTPUTS):
        sample = tmp_path / f"o{index}.txt"
        write_exactly(sample, case.values[0])
        counted.append(int(run(shell, SHIPPED_COUNT, sample.as_posix(),
                               check=False).strip()))
    print(f"{shell}: counts from the shipped pipeline: {counted}")
    assert sum(1 for c in counted if c) >= 6, counted
    assert max(counted) > 5, (
        "no case exceeds five findings, so the `... run:` branch and the "
        "COUNT-in-the-parent assertion are never exercised")
    # The size denominator, and the reason this assertion exists at all: every
    # sample was under 600 bytes when a 4 KB threshold was silently breaking
    # the count. A table that cannot reach the boundary cannot see the bug.
    biggest = max(len(case.values[0]) for case in OUTPUTS)
    print(f"{shell}: largest sample is {biggest} bytes")
    assert biggest > 8000, (
        f"largest sample is {biggest} bytes; nothing here crosses the ~4 KB "
        f"boundary where a here-document silently stopped returning lines")


def test_a_shell_was_actually_found() -> None:
    """Otherwise every parametrised test above collects zero cases and passes."""
    print("shells exercised: "
          + ", ".join(f"{name} ({shutil.which(name)})" for name in SHELLS))
    assert SHELLS, "no POSIX shell available; the tables above proved nothing"
