"""Checks on the package itself, rather than on what it validates.

These exist because the failure mode this project cares about is an unfinished
thing that looks finished. A placeholder in a legal notice and a non-ASCII
character in printed output are both invisible until they are expensive.
"""
from __future__ import annotations

import io
import sys
import tokenize
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
SKILL_ROOT = PACKAGE_ROOT / "plugin" / "skills" / "extant"


def test_no_publication_placeholders_remain() -> None:
    """Fails while any shipped file still carries the owner placeholder.

    It appears in LICENSE as a copyright holder, and in both plugin manifests
    as an owner, author, and homepage URL. A placeholder in a legal notice is
    not a legal notice, and a marketplace entry pointing at a homepage that does
    not exist is worse than one with no homepage at all.

    Swept rather than checked file by file, because the placeholder spread from
    one file to three the moment the plugin manifests were added, and a
    per-file assertion would have kept passing on the two new ones.
    """
    # Split so this file is not its own match.
    placeholder = "<GITHUB-" + "USERNAME>"

    offenders: list[str] = []
    checked = 0
    for path in sorted(PACKAGE_ROOT.rglob("*")):
        parts = path.relative_to(PACKAGE_ROOT).parts
        if not path.is_file() or {".git", "__pycache__", ".pytest_cache"} & set(parts):
            continue
        if path.name == "test_packaging.py":
            continue
        checked += 1
        if placeholder in path.read_text(encoding="utf-8", errors="replace"):
            offenders.append(path.relative_to(PACKAGE_ROOT).as_posix())

    assert checked > 15, f"only {checked} files scanned; the skip list is wrong"
    assert "MIT License" in PACKAGE_ROOT.joinpath("LICENSE").read_text(encoding="utf-8")
    assert not offenders, (
        f"{len(offenders)} file(s) still carry the {placeholder} placeholder. "
        f"Replace it with the owner's real name or handle:\n  "
        + "\n  ".join(offenders)
    )


def test_no_read_text_newline_argument() -> None:
    """`Path.read_text(newline=...)` requires Python 3.13 and breaks below it.

    pathlib gained that argument in 3.13. On 3.11 and 3.12 it raises
    TypeError, and it shipped: `detect.py` used it, so `install.py` crashed
    outright on the two oldest versions this project claims to support. The test
    suite ran on both in CI and stayed green on that file, because nothing
    called into it.

    `write_text` took the same argument back in 3.10, which is why only the read
    side broke, and why this is easy to write without noticing.

    Parsed rather than grepped, so a call split across lines cannot slip past.
    """
    import ast

    offenders: list[str] = []
    files = 0
    read_text_calls = 0
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        parts = path.relative_to(PACKAGE_ROOT).parts
        if {"__pycache__", ".venv", ".pytest_cache"} & set(parts):
            continue
        files += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr == "read_text":
                read_text_calls += 1
                if any(kw.arg == "newline" for kw in node.keywords):
                    offenders.append(
                        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{node.lineno}"
                    )

    assert files > 3, f"only {files} Python files parsed"
    assert read_text_calls > 0, "no read_text calls found at all; this proves nothing"
    assert not offenders, (
        "read_text(newline=...) needs Python 3.13. Use "
        "open(path, encoding=..., newline=...) instead:\n  " + "\n  ".join(offenders)
    )


def test_payload_string_literals_are_ascii() -> None:
    """Non-ASCII in printed output crashes a cp437 console.

    Printing U+2014 there raises UnicodeEncodeError and terminates the process.
    The installer died partway through, after it had already copied files into
    the target repository. A cp1252 console renders it as mojibake instead,
    which is why it went unnoticed during development.

    Scoped to string literals, since comments never reach a console.
    """
    string_types = {tokenize.STRING}
    for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
        if hasattr(tokenize, name):
            string_types.add(getattr(tokenize, name))

    offenders: list[str] = []
    files = 0
    literals = 0
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        parts = path.relative_to(PACKAGE_ROOT).parts
        if "__pycache__" in parts or ".venv" in parts:
            continue
        files += 1
        source = path.read_text(encoding="utf-8")
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type not in string_types:
                continue
            literals += 1
            for char in tok.string:
                if ord(char) > 127:
                    offenders.append(
                        f"{path.relative_to(PACKAGE_ROOT)}:{tok.start[0]}: "
                        f"U+{ord(char):04X}"
                    )
                    break

    # Both denominators. Either one reaching zero would turn this into a test
    # that passes by examining nothing.
    assert files > 3, f"only {files} Python files scanned"
    assert literals > 50, f"only {literals} string literals examined"
    assert not offenders, (
        "non-ASCII in a string literal (use '-' for an em dash, '...' for an "
        "ellipsis, '->' for an arrow):\n" + "\n".join(offenders)
    )


def test_this_repositorys_own_config_is_kept_out_of_tests() -> None:
    """Pins the `neutral_config` fixture, which is otherwise unfalsifiable.

    Settings load at import, relative to the payload, and the upward search
    finds this repository's `.extant.toml`. Every in-process test would then
    run against whatever this project configures for itself. An autouse fixture
    resets that to defaults, and an autouse fixture that quietly stops working
    looks exactly like one that is working.
    """
    import extant_collect as hc
    from extant_config import load_config

    own = load_config(PACKAGE_ROOT)

    # The denominator. If this repository stops configuring extra documents,
    # the assertion below passes while demonstrating nothing, so fail loudly
    # and say what to re-point it at rather than pass in silence.
    assert own.extra_docs, (
        "this repository no longer sets extra_docs, so this test no longer "
        "shows that ambient configuration is kept out of tests. Re-point it at "
        "whatever setting this repository does configure."
    )
    assert hc.CONFIG.extra_docs == (), (
        "this repository's own extra_docs leaked into a test: "
        f"{hc.CONFIG.extra_docs}. The neutral_config fixture is not applying."
    )


def test_every_shipped_file_is_ascii_including_prose() -> None:
    """Nothing pinned the DOCUMENTATION, which is where an em dash comes from.

    Two ASCII checks already exist and neither covers a markdown file: one
    tokenizes Python and reads string literals only, the other reads the shell
    hooks. Prose was the gap, and prose is exactly where a smart-quote or an em
    dash arrives, pasted in with a sentence, in a README that a Windows console
    then cannot print.

    Whole-file and allowlist-free on purpose. An extension filter is how this
    check would quietly stop covering something: a hand-written list of
    suffixes silently skips every file whose kind nobody thought of, and the
    extensionless hooks are already three such files. Everything tracked is
    read, and a binary would have to be declared here deliberately.
    """
    skipped: list[str] = []
    offenders: list[str] = []
    scanned = 0

    for path in sorted(PACKAGE_ROOT.rglob("*")):
        parts = path.relative_to(PACKAGE_ROOT).parts
        if not path.is_file():
            continue
        if {".git", "__pycache__", ".pytest_cache", ".venv"} & set(parts):
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            # Report the character rather than the byte offset alone: "U+2014"
            # is actionable and "invalid byte at 4211" is not.
            char = raw.decode("utf-8", errors="replace")[:exc.start + 1][-1]
            offenders.append(
                f"{path.relative_to(PACKAGE_ROOT)}: U+{ord(char):04X} ({char!r})"
            )
            continue
        if "\x00" in text:
            skipped.append(str(path.relative_to(PACKAGE_ROOT)))
            continue
        scanned += 1

    # Denominators. A rglob that matched nothing, or an exclusion that grew to
    # cover the repository, would otherwise pass in exactly the same silence.
    assert scanned > 20, f"only {scanned} files scanned; the sweep is not reaching them"
    assert not skipped, f"binary files present and unexamined: {skipped}"
    assert not offenders, (
        "non-ASCII in a shipped file (use '-' for an em dash, '...' for an "
        "ellipsis, '->' for an arrow, and plain quotes):\n  "
        + "\n  ".join(offenders)
    )


def test_shipped_shell_hooks_are_ascii() -> None:
    """The hooks echo to a terminal too, and are not Python, so tokenize cannot
    see them. Whole-file check: they carry no diagrams to preserve."""
    hooks = sorted((SKILL_ROOT / "payload" / "hooks").iterdir())
    offenders = [
        f"{h.name}: U+{ord(c):04X}"
        for h in hooks if h.is_file()
        for c in h.read_text(encoding="utf-8") if ord(c) > 127
    ]

    assert len(hooks) >= 3, f"only {len(hooks)} hook files found"
    assert not offenders, "non-ASCII in a shell hook:\n" + "\n".join(offenders)


def test_installer_ships_every_hook_it_wires() -> None:
    """The pre-commit guard was wired by the hook installer while nothing
    shipped the file, so it never ran once and the installer reported success.
    """
    import re

    hooks = SKILL_ROOT / "payload" / "hooks"
    text = hooks.joinpath("install").read_text(encoding="utf-8")
    referenced = sorted(set(re.findall(r"tools/hooks/([A-Za-z0-9_-]+)", text)))

    assert referenced, "found no hook references in payload/hooks/install"
    missing = [n for n in referenced if not (hooks / n).is_file()]
    assert not missing, (
        f"payload/hooks/install wires {referenced}; missing from payload/hooks/: "
        f"{missing}"
    )


def test_command_template_placeholders_are_all_rendered() -> None:
    """Every placeholder in the template must be one the installer substitutes.

    A placeholder added to the template but not to the renderer's mapping would
    ship literally into an adopter's slash command, which is how the command
    file came to name another project in the first place.
    """
    import sys

    sys.path.insert(0, str(SKILL_ROOT))
    import install as installer  # noqa: E402

    template = SKILL_ROOT / "payload" / "commands" / "extant.md.template"
    found = set(__import__("re").findall(r"\{\{[A-Z_]+\}\}", template.read_text(encoding="utf-8")))

    assert found, "template contains no placeholders; the renderer would be a no-op"

    from detect import DERIVED, Observation  # noqa: E402

    obs = [
        Observation("primary_doc", "STATUS.md", DERIVED, "test"),
        Observation("archive_doc", "docs/archive.md", DERIVED, "test"),
        Observation("entry_prefix", "## Release ", DERIVED, "test"),
    ]
    rendered, notes = installer.render_command(obs, "example-project")

    assert "{{" not in rendered, f"unsubstituted placeholder survived: {notes}"
    assert "example-project" in rendered
    assert "STATUS.md" in rendered


def test_no_invalid_escape_sequences_anywhere() -> None:
    r"""No source file may contain an invalid string escape such as "\d".

    Python still accepts these while warning that they will stop working, so
    they are a latent break rather than a style nit. They are also nearly
    invisible: the SyntaxWarning fires only when a module is COMPILED, so a
    .pyc cache hides it after the first run and the file looks clean forever.

    Absent from this package until now, and it cost four separate occurrences
    in one session - every one written by a heredoc that consumed a backslash,
    every one caught by hand rather than by the suite. The check that would
    have caught them existed in the project this was extracted from and was
    simply not carried across.
    """
    import warnings

    offenders: list[str] = []
    scanned = 0
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        parts = path.relative_to(PACKAGE_ROOT).parts
        if {"__pycache__", ".venv", ".pytest_cache"} & set(parts):
            continue
        scanned += 1
        source = path.read_text(encoding="utf-8")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                compile(source, str(path), "exec")
            except SyntaxError as exc:
                offenders.append(f"{path.relative_to(PACKAGE_ROOT)}: {exc}")
                continue
        offenders += [
            f"{path.relative_to(PACKAGE_ROOT)}:{entry.lineno}: {entry.message}"
            for entry in caught if issubclass(entry.category, SyntaxWarning)
        ]

    # A scan that examined nothing passes silently, which is how the equivalent
    # check shipped broken elsewhere. Assert it looked at the codebase.
    assert scanned > 10, f"only {scanned} files scanned; the skip list is wrong"
    assert not offenders, (
        "invalid escape sequences (use a raw string or double the backslash):\n  "
        + "\n  ".join(offenders)
    )


def test_every_config_derived_global_is_reloadable() -> None:
    """A derived global that reload_config forgets keeps a stale value.

    Configuration is read at import, relative to the file. Installed as a
    package - which the pre-commit framework does - that location is
    site-packages, so the tool must re-read config for the repository it was
    pointed at. Anything derived from CONFIG and not refreshed then silently
    describes some other project.

    The source is PARSED for the assignments rather than compared against a
    hand-written list, so adding a derived global without reloading it fails
    here instead of shipping.
    """
    import re
    import sys

    sys.path.insert(0, str(SKILL_ROOT / "payload"))
    import extant_collect as hc

    source = (SKILL_ROOT / "payload" / "extant_collect.py").read_text(encoding="utf-8")
    assigned = dict(re.findall(r"^(\w+) = CONFIG\.(\w+)$", source, re.M))

    assert assigned, "found no CONFIG-derived globals; this check proves nothing"
    assert assigned == hc._CONFIG_DERIVED, (
        "reload_config does not cover every derived global.\n"
        f"  in the source but not reloaded: {set(assigned) - set(hc._CONFIG_DERIVED)}\n"
        f"  reloaded but not in the source: {set(hc._CONFIG_DERIVED) - set(assigned)}"
    )


def test_reload_config_actually_changes_the_derived_values(tmp_path) -> None:
    """Catches a reload that updates CONFIG and leaves the globals behind."""
    import sys

    sys.path.insert(0, str(SKILL_ROOT / "payload"))
    import extant_collect as hc

    before = hc.PRIMARY_DOC
    (tmp_path / ".git").mkdir()
    (tmp_path / ".extant.toml").write_text(
        'primary_doc = "SOMETHING_ELSE.md"\ntrunk = "develop"\n', encoding="utf-8")
    try:
        hc.reload_config(tmp_path)
        assert hc.PRIMARY_DOC == "SOMETHING_ELSE.md"
        assert hc.TRUNK == "develop"
        assert hc._MERGE_CLAIM.search("merged to `develop` at `abc1234`"), (
            "a compiled pattern that interpolates trunk was not rebuilt"
        )
    finally:
        hc.reload_config(PACKAGE_ROOT)
    assert hc.PRIMARY_DOC == before


def test_no_syntax_newer_than_the_python_floor_we_claim() -> None:
    """The floor is 3.9, and nothing mechanical kept it there.

    A support claim decays the first time somebody writes a `match` statement,
    and the decay is invisible on a modern interpreter: the file compiles, the
    suite passes, and the only symptom appears on a machine nobody testing has.
    RHEL 9 and Debian 11 ship 3.9; Ubuntu 22.04 LTS ships 3.10.

    Annotations are exempt because every module imports `annotations` from
    `__future__`, which makes them strings at runtime - so `str | None` in a
    signature is fine all the way back to 3.7. That is asserted separately
    below, because the exemption depends on it.
    """
    import ast

    # (attribute or name, the version that introduced it)
    TOO_NEW = {
        "pairwise": "3.10 (itertools.pairwise)",
        "StrEnum": "3.11 (enum.StrEnum)",
        "ExceptionGroup": "3.11",
        "UTC": "3.11 (datetime.UTC)",
        "tomllib": "3.11 - import it inside a try/except, as extant_config does",
    }

    # Looked up rather than named. `ast.Match` does not exist before 3.10 and
    # `ast.TryStar` does not exist before 3.11, so referring to either directly
    # raises AttributeError on precisely the versions this check exists to
    # protect. That shipped: the guard asserting 3.9 support was itself
    # 3.11-only code, and it failed in CI on 3.9 and 3.10 while passing
    # locally. `isinstance(x, ())` is False everywhere, so an absent class
    # simply never matches.
    too_new_nodes = [
        (getattr(ast, "Match", ()), "match statement needs 3.10"),
        (getattr(ast, "TryStar", ()), "except* needs 3.11"),
    ]

    offenders: list[str] = []
    files = 0
    nodes = 0
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        parts = path.relative_to(PACKAGE_ROOT).parts
        if {"__pycache__", ".venv", ".pytest_cache"} & set(parts):
            continue
        if path.name == "test_packaging.py":        # names the constructs above
            continue
        files += 1
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            # On an old interpreter a too-new construct does not parse at all,
            # and the parser is then a better oracle than any node list: it
            # knows every construct, including ones added after this was
            # written. Report it rather than erroring out.
            offenders.append(f"{path.relative_to(PACKAGE_ROOT)}:{exc.lineno}: "
                             f"does not parse on Python "
                             f"{sys.version_info.major}.{sys.version_info.minor}: {exc.msg}")
            continue

        # Imports of a too-new module are fine when guarded by a try/except,
        # which is how a fallback is spelled. Collect the guarded ones first.
        guarded = {
            alias.name
            for node in ast.walk(tree) if isinstance(node, ast.Try)
            for child in ast.walk(node) if isinstance(child, (ast.Import, ast.ImportFrom))
            for alias in child.names
        }

        rel = path.relative_to(PACKAGE_ROOT)
        for node in ast.walk(tree):
            nodes += 1
            gated = next((why for cls, why in too_new_nodes
                          if cls and isinstance(node, cls)), None)
            if gated:
                offenders.append(f"{rel}:{node.lineno}: {gated}")
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    why = TOO_NEW.get(alias.name)
                    if why and alias.name not in guarded:
                        offenders.append(f"{rel}:{node.lineno}: unguarded import of "
                                         f"{alias.name}, needs {why}")
            elif isinstance(node, ast.Attribute) and node.attr in TOO_NEW:
                offenders.append(f"{rel}:{node.lineno}: .{node.attr} needs "
                                 f"{TOO_NEW[node.attr]}")

    # Denominators. An rglob that matched nothing, or an exclusion that grew,
    # would otherwise pass in exactly the same silence as a clean scan.
    assert files > 10, f"only {files} Python files scanned"
    assert nodes > 1000, f"only {nodes} AST nodes visited"
    assert not offenders, (
        "syntax newer than the Python floor this project claims to support:\n  "
        + "\n  ".join(offenders)
    )


def test_every_module_defers_annotations() -> None:
    """The exemption the check above depends on, asserted rather than assumed.

    `from __future__ import annotations` makes every annotation a string at
    runtime, which is what lets `str | None` appear in a signature on 3.9. Drop
    it from one module and that module raises TypeError on import there, while
    remaining perfectly fine on the interpreter it was written on.
    """
    import ast

    missing: list[str] = []
    files = 0
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        parts = path.relative_to(PACKAGE_ROOT).parts
        if {"__pycache__", ".venv", ".pytest_cache"} & set(parts):
            continue
        files += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if not any(isinstance(n, ast.ImportFrom) and n.module == "__future__"
                   and any(a.name == "annotations" for a in n.names)
                   for n in tree.body):
            missing.append(str(path.relative_to(PACKAGE_ROOT)))

    assert files > 10, f"only {files} Python files scanned"
    assert not missing, (
        "modules without `from __future__ import annotations`, so a `X | Y` "
        "annotation in them fails on Python 3.9:\n  " + "\n  ".join(missing)
    )
