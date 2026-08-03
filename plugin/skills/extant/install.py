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

# Evidence that this repository is worked on with Claude Code. Checked because
# the slash command is the one artifact here that only one tool can read, and
# writing it unconditionally put a `.claude/` directory into repositories whose
# owners use Codex, Cursor or no agent at all.
#
# The skill at `.agents/skills/` is NOT gated on anything: it is the open
# standard, every agent reads it, and it is what makes the install
# tool-agnostic. Only the Claude-specific extra asks for a reason first.
CLAUDE_EVIDENCE = (".claude", "CLAUDE.md")

# Agent Skills is an open standard: one SKILL.md, read by Claude Code, OpenAI
# Codex, Gemini CLI, GitHub Copilot, Cursor, Kimi Code and twenty-odd others.
# `.agents/skills/` is the cross-platform location - Codex reads it natively and
# Gemini CLI prefers it over its own `.gemini/skills/` when both exist.
#
# The validator itself was never Claude-specific: it is Python, git hooks and a
# pre-commit entry. Exactly one line of this installer was, and it was the line
# that decided where the agent-facing instructions went. Writing them to the
# standard location instead is the whole of "works with any agent".
AGENT_SKILL_TEMPLATE = "payload/commands/agent-skill.md.template"
AGENT_SKILL_DEST = ".agents/skills/extant/SKILL.md"


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
    # The eight below were shaped by reading each ecosystem's conventions rather
    # than by pattern-matching on the four above, and that research repeatedly
    # ruled out the obvious pair. Four times the two files that look like they
    # should agree are documented as deliberately NOT agreeing:
    #
    #   Helm       `version` is the chart, `appVersion` is the app, and the
    #              documentation says outright they are unrelated.
    #   Terraform  `required_version` is a CONSTRAINT (">= 1.5.0");
    #              `.terraform-version` is an exact pin. ">= 1.5.0" and "1.5.7"
    #              disagree as strings and agree in fact.
    #   Go         `go` is a minimum language version, `toolchain` an exact
    #              build version. `.go-version` is a third-party convention, not
    #              Go's.
    #   Mobile     `versionName`/`MARKETING_VERSION` are what a user sees;
    #              `versionCode`/`CURRENT_PROJECT_VERSION` are build counters
    #              that change every upload.
    #
    # Each of those would have produced a check that fires on a correct
    # repository. Where no honest pair exists the preset carries none, and the
    # document set is the whole value - which for most of these is the point:
    # a runbook, a chart README or an agent instruction file is mostly paths and
    # commands, and paths and commands are what rot.
    "agent": {
        "summary": "instruction files that AI coding agents read as fact",
        "primary_doc": "README.md",
        # AGENTS.md is the cross-tool standard, stewarded by the Linux
        # Foundation and read natively by Codex, Copilot, Cursor, Windsurf,
        # Aider, Zed and others; CLAUDE.md and GEMINI.md are the vendor-native
        # equivalents. These matter more than ordinary prose: an agent cannot
        # tell an expired line from a current one, so a dead path here becomes
        # confidently wrong work rather than a puzzled human.
        "extra_docs": ["AGENTS.md", "CLAUDE.md", "GEMINI.md",
                       ".github/copilot-instructions.md", "CONTRIBUTING.md"],
        "disable": ["phase_task", "phase_bare", "plans_dir"],
    },
    "go": {
        "summary": "a Go module: docs, and the Go version the build actually uses",
        "primary_doc": "README.md",
        "extra_docs": ["CONTRIBUTING.md", "SECURITY.md"],
        "disable": ["phase_task", "phase_bare", "plans_dir"],
        "consistency": {
            # Go modules carry no version of their own - releases are git tags -
            # so there is nothing to cross-check a CHANGELOG against. What does
            # drift is the language version the module requires against the one
            # the image builds with, and that only shows up in CI.
            "go_version": {
                "go.mod": r"^go (\d+\.\d+)",
                "Dockerfile": r"^FROM (?:--\S+ )?golang:(\d+\.\d+)",
            },
        },
    },
    "docker": {
        "summary": "images and compose files: runbooks, and the paths in them",
        "primary_doc": "README.md",
        "extra_docs": ["CONTRIBUTING.md", "DEPLOY.md", "RUNBOOK.md",
                       "OPERATIONS.md"],
        "disable": ["phase_task", "phase_bare", "plans_dir"],
        # No consistency check. An image tag in a compose file is the deployed
        # version, a tag in a Dockerfile is a base image, and a version in a
        # manifest is the application: three different things that a naive pair
        # would demand agree. The value here is the runbook, which is mostly
        # paths and commands and rots faster than anything else in the repo.
    },
    "jvm": {
        "summary": "Gradle or Maven: docs, plus the published version",
        "primary_doc": "README.md",
        "extra_docs": ["CONTRIBUTING.md", "SECURITY.md", "UPGRADING.md",
                       "MIGRATION.md"],
        "disable": ["phase_task", "phase_bare", "plans_dir"],
        "consistency": {
            "version": {
                "gradle.properties": r"^version\s*=\s*(\S+)",
                "CHANGELOG.md": r"^##\s*\[?v?(\d+\.\d+\.\d+)",
            },
        },
    },
    "k8s": {
        "summary": "Helm charts and manifests: chart docs and chart version",
        "primary_doc": "README.md",
        "extra_docs": ["CONTRIBUTING.md", "UPGRADING.md", "RUNBOOK.md"],
        "disable": ["phase_task", "phase_bare", "plans_dir"],
        "consistency": {
            # Chart.yaml `version` against the chart's own changelog. NOT
            # against `appVersion`: Helm's documentation states plainly that
            # appVersion is unrelated to version and moves independently, so
            # pairing them would report every correctly-maintained chart.
            "chart_version": {
                "Chart.yaml": r"^version:\s*v?(\d+\.\d+\.\d+)",
                "CHANGELOG.md": r"^##\s*\[?v?(\d+\.\d+\.\d+)",
            },
        },
    },
    "monorepo": {
        "summary": "a workspace root: shared docs and the root version",
        "primary_doc": "README.md",
        "extra_docs": ["CONTRIBUTING.md", "ARCHITECTURE.md", "docs/README.md"],
        "disable": ["phase_task", "phase_bare", "plans_dir"],
        "consistency": {
            # Root package.json against the root changelog. NOT lerna.json,
            # whose `version` is the literal string "independent" whenever a
            # project versions packages separately - the common case, and one
            # where a numeric pattern would match nothing and be reported as a
            # blind check on every run.
            "version": {
                "package.json": r'"version":\s*"([^"]+)"',
                "CHANGELOG.md": r"^##\s*\[?v?(\d+\.\d+\.\d+)",
            },
        },
    },
    "terraform": {
        "summary": "Terraform modules: the generated README and its neighbours",
        "primary_doc": "README.md",
        "extra_docs": ["CONTRIBUTING.md", "UPGRADING.md", "MIGRATION.md"],
        "disable": ["phase_task", "phase_bare", "plans_dir"],
        # No consistency check, and the reason is worth knowing: `required_version`
        # in versions.tf is a CONSTRAINT and `.terraform-version` is an exact
        # pin, so ">= 1.5.0" and "1.5.7" differ as strings while agreeing
        # perfectly in fact. A module README is generated by terraform-docs and
        # goes stale the moment a variable is renamed, which is what this checks.
    },
    # Both game presets were derived by measuring real shipped projects rather
    # than by reasoning about engine layouts, and the measurement contradicted
    # the obvious design three times. The corrections are recorded on each.
    #
    # The largest: the plan was to widen `path_pointer` with asset and source
    # extensions. Measured against a real Unity project and a real Godot one,
    # that rule examines ZERO references in either. Game documentation writes
    # paths as markdown links - `[ART_NOTES.md](Documentation/ART_NOTES.md)` -
    # and `path_pointer` requires a BACKTICKED path after an operative marker.
    # Widening it would have been a no-op that looked like a feature. Neither
    # preset touches it. `dead-md-link` is the rule that carries these projects,
    # and it needed no change: 257 links examined across the two, one reported,
    # and that one is a genuine bug in a shipped README.
    "unity": {
        "summary": "a Unity project: docs tree, and the editor version badge",
        "primary_doc": "README.md",
        "extra_docs": ["CONTRIBUTING.md", "CHANGELOG.md",
                       "Documentation/ART_NOTES.md"],
        "disable": ["phase_task", "phase_bare", "plans_dir"],
        "consistency": {
            # Anchored on the shields.io BADGE, not the prose. Measured on Unity
            # BossRoom: the badge carries `6000.0.52f1`, matching
            # ProjectVersion.txt exactly, while the prose two paragraphs later
            # says "currently 6000.0 LTS". A check keyed on the prose needs
            # major.minor on both sides and would then miss a drift from .52f1
            # to .61f1 entirely. Badges also rot faster than prose, which makes
            # this the more useful of the two claims to pin.
            "unity_version": {
                "README.md": r"Unity%20Version:-([\d.]+f\d+)",
                "ProjectSettings/ProjectVersion.txt": r"^m_EditorVersion:\s*(\S+)",
            },
        },
    },
    "godot": {
        "summary": "a Godot project: doc tree, and the engine version",
        "primary_doc": "README.md",
        "extra_docs": ["CONTRIBUTING.md", "doc/setup_instructions.md",
                       "doc/architecture.md", "doc/style_guide.md"],
        "disable": ["phase_task", "phase_bare", "plans_dir"],
        "consistency": {
            # NOT the README. Measured on Thrive, a shipped Godot game: its
            # README states no engine version at all, so a check keyed there
            # would have examined nothing forever while every run exited 0. The
            # version lives in the setup document - "The currently used Godot
            # version is 4.7 .NET" - against `config/features` in project.godot.
            #
            # Only major.minor is captured, because the two sides genuinely
            # differ in precision: the document says "4.7 .NET" and the project
            # file says "4.7". Capturing more would report a correct project.
            "godot_version": {
                "doc/setup_instructions.md": r"Godot version is[^\d]*(\d+\.\d+)",
                "project.godot": r'config/features=PackedStringArray\("(\d+\.\d+)"',
            },
        },
    },
    # No `unreal` preset, deliberately. There is no measured corpus for it here,
    # and shipping one derived from what Unreal projects are supposed to look
    # like is the failure this file already documents twice. Two things are
    # known and neither is enough: `.uproject` is JSON carrying an
    # `EngineAssociation`, and that field holds a GUID rather than a version on
    # any studio using a custom engine build - so the obvious consistency check
    # would false-positive on exactly the teams most likely to want this.
    "mobile": {
        "summary": "iOS and Android: store docs, and one marketing version",
        "primary_doc": "README.md",
        "extra_docs": ["CONTRIBUTING.md", "CHANGELOG.md", "RELEASE_NOTES.md",
                       "PRIVACY.md"],
        "disable": ["phase_task", "phase_bare", "plans_dir"],
        "consistency": {
            # The one number a user sees, which must be the same app on both
            # stores. NOT versionCode or CURRENT_PROJECT_VERSION: those are
            # build counters that change on every upload and are expected to
            # differ between platforms.
            "marketing_version": {
                "android/app/build.gradle": r'versionName\s+"([^"]+)"',
                "ios/App.xcodeproj/project.pbxproj": r"MARKETING_VERSION = ([^;]+);",
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
        # Only checks whose files are ALL present AND whose patterns actually
        # MATCH are emitted. A check naming a file that does not exist reports
        # a finding on the first run, which teaches the reader that this tool
        # complains about nothing, and that lesson is very hard to unteach.
        #
        # The pattern half was added after a scenario caught it: the Unity
        # preset reads the editor version out of a shields.io badge, and a
        # Unity project whose README has no badge got a permanent
        # "the pattern matches nothing" finding. Both files existed, so the
        # file check passed it through. Present-but-unmatched is the same
        # failure as absent, and deserves the same treatment.
        usable = {
            check: sources for check, sources in consistency.items()   # type: ignore[union-attr]
            if all((repo / f).is_file() for f in sources)
            and all(_pattern_matches(repo / f, pattern)
                    for f, pattern in sources.items())
        }
        skipped = sorted(set(consistency) - set(usable))                # type: ignore[arg-type]
        if usable:
            out.append(Observation("consistency", usable, DERIVED,
                                   f"preset '{name}', files and patterns verified"))
            notes.append(f"  consistency -> {', '.join(usable)}")
        for check in skipped:
            sources = consistency[check]                                # type: ignore[index]
            missing = [f for f in sources if not (repo / f).is_file()]
            blind = [f for f, pattern in sources.items()
                     if (repo / f).is_file() and not _pattern_matches(repo / f, pattern)]
            why = ", ".join(
                ([f"{', '.join(missing)} not here"] if missing else [])
                + ([f"nothing matched in {', '.join(blind)}"] if blind else []))
            notes.append(f"  consistency.{check} skipped: {why}")
    return out, notes


def _pattern_matches(path: Path, pattern: str) -> bool:
    """Does this file actually contain what the check intends to compare?

    A consistency block whose pattern matches nothing compares nothing, and
    reports that on every run forever. Verified once, at install time, where
    the answer is cheap and the fix is obvious.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    try:
        return re.search(pattern, text, re.MULTILINE) is not None
    except re.error:
        return False


def render_command(obs: list[Observation], project: str,
                   template: str = COMMAND_TEMPLATE) -> tuple[str, list[str]]:
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

    text = (SKILL_ROOT / template).read_text(encoding="utf-8")
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

    # A release claim in THIS project's own status document is about THIS
    # project's tags, and the installer is the one place that can say so.
    #
    # The setting is off by default because in general it is unknowable: a
    # version in prose can name a git tag, an npm or PyPI release, a
    # sub-package or somebody else's toolchain, and reading every one as a
    # local tag was wrong 19 times out of 26 across 15 projects that write such
    # claims. None of that ambiguity applies here. Installing extant INTO a
    # repository to check that repository's own document is precisely the
    # assertion the setting exists to record, so the installer records it.
    obs.append(Observation(
        "release_claims_name_our_tags", True, DERIVED,
        "this document describes this repository, so its release claims name "
        "these tags",
    ))

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
        # TWO groups: the ref the claim names, then the commit. The verbs are
        # still measured from this project's own prose; only the target stopped
        # being hard-coded to the configured trunk.
        #
        # This line is why the collector's fix alone was not enough. The
        # installer writes its own pattern into `.extant.toml`, which overrides
        # the default, so every freshly installed project would have kept the
        # old single-trunk behaviour no matter what the rule supported. Unit
        # tests missed it because they exercise the default; the gitflow
        # scenario runs the real installer and caught it immediately.
        obs.append(Observation(
            "merge_claim",
            rf"(?:{alt})\s+(?:to|into|in|on)\s+(`[^`\n]+`|[\w.\-/]+)"
            rf"\s+(?:at|in|as)\s+`([0-9a-f]{{7,40}})`",
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
        elif isinstance(o.value, bool):
            # TOML booleans are lowercase. `str(True)` is "True", which TOML
            # rejects, so the bare fallback at the bottom wrote a file the tool
            # then refused to read - silencing every rule at once.
            #
            # That is the THIRD time this shape has shipped from this function:
            # `plans_dir = ` with nothing after it, then `release_tag` written
            # bare, now the first boolean observation. The fallback grew a
            # string branch and a list branch each time and still had no branch
            # for the type nobody had used yet, which is what the comment below
            # means by "an allowlist of keys cannot protect a key nobody has
            # thought of". Booleans are the type that was missing; the test
            # that parses every generated config is the guard that generalises.
            lines.append(f"{o.key} = {'true' if o.value else 'false'}")
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
                # A literal apostrophe inside a single-quoted TOML string ends
                # it early, and the generated config then does not parse at
                # all. The plain-pattern branch above already guards this; the
                # consistency block did not, so one apostrophe in a measured
                # pattern would have shipped a broken file.
                if "'" in pattern:
                    lines.append(f'"{file_path}" = \'\'\'{pattern}\'\'\'')
                else:
                    lines.append(f'"{file_path}" = \'{pattern}\'')
            lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="install", description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--doc", help="path to the status document, if ambiguous")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="overwrite existing payload files")
    # Three states, not two: unset means decide from the repository. A plain
    # store_true could not tell "left at the default" from "explicitly off",
    # so there would be no way to suppress the file in a repo that does carry
    # Claude evidence.
    parser.add_argument("--claude-command", default=None, action="store_true",
                        help="write the Claude Code slash command even without "
                             "evidence this repo uses Claude Code")
    parser.add_argument("--no-claude-command", dest="claude_command",
                        action="store_false",
                        help="never write the Claude Code slash command")
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
            with open(cfg, "w", encoding="utf-8", newline="") as fh:
                fh.write(render_config(obs))

    command_path = repo / COMMAND_DEST
    found = [name for name in CLAUDE_EVIDENCE if (repo / name).exists()]
    if args.claude_command is None:
        wanted, why = bool(found), (
            f"found {', '.join(found)}" if found
            else f"no {' or '.join(CLAUDE_EVIDENCE)} here")
    else:
        wanted, why = args.claude_command, "asked for on the command line"

    if not wanted:
        # Stated rather than silent, and it names the flag. A file that does
        # not appear is invisible, so without this line the only way to learn
        # the slash command exists would be to read the installer.
        print(f"  skipped {COMMAND_DEST}: {why}"
              f" - use --claude-command to write it anyway")
    elif command_path.exists() and not args.force:
        print(f"  {COMMAND_DEST} already exists - left alone (use --force to replace)")
    else:
        command_text, command_notes = render_command(obs, repo.name)
        print(f"  {'would write' if args.dry_run else 'wrote'} {COMMAND_DEST}, "
              f"rendered for '{repo.name}' ({why})")
        if not args.dry_run:
            command_path.parent.mkdir(parents=True, exist_ok=True)
            with open(command_path, "w", encoding="utf-8", newline="") as fh:
                fh.write(command_text)
        for note in command_notes:
            print(f"  {note}")

    # The same guidance, at the location every OTHER agent reads. Rendered from
    # the same observations as the slash command above, so the two cannot end up
    # describing different repositories.
    skill_text, skill_notes = render_command(obs, repo.name, AGENT_SKILL_TEMPLATE)
    skill_path = repo / AGENT_SKILL_DEST
    if skill_path.exists() and not args.force:
        print(f"  {AGENT_SKILL_DEST} already exists - left alone (use --force to replace)")
    else:
        print(f"  {'would write' if args.dry_run else 'wrote'} {AGENT_SKILL_DEST}, "
              f"read by Codex, Gemini CLI, Copilot, Cursor and Kimi")
        if not args.dry_run:
            skill_path.parent.mkdir(parents=True, exist_ok=True)
            with open(skill_path, "w", encoding="utf-8", newline="") as fh:
                fh.write(skill_text)
    for note in skill_notes:
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
