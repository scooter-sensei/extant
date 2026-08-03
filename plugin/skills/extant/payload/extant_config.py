"""Project-specific configuration for the status workflow.

Everything the validator knows about a particular project lives here: document
names, entry-header shapes, and the patterns each rule matches. The defaults
reproduce Cerene's behaviour exactly, so a repo with no `.extant.toml` sees no
change.

    from tools.extant_config import load_config
    cfg = load_config(repo)
    cfg.primary_doc          # "NEXT_SESSION.md"
    cfg.live_phrases         # compiled pattern

WHY THIS FILE EXISTS, AND THE WARNING THAT COMES WITH IT
--------------------------------------------------------
Three of the rules below were derived by MEASURING Cerene's real documents, not
by reasoning about what status prose "should" look like. Copying those patterns
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

So: when porting, run `extant_collect.py --init` against the target repo. It
samples the real document and reports what it finds, so the config is derived
rather than guessed. See references/porting.md in the skill.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# `tomllib` arrived in 3.11, and enterprise distributions are years behind it:
# RHEL 9 and Debian 11 ship 3.9, Ubuntu 22.04 LTS ships 3.10. Nothing else here
# needs 3.11, so requiring it would exclude those for one import.
#
# `tomli` is not a substitute parser, it is the SAME parser: tomllib was adopted
# into the standard library from tomli, same author, same code. So an old
# interpreter reads a config file exactly the way a new one does, which matters
# more here than usual - a loader that parsed subtly differently by Python
# version would produce a config that looks right and is not, and that failure
# has already cost this project twice.
#
# Absent both, the value is None rather than an error at import. A repository
# with no config file never parses TOML at all: the defaults below are Python.
# Failing at import would deny the whole tool to someone who needs none of this,
# so the failure is raised at the point a config file is actually found.
try:
    import tomllib
except ModuleNotFoundError:                              # Python < 3.11
    try:
        import tomli as tomllib                          # type: ignore[no-redef]
    except ModuleNotFoundError:
        tomllib = None                                   # type: ignore[assignment]

_NO_PARSER = (
    "reading {path} needs a TOML parser.\n\n"
    "This interpreter is older than 3.11, where `tomllib` joined the standard\n"
    "library. Either run the tool on Python 3.11 or newer, or install the same\n"
    "parser under its original name:\n\n"
    "    python -m pip install tomli\n\n"
    "Deleting the config file also works: every setting has a default, and the\n"
    "tool runs on those without parsing anything."
)

CONFIG_NAME = ".extant.toml"

DEFAULTS: dict[str, object] = {
    "primary_doc": "NEXT_SESSION.md",
    "archive_doc": "docs/status-archive.md",
    "retain_entries": 3,
    # None leaves user-supplied consistency patterns unbounded, which is the
    # historical behaviour. A positive number bounds each search, at the cost
    # of a process spawn per pattern. See _search_with_limit for why there is
    # no cheaper mechanism that actually works.
    "consistency_timeout_seconds": None,
    # Does a release claim in these documents name a tag of THIS repository?
    #
    # OFF by default, because in general nothing in prose says so. A version in
    # a sentence can name a git tag, an npm or PyPI release, a sub-package, a
    # plugin, or a toolchain somebody else ships. Measured on 15 repositories
    # that write prose release claims, treating every one as a tag of the local
    # repository was wrong 19 times out of 26: eugenelim/agent-ready-repo tags
    # `credbroker-v0.4.0` and writes "shipped as 0.27.0"; 10CG/Aria tags to
    # v1.5.0 and cites its plugin's v1.17.3 through v1.24.1; rust-lang/rfcs has
    # no tags at all and discusses Rust's releases throughout.
    #
    # ON, the rule also reports a claimed release that was never tagged. That
    # is the right setting for a project validating ITS OWN status document -
    # extant's primary use, where the author knows the claims are about these
    # tags - and it is the author asserting it rather than the tool guessing.
    # The half that needs no assertion, "this tag is here and shipped on
    # nothing", is always checked; it was right 7 times out of 7.
    #
    # A range test was tried instead and does not separate the cases: two of
    # the false positives sit inside the repository's own tag range.
    "release_claims_name_our_tags": False,
    "trunk": "main",
    "plans_dir": "docs/superpowers/plans",
    "archive_header": "# Cerene - Status Archive\n\nOlder phase entries, newest first.\n\n",
    "entry_prefix": "## Phase ",
    "pointer_prefix": "## Archive pointer",
    # Regex sources, kept as strings so they can live in TOML.
    "base_header": r"^## \d+[a-z]?\. ",
    "phase_task": r"\((\d+(?:\.\d+)*[a-z]?)\s+Task\b",
    "phase_bare": r"\bPhase (\d+\.\d+[a-z]?)",
    "branch_token": r"`((?:claude|feature|feat)/[^`]+)`",
    "live_phrases": r"NOT yet merged|awaiting (?:user )?merge|pending merge|still unmerged",
    # TWO groups: the ref the claim names, then the commit. The rule checks the
    # commit against THAT ref, so nothing here is substituted and `{trunk}` no
    # longer appears - a claim like "merged to `develop` at `abc1234`" says
    # which branch it means, and comparing it against a single configured trunk
    # was measurably wrong in both directions on a two-trunk repository.
    #
    # The backticks are kept INSIDE group 1 on purpose. They are what separates
    # a deliberate ref (report a typo in it) from a word of prose (say
    # nothing); see `_claimed_ref`. Writing `` `([^`]+)` `` instead would drop
    # every project that spells the branch name bare.
    #
    # A one-group pattern remains supported and keeps the old meaning, checked
    # against trunk, so a customised `merge_claim` does not break.
    # The BACKTICKS AROUND THE COMMIT ARE OPTIONAL, and requiring them was the
    # rule's largest blind spot. Measured on a corpus of agent-written project
    # documents: basilisk-labs/agentplane writes 32 claims as
    # `PR #499 merged into main at 6ff1f4ac`, with the ref and the commit both
    # bare, and the rule examined ZERO of them across 7,489 files. Making the
    # backticks optional takes the corpus from 3 claims examined to 35 and adds
    # no findings at all - every one of the 32 is true, and all five distinct
    # commits resolve, so ancestry was really checked rather than skipped.
    #
    # Safe by construction as well as by measurement: `validate_merge_claims`
    # skips any claim whose SHA does not resolve, so a hex-looking token that
    # is not a commit produces silence rather than a finding.
    #
    # The trailing lookahead replaces the boundary the closing backtick used to
    # provide. Without it a 46-character hex run matches its first 40 and the
    # rule reports a commit nobody wrote.
    "merge_claim": (
        r"(?:merged|shipped)\s+(?:to|into)\s+"
        r"(`[^`\n]+`|[\w.\-/]+)\s+at\s+`?([0-9a-f]{7,40})`?(?![0-9a-f])"
    ),
    "path_pointer": (
        r"(?:\*\*(?:Plan|Design|Spec|Authority|Source)s?:?\*\*|\bsee\b|\bread\b)"
        r"[^`\n]{0,40}`([\w:.\\/-]+\.(?:py|qml|md|txt|json|toml|cfg|ini))`"
    ),
    # Release-tag claims: "released in v2.1", "shipped as v2.1.0". Measured as
    # ABSENT from the corpus this was built on, which is why the denominator
    # will honestly report 0 for projects that never phrase things this way. It
    # is here for CHANGELOG-keeping projects, where it is the common shape.
    # The tail must not END on a dot or hyphen. `[\w.-]*` is greedy and
    # swallows a sentence-ending period, so "Released in v2.1." looked for a
    # tag literally named `v2.1.` and reported a false positive on ordinary
    # English. Every fixture happened to continue the sentence, so nothing
    # caught it until the tool read its own status document.
    "release_tag": r"(?:released|shipped|tagged)\s+(?:in|as|at)\s+`?(v?\d+\.\d+(?:[\w.-]*[\w])?)`?",
    # Additional documents that get the whole-file rules. They have no entry
    # structure, so the newest-entry rules are skipped for them exactly as they
    # are for the archive. This is how a project whose state lives in a tracker
    # still gets its CLAUDE.md, AGENTS.md and README checked.
    "extra_docs": [],
    # Named values that must AGREE across several files, as
    # {check_name: {path: regex-with-one-capture-group}}.
    #
    #     [extant.consistency.version]
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
    # Both spellings: `tools/` is where the collector lands once INSTALLED
    # into a project, and the payload path is where it lives in this
    # repository. Only the first was listed, so in this repo the skip-list
    # excluded nothing and the collector's own marker patterns counted as
    # TODOs of its own.
    "todo_exclude_files": [
        "tools/extant_collect.py",
        "plugin/skills/extant/payload/extant_collect.py",
    ],
    "todo_exclude_dirs": ["tests/"],
    # Windows lays a virtualenv out as Scripts/python.exe and POSIX as
    # bin/python, so a single literal is wrong on one of them. Chosen from
    # the running platform rather than hard-coded: a fresh install on Linux
    # or macOS otherwise inherits an interpreter path that does not exist,
    # and the suite command silently fails to run.
    "venv_python": (".venv/Scripts/python.exe" if os.name == "nt"
                    else ".venv/bin/python"),
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
class StatusConfig:
    """Resolved configuration. Regexes are compiled once at load."""

    primary_doc: str
    archive_doc: str
    retain_entries: int
    consistency_timeout_seconds: float | None
    release_claims_name_our_tags: bool
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
    # Raised HERE rather than at import, because this is the first moment the
    # parser is genuinely needed. Someone on 3.9 with no config file gets a
    # working tool; someone on 3.9 WITH one gets a sentence naming the remedy,
    # rather than a ModuleNotFoundError naming a module they never imported.
    if tomllib is None:
        raise ValueError(_NO_PARSER.format(path=path))
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        # The bare decoder error names a line and column and nothing else, which
        # is useless to someone hand-writing a regex - and porting.md explicitly
        # asks them to. Re-raise with the cause that fits THIS error.
        raise ValueError(_explain(path, exc)) from exc
    # MERGED, not chosen between. Writing a sub-table such as
    # [extant.consistency.version] creates a `status` key, and picking that
    # over the top level silently discarded every setting written above it -
    # primary_doc, extra_docs, everything. The file looked configured and was
    # not, which is the exact failure this project exists to surface, sitting
    # in its own loader. Found by trying to configure a README-only project.
    nested = data.get("extant", {})
    if not isinstance(nested, dict):
        raise ValueError(f"{path}: [extant] must be a table")
    top_level = {k: v for k, v in data.items() if k != "extant"}

    both = sorted(set(top_level) & set(nested) & set(DEFAULTS))
    if both:
        raise ValueError(
            f"{path}: {', '.join(both)} set both at the top level and under "
            f"[extant]. Pick one place; leaving two is how the wrong value "
            f"gets read while the right one sits there looking correct."
        )
    section = {**top_level, **nested}
    warnings = [
        _UNKNOWN_HINT.format(key=k, path=path.name)
        for k in section if k not in DEFAULTS
    ]
    return {k: v for k, v in section.items() if k in DEFAULTS}, warnings


def _find_config(start: Path) -> Path | None:
    """Look for `.extant.toml` beside `start`, then upward to the repo root.

    Installed as `tools/extant_collect.py`, the first directory checked IS the
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
        raise ValueError(f"{path}: [extant.consistency] must be a table of checks")

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


def load_config(repo: Path) -> StatusConfig:
    """Load `.extant.toml` from `repo`, falling back to Cerene's defaults.

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
    # The default pattern no longer embeds the trunk name, but a project that
    # customised `merge_claim` before this change may still write `{trunk}`, and
    # substituting it costs nothing when the token is absent. Dropping the
    # substitution would turn those configs into a pattern that compiles and
    # matches nothing, which is this module's named failure mode.
    merge_src = str(values["merge_claim"]).replace("{trunk}", re.escape(trunk))

    def _timeout(raw: object) -> float | None:
        """A positive number of seconds, or None for unbounded."""
        if raw is None or raw == "":
            return None
        if not isinstance(raw, (int, float)) or isinstance(raw, bool) or raw <= 0:
            raise ValueError(
                "consistency_timeout_seconds must be a positive number of "
                "seconds, or absent to leave patterns unbounded"
            )
        return float(raw)

    def optional(key: str) -> re.Pattern[str] | None:
        """A disableable pattern: empty means off, not 'use the default'."""
        raw = values[key]
        return re.compile(str(raw)) if raw else None

    return StatusConfig(
        primary_doc=str(values["primary_doc"]),
        archive_doc=str(values["archive_doc"]),
        retain_entries=int(values["retain_entries"]),
        consistency_timeout_seconds=_timeout(values["consistency_timeout_seconds"]),
        release_claims_name_our_tags=bool(
            values["release_claims_name_our_tags"]),
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
