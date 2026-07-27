"""Install the status workflow into a repository, deriving its configuration.

    python install.py --repo /path/to/repo --dry-run
    python install.py --repo /path/to/repo
    python install.py --repo /path/to/repo --doc docs/STATUS.md

Copies the tool, hooks and slash command, then writes a `.extant.toml` derived
by INSPECTING the repository - its trunk branch, branch naming, commit
conventions and the document itself - rather than by copying another project's
values.

The failure this guards against: patterns that match nothing make the validator
exit 0 forever while appearing healthy. So every value is reported with its
confidence, anything undetermined is written COMMENTED OUT rather than guessed,
and the closing advice says plainly what still needs a human.

See references/porting.md for the manual derivation procedure, which this
automates about eighty per cent of.
"""
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

import detect
from detect import DEFAULT, DERIVED, GUESSED, UNKNOWN, Observation

SKILL_ROOT = Path(__file__).resolve().parent

PAYLOAD = [
    ("payload/extant_collect.py", "tools/extant_collect.py"),
    ("payload/extant_config.py", "tools/extant_config.py"),
    ("payload/hooks/extant-verify", "tools/hooks/extant-verify"),
    ("payload/hooks/main-tree-guard", "tools/hooks/main-tree-guard"),
    ("payload/hooks/install", "tools/hooks/install"),
    # The slash command is RENDERED, not copied - see render_command.
]

COMMAND_TEMPLATE = "payload/commands/extant.md.template"
COMMAND_DEST = ".claude/commands/extant.md"


def verify_hooks(repo: Path) -> list[str]:
    """Confirm every hook the shim wires is actually present on disk.

    `tools/hooks/install` wires a pre-commit pointing at `main-tree-guard` and
    skips silently when the file is absent. While the payload list omitted that
    file, the installer printed `installed: pre-commit -> main-tree-guard` and
    the guard never ran once - a check indistinguishable from a passing one.

    Checked here because this is the moment the omission is cheap to see, and
    because it needs no test runner: the repos this skill targets may have no
    Python suite to put an assertion in.
    """
    hooks = repo / "tools" / "hooks"
    shim = hooks / "install"
    if not shim.is_file():
        return ["tools/hooks/install did not land - no hooks can be wired"]

    names = sorted(set(re.findall(r"tools/hooks/([A-Za-z0-9_-]+)",
                                  shim.read_text(encoding="utf-8"))))
    if not names:
        return ["tools/hooks/install names no hooks - expected at least one; "
                "the check below would pass vacuously"]

    missing = [n for n in names if not (hooks / n).is_file()]
    # State the denominator, not just the verdict.
    lines = [f"checked {len(names)} hook reference(s): {', '.join(names)}"]
    if missing:
        lines.append(f"MISSING: {', '.join(missing)} - wired but absent, so they "
                     f"will silently NOT run")
    return lines


# Presets exist because the documented failure mode of this tool is a
# configuration that matches nothing and reports a healthy run forever. Asking
# every adopter to derive patterns before they have seen the tool work once is
# a fine way to lose them at step one.
#
# A preset names the DOCUMENTS and the shape. Detection still supplies trunk,
# branch naming and commit conventions, because those are measured from the
# repository and a guess would be worse than a measurement.
#
# `readme` deliberately needs nothing else: it is the shape of a project that
# keeps no status document at all, which is most of them.
PRESETS: dict[str, dict[str, object]] = {
    "readme": {
        "summary": "check the docs you already have (no status file needed)",
        "primary_doc": "README.md",
        "extra_docs": ["CONTRIBUTING.md"],
        # No dated entries in a README, so nothing to archive or group.
        "disable": ["phase_task", "phase_bare", "plans_dir"],
    },
    "node": {
        "summary": "a README-shaped project, plus package.json cross-checks",
        "primary_doc": "README.md",
        "extra_docs": ["CONTRIBUTING.md"],
        "disable": ["phase_task", "phase_bare", "plans_dir"],
        "suite_command": ["npm", "test"],
        "consistency": {
            "version": {
                "package.json": r'"version":\s*"([^"]+)"',
                "CHANGELOG.md": r"^##\s*\[?v?(\d+\.\d+\.\d+)",
            },
        },
    },
    "python": {
        "summary": "a README-shaped project, plus pyproject cross-checks",
        "primary_doc": "README.md",
        "extra_docs": ["CONTRIBUTING.md"],
        "disable": ["phase_task", "phase_bare", "plans_dir"],
        "consistency": {
            "version": {
                "pyproject.toml": r'^version\s*=\s*"([^"]+)"',
                "CHANGELOG.md": r"^##\s*\[?v?(\d+\.\d+\.\d+)",
            },
        },
    },
    "rust": {
        "summary": "a README-shaped project, plus Cargo.toml cross-checks",
        "primary_doc": "README.md",
        "extra_docs": ["CONTRIBUTING.md"],
        "disable": ["phase_task", "phase_bare", "plans_dir"],
        "suite_command": ["cargo", "test"],
        "consistency": {
            "version": {
                "Cargo.toml": r'^version\s*=\s*"([^"]+)"',
                "CHANGELOG.md": r"^##\s*\[?v?(\d+\.\d+\.\d+)",
            },
        },
    },
    # The three below are shaped by what their audience actually keeps, and all
    # three lean on EXTRA DOCUMENTS rather than on clever patterns. Long-lived
    # policy and upgrade documents are where a project's oldest links and file
    # pointers live, and age is the whole subject here.
    #
    # Their consistency checks compare two MACHINE-READABLE files, never prose
    # against a manifest. Every check above does the same, and it is the reason
    # none of them has produced a false positive: a JSON version field has one
    # spelling, whereas a sentence naming a version has as many as there are
    # authors. Each check is also a PAIR, because a check is emitted only when
    # every file it names is present, so a third file makes it likelier to be
    # skipped entirely than to catch anything.
    "enterprise": {
        "summary": "long-lived policy, support and upgrade documents",
        "primary_doc": "README.md",
        # An LTS project's rot lives here: security policies naming versions
        # that left support, upgrade notes pointing at moved files, and release
        # claims for tags that were never cut.
        "extra_docs": ["CONTRIBUTING.md", "SECURITY.md", "SUPPORT.md",
                       "UPGRADING.md", "MIGRATION.md"],
        "disable": ["phase_task", "phase_bare", "plans_dir"],
        # No consistency check on purpose. "Enterprise" names an audience, not
        # a language, so there is no manifest common to all of them. A guessed
        # pair would be skipped on most repositories and wrong on the rest.
    },
    "ml": {
        "summary": "a data or model project: cards, and environment pins",
        "primary_doc": "README.md",
        "extra_docs": ["CONTRIBUTING.md", "MODEL_CARD.md", "DATA_CARD.md"],
        "disable": ["phase_task", "phase_bare", "plans_dir"],
        "consistency": {
            # The classic drift in this ecosystem: the environment file and the
            # project metadata pin different interpreters, and the difference
            # only shows up on someone else's machine.
            "python_version": {
                "pyproject.toml": r'^requires-python\s*=\s*"[^\d]*(\d+\.\d+)',
                "environment.yml": r"^\s*-\s*python\s*[=>~]=?\s*(\d+\.\d+)",
            },
            "version": {
                "pyproject.toml": r'^version\s*=\s*"([^"]+)"',
                "CHANGELOG.md": r"^##\s*\[?v?(\d+\.\d+\.\d+)",
            },
        },
    },
    "legacy-web": {
        "summary": "an older web app: install and deploy notes, runtime pins",
        "primary_doc": "README.md",
        "extra_docs": ["CONTRIBUTING.md", "INSTALL.md", "DEPLOY.md",
                       "UPGRADING.md"],
        "disable": ["phase_task", "phase_bare", "plans_dir"],
        "consistency": {
            # A runtime pinned in two places that drifted apart is the defining
            # bug of an application nobody has upgraded in three years.
            "node_version": {
                ".nvmrc": r"^v?(\d+)",
                "package.json": r'"node":\s*"[^\d]*(\d+)',
            },
            "version": {
                "package.json": r'"version":\s*"([^"]+)"',
                "CHANGELOG.md": r"^##\s*\[?v?(\d+\.\d+\.\d+)",
            },
        },
    },
    "status": {
        "summary": "a running status document with dated entries (the original shape)",
        "primary_doc": None,      # detected
        "extra_docs": [],
        "disable": [],
    },
}


def apply_preset(name: str, obs: list[Observation], repo: Path) -> tuple[list[Observation], list[str]]:
    """Fold a preset into the derived observations, reporting what it changed.

    A preset never overrides something MEASURED from the repository. Detection
    beats a template every time: the whole point of the installer is that it
    looks rather than assumes, and a preset that silently replaced a derived
    trunk would reintroduce exactly the copied-config failure this project was
    built around.
    """
    preset = PRESETS[name]
    notes = [f"preset '{name}': {preset['summary']}"]
    by_key = {o.key: o for o in obs}
    out = list(obs)

    doc = preset.get("primary_doc")
    if doc:
        existing = by_key.get("primary_doc")
        if existing is not None and existing.value == doc:
            notes.append(f"  primary_doc already {doc}")
        elif (repo / str(doc)).is_file():
            chosen = Observation("primary_doc", doc, DERIVED,
                                 f"chosen by preset '{name}'")
            # Replace if present, APPEND if not. A comprehension that only
            # substitutes drops the value silently when there is nothing to
            # substitute, which is the same defect in miniature as the one
            # that made this preset unusable: a value computed and discarded.
            if existing is not None:
                out = [chosen if o.key == "primary_doc" else o for o in out]
            else:
                out.append(chosen)
            notes.append(f"  primary_doc -> {doc}")
        else:
            notes.append(f"  {doc} does not exist here; kept the detected document")

    extras = [e for e in preset.get("extra_docs", []) if (repo / str(e)).is_file()]
    if extras:
        out.append(Observation("extra_docs", extras, DERIVED,
                               f"present in this repo, added by preset '{name}'"))
        notes.append(f"  extra_docs -> {', '.join(extras)}")

    for key in preset.get("disable", []):          # type: ignore[union-attr]
        out = [o for o in out if o.key != key]
        out.append(Observation(key, "", DERIVED,
                               f"switched off by preset '{name}'"))
    if preset.get("disable"):
        notes.append(f"  disabled: {', '.join(preset['disable'])}")  # type: ignore[arg-type]

    if "suite_command" in preset:
        out.append(Observation("suite_command", preset["suite_command"], DERIVED,
                               f"preset '{name}'"))
        notes.append(f"  suite_command -> {preset['suite_command']}")

    consistency = preset.get("consistency", {})
    if consistency:
        # Only checks whose files are ALL present are emitted. A check naming a
        # file that does not exist reports a finding on the first run, which
        # teaches the reader that this tool complains about nothing, and that
        # lesson is very hard to unteach.
        usable = {
            check: sources for check, sources in consistency.items()   # type: ignore[union-attr]
            if all((repo / f).is_file() for f in sources)
        }
        skipped = sorted(set(consistency) - set(usable))                # type: ignore[arg-type]
        if usable:
            out.append(Observation("consistency", usable, DERIVED,
                                   f"preset '{name}', files verified present"))
            notes.append(f"  consistency -> {', '.join(usable)}")
        for check in skipped:
            missing = [f for f in consistency[check]                    # type: ignore[index]
                       if not (repo / f).is_file()]
            notes.append(f"  consistency.{check} skipped: {', '.join(missing)} not here")
    return out, notes


def render_command(obs: list[Observation], project: str) -> tuple[str, list[str]]:
    """Render the /extant slash command for THIS repo.

    This file used to be copied verbatim. Every installation therefore told the
    agent it was working on the source project, to write that project's document
    at that project's path, in a layout the target repo may not use - while a
    correctly derived .extant.toml sat next to it, unread. It is the same
    "config key nothing reads" defect the validator exists to catch, and it was
    the single largest obstacle to this skill being usable anywhere else.
    """
    values = {o.key: o.value for o in obs}
    notes: list[str] = []

    entry_prefix = values.get("entry_prefix")
    if not entry_prefix:
        entry_prefix = "## Phase "
        notes.append(
            "entry_prefix was not detected; the command file falls back to "
            "'## Phase '. Set it in .extant.toml and correct the command, or "
            "archiving and live-claim checks will not recognise your entries."
        )

    mapping = {
        "{{PROJECT}}": project,
        "{{DOC}}": str(values.get("primary_doc") or "NEXT_SESSION.md"),
        "{{ARCHIVE}}": str(values.get("archive_doc") or "status-archive.md"),
        "{{ENTRY_PREFIX}}": str(entry_prefix),
    }

    text = (SKILL_ROOT / COMMAND_TEMPLATE).read_text(encoding="utf-8")
    for token, value in mapping.items():
        text = text.replace(token, value)

    # A placeholder added to the template but never to the mapping would ship
    # literally into someone's command file. Catch it here rather than let them
    # read `{{DOC}}` in a prompt.
    leftover = sorted(set(re.findall(r"\{\{[A-Z_]+\}\}", text)))
    if leftover:
        notes.append(f"UNSUBSTITUTED placeholder(s): {', '.join(leftover)}")
    return text, notes


def copy_payload(repo: Path, *, dry_run: bool, force: bool) -> list[str]:
    """Copy the payload, refusing to clobber a modified existing install."""
    actions: list[str] = []
    for src_rel, dst_rel in PAYLOAD:
        src, dst = SKILL_ROOT / src_rel, repo / dst_rel
        if not src.is_file():
            actions.append(f"MISSING from skill payload: {src_rel}")
            continue
        if dst.is_file() and not force:
            same = dst.read_bytes() == src.read_bytes()
            actions.append(
                f"{dst_rel}: already present and identical, skipped" if same
                else f"{dst_rel}: EXISTS AND DIFFERS - left alone, use --force to overwrite"
            )
            continue
        actions.append(f"{'would copy' if dry_run else 'copied'} {dst_rel}")
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    return actions


def choose_document(
    repo: Path, explicit: str | None, preset_doc: str | None = None
) -> tuple[Path | None, list[str]]:
    """Pick the primary document, and say so when the choice was ambiguous.

    `preset_doc` is the document a preset names, and it is settled HERE rather
    than folded in afterwards. Two reasons, one of which was a bug:

    Choosing a preset is an instruction, not a measurement, so it outranks
    detection for the document. That is different from the rule in
    `apply_preset`, where a preset must never override a MEASURED fact such as
    the trunk name. Which file to check is the user's call; which branch is
    trunk is the repository's.

    And everything else is derived FROM this document - the archive is placed
    beside it, the evidence quotes its length. Switching the document after
    those were computed left them describing the previous file, so a preset
    could point `primary_doc` at the README while the archive sat next to a
    status document in `docs/`.

    Before this, the `readme` preset was unusable on exactly the projects it
    exists for: it names README.md, which is not a status-document name, so
    detection found nothing and the installer exited before the preset was ever
    read. It advertised "no status file needed" and then demanded one.
    """
    notes: list[str] = []
    if explicit:
        path = repo / explicit
        if not path.is_file():
            return None, [f"--doc {explicit} does not exist"]
        return path, [f"using --doc {explicit}"]

    if preset_doc and (repo / preset_doc).is_file():
        return repo / preset_doc, [f"using {preset_doc}, named by the preset"]

    found = detect.find_documents(repo)
    if not found:
        return None, ["no status document found in the usual places"]
    if len(found) > 1:
        rels = [str(p.relative_to(repo)).replace("\\", "/") for p in found]
        notes.append(f"MULTIPLE candidates: {', '.join(rels)}")
        notes.append(f"  chose {rels[0]} (nearest the root) - rerun with --doc to override")
    return found[0], notes


def observe(repo: Path, doc: Path) -> tuple[list[Observation], dict[str, object]]:
    """Everything derivable, each with its confidence."""
    info = detect.inspect_document(doc)
    rel = str(doc.relative_to(repo)).replace("\\", "/")

    obs: list[Observation] = [
        Observation("primary_doc", rel, DERIVED, f"{info['lines']} lines"),
        detect.detect_trunk(repo),
        detect.detect_branch_pattern(repo),
        detect.detect_release_tag(repo),
        *detect.detect_commit_convention(repo),
    ]

    # Archive sits beside the document, not at a path borrowed from elsewhere.
    parent = doc.parent.relative_to(repo).as_posix()
    archive = f"{parent}/status-archive.md" if parent != "." else "status-archive.md"
    obs.append(Observation("archive_doc", archive, DERIVED, "placed beside the document"))

    # Entry header: repeated AND date-bearing headers score above reference ones.
    scores = info["header_scores"]  # type: ignore[index]
    if scores and scores[0][1] > 1:
        obs.append(Observation(
            "entry_prefix", scores[0][0] + " ", GUESSED,
            f"highest-scoring header {scores[0][0]!r}; others: "
            + ", ".join(h for h, _ in scores[1:4]),
        ))
    else:
        obs.append(Observation("entry_prefix", None, UNKNOWN, "no repeated dated header found"))

    # Merge claim, built from the verbs actually used here.
    verbs = info["merge_verbs"]  # type: ignore[index]
    if verbs:
        alt = "|".join(sorted(verbs))
        # Emitted into a TOML *literal* string, so backslashes are written once
        # and not escaped. A basic (double-quoted) string would reject `\s` and
        # `\d` outright - the generated file simply would not parse.
        obs.append(Observation(
            "merge_claim",
            rf"(?:{alt})\s+(?:to|into|in|on)\s+`?{{trunk}}`?\s+(?:at|in|as)\s+`([0-9a-f]{{7,40}})`",
            DERIVED,
            f"{info['merge_count']} example(s) using: {', '.join(verbs)}",
        ))
    else:
        obs.append(Observation("merge_claim", None, UNKNOWN, "no 'verb ... target at <sha>' phrasing found"))

    obs.append(Observation(
        "live_phrases", None, DEFAULT,
        "cannot be derived - depends on how THIS project says 'not done yet'",
    ))
    return obs, info


def render_config(obs: list[Observation]) -> str:
    """Emit TOML. Undetermined values are commented out, never guessed."""
    lines = [
        "# Generated by the extant skill's installer, by inspecting this repo.",
        "#",
        "# Confidence is recorded per value. Anything marked unknown/default is",
        "# COMMENTED OUT rather than guessed: a pattern that matches nothing makes",
        "# --verify exit 0 forever while looking healthy, which is worse than an",
        "# obviously missing setting. See references/porting.md.",
        "",
        "[extant]",
    ]
    # Regex values go in TOML LITERAL strings (single quotes), which perform no
    # escape processing. In a basic string `\d` and `\s` are invalid escapes and
    # the whole file fails to parse - which is exactly what the first generated
    # config did, caught only by parsing the output rather than reading it.
    regexy = {"branch_token", "merge_claim", "phase_task", "live_phrases",
              "base_header", "path_pointer", "phase_bare", "todo_markers",
              "release_tag"}
    plain = {"primary_doc", "archive_doc", "trunk", "entry_prefix", "pointer_prefix"}
    # `consistency` is a nested table, so it must be emitted AFTER every plain
    # key: in TOML everything following a table header belongs to that table,
    # and a scalar written below one silently joins it. That is the same shape
    # as the bug where a [extant.*] sub-table swallowed the top-level keys.
    deferred = [o for o in obs if o.key == "consistency"]
    for o in [o for o in obs if o.key != "consistency"]:
        lines.append(f"# [{o.confidence}] {o.evidence}")
        if o.value is None:
            lines.append(f"# {o.key} = '...'   # NOT DETERMINED - set this by hand")
        elif o.key in regexy:
            value = str(o.value)
            if "'" in value:  # literal strings cannot contain a single quote
                lines.append(f"{o.key} = '''{value}'''")
            else:
                lines.append(f"{o.key} = '{value}'")
        elif o.key in plain:
            lines.append(f'{o.key} = "{o.value}"')
        elif isinstance(o.value, list):
            rendered = ", ".join(f'"{item}"' for item in o.value)
            lines.append(f"{o.key} = [{rendered}]")
        elif o.value == "":
            # An empty string is how a feature is switched OFF, and it has to be
            # written as a quoted empty string. Falling through to the bare
            # branch produced `plans_dir = ` with nothing after it, which is not
            # valid TOML - so the installer wrote a file the tool then refused
            # to read. An installer that emits a broken config is worse than one
            # that emits none.
            lines.append(f"{o.key} = ''")
        elif isinstance(o.value, str):
            # Any string not named in a set above. Quoting it is the only safe
            # default: writing a string bare is never valid TOML, and this
            # branch is where an observation added later lands by definition.
            # `release_tag` landed here the day it was added and produced a
            # config the tool then refused to read, silencing every rule at
            # once - the same defect as the `plans_dir = ` case below, reached
            # from the opposite direction. An allowlist of keys cannot protect
            # a key nobody has thought of yet; a safe fallback can.
            lines.append(f"{o.key} = '''{o.value}'''"
                         if "'" in o.value else f"{o.key} = '{o.value}'")
        else:
            lines.append(f"{o.key} = {o.value}")
        lines.append("")
    lines += ["retain_entries = 3", ""]

    for o in deferred:
        lines.append(f"# [{o.confidence}] {o.evidence}")
        for check, sources in o.value.items():          # type: ignore[union-attr]
            lines.append(f"[extant.consistency.{check}]")
            for file_path, pattern in sources.items():
                lines.append(f'"{file_path}" = \'{pattern}\'')
            lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="install", description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--doc", help="path to the status document, if ambiguous")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="overwrite existing payload files")
    parser.add_argument("--preset", choices=sorted(PRESETS),
                        help="start from a known project shape; "
                             + "; ".join(f"{k}: {v['summary']}" for k, v in PRESETS.items()))
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists():
        print(f"not a git repository: {repo}")
        return 1

    print("payload")
    for action in copy_payload(repo, dry_run=args.dry_run, force=args.force):
        print(f"  {action}")
    if not args.dry_run:
        for line in verify_hooks(repo):
            print(f"  {line}")

    preset_doc = PRESETS[args.preset].get("primary_doc") if args.preset else None
    doc, notes = choose_document(repo, args.doc, str(preset_doc) if preset_doc else None)
    print("\ndocument")
    for note in notes:
        print(f"  {note}")
    if doc is None:
        print("\n  No document to check. Pass --doc <path>, or --preset readme")
        print("  to check the README and CONTRIBUTING file you already have.")
        return 1

    obs, _info = observe(repo, doc)
    if args.preset:
        obs, preset_notes = apply_preset(args.preset, obs, repo)
        print()
        for note in preset_notes:
            print(f"  {note}")
    print("\nderived configuration")
    width = max(len(o.key) for o in obs)
    for o in obs:
        shown = "NOT DETERMINED" if o.value is None else str(o.value)
        print(f"  {o.key:<{width}}  [{o.confidence:<8}] {shown[:70]}")
        print(f"  {'':<{width}}   {o.evidence}")

    cfg = repo / ".extant.toml"
    print()
    if cfg.exists() and not args.force:
        print("  .extant.toml already exists - left alone (use --force to replace)")
    else:
        print(f"  {'would write' if args.dry_run else 'wrote'} .extant.toml")
        if not args.dry_run:
            cfg.write_text(render_config(obs), encoding="utf-8", newline="")

    command_text, command_notes = render_command(obs, repo.name)
    command_path = repo / COMMAND_DEST
    if command_path.exists() and not args.force:
        print(f"  {COMMAND_DEST} already exists - left alone (use --force to replace)")
    else:
        print(f"  {'would write' if args.dry_run else 'wrote'} {COMMAND_DEST}, "
              f"rendered for '{repo.name}'")
        if not args.dry_run:
            command_path.parent.mkdir(parents=True, exist_ok=True)
            command_path.write_text(command_text, encoding="utf-8", newline="")
    for note in command_notes:
        print(f"  {note}")

    unresolved = [o.key for o in obs if o.confidence in (UNKNOWN, DEFAULT)]
    weak = [o.key for o in obs if o.confidence == GUESSED]

    print("\nstill needs you")
    if unresolved:
        print(f"  NOT DETERMINED: {', '.join(unresolved)} - commented out in the config.")
        print("  Rules with no pattern check nothing. Set them or accept the gap knowingly.")
    if weak:
        print(f"  LOW CONFIDENCE: {', '.join(weak)} - verify against the real document.")
    print("  Then run --verify and read its denominator line: a rule that examined")
    print("  0 candidates is inert whatever the exit code says. Then break something")
    print("  on purpose to watch a rule fire - a rule never observed failing has not")
    print("  been tested.")
    print("  Finally: sh tools/hooks/install")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
