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


def test_no_pathlib_newline_argument() -> None:
    """`newline=` on pathlib's text helpers postdates the floor this claims.

    `read_text` gained it in 3.13; `write_text` gained it in **3.10**. The floor
    here is 3.9, so both are out of reach.

    The read side had this guard already, and its own docstring said "write_text
    took the same argument back in 3.10, which is why only the read side broke".
    That sentence was true when written and stopped being true the moment the
    floor moved to 3.9 - so the guard covered one of two methods, and nine
    `write_text(newline=...)` calls sailed past it. Two were in the shipped
    installer, so the TOOL raised TypeError on 3.9, not merely the suite. CI on
    3.9 caught it; nothing local could.

    The read side shipped once already: `detect.py` used it, so `install.py`
    crashed outright on 3.11 and 3.12. The suite ran on both in CI and stayed
    green on that file, because nothing called into it.

    Parsed rather than grepped, so a call split across lines cannot slip past.
    """
    import ast

    needs = {"read_text": "3.13", "write_text": "3.10"}
    offenders: list[str] = []
    files = 0
    calls = 0
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        parts = path.relative_to(PACKAGE_ROOT).parts
        if {"__pycache__", ".venv", ".pytest_cache"} & set(parts):
            continue
        files += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr in needs:
                calls += 1
                if any(kw.arg == "newline" for kw in node.keywords):
                    offenders.append(
                        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{node.lineno}: "
                        f"{node.func.attr}(newline=...) needs {needs[node.func.attr]}"
                    )

    assert files > 3, f"only {files} Python files parsed"
    assert calls > 0, "no read_text/write_text calls found at all; this proves nothing"
    assert not offenders, (
        "pathlib's newline argument postdates the supported floor. Use "
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
    from extant.config import load_config

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
    import subprocess

    # Tracked files, enumerated from git rather than a filesystem walk: this
    # test is named for SHIPPED files, and a file that only exists on disk -
    # untracked scratch, a downloaded fixture, an editor swap file - is not
    # itself shipped just by sitting in the working tree. `rglob` could not
    # tell the difference, so an untracked file with an em dash in it once
    # failed a test about what ships. `-z` NUL-separates the output instead
    # of newline-separating it: without it, plain `git ls-files` OCTAL-QUOTES
    # any path containing a space or a non-ASCII character, which would
    # silently corrupt the filename rather than merely mis-split it, if one
    # is ever added. NUL-separation also sidesteps a second, unrelated
    # failure mode that has already bitten this project: `text=True`
    # translates "\n" to "\r\n" on Windows, corrupting every path but the
    # last (see the "BYTES and NUL separators" comment in extant_collect.py).
    # Read as raw bytes for the same reason.
    proc = subprocess.run(
        ["git", "ls-files", "-z"], cwd=PACKAGE_ROOT,
        capture_output=True, check=False,
    )
    # Fail loudly rather than silently falling back to zero tracked files: a
    # check that degrades to "found nothing" on error is indistinguishable
    # from a clean sweep, which is the exact failure mode this project exists
    # to prevent.
    assert proc.returncode == 0, (
        f"git ls-files -z failed (exit {proc.returncode}), cannot enumerate "
        f"shipped files:\n{proc.stderr.decode('utf-8', errors='replace')}"
    )
    tracked = {p for p in proc.stdout.decode("utf-8").split("\0") if p}

    # Tracked is not the whole story: `install.py`'s `copy_payload` ships this
    # skill's payload by copying from DISK, not from git. Its PAYLOAD_TREES
    # loop runs `src_root.rglob("*.py")` over `payload/extant` and copies
    # whatever it finds with `shutil.copyfile`, so an untracked file sitting
    # under `plugin/skills/extant/payload/` would be invisible to
    # `git ls-files` above and would still ship into an adopter's `tools/`.
    # It is scanned too, unioned with `tracked` below rather than replacing
    # it - almost every payload file is both tracked and on disk, and using
    # sets de-duplicates that overlap.
    payload_root = SKILL_ROOT / "payload"
    on_disk: set[str] = set()
    for candidate in payload_root.rglob("*"):
        if not candidate.is_file():
            continue
        rel_parts = candidate.relative_to(PACKAGE_ROOT).parts
        if {"__pycache__", ".pytest_cache"} & set(rel_parts):
            continue
        if any(part.endswith(".egg-info") for part in rel_parts):
            continue
        on_disk.add(candidate.relative_to(PACKAGE_ROOT).as_posix())

    skipped: list[str] = []
    offenders: list[str] = []
    scanned = 0

    for rel in sorted(tracked | on_disk):
        path = PACKAGE_ROOT / rel
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

    # Denominators. A git enumeration that returned nothing, or an exclusion
    # that grew to cover the repository, would otherwise pass in exactly the
    # same silence.
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


def test_configuration_is_applied_in_exactly_one_place() -> None:
    """The structural property that makes the staleness class impossible.

    Configuration is read at import, relative to the file. Installed as a
    package - which the pre-commit framework does - that location is
    site-packages, so the tool must re-read config for the repository it was
    pointed at, and anything derived from CONFIG and not refreshed then
    silently describes some other project.

    That used to be nineteen scattered assignments plus a SECOND list inside
    reload_config naming which to refresh. The same information written twice
    diverged exactly as invited: `_SECTION_HEADER` is computed rather than
    copied, the second list held only copies, and it went stale on every
    reload. Now `_apply_config` is the only writer and both paths call it.

    This guards the SHAPE. `test_reloading_matches_a_fresh_import_of_the_same_project`
    guards the outcome; keeping the shape is what stops anyone needing to.
    """
    import ast
    import sys

    sys.path.insert(0, str(SKILL_ROOT / "payload"))
    import extant_collect as hc

    sources = [SKILL_ROOT / "payload" / "extant_collect.py"]
    sources += sorted((SKILL_ROOT / "payload" / "extant").rglob("*.py"))
    assert len(sources) > 1, (
        "only the shim was found; after the split this test would scan a "
        "20-line file and pass while covering none of the real modules")
    print(f"checked {len(sources)} module(s) for stray CONFIG readers")

    # NOTE: this loop deliberately parses into `module_tree`, not `tree`. `tree`
    # is reused below (unchanged) to mean specifically the SHIM's AST, for the
    # "_apply_config is called at import" and "reload_config calls it" checks -
    # a loop variable named `tree` here would silently rebind it to whichever
    # package module sorts last and break those checks against the wrong file.
    strays = []
    for source_path in sources:
        module_tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in module_tree.body:
            # Assign (`X = ...`) and AnnAssign (`X: T = ...`) both bind a
            # module global, and an annotated one is exactly as stale-prone
            # as a bare one - `ast.Assign` alone let `_ACTIVE: Config =
            # Config.build(CONFIG)` slip through with zero strays reported.
            # The shim itself uses the annotated form for two globals
            # (`_ACTIVE: Config | None = None`, and `_CONSISTENCY_TIMEOUT:
            # float | None` with no value at all), so this walk must
            # recognise the shape rather than assume nobody writes it.
            # AnnAssign.value is None for an annotation with no value,
            # which ast.walk() cannot take - skipped rather than crashed on.
            if isinstance(node, ast.Assign):
                if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    continue
                target, value = node.targets[0], node.value
            elif isinstance(node, ast.AnnAssign):
                if not isinstance(node.target, ast.Name) or node.value is None:
                    continue
                target, value = node.target, node.value
            else:
                continue
            name = target.id
            if name == "_CONFIG_DERIVED":
                continue
            if any(isinstance(s, ast.Name) and s.id == "CONFIG"
                   for s in ast.walk(value)):
                strays.append(f"{source_path.name}:{name} (line {node.lineno})")
    tree = ast.parse(sources[0].read_text(encoding="utf-8"))  # the shim; used below

    assert hc._CONFIG_DERIVED, "the derived table is empty; this proves nothing"
    assert all(callable(v) for v in hc._CONFIG_DERIVED.values()), (
        "every entry must be a builder, so a COMPUTED value is expressed the "
        "same way as a copied one and cannot become the forgotten special case"
    )

    # No module-level assignment, in the shim OR anywhere in the package, may
    # read CONFIG except the table itself. `strays` was built above by walking
    # every source in `sources`, not just the shim.
    assert not strays, (
        "these globals read CONFIG outside _CONFIG_DERIVED, so reload_config "
        "cannot refresh them and they will keep their import-time value: "
        + ", ".join(strays)
    )

    # Both paths must go through the one writer.
    called_at_import = any(
        isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name) and n.value.func.id == "_apply_config"
        for n in tree.body
    )
    assert called_at_import, "_apply_config is never called at import"

    reload_fn = next(n for n in tree.body
                     if isinstance(n, ast.FunctionDef) and n.name == "reload_config")
    assert any(isinstance(s, ast.Name) and s.id == "_apply_config"
               for s in ast.walk(reload_fn)), (
        "reload_config no longer calls _apply_config, so it is free to drift "
        "from what import does - which is the bug this shape exists to prevent"
    )


def test_reload_config_rebuilds_the_computed_globals_at_runtime(tmp_path) -> None:
    """The behaviour, not the source text.

    The check above reads the module and asks whether `reload_config` contains
    an assignment. That is a proxy, and a proxy is what let this bug exist:
    `_SECTION_HEADER` looked refreshed because its NAME appeared in a `global`
    statement. This calls reload_config against a repository with a different
    `entry_prefix` and asserts the compiled pattern actually changed, which no
    source-text rearrangement can fake.

    The prefix here differs in HEADING LEVEL, which is the part that reaches
    the pattern: `_section_header` takes `prefix.split()[0]`, so `## Phase `
    and `## Release ` both compile to `^\\#\\# ` and a test that varied only
    the word would assert something the code never does. A project writing
    `### Phase ` is the case where a stale value actually bites - the splitter
    would then look for the wrong heading level and find no entries at all.
    """
    import sys

    sys.path.insert(0, str(SKILL_ROOT / "payload"))
    import extant_collect as hc

    (tmp_path / ".git").mkdir()
    (tmp_path / ".extant.toml").write_text(
        '[extant]\nentry_prefix = "### Phase "\n', encoding="utf-8")

    before = hc._SECTION_HEADER.pattern
    saved = {name: getattr(hc, name) for name in hc._CONFIG_DERIVED}
    # `_ACTIVE` holds the same values in a second shape. Restoring the globals
    # and leaving it behind would put this module in a state neither the test
    # nor the fixture ever asked for.
    saved_config, saved_header, saved_active = (
        hc.CONFIG, hc._SECTION_HEADER, hc._ACTIVE)
    try:
        hc.reload_config(tmp_path)

        assert hc.CONFIG.entry_prefix == "### Phase ", "config did not reload"
        assert hc._SECTION_HEADER.pattern != before, (
            f"_SECTION_HEADER still {hc._SECTION_HEADER.pattern!r} after a "
            f"reload that set entry_prefix to '### Phase '"
        )
        # It must still WORK, not merely differ: a pattern rebuilt from the
        # wrong part of the prefix would also change, and match nothing.
        assert hc._SECTION_HEADER.search("### Phase 3 - checkout\n")
        assert not hc._SECTION_HEADER.search("## Phase 3 - checkout\n")
    finally:
        hc.CONFIG, hc._SECTION_HEADER = saved_config, saved_header
        hc._ACTIVE = saved_active
        for name, value in saved.items():
            setattr(hc, name, value)


def test_reload_config_actually_changes_the_derived_values(tmp_path) -> None:
    """Catches a reload that updates CONFIG and leaves the globals behind."""
    import sys

    sys.path.insert(0, str(SKILL_ROOT / "payload"))
    import extant_collect as hc

    # Snapshot and restore the exact prior state. The cleanup used to call
    # reload_config(PACKAGE_ROOT), which reloads THIS repository's own config
    # rather than whatever was in place before - so it depended on
    # `.extant.toml` existing here, and it silently defeated the autouse
    # `neutral_config` fixture for every test that ran afterwards.
    saved_config = hc.CONFIG
    saved = {name: getattr(hc, name) for name in hc._CONFIG_DERIVED}
    # Same reason as above: the built Config is state this test changes too.
    saved_active = hc._ACTIVE
    before = hc.PRIMARY_DOC

    (tmp_path / ".git").mkdir()
    (tmp_path / ".extant.toml").write_text(
        'primary_doc = "SOMETHING_ELSE.md"\ntrunk = "develop"\n', encoding="utf-8")
    try:
        hc.reload_config(tmp_path)
        assert hc.PRIMARY_DOC == "SOMETHING_ELSE.md"
        assert hc.TRUNK == "develop"
        assert hc._MERGE_CLAIM.search("merged to `develop` at `abc1234`"), (
            "a compiled pattern was not rebuilt"
        )
    finally:
        hc.CONFIG = saved_config
        hc._ACTIVE = saved_active
        for name, value in saved.items():
            setattr(hc, name, value)
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
        "tomllib": "3.11 - import it inside a try/except, as extant/config.py does",
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


# Values that legitimately differ between two checkouts of the same code, with
# the reason each is exempt. Kept SHORT and justified: a skip-list is how a
# check quietly stops examining anything, so the assertion below also states
# how many globals it did compare.
_RELOAD_ORACLE_EXEMPT = {
    "REPO_ROOT",        # derived from __file__, so it differs by construction
    "CONFIG",           # carries `source`, the path the config was read from
    "_LINK_BASE",       # per-call state, not configuration
    "_DIRCACHE",        # caches, emptied and restored around validate()
    "_ANCESTORS",
    "_REFS",
    "_LFS",
    "_RENAMES",
}


def _canonical(value: object) -> object:
    """A comparable form for a module global.

    Compiled patterns compare by identity, and sets have no stable order, so
    both would produce spurious differences between two processes.
    """
    import re as _re

    if isinstance(value, _re.Pattern):
        return f"re:{value.pattern}"
    if isinstance(value, (set, frozenset)):
        return sorted(str(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return repr(value)


def _module_state(payload_dir, repo, reload_to=None):
    """Every module global, from a subprocess that imports the payload.

    `reload_to` runs `reload_config` against that repository after importing,
    which is the path under test. Without it the import itself reads the
    configuration, which is the oracle.
    """
    import json
    import subprocess
    import sys
    import textwrap

    target = repr(str(reload_to)) if reload_to else "None"
    script = textwrap.dedent(f"""
        import dataclasses, json, re, sys
        sys.path.insert(0, {str(payload_dir)!r})
        import extant_collect as ec
        reload_to = {target}
        if reload_to:
            import pathlib
            ec.reload_config(pathlib.Path(reload_to))

        def canon(value):
            # The same intent as a flat set/pattern check, applied at EVERY
            # depth. A set nested inside a dataclass never reaches a top-level
            # branch, so it falls through to repr() - and a frozenset reprs in
            # hash order, which differs between any two processes because
            # string hashing is randomised per process.
            #
            # Measured 2026-08-11, when `_ACTIVE` (a Config) became a module
            # global: its two-element `todo_excluded_files` made this test fail
            # in five runs out of eight with nothing stale at all. Every other
            # field was identical in both processes.
            if isinstance(value, re.Pattern):
                return "re:" + value.pattern
            if isinstance(value, (set, frozenset)):
                return sorted(str(canon(v)) for v in value)
            if isinstance(value, (list, tuple)):
                return [str(canon(v)) for v in value]
            if dataclasses.is_dataclass(value) and not isinstance(value, type):
                return [f.name + "=" + str(canon(getattr(value, f.name)))
                        for f in dataclasses.fields(value)]
            return repr(value)

        out = {{}}
        for name, value in vars(ec).items():
            if name.startswith("__") or callable(value):
                continue
            if isinstance(value, type(sys)) or isinstance(value, type):
                continue
            out[name] = canon(value)
        # Object reprs carry a memory address, which differs between any two
        # processes and would make every container of functions look stale.
        # The NAMES still compare, which is the part that can go wrong.
        for key in list(out):
            item = out[key]
            if isinstance(item, str):
                out[key] = re.sub(" at 0x[0-9a-fA-F]+", "", item)
            else:
                out[key] = [re.sub(" at 0x[0-9a-fA-F]+", "", i) for i in item]
        print("<<<JSON>>>" + json.dumps(out))
    """)
    proc = subprocess.run([sys.executable, "-c", script], cwd=str(repo),
                          capture_output=True, text=True, encoding="utf-8")
    assert "<<<JSON>>>" in proc.stdout, (
        f"the probe process produced no state:\n{proc.stdout}\n{proc.stderr}"
    )
    return json.loads(proc.stdout.split("<<<JSON>>>", 1)[1])


def test_reloading_matches_a_fresh_import_of_the_same_project(tmp_path) -> None:
    """THE guard for the whole staleness class, stated as the real invariant.

    After `reload_config(repo)`, this module must hold exactly what it would
    hold had it been imported inside `repo` in the first place. That is the
    promise the pre-commit install path depends on, and everything else here
    is a proxy for it.

    Three proxies were tried before this and two of them were wrong. A table
    of plain `X = CONFIG.y` copies could not see a value COMPUTED from CONFIG,
    which is how `_SECTION_HEADER` went stale. A source scan asking whether
    `reload_config` mentions the name passed happily, because
    `global CONFIG, _SECTION_HEADER` mentions it. A source scan asking whether
    it CONTAINS an assignment still cannot tell a correct rebuild from one
    reading the wrong field.

    This compares behaviour against an oracle, so it needs no naming
    convention, no AST, and no list of what counts as derived. A global added
    tomorrow is covered without anyone remembering this test exists.
    """
    import shutil

    payload = SKILL_ROOT / "payload"

    # A project whose configuration differs from this repository's in the
    # fields that reach a module global.
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    (project / ".extant.toml").write_text(
        "[extant]\n"
        'primary_doc = "STATUS.md"\n'
        'archive_doc = "docs/old.md"\n'
        "retain_entries = 9\n"
        'trunk = "mainline"\n'
        'entry_prefix = "### Release "\n'
        'pointer_prefix = "## Old pointer"\n'
        'todo_exclude_dirs = ["vendor/"]\n',
        encoding="utf-8")
    shutil.copytree(payload, project / "tools")

    # The oracle: imported INSIDE that project, so import-time config is its own.
    fresh = _module_state(project / "tools", project)
    # The path under test: imported elsewhere, then pointed at that project.
    reloaded = _module_state(payload, SKILL_ROOT, reload_to=project)

    compared = sorted(set(fresh) & set(reloaded) - _RELOAD_ORACLE_EXEMPT)
    assert len(compared) >= 19, (
        f"only {len(compared)} globals compared; the probe is not reading the "
        "module properly and a clean result here would mean nothing"
    )
    assert fresh["TRUNK"] == "'mainline'", (
        f"the oracle did not pick up the project's config: TRUNK={fresh['TRUNK']}"
    )

    stale = {name: (reloaded[name], fresh[name])
             for name in compared if reloaded[name] != fresh[name]}
    assert not stale, (
        f"compared {len(compared)} globals; these differ after reload_config, "
        "so they keep a value from wherever the module was imported:\n  "
        + "\n  ".join(f"{n}: reloaded={r!r} but a fresh import gives {f!r}"
                       for n, (r, f) in sorted(stale.items()))
    )


def test_the_console_entry_point_accepts_every_mode(tmp_path) -> None:
    """`extant --sweep` must not have `--verify` inserted in front of it.

    The entry point inserts a default mode when none is given, and it decided
    what counted as a mode from a list written beside the parser rather than
    from the parser. `--sweep` was added and the list was not, so the pip and
    uvx installs answered the README's headline command with
    "argument --sweep: not allowed with argument --verify".

    That shipped in 0.13.0. The release gate installs the wheel and runs it,
    but it ran `--validate`, so the one command the front page leads with was
    the one nothing exercised.

    Asserted against the parser's own mode group, so a mode added later is
    covered without anyone remembering to come back here.
    """
    import extant_collect as hc

    parser = hc.build_parser()
    declared = {opt
                for group in parser._mutually_exclusive_groups
                for action in group._group_actions
                for opt in action.option_strings}

    assert "--sweep" in declared, "the mode group no longer holds --sweep"
    assert declared == hc._mode_flags(), (
        f"the entry point disagrees with the parser: "
        f"{declared ^ hc._mode_flags()}"
    )
