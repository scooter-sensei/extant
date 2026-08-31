"""Argument parsing, and the modes that neither survey nor gate.

`main` is the whole command line: it reads the flags, picks the mode, and is
the only place an exit code is decided. `cli` is the console-script entry point
the pre-commit hook invokes bare from the repository being committed to, which
is why it differs from `main` in exactly two ways - a missing mode means
`--verify`, and `--repo` defaults to the current directory rather than to
wherever the package was installed.

The modes now live in three places, and the line between them is what the mode
DOES with what it finds:

* extant/sweep.py surveys and never gates: `--sweep`, `--deleted-since`.
* extant/gate.py checks one document and decides an exit code: `--validate`,
  `--verify`, `--check-text`.
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
import sys
from pathlib import Path

from extant import session
from extant.collect import collect
from extant.config import StatusConfig
from extant.entries import archive, split_entries
from extant.gate import run_check_text, run_validate
from extant.registry import RULE_ERRORS
from extant.report import BASELINE_NAME, FORMATS
from extant.sweep import run_deleted_since, run_sweep

__all__ = ["build_parser", "cli", "main", "search_entries"]


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
    config = session.context(repo).config
    for relative in (session.PRIMARY_DOC, session.ARCHIVE_DOC):
        path = repo / relative
        if not path.is_file():
            continue
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
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
    session.reload_config(repo)
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
        try:
            if sarif and stream is sys.stdout:
                stream.reconfigure(encoding="utf-8", errors="replace")
            else:
                stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            # A replaced stream (pytest's capture, a StringIO) may not support
            # reconfigure. Nothing to harden there, and failing here would be
            # worse than the problem.
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
    results = search_entries(repo, args.search)
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
    # The denominator again: "no matches" and "searched nothing" print the
    # same blank otherwise, and the second happens whenever a document is
    # missing or its entry header does not match the configured prefix.
    searched = sum(1 for relative in (session.PRIMARY_DOC,
                                      session.ARCHIVE_DOC)
                   if (repo / relative).is_file())
    # split_entries needs the DERIVED Config (section_header, phase_prefix),
    # the same object search_entries() above already built for itself -
    # not `status`, the raw StatusConfig `main()` reads before dispatching
    # here. Passing `status` here is the exact mistake that used to crash
    # this mode.
    built_config = session.context(repo).config
    total = 0
    for relative in (session.PRIMARY_DOC, session.ARCHIVE_DOC):
        path = repo / relative
        if path.is_file():
            with open(path, encoding="utf-8", newline="") as fh:
                total += sum(
                    1 for kind, _ in split_entries(fh.read(),
                                                   built_config)[1]
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
    target = repo / session.PRIMARY_DOC
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
          f"{session.PRIMARY_DOC}\n")
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
    bundle = collect(repo, args.suite_json,
                     session.context(repo).config, status)
    out = Path(args.out) if args.out else repo / "status_bundle.json"
    with open(out, "w", encoding="utf-8", newline="") as fh:
        json.dump(bundle, fh, indent=2)
    if bundle["nothing_to_hand_off"]:
        print("nothing to hand off: no commits since the last status")
    print(out)
    return 0


def run_archive(repo: Path) -> int:
    """`--archive`: split old entries out of the primary document."""
    counts = archive(repo, None, session.context(repo).config)
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
    # Configuration is read once at import, relative to THIS FILE, which is
    # correct when the tool sits at tools/ inside the repository it checks. Run
    # from anywhere else with --repo, git operations follow --repo while the
    # config does not, so .extant.toml in the target is silently ignored. Say
    # so on stderr rather than let the two disagree quietly.
    # Narrowed to the case where a real config file is actually being ignored.
    # Warning whenever the paths merely differ would fire on every run against a
    # repository that has no config at all, where nothing is lost and the
    # defaults are what was wanted. A validator that cries wolf stops being read
    # applies to its own diagnostics too.
    ignored_config = repo / ".extant.toml"
    # Read once, here: `reload_config` may not have run, and every reader
    # below wants the SAME settings object rather than one re-read per line.
    #
    # Named `status`, not `config` - matching extant/collect.py's convention
    # of `config: Config` vs `status: StatusConfig` - because this IS a
    # StatusConfig (session.CONFIG, the raw parsed settings), not the derived
    # Config that split_entries/archive/rules need. A `config` local here once
    # shadowed that distinction closely enough that the search-mode
    # denominator below passed this straight into split_entries(), which
    # crashed on the first field only Config carries. See entries.py's
    # split_entries for what the two types are for.
    status = session.CONFIG
    # Compared as resolved paths, not as strings. The upward search means the
    # config found from the script's own location is very often the same file
    # this names, and a string comparison called them different over a
    # separator - producing a warning that said the file it had just read was
    # not read.
    same_file = (ignored_config.is_file() and status.source != "defaults"
                 and ignored_config.resolve() == Path(status.source).resolve())
    if (repo.resolve() != session.REPO_ROOT.resolve()
            and ignored_config.is_file() and not same_file):
        print(f"NOTE: settings came from {status.source}, so {ignored_config} was "
              f"NOT read. Configuration loads relative to this script; install it "
              f"into that repository as tools/ for its own settings to apply.",
              file=sys.stderr)
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
        return run_archive(repo)
    if args.deleted_since:
        return run_deleted_since(repo, args.deleted_since, args.format)
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
        args.validate = str(repo / session.PRIMARY_DOC)
    if args.validate == "":
        # M-a: argparse still counts --validate as "provided" (satisfying
        # the required mutually-exclusive group) even when its value is the
        # empty string, so this is a genuinely reachable state, not dead
        # code. It must not fall through to an implicit `None` return -
        # SystemExit(None) is exit code 0, a silent false success for a
        # nonsensical invocation.
        parser.error("--validate requires a non-empty FILE path")
    if args.validate:
        return run_validate(repo, args, status)
    # M-a: unreachable. The mutually-exclusive group is required, and every
    # member (collect, archive, verify, validate-non-empty) returns above;
    # validate-empty-string calls parser.error above, which exits. No state
    # argparse can produce falls through to here.
    raise AssertionError(f"unreachable: argparse guarantees one mode; got {args}")
