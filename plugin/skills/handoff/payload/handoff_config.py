"""Project-specific configuration for the handoff system.

Everything the validator knows about a particular project lives here: document
names, entry-header shapes, and the patterns each rule matches. The defaults
reproduce Cerene's behaviour exactly, so a repo with no `.handoff.toml` sees no
change.

    from tools.handoff_config import load_config
    cfg = load_config(repo)
    cfg.handoff_doc          # "NEXT_SESSION.md"
    cfg.live_phrases         # compiled pattern

WHY THIS FILE EXISTS, AND THE WARNING THAT COMES WITH IT
--------------------------------------------------------
Three of the rules below were derived by MEASURING Cerene's real documents, not
by reasoning about what handoff prose "should" look like. Copying those patterns
to another project without re-measuring is the main way this system fails
silently:

- `merge_claim` matches "merged to `main` at `<sha>`" because that is how these
  documents actually phrase it. A project that writes "shipped in v2.1 (abc1234)"
  matches nothing, and the validator then exits 0 forever while looking healthy.
- `path_pointer` keys on operative markers ("Plan:", "Design:", "see", "read").
  An earlier shape-keyed version would have produced 23 findings on this repo,
  every one false - historical layout descriptions, deferred work, and files
  explicitly described as deleted.
- `live_phrases` is a small closed set. Widening it to anything that "sounds
  like" a status claim reintroduces false positives, and a validator that cries
  wolf stops being read, which costs more than having no validator.

So: when porting, run `handoff_collect.py --init` against the target repo. It
samples the real document and reports what it finds, so the config is derived
rather than guessed. See references/porting.md in the skill.
"""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_NAME = ".handoff.toml"

DEFAULTS: dict[str, object] = {
    "handoff_doc": "NEXT_SESSION.md",
    "archive_doc": "docs/handoff-archive.md",
    "retain_entries": 3,
    "trunk": "main",
    "plans_dir": "docs/superpowers/plans",
    "archive_header": "# Cerene - Handoff Archive\n\nOlder phase entries, newest first.\n\n",
    "entry_prefix": "## Phase ",
    "pointer_prefix": "## Archive pointer",
    # Regex sources, kept as strings so they can live in TOML.
    "base_header": r"^## \d+[a-z]?\. ",
    "phase_task": r"\((\d+(?:\.\d+)*[a-z]?)\s+Task\b",
    "phase_bare": r"\bPhase (\d+\.\d+[a-z]?)",
    "branch_token": r"`((?:claude|feature|feat)/[^`]+)`",
    "live_phrases": r"NOT yet merged|awaiting (?:user )?merge|pending merge|still unmerged",
    # `{trunk}` is substituted by str.replace, NOT str.format - so the repetition
    # braces are written literally. Doubling them (as .format would require)
    # produced a pattern that compiled fine and matched nothing, which is the
    # precise failure this module's docstring warns about: a rule that looks
    # healthy while validating nothing. Caught only by counting matches against
    # the real documents.
    "merge_claim": r"(?:merged|shipped)\s+(?:to|into)\s+`?{trunk}`?\s+at\s+`([0-9a-f]{7,40})`",
    "path_pointer": (
        r"(?:\*\*(?:Plan|Design|Spec|Authority|Source)s?:?\*\*|\bsee\b|\bread\b)"
        r"[^`\n]{0,40}`([\w:.\\/-]+\.(?:py|qml|md|txt|json|toml|cfg|ini))`"
    ),
    # Release-tag claims: "released in v2.1", "shipped as v2.1.0". Measured as
    # ABSENT from the corpus this was built on, which is why the denominator
    # will honestly report 0 for projects that never phrase things this way. It
    # is here for CHANGELOG-keeping projects, where it is the common shape.
    "release_tag": r"(?:released|shipped|tagged)\s+(?:in|as|at)\s+`?(v?\d+\.\d+[\w.-]*)`?",
    # Additional documents that get the whole-file rules. They have no entry
    # structure, so the newest-entry rules are skipped for them exactly as they
    # are for the archive. This is how a project whose state lives in a tracker
    # still gets its CLAUDE.md, AGENTS.md and README checked.
    "extra_docs": [],
    # Named values that must AGREE across several files, as
    # {check_name: {path: regex-with-one-capture-group}}.
    #
    #     [handoff.consistency.version]
    #     "plugin/.claude-plugin/plugin.json" = '"version":\s*"([^"]+)"'
    #     "CHANGELOG.md" = '^## (\d+\.\d+\.\d+)'
    #
    # This does NOT breach the no-numbers guarantee, and the distinction is
    # worth stating precisely. The forbidden thing is judging whether a number
    # is CORRECT - "the suite was 2238" cannot be checked against anything, so a
    # rule that tried would cry wolf. Asking whether two files in the repository
    # CONTRADICT EACH OTHER is a different question with a definite answer, and
    # it needs nothing but the filesystem.
    #
    # Empty by default: the files and patterns are per-project, and a guessed
    # default would either match nothing or accuse an innocent repository.
    "consistency": {},
    "todo_markers": r"\b(TODO|FIXME|XXX)\b",
    "code_suffixes": [".py", ".qml"],
    "todo_exclude_files": ["tools/handoff_collect.py"],
    "todo_exclude_dirs": ["tests/tools/"],
    "venv_python": ".venv/Scripts/python.exe",
    # How to run the suite, and how to read its output. `{python}` is replaced
    # with the resolved interpreter; a command that does not mention it needs no
    # Python at all, which is how a JS, Rust or .NET project uses the measured
    # path. Examples that work with the patterns below:
    #     ["npm", "test"]                  jest / vitest
    #     ["cargo", "test"]                "test result: ok. 12 passed; 0 failed"
    #     ["dotnet", "test"]               "Passed!  - Failed: 0, Passed: 25"
    # Go prints no totals by default; supply --suite-json there, or use
    # gotestsum with a matching pattern.
    "suite_command": ["{python}", "-m", "pytest", "-q"],
    "suite_passed": r"(\d+) passed",
    "suite_failed": r"(\d+) failed",
    "suite_duration": r"\bin ([\d.]+)s",
}

# Keys that may be set empty to DISABLE the feature rather than fall back to a
# default. Without this, a project with no phase cadence silently inherits this
# project's phase regex and every commit is labelled "unknown" - a Cerene habit
# quietly applied to a repo that never had one.
DISABLEABLE = frozenset({"phase_task", "phase_bare", "plans_dir"})


@dataclass(frozen=True)
class HandoffConfig:
    """Resolved configuration. Regexes are compiled once at load."""

    handoff_doc: str
    archive_doc: str
    retain_entries: int
    trunk: str
    plans_dir: str
    archive_header: str
    entry_prefix: str
    pointer_prefix: str
    venv_python: str
    suite_command: tuple[str, ...]
    suite_passed: re.Pattern[str]
    suite_failed: re.Pattern[str]
    suite_duration: re.Pattern[str]
    code_suffixes: tuple[str, ...]
    todo_exclude_files: tuple[str, ...]
    todo_exclude_dirs: tuple[str, ...]
    extra_docs: tuple[str, ...]
    release_tag: re.Pattern[str]
    # {check_name: ((path, compiled_pattern), ...)}
    consistency: dict[str, tuple[tuple[str, re.Pattern[str]], ...]]
    base_header: re.Pattern[str]
    # None means the feature is switched off for this project, not that a
    # default applies. See DISABLEABLE.
    phase_task: re.Pattern[str] | None
    phase_bare: re.Pattern[str] | None
    branch_token: re.Pattern[str]
    live_phrases: re.Pattern[str]
    merge_claim: re.Pattern[str]
    path_pointer: re.Pattern[str]
    todo_markers: re.Pattern[str]
    source: str = "defaults"
    warnings: tuple[str, ...] = field(default_factory=tuple)


_UNKNOWN_HINT = (
    "unknown key {key!r} in {path} - check for a typo; unknown keys are ignored "
    "rather than defaulted silently"
)


_ESCAPE_HINT = """Most likely cause: a regex written in a TOML *basic* string
(double quotes). TOML processes escapes there, and `\\d` / `\\s` / `\\(` are not
valid ones, so the whole file fails to parse.

Put regex values in LITERAL strings (single quotes), which perform no escape
processing at all:

    branch_token = '`((?:feature|fix)/[^`]+)`'      correct
    branch_token = "`((?:feature|fix)/[^`]+)`"      fails if it contains a backslash

Use ''' triple quotes ''' if the pattern itself contains a single quote."""


_DUPLICATE_HINT = """Cause: the same key is set twice, and TOML refuses to let a
later line overwrite an earlier one.

Check for a key that appears both in the generated block near the top and again
lower down, which is what appending to this file rather than editing it in place
produces."""


_GENERIC_HINT = """The file is not valid TOML. The position above is where the
parser gave up, which is usually at or just after the offending line.

See references/config.md for the shape of every key."""


# EVERY hint here must fit the error it is attached to. This dispatch exists
# because the escape hint used to be unconditional: a duplicate key produced
# "Cannot overwrite a value" followed by a confident paragraph about regex
# quoting, which is not merely unhelpful but actively misleading. Someone would
# check their quotes, find them correct, and have no next move.
#
# A wrong cause is worse than no cause: it gets believed, acted on, and repeated.
_HINTS = (
    ("cannot overwrite", _DUPLICATE_HINT),
    ("escape", _ESCAPE_HINT),
    ("invalid literal", _ESCAPE_HINT),
    ("unterminated", _ESCAPE_HINT),
)


def _explain(path: Path, exc: Exception) -> str:
    """Attach the hint that actually matches this decoder error."""
    text = str(exc).lower()
    hint = next((h for needle, h in _HINTS if needle in text), _GENERIC_HINT)
    return f"{path}: {exc}\n\n{hint}"


def _read_toml(path: Path) -> tuple[dict[str, object], list[str]]:
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        # The bare decoder error names a line and column and nothing else, which
        # is useless to someone hand-writing a regex - and porting.md explicitly
        # asks them to. Re-raise with the cause that fits THIS error.
        raise ValueError(_explain(path, exc)) from exc
    section = data.get("handoff", data)
    if not isinstance(section, dict):
        raise ValueError(f"{path}: [handoff] must be a table")
    warnings = [
        _UNKNOWN_HINT.format(key=k, path=path.name)
        for k in section if k not in DEFAULTS
    ]
    return {k: v for k, v in section.items() if k in DEFAULTS}, warnings


def _find_config(start: Path) -> Path | None:
    """Look for `.handoff.toml` beside `start`, then upward to the repo root.

    Installed as `tools/handoff_collect.py`, the first directory checked IS the
    repository root and the search stops immediately. Run from anywhere else -
    this project's own CI invokes the script from inside `plugin/`, and a
    developer may run it from a checkout of the source - the file sits several
    levels up, and looking only beside the script found nothing while reporting
    a healthy run against default settings. That is the "config nothing reads"
    failure, and it was reached by trying to configure this very repository.

    The walk STOPS at the directory holding `.git`, inclusive. Without that
    bound a project nested inside another checkout would silently inherit the
    outer project's configuration, which is a worse failure than the one being
    fixed: wrong settings that look deliberate.
    """
    current = start.resolve()
    for directory in (current, *current.parents):
        candidate = directory / CONFIG_NAME
        if candidate.is_file():
            return candidate
        if (directory / ".git").exists():
            return None      # repository root reached, nothing found
    return None


def _compile_consistency(
    raw: object, path: Path
) -> dict[str, tuple[tuple[str, re.Pattern[str]], ...]]:
    """Validate and compile the consistency block.

    Shape errors are raised rather than skipped. A mistyped block that quietly
    checks nothing is the failure this whole project exists to prevent, and it
    would be especially cruel here: the reader would believe two files are being
    compared when nothing is reading either.

    A pattern with no capture group is rejected for the same reason - there
    would be no value to compare, so the check would pass vacuously forever.
    """
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: [handoff.consistency] must be a table of checks")

    compiled: dict[str, tuple[tuple[str, re.Pattern[str]], ...]] = {}
    for name, sources in raw.items():
        if not isinstance(sources, dict) or not sources:
            raise ValueError(
                f"{path}: consistency.{name} must be a table of "
                f'"path" = \'pattern\' pairs, and must not be empty'
            )
        if len(sources) < 2:
            raise ValueError(
                f"{path}: consistency.{name} lists one file. A consistency check "
                f"compares files against each other, so it needs at least two; "
                f"with one it can only ever agree with itself."
            )
        # Two spellings of one file agree with themselves forever. TOML keeps
        # "a.md" and "./a.md" as distinct keys, so the two-file minimum above
        # passes and the check is vacuous - the exact shape of failure this
        # project exists to make visible. Found by an adversarial probe, not by
        # reasoning about the config format.
        normalised: dict[str, str] = {}
        for file_path in sources:
            key = os.path.normpath(str(file_path)).replace("\\", "/")
            if key in normalised:
                raise ValueError(
                    f"{path}: consistency.{name} lists the same file twice, as "
                    f"{normalised[key]!r} and {str(file_path)!r}. A file always "
                    f"agrees with itself, so the check would pass without "
                    f"comparing anything."
                )
            normalised[key] = str(file_path)

        entries = []
        for file_path, pattern in sources.items():
            try:
                regex = re.compile(str(pattern), re.MULTILINE)
            except re.error as exc:
                raise ValueError(
                    f"{path}: consistency.{name} pattern for {file_path} does "
                    f"not compile: {exc}"
                ) from exc
            if regex.groups != 1:
                raise ValueError(
                    f"{path}: consistency.{name} pattern for {file_path} has "
                    f"{regex.groups} capture groups; it needs exactly one, "
                    f"around the value being compared"
                )
            entries.append((str(file_path), regex))
        compiled[str(name)] = tuple(entries)
    return compiled


def load_config(repo: Path) -> HandoffConfig:
    """Load `.handoff.toml` from `repo`, falling back to Cerene's defaults.

    A missing file is normal, not an error: the defaults are a working
    configuration. An unknown key is reported as a warning rather than being
    silently ignored, because a typo'd key that quietly does nothing is exactly
    the kind of failure this system exists to prevent.
    """
    values = dict(DEFAULTS)
    source = "defaults"
    warnings: list[str] = []

    path = _find_config(repo)
    if path is not None and path.is_file():
        overrides, warnings = _read_toml(path)
        values.update(overrides)
        source = str(path)

    trunk = str(values["trunk"])
    # merge_claim embeds the trunk name, so it is formatted rather than fixed.
    merge_src = str(values["merge_claim"]).replace("{trunk}", re.escape(trunk))

    def optional(key: str) -> re.Pattern[str] | None:
        """A disableable pattern: empty means off, not 'use the default'."""
        raw = values[key]
        return re.compile(str(raw)) if raw else None

    return HandoffConfig(
        handoff_doc=str(values["handoff_doc"]),
        archive_doc=str(values["archive_doc"]),
        retain_entries=int(values["retain_entries"]),
        trunk=trunk,
        plans_dir=str(values["plans_dir"]),
        archive_header=str(values["archive_header"]),
        entry_prefix=str(values["entry_prefix"]),
        pointer_prefix=str(values["pointer_prefix"]),
        venv_python=str(values["venv_python"]),
        suite_command=tuple(values["suite_command"]),          # type: ignore[arg-type]
        suite_passed=re.compile(str(values["suite_passed"])),
        suite_failed=re.compile(str(values["suite_failed"])),
        suite_duration=re.compile(str(values["suite_duration"])),
        code_suffixes=tuple(values["code_suffixes"]),          # type: ignore[arg-type]
        todo_exclude_files=tuple(values["todo_exclude_files"]),  # type: ignore[arg-type]
        todo_exclude_dirs=tuple(values["todo_exclude_dirs"]),    # type: ignore[arg-type]
        extra_docs=tuple(values["extra_docs"]),                  # type: ignore[arg-type]
        release_tag=re.compile(str(values["release_tag"]), re.IGNORECASE),
        consistency=_compile_consistency(values["consistency"], path),
        base_header=re.compile(str(values["base_header"]), re.MULTILINE),
        phase_task=optional("phase_task"),
        phase_bare=optional("phase_bare"),
        branch_token=re.compile(str(values["branch_token"])),
        live_phrases=re.compile(str(values["live_phrases"]), re.IGNORECASE),
        merge_claim=re.compile(merge_src, re.IGNORECASE),
        path_pointer=re.compile(str(values["path_pointer"]), re.IGNORECASE),
        todo_markers=re.compile(str(values["todo_markers"])),
        source=source,
        warnings=tuple(warnings),
    )
