"""Install the handoff system into a repository, deriving its configuration.

    python install.py --repo /path/to/repo --dry-run
    python install.py --repo /path/to/repo
    python install.py --repo /path/to/repo --doc docs/STATUS.md

Copies the tool, hooks and slash command, then writes a `.handoff.toml` derived
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
    ("payload/handoff_collect.py", "tools/handoff_collect.py"),
    ("payload/handoff_config.py", "tools/handoff_config.py"),
    ("payload/hooks/handoff-verify", "tools/hooks/handoff-verify"),
    ("payload/hooks/main-tree-guard", "tools/hooks/main-tree-guard"),
    ("payload/hooks/install", "tools/hooks/install"),
    # The slash command is RENDERED, not copied - see render_command.
]

COMMAND_TEMPLATE = "payload/commands/handoff.md.template"
COMMAND_DEST = ".claude/commands/handoff.md"


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


def render_command(obs: list[Observation], project: str) -> tuple[str, list[str]]:
    """Render the /handoff slash command for THIS repo.

    This file used to be copied verbatim. Every installation therefore told the
    agent it was working on the source project, to write that project's document
    at that project's path, in a layout the target repo may not use - while a
    correctly derived .handoff.toml sat next to it, unread. It is the same
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
            "'## Phase '. Set it in .handoff.toml and correct the command, or "
            "archiving and live-claim checks will not recognise your entries."
        )

    mapping = {
        "{{PROJECT}}": project,
        "{{DOC}}": str(values.get("handoff_doc") or "NEXT_SESSION.md"),
        "{{ARCHIVE}}": str(values.get("archive_doc") or "handoff-archive.md"),
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


def choose_document(repo: Path, explicit: str | None) -> tuple[Path | None, list[str]]:
    """Pick the handoff document, and say so when the choice was ambiguous."""
    notes: list[str] = []
    if explicit:
        path = repo / explicit
        if not path.is_file():
            return None, [f"--doc {explicit} does not exist"]
        return path, [f"using --doc {explicit}"]

    found = detect.find_documents(repo)
    if not found:
        return None, ["no handoff document found in the usual places"]
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
        Observation("handoff_doc", rel, DERIVED, f"{info['lines']} lines"),
        detect.detect_trunk(repo),
        detect.detect_branch_pattern(repo),
        *detect.detect_commit_convention(repo),
    ]

    # Archive sits beside the document, not at a path borrowed from elsewhere.
    parent = doc.parent.relative_to(repo).as_posix()
    archive = f"{parent}/handoff-archive.md" if parent != "." else "handoff-archive.md"
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
        "# Generated by the handoff skill's installer, by inspecting this repo.",
        "#",
        "# Confidence is recorded per value. Anything marked unknown/default is",
        "# COMMENTED OUT rather than guessed: a pattern that matches nothing makes",
        "# --verify exit 0 forever while looking healthy, which is worse than an",
        "# obviously missing setting. See references/porting.md.",
        "",
        "[handoff]",
    ]
    # Regex values go in TOML LITERAL strings (single quotes), which perform no
    # escape processing. In a basic string `\d` and `\s` are invalid escapes and
    # the whole file fails to parse - which is exactly what the first generated
    # config did, caught only by parsing the output rather than reading it.
    regexy = {"branch_token", "merge_claim", "phase_task", "live_phrases",
              "base_header", "path_pointer", "phase_bare", "todo_markers"}
    plain = {"handoff_doc", "archive_doc", "trunk", "entry_prefix", "pointer_prefix"}
    for o in obs:
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
        else:
            lines.append(f"{o.key} = {o.value}")
        lines.append("")
    lines += ["retain_entries = 3", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="install", description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--doc", help="path to the handoff document, if ambiguous")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="overwrite existing payload files")
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

    doc, notes = choose_document(repo, args.doc)
    print("\ndocument")
    for note in notes:
        print(f"  {note}")
    if doc is None:
        print("\n  Create a handoff document, then rerun - or pass --doc.")
        return 1

    obs, _info = observe(repo, doc)
    print("\nderived configuration")
    width = max(len(o.key) for o in obs)
    for o in obs:
        shown = "NOT DETERMINED" if o.value is None else str(o.value)
        print(f"  {o.key:<{width}}  [{o.confidence:<8}] {shown[:70]}")
        print(f"  {'':<{width}}   {o.evidence}")

    cfg = repo / ".handoff.toml"
    print()
    if cfg.exists() and not args.force:
        print("  .handoff.toml already exists - left alone (use --force to replace)")
    else:
        print(f"  {'would write' if args.dry_run else 'wrote'} .handoff.toml")
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
