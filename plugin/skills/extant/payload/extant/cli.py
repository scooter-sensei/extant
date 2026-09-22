"""Argument parsing, and the modes that neither survey nor gate.

`main` is the whole command line: it reads the flags, picks the mode, and is
the only place an exit code is decided. `cli` is the console-script entry point
the pre-commit hook invokes bare from the repository being committed to, which
is why it differs from `main` in exactly two ways - a missing mode means
`--verify`, and `--repo` defaults to the current directory rather than to
wherever the package was installed.

The modes now live in three places, and the line between them is what the mode
DOES with what it finds:

* extant/sweep.py surveys and never gates: `--sweep`; `--deleted-since` is
  the same shape and lives in extant/deleted_since.py.
* extant/gate.py checks one document and decides an exit code: `--validate`,
  `--verify`, `--check-text`.
* extant/introduced_since.py is a survey that gates: `--introduced-since`
  sweeps the documents a range changed and fails on the findings that sit
  on lines the range wrote.
* here: `--collect`, `--archive`, `--search`, `--selftest`, which are each a
  handful of lines over machinery that already exists.

That third clause used to cover `--validate` too, and it was true when written.
It stopped being true quietly: `run_validate` reached 295 lines against the
303-line ceiling, which is a ceiling doing its job rather than a surprise. The
argument for keeping the small modes together is unchanged - splitting them
further would put one caller per file.

This module reaches the ambient run state through extant/session.py rather than
holding any of its own. That is the boundary Task 10 exists to draw: the state
has one home, and the modes are callers of it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from extant import session
from extant.collect import collect
from extant.config import StatusConfig
from extant.entries import archive, split_entries
from extant.gate import run_check_text, run_validate
from extant.git import repository_root
from extant.registry import RULE_ERRORS
from extant.report import BASELINE_NAME, FORMATS
from extant.deleted_since import run_deleted_since
from extant.introduced_since import run_introduced_since
from extant.sweep import run_sweep

__all__ = ["build_parser", "cli", "main", "search_entries",
           "UndecodableDocument"]


class UndecodableDocument(Exception):
    """A document `--search` had to read is not valid UTF-8.

    Carries the PATH, which `UnicodeDecodeError` does not. `--archive` catches
    the bare error at the CLI boundary and names `primary_doc`, which is safe
    there because it reads exactly one document. `--search` reads TWO - the
    live document and the archive - so the same shortcut would name a guess,
    and a diagnostic naming the wrong file is a false claim, which is the one
    thing this tool exists not to make.

    Public because `search_entries` is: a caller that can be made to raise has
    to be able to name what it raises.
    """

    def __init__(self, relative: str, exc: UnicodeDecodeError) -> None:
        super().__init__(relative)
        self.relative = relative
        self.reason = exc.reason
        self.start = exc.start


def search_entries(repo: Path, query: str) -> list[tuple[str, str, str]]:
    """Entries mentioning `query`, newest first, as (document, header, body).

    Returns whole ENTRIES rather than matching lines, which is the entire point
    and the only reason this beats `grep`. A decision is recorded in a dated
    entry with the reasoning around it; a naked line out of the middle tells you
    a phrase exists and not what was decided or when.

    Searches the live document and the archive together, because the whole
    problem is that entries move from one to the other. Somebody looking for a
    decision does not know, and should not need to know, whether it has been
    retired yet.
    """
    needle = query.lower()
    results: list[tuple[str, str, str]] = []
    config = session.config()
    for relative in (config.primary_doc, config.archive_doc):
        path = repo / relative
        if not path.is_file():
            continue
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                text = fh.read()
        except UnicodeDecodeError as exc:
            # REPORTED, NEVER SKIPPED. A document that could not be read is not
            # a document with no matching entries, and `--search` printing "0
            # match(es)" for one is exactly the conflation this tool exists to
            # remove - the same argument `_scan_one` in sweep.py makes for
            # counting an unreadable file rather than passing over it.
            #
            # Raised rather than handled here because the exit code is the CLI
            # layer's to choose, and `search_entries` is also called directly.
            raise UndecodableDocument(relative, exc) from exc
        _, segments, _ = split_entries(text, config)
        for kind, entry in segments:
            if kind != "phase" or needle not in entry.lower():
                continue
            header = entry.splitlines()[0].strip() if entry.strip() else "(untitled)"
            results.append((relative, header, entry))
    return results


def _mode_flags() -> set[str]:
    """Every flag in the parser's mutually exclusive mode group.

    Read from the parser so that adding a mode cannot leave this behind.
    """
    parser = build_parser()
    flags: set[str] = set()
    for group in parser._mutually_exclusive_groups:      # noqa: SLF001
        for action in group._group_actions:              # noqa: SLF001
            flags.update(action.option_strings)
    return flags


def cli() -> int:
    """Console-script entry point, used by the pre-commit hook.

    Differs from `main` in two ways, both because a hook invokes the command
    bare from the repository being committed to:

    - no mode given means `--verify`
    - `--repo` defaults to the CURRENT DIRECTORY rather than to wherever the
      package was installed
    """
    argv = list(sys.argv[1:])
    # Asked of the parser, never listed here. The duplicate list went stale the
    # moment `--sweep` was added: it was not recognised as a mode, so this
    # inserted `--verify` in front of it and argparse rejected the pair. That
    # shipped in 0.13.0 and broke the exact command the README leads with,
    # because the release gate exercised `--validate` instead of the documented
    # one. A list that has to be kept in step with another list will fall out
    # of step; this cannot.
    modes = _mode_flags()
    if not any(arg.split("=", 1)[0] in modes for arg in argv):
        argv.insert(0, "--verify")
    if not any(arg.split("=", 1)[0] == "--repo" for arg in argv):
        repo = Path.cwd()
        argv += ["--repo", str(repo)]
    else:
        index = next(i for i, a in enumerate(argv) if a.split("=", 1)[0] == "--repo")
        raw = argv[index]
        if "=" in raw:
            repo = Path(raw.split("=", 1)[1])
        elif index + 1 < len(argv):
            repo = Path(argv[index + 1])
        else:
            # `extant --repo` with nothing after it. Reaching for argv[i+1]
            # raised IndexError before argparse could say what was wrong.
            build_parser().error("--repo requires a PATH")
    return main(argv)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="extant_collect", description="Collect and validate status facts."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--collect", action="store_true", help="emit bundle.json")
    mode.add_argument("--archive", action="store_true", help="split old entries out")
    mode.add_argument("--validate", metavar="FILE", help="validate a status document")
    mode.add_argument("--verify", action="store_true", help="validate the committed doc")
    mode.add_argument("--deleted-since", metavar="REF",
                      help="report claims removed while still false, since "
                           "REF; never gates. Use the merge base in CI, so "
                           "splitting a removal across commits does not hide it")
    mode.add_argument("--sweep", action="store_true",
                      help="survey every tracked markdown file; needs no config")
    mode.add_argument("--introduced-since", metavar="REF",
                      help="gate on the findings that sit on lines this "
                           "checkout wrote since its merge base with REF; "
                           "needs no config and pins no document. Pass the "
                           "base branch in CI")
    mode.add_argument("--selftest", action="store_true",
                      help="corrupt one real claim per rule and confirm each fires")
    mode.add_argument("--search", metavar="TEXT",
                      help="find past entries mentioning TEXT, live and archived")
    mode.add_argument("--check-text", action="store_true",
                      help="check a document read from stdin; needs no file on "
                           "disk. Pair with --as-path so the rules that key on "
                           "a location can answer")
    parser.add_argument("--as-path", metavar="RELATIVE",
                        help="with --check-text, the repo-relative path this "
                             "document would have. Sets what relative links "
                             "resolve against, which filename the keyed rules "
                             "read, and the markup language")
    parser.add_argument("--full", action="store_true",
                        help="with --search, print whole entries rather than excerpts")
    parser.add_argument("--suggest-fixes", action="store_true",
                        help="with --validate/--verify, print a patch repointing "
                             "renamed files. Writes nothing; pipe to `git apply`.")
    parser.add_argument("--out", metavar="PATH", help="bundle output path")
    parser.add_argument("--suite-json", metavar="PATH", help="reuse a completed suite run")
    parser.add_argument("--sha-map", metavar="PATH", help="filter-repo commit-map")
    parser.add_argument("--repo", metavar="PATH",
                        default=str(session.REPO_ROOT))
    parser.add_argument("--format", choices=FORMATS, default="text",
                        help="findings output: text, github annotations, or SARIF")
    # A ratchet, for adopting on a repository that already has years of prose.
    # The first run on an old project reports everything at once, CI goes red,
    # and the tool comes back out. Recording what is already there means new
    # claims are checked from day one without a week of archaeology first.
    parser.add_argument("--baseline", metavar="PATH", nargs="?",
                        const=BASELINE_NAME,
                        help=f"suppress findings recorded in PATH "
                             f"(default {BASELINE_NAME}). New ones still fail.")
    parser.add_argument("--write-baseline", metavar="PATH", nargs="?",
                        const=BASELINE_NAME,
                        help=f"record every current finding to PATH (default "
                             f"{BASELINE_NAME}) and exit 0. Never implicit.")
    parser.add_argument("--baseline-check", action="store_true",
                        help="report baseline entries that no longer occur, so "
                             "a granted amnesty cannot outlive its finding")
    return parser


def _survivable_output() -> None:
    """Never die encoding a finding after doing all the work.

    A finding quotes the document, and a document may be in any language.
    Written to a console the process did not choose - cp1252 on a default
    Windows shell, cp437 on an older one - an unencodable character raises
    UnicodeEncodeError and the run dies AFTER the analysis, at the moment of
    reporting it. Found by sweeping jgm/pandoc, whose docs quote Japanese.

    Replacement rather than a forced encoding, because the console genuinely
    cannot render those characters and pretending otherwise produces mojibake;
    a `?` is the honest rendering and the rest of the line still arrives.
    SARIF is the exception: it is a file format rather than console text, so it
    gets UTF-8 and stays faithful.

    This was believed to be handled. `test_a_finding_quoting_non_ascii_does_not
    _crash_the_printer` passes `PYTHONIOENCODING=cp437:replace` in the
    environment, so it was proving that the ENVIRONMENT can cope, not that the
    tool can. Every mode crashed without it.
    """
    sarif = "--format=sarif" in sys.argv or "sarif" in sys.argv
    for stream in (sys.stdout, sys.stderr):
        # A replaced stream (pytest's capture, a StringIO) may not offer
        # reconfigure at all - `TextIO` promises nothing of the kind, only
        # `TextIOWrapper` has it - and nothing there needs hardening. Asked
        # for by name rather than tried, so the absence is a branch rather
        # than an exception read as one.
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            if sarif and stream is sys.stdout:
                reconfigure(encoding="utf-8", errors="replace")
            else:
                reconfigure(errors="replace")
        except (ValueError, OSError):
            # A stream that has the method but is closed or detached. Failing
            # here would be worse than the problem.
            pass


def run_search(repo: Path, parser: argparse.ArgumentParser,
               args: argparse.Namespace) -> int:
    """`--search`: print past entries mentioning TEXT, live and archived.

    `search_entries()` above does the lookup; this is the excerpt/`--full`
    formatting and the "N match(es) in M entries" denominator around it -
    the CLI-shaped half that used to live inline in `main()`.
    """
    if not args.search.strip():
        parser.error("--search needs something to look for")
    try:
        results = search_entries(repo, args.search)
    except UndecodableDocument as bad:
        # THE SAME SENTENCE `--validate` AND `--archive` PRINT for the same
        # input, so one encoding gets one answer whichever mode meets it.
        # Before this, `--validate` refused a UTF-16 document by name while
        # `--search` exited with a traceback out of `codecs`, and the fuzzer
        # reported the second as a CRASH the moment the encoding axis and this
        # mode were drawn together. Same finding as `--archive`, one mode over.
        print(f"{repo / bad.relative}: not valid UTF-8 ({bad.reason} at byte "
              f"{bad.start}). The status document must be a text file.",
              file=sys.stderr)
        return 1
    for relative, header, entry in results:
        print(f"{relative}: {header}")
        body = entry.splitlines()[1:]
        if args.full:
            for line in body:
                print(f"    {line}")
        else:
            # A few lines of context, because the header alone rarely says
            # what was decided. --full prints the entry when it does not.
            excerpt = [ln for ln in body if ln.strip()][:4]
            for line in excerpt:
                print(f"    {line.strip()[:96]}")
        print()
    # split_entries needs the BUILT Config (section_header, phase_prefix),
    # the same object search_entries() above read - not `status`, the raw
    # StatusConfig `main()` reads before dispatching here. Passing `status`
    # here is the exact mistake that used to crash this mode.
    config = session.config()
    # The denominator again: "no matches" and "searched nothing" print the
    # same blank otherwise, and the second happens whenever a document is
    # missing or its entry header does not match the configured prefix.
    searched = sum(1 for relative in (config.primary_doc, config.archive_doc)
                   if (repo / relative).is_file())
    total = 0
    for relative in (config.primary_doc, config.archive_doc):
        path = repo / relative
        if path.is_file():
            with open(path, encoding="utf-8", newline="") as fh:
                total += sum(
                    1 for kind, _ in split_entries(fh.read(), config)[1]
                    if kind == "phase")
    print(f"{len(results)} match(es) in {total} entries "
          f"across {searched} document(s)")
    if total == 0:
        print("  NOTE: no entries were found to search. Either these "
              "documents have none, or entry_prefix does not match their "
              "headers.")
    return 0


def run_selftest(repo: Path, status: StatusConfig) -> int:
    """`--selftest`: corrupt one real claim per rule and confirm each fires."""
    primary = session.config().primary_doc
    target = repo / primary
    if not target.is_file():
        # stderr directly, NOT `diag`: that helper is local to run_validate
        # now, a different function, so calling it here raises NameError.
        # Before this split it raised UnboundLocalError instead, because
        # both lived in one `main()` - and `--selftest` on any repository
        # without the primary document ended in a traceback instead of this
        # message. The reason for not using `print` to stdout stands: in
        # SARIF mode stdout carries nothing but JSON.
        print(f"no such document: {target}", file=sys.stderr)
        print(f"  primary_doc is '{status.primary_doc}', from "
              f"{status.source}", file=sys.stderr)
        return 1
    try:
        with open(target, encoding="utf-8", newline="") as fh:
            text = fh.read()
    except UnicodeDecodeError as exc:
        # A document that is not valid UTF-8 is a situation to report, not
        # to crash on. Reading it with errors="replace" instead would let
        # every rule run against silently corrupted text and report findings
        # about bytes that are not there.
        print(f"{target}: not valid UTF-8 ({exc.reason} at byte "
              f"{exc.start}). The status document must be a text file.",
              file=sys.stderr)
        return 1
    session.set_document(link_base=target.parent)
    lines, fired, unprobeable, errored = session.selftest(repo, text)
    print(f"selftest: probing {len(session.RULES)} rules against "
          f"{primary}\n")
    for line in lines:
        print(line)
    silent = len(session.RULES) - fired - unprobeable - errored
    print(f"\n  {fired} fired, {unprobeable} had nothing to corrupt, "
          f"{errored} could not be run, {silent} stayed silent")
    if silent:
        print("  A rule that stays silent after a real match is corrupted is "
              "not working. Check its pattern against this document.")
    if errored:
        print("  A rule that could not be run has not been shown to work "
              "either - see the ERRORED line(s) above for what it raised.")
    if unprobeable:
        print("  'No probe' is not a failure by itself, but a rule that "
              "cannot be exercised is also not known to work.")
    session.set_document(link_base=None)
    return 1 if (silent or errored) else 0


def run_collect(repo: Path, args: argparse.Namespace,
                status: StatusConfig) -> int:
    """`--collect`: assemble the handoff bundle and write it to --out."""
    # `run_suite` raises RuntimeError for the two states it cannot proceed
    # from - no project interpreter, and a suite_command that will not run -
    # and its docstring says the point of raising was to replace "an uncaught
    # FileNotFoundError crashing /extant step 1" with something actionable.
    # The message became actionable and the crash did not go away: nothing
    # caught it, so it arrived as a traceback with a good paragraph inside it.
    #
    # Found by fuzzing `--collect`, which had never been run by that harness.
    # Every generated repository lacks a `.venv`, so this was not an edge case
    # there - it was the mode's ONLY behaviour.
    #
    # Exit 2, matching every other "this run cannot proceed" in this file: a
    # bundle was not written, and 0 or 1 would both claim one was.
    try:
        bundle = collect(repo, args.suite_json,
                         session.context(repo).config, status)
    except RuntimeError as exc:
        print(f"extant --collect cannot measure the suite: {exc}",
              file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else repo / "status_bundle.json"
    with open(out, "w", encoding="utf-8", newline="") as fh:
        json.dump(bundle, fh, indent=2)
    if bundle["nothing_to_hand_off"]:
        print("nothing to hand off: no commits since the last status")
    print(out)
    return 0


def run_archive(repo: Path, status: StatusConfig) -> int:
    """`--archive`: split old entries out of the primary document."""
    # A DOCUMENT THAT IS NOT THERE WAS THE SECOND WAY INTO THE SAME CRASH.
    #
    # `run_validate` refuses this input three functions away, and says what
    # to do about it: `entries.archive` opens `primary_doc` as the first
    # thing it does, so a config naming a document that does not exist -
    # a typo, a file not created yet, a `primary_doc` left pointing at a
    # renamed one - met the only irreversible write in the product with an
    # unhandled FileNotFoundError.
    #
    # Reported the way the sibling reports it, naming the setting and where
    # it was read from, because "no such file" alone does not tell anyone
    # WHICH of the two - the config or the document - is the thing to fix.
    #
    # Found by fuzzing `--archive` against a deliberately broken config,
    # which is the same mode and the same generator that found the encoding
    # crash below, one shape later.
    target = repo / session.context(repo).config.primary_doc
    if not target.is_file():
        print(f"no such document: {target}", file=sys.stderr)
        print(f"  primary_doc is '{status.primary_doc}', from "
              f"{status.source}", file=sys.stderr)
        print("  set primary_doc in .extant.toml, or create the document",
              file=sys.stderr)
        return 1
    # THE ONE MODE THAT REWRITES THE DOCUMENT WAS THE ONE NOT CHECKING IT.
    #
    # `entries.archive` opens the primary document as UTF-8 and every other
    # mode guards that read - `--validate`, `--verify`, `--selftest` and
    # `--check-text` all report "not valid UTF-8" and refuse. This one let the
    # exception out, so a UTF-16 or otherwise undecodable status document met
    # the only irreversible file write in the product with an unhandled
    # traceback instead of a diagnostic.
    #
    # Nothing had been written at the point it raised - the read is the first
    # thing `archive` does - so the file was intact either way. What was wrong
    # is that a crash is not an answer, and this mode's crash looks identical
    # to one that failed halfway through a rewrite.
    #
    # Found by fuzzing `--archive`, one of the four modes that harness had
    # never run, against an encoding it had never built.
    try:
        counts = archive(repo, None, session.context(repo).config)
    except UnicodeDecodeError as exc:
        target = repo / session.context(repo).config.primary_doc
        print(f"{target}: not valid UTF-8 ({exc.reason} at byte "
              f"{exc.start}). The status document must be a text file.",
              file=sys.stderr)
        return 1
    print(f"retained={counts['retained']} archived={counts['archived']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    _survivable_output()
    # One RUN, one list. Cleared here rather than by `validate()`, which is
    # called several times per run and would otherwise forget the primary
    # document's failures the moment it read the archive. MUTATED, never
    # rebound: `_registry.RULE_ERRORS` and this name are one list, and an
    # assignment here would leave the rules appending to the other one.
    RULE_ERRORS.clear()
    parser = build_parser()
    args = parser.parse_args(argv)
    repo = Path(args.repo)
    # Which repository git will answer about, said once when it is not the
    # one `--repo` names. From a subdirectory git walks UP and answers about
    # the checkout above, while every document and path here resolves against
    # `--repo`: neither half is wrong alone, and together they are the "true
    # where you are standing" confusion this tool exists to catch. A note, not
    # a refusal - `--repo <subdir>` has worked since the flag existed. From a
    # directory with no repository above it - a `git archive` extract, say -
    # every rule that asks git errors, and this names the cause in front of
    # the thirteen rule errors that would otherwise have to imply it.
    root = repository_root(repo)
    if root is None:
        print(f"NOTE: no repository found at or above --repo {repo}, so every "
              f"rule that asks git will report an error.", file=sys.stderr)
    elif root != Path(os.path.abspath(repo)):
        print(f"NOTE: --repo {repo} is not the root of a repository. git "
              f"answers about {root}, while documents and paths resolve "
              f"against --repo. Point --repo at {root} unless that is "
              f"intended.", file=sys.stderr)
    # SETTINGS COME FROM THE REPOSITORY BEING CHECKED. Configuration is read
    # once at import, relative to this file - right when the tool sits at
    # tools/ inside the repository it checks, and wrong for a run pointed
    # anywhere else, where git followed --repo while the settings did not.
    # This used to print a NOTE saying the target's `.extant.toml` was NOT
    # read and leave the two disagreeing; the console script `cli()` had
    # already learned to re-read from --repo, and this entry point - the one
    # the installed shim and every hook run - had not. Re-read here, once,
    # for both: an ordinary install finds the same file the import found, a
    # run pointed elsewhere finds that repository's own settings or the
    # defaults, and the NOTE has no condition left to report. The README's
    # "what it cannot do" entry for this went with it. A `--config PATH` and
    # a `[tool.extant]` table were considered and refused: 0 of the 152
    # visible corpus repositories carry a `.extant.toml`, 0 a `[tool.extant]`,
    # so neither has a population, and a second place for one setting is how
    # a setting nobody reads gets written.
    session.reload_config(repo)
    # Read once, here, AFTER the reload, so every reader below wants the SAME
    # settings object rather than one re-read per line. Named `status`, not
    # `config` - matching extant/collect.py's convention of `config: Config`
    # vs `status: StatusConfig` - because this IS a StatusConfig
    # (session.CONFIG, the raw parsed settings), not the derived Config that
    # split_entries/archive/rules need. A `config` local here once shadowed
    # that distinction closely enough that the search-mode denominator below
    # passed this straight into split_entries(), which crashed on the first
    # field only Config carries. See entries.py's split_entries for what the
    # two types are for.
    status = session.CONFIG
    # Refused rather than ignored, on the reasoning `--sweep` uses below: a
    # flag that names a file cannot mean anything for a document that has no
    # file, and silently dropping it would let a caller believe a location was
    # supplied when none was.
    if args.as_path and not args.check_text:
        print("--as-path applies to --check-text, which reads a document with "
              "no path of its own. --validate already knows where its file is.",
              file=sys.stderr)
        return 2
    if args.search is not None:
        return run_search(repo, parser, args)
    if args.check_text:
        # The two baseline flags that WRITE or JUDGE the recorded set are
        # refused here, and neither refusal is tidiness. Both were measured
        # doing real damage before this block existed.
        #
        # `--write-baseline` records `located` and replaces the file. Over one
        # stdin document that is one document's findings keyed on `<stdin>` or
        # on an asserted path, and it OVERWRITES a baseline recorded from the
        # whole project - measured: a two-entry baseline became a one-entry
        # one, the run exited 0, and the next `--verify --baseline` reported
        # "2 new finding(s), 0 suppressed" with nothing anywhere saying an
        # amnesty had been thrown away.
        #
        # `--baseline-check` asks which recorded entries this RUN did not
        # encounter. `--verify` reads the primary document, the archive and
        # every extra_doc, so its answer means something. A run over one piped
        # document encounters almost nothing, so it calls live entries STALE
        # and prints "These no longer happen ... Remove them" - advice which,
        # followed, deletes suppressions that are still needed. Measured: both
        # entries of a correct baseline reported stale by a document that
        # mentioned neither.
        #
        # Reading one is fine and stays allowed: `--baseline` suppresses what
        # the project already forgave, which is what a caller checking a draft
        # against project policy wants.
        conflicting = [name for name, value in (
            ("--write-baseline", args.write_baseline),
            ("--baseline-check", args.baseline_check)) if value]
        if conflicting:
            print(f"--check-text does not support {', '.join(conflicting)}. It "
                  "reads ONE document, so it cannot say what the project's "
                  "recorded findings look like - writing a baseline from it "
                  "would discard the rest, and checking one would report live "
                  "entries as stale. Use --verify for both. `--baseline` "
                  "(reading) works here.", file=sys.stderr)
            return 2
        # SARIF locates every result by `artifactLocation.uri`, and a document
        # with no path has none. Emitting `<stdin>` put `<` and `>` in a field
        # the format requires to be a URI - characters RFC 3986 forbids - so
        # the document is invalid and a code-scanning upload can reject the
        # whole file rather than report the findings in it. Refused rather
        # than papered over with a plausible-looking name: a URI reading
        # `stdin` would be a valid path to a file that does not exist, which
        # is the wrong answer wearing a better disguise.
        if args.format == "sarif" and not args.as_path:
            print("--check-text --format=sarif needs --as-path: SARIF locates "
                  "every result by a URI, and a document with no path has "
                  "none. Use --format=text or --format=github, or say where "
                  "this document would live.", file=sys.stderr)
            return 2
        return run_check_text(repo, args, status)
    if args.selftest:
        return run_selftest(repo, status)
    if args.collect:
        return run_collect(repo, args, status)
    if args.archive:
        return run_archive(repo, status)
    if args.deleted_since:
        return run_deleted_since(repo, args.deleted_since, args.format)
    if args.introduced_since:
        # Refused for the reason `--sweep` refuses the first four below, and
        # `--sha-map` besides: a baseline is a ratchet against OLD findings
        # and this mode has none by construction, while the other two WRITE,
        # and a gate on what a change wrote must not rewrite it.
        conflicting = [name for name, value in (
            ("--baseline", args.baseline), ("--write-baseline", args.write_baseline),
            ("--baseline-check", args.baseline_check),
            ("--suggest-fixes", args.suggest_fixes),
            ("--sha-map", args.sha_map)) if value]
        if conflicting:
            print(f"--introduced-since does not support "
                  f"{', '.join(conflicting)}. It gates on the lines a change "
                  "wrote, which is already the ratchet a baseline provides, "
                  "and it writes nothing; run --verify for the modes that "
                  "suppress or rewrite.", file=sys.stderr)
            return 2
        return run_introduced_since(repo, args.introduced_since, args.format)
    if args.sweep:
        # Refused rather than ignored. A baseline suppresses findings, and a
        # survey whose whole job is to SHOW them would be silently gutted by
        # one - the user would read "3 findings" and never learn that forty
        # more were hidden. Saying so costs a line; the alternative is the
        # quiet-wrong-answer failure this project is built around.
        conflicting = [name for name, value in (
            ("--baseline", args.baseline), ("--write-baseline", args.write_baseline),
            ("--baseline-check", args.baseline_check),
            ("--suggest-fixes", args.suggest_fixes)) if value]
        if conflicting:
            print(f"--sweep does not support {', '.join(conflicting)}. It is a "
                  "survey of every tracked document, not a gate on one; run "
                  "--verify for the modes that suppress or rewrite.",
                  file=sys.stderr)
            return 2
        return run_sweep(repo, args.format)
    if args.verify:
        args.validate = str(repo / session.config().primary_doc)
    if args.validate == "":
        # M-a: argparse still counts --validate as "provided" (satisfying
        # the required mutually-exclusive group) even when its value is the
        # empty string, so this is a genuinely reachable state, not dead
        # code. It must not fall through to an implicit `None` return -
        # SystemExit(None) is exit code 0, a silent false success for a
        # nonsensical invocation.
        parser.error("--validate requires a non-empty FILE path")
    if args.validate:
        # THE SAME REFUSAL as `--check-text --format=sarif` above, at the other
        # door. SARIF locates a result by a URI that GitHub resolves against
        # the repository root, and a document OUTSIDE the repository has no
        # such path: `finding.rel` falls back to the absolute one, and the
        # encoder then percent-escapes the drive colon, so
        # `D:/elsewhere/doc.md` is published as `D%3A/elsewhere/doc.md`.
        #
        # That is a VALID relative reference naming a file the repository does
        # not contain - which is strictly worse than the invalid URI it
        # replaced, because an invalid one is rejected loudly and this one
        # resolves quietly to nothing. It is the same "wrong answer wearing a
        # better disguise" the `<stdin>` refusal above was written for, and it
        # was reached by fixing that field's encoding without asking who ELSE
        # puts a path into it.
        #
        # Only SARIF. `text` prints the absolute path, which is honest, and
        # `github` matches its own annotation against the diff and simply does
        # not attach - neither invents a location.
        if args.format == "sarif":
            target = Path(args.validate)
            try:
                target.resolve().relative_to(repo.resolve())
            except ValueError:
                print("--validate --format=sarif needs a document INSIDE the "
                      "repository: SARIF locates every result by a path "
                      "relative to the repository root, and this one has "
                      "none. Use --format=text or --format=github, or point "
                      "--repo at the repository that contains it.",
                      file=sys.stderr)
                return 2
        return run_validate(repo, args, status)
    # M-a: unreachable. The mutually-exclusive group is required, and every
    # member (collect, archive, verify, validate-non-empty) returns above;
    # validate-empty-string calls parser.error above, which exits. No state
    # argparse can produce falls through to here.
    raise AssertionError(f"unreachable: argparse guarantees one mode; got {args}")
