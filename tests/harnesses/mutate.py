"""Mutation campaign: break the code on purpose and see if the suite notices.

    python tests/harnesses/mutate.py

A mutation that SURVIVES means the behaviour changed and no test complained,
which is a gap in the suite rather than a bug in the code. That is the only
mechanical way to answer "does this test actually pin anything", which
CONTRIBUTING.md asks for and which nothing else here enforces.

Every mutation asserts it applied. A substitution that silently misses leaves
the code correct, the suite green, and reports SURVIVED - a false alarm
indistinguishable from a real gap, and exactly the failure this project is
about. NOT APPLIED is therefore reported as a harness fault, never as a result.

This found six gaps the 168-test suite could not, including two tests that a
broken implementation satisfied. It is slow by nature: one full suite run per
mutation. Expect roughly half an hour.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def build_mutations(collect: Path, detect: Path) -> list[tuple[str, Path, str, str]]:
    """(label, file, find, replace). Each must match exactly once."""
    # Code that used to live in extant_collect.py and now has its own module. A
    # mutation names the file the code is in TODAY; the LABEL says which
    # behaviour it probes, and that does not change when the code moves house.
    #
    # Twelve anchors below moved here in Task 8 with the ancestry, ref-table,
    # rename and object-resolution helpers. Seven of the twelve also needed
    # their TEXT rewritten, not just their path: those functions stopped
    # reading `_SCOPE`, `_GIT` and `repo` off a module and started taking the
    # Context that carries them, so `_SCOPE.ancestors` became
    # `ctx.run.ancestors` and `_GIT.run(repo, ...)` became
    # `ctx.git.run(ctx.repo, ...)`. A path-only retarget would have left those
    # seven matching nothing, which --check-only reports as STALE and a
    # campaign would have reported as a clean result it did not earn.
    refs = collect.parent / "extant/refs.py"
    # Task 9 moved the rules into extant/rules/, and moved out from under them
    # the two things more than one rule reads: the SHA-token and merge-claim
    # scanners (extant/commits.py) and the shared probe machinery
    # (extant/probes.py). Anchors follow the code, and several also needed
    # their TEXT rewritten rather than only their path - a rule reads
    # `ctx.repo`, `ctx.run` and `ctx.config` where the shim read `repo`,
    # `_SCOPE` and a module global, and the names it calls across a package
    # boundary lost their underscores when they became sibling calls. A
    # path-only retarget leaves those matching nothing, which --check-only
    # reports as STALE and a campaign reports as a clean result it did not
    # earn. Three anchors in refs.py needed exactly that rename this task, from
    # code that moved in Task 8 and did not move again.
    commits = collect.parent / "extant/commits.py"
    rules = collect.parent / "extant/rules"
    text = collect.parent / "extant/text.py"
    sites = collect.parent / "extant/sites.py"
    return [
        # --- rule logic ------------------------------------------------------
        # Retargeted when ancestry moved from a per-claim merge-base call to a
        # batched rev-list. The old string named a line that no longer exists,
        # so this mutation silently stopped probing anything - reported as a
        # HARNESS FAULT rather than as a pass, which is the only reason it was
        # noticed. Mutations rot alongside the code they point at.
        # Retargeted a second time when claims became self-describing and the
        # ancestry map became keyed by (ref, sha) rather than by sha alone.
        ("merge-claim never fires", rules / "merge.py",
         "        if not merged[key]:\n            findings.append(Finding(",
         "        if False:\n            findings.append(Finding("),
        # Retargeted when ancestry became per-ref: the index is keyed by
        # (repo, ref) now and the prefix lookup moved into reachable_from.
        ("batched ancestry always answers yes", refs,
         "        return any(full.startswith(rev) for full in index.get(rev[:7], ()))",
         "        return True"),
        # The three rules that used to ask about trunk now ask about the
        # measured integration set, so its two failure directions each get a
        # mutation: naming nothing makes them blind, naming everything makes
        # them permissive.
        # Both retargeted when the ref list learned to drop names that do not
        # resolve: the scan moved into an `else` branch and the indentation
        # changed with it. The first anchor still matched by accident, being a
        # substring of the newly indented line, which is exactly the kind of
        # near-miss --check-only exists to stop being lucky about.
        # Retargeted a third time, when the branch scan moved into the shared
        # ref table and this function stopped parsing `for-each-ref` itself.
        ("integration refs collapse to the configured trunk alone", refs,
         "    present = set(ref_table(ctx)[0])",
         "    present = set()"),
        ("any branch counts as an integration branch", refs,
         "    for name in _INTEGRATION_NAMES:\n"
         "        if name in present and name not in refs:\n"
         "            refs.append(name)",
         "    for name in sorted(present):\n"
         "        if name not in refs:\n"
         "            refs.append(name)"),
        ("merge claims stop checking the ref the claim names", rules / "merge.py",
         "            merged[key] = reachable_from(ctx, sha, ref)",
         "            merged[key] = reachable_from(ctx, sha, ctx.config.trunk)"),
        ("a bare word after the merge verb is treated as a branch", rules / "merge.py",
         "            if not quoted:\n"
         "                continue        # a bare word, likelier prose than a ref",
         "            if False:\n"
         "                continue        # a bare word, likelier prose than a ref"),
        # Retargeted when the caches moved onto a RunScope; the cache
        # is the same, the name it is reached through is not.
        ("the ancestry cache stops distinguishing repositories", refs,
         "    key = (str(ctx.repo), ref)\n    if key in ctx.run.ancestors:",
         '    key = ("", ref)\n    if key in ctx.run.ancestors:'),
        ("a branch counts as merged into itself", refs,
         "    return [ref for ref in integration_refs(ctx)\n"
         "            if ref != exclude and reachable_from(ctx, rev, ref)]",
         "    return [ref for ref in integration_refs(ctx)\n"
         "            if reachable_from(ctx, rev, ref)]"),
        # The installer writes its own merge_claim, which OVERRIDES the default,
        # so a collector that supports named refs still ships single-trunk
        # behaviour if this line regresses. That is exactly what happened.
        ("the installer emits a single-trunk merge_claim again",
         detect.parent / "install.py",
         'rf"(?:{alt})\\s+(?:to|into|in|on)\\s+(`[^`\\n]+`|[\\w.\\-/]+)"',
         'rf"(?:{alt})\\s+(?:to|into|in|on)\\s+`?{{trunk}}`?"'),
        # The SAME trap as the line above, sprung a second time. 0.16.1 widened
        # the collector's default so a bare commit is seen at all; this line
        # went on writing the backticked-only form, and the installed config
        # overrides the default - so every freshly installed project kept
        # missing `merged into main at 6ff1f4ac`. Found by a mutation SURVIVOR
        # in the group above, whose test was being written when this surfaced.
        ("the installer demands backticks round the commit again",
         detect.parent / "install.py",
         'rf"\\s+(?:at|in|as)\\s+`?([0-9a-f]{{7,40}})`?(?![0-9a-f])"',
         'rf"\\s+(?:at|in|as)\\s+`([0-9a-f]{{7,40}})`"'),
        ("live-claim checks EVERY entry, not just the newest",
         rules / "live_claim.py",
         '        if kind != "phase" or newest_checked:\n            continue\n'
         "        newest_checked = True\n"
         "        if not ctx.config.live_phrases.search(entry):",
         '        if kind != "phase":\n            continue\n'
         "        if not ctx.config.live_phrases.search(entry):"),
        ("branch rule loses the merge-history rescue", rules / "branch.py",
         "            if branch_exists(ctx, branch) or named_in_merge_history(ctx, branch):",
         "            if branch_exists(ctx, branch):"),
        # Half the ecosystem tags `v1.2.3` and half tags `1.2.3`. Reading the
        # prefix from the repository is what stops a claim written in the other
        # convention reporting a release that shipped.
        # Retargeted when the caches moved onto a RunScope; the cache
        # is the same, the name it is reached through is not.
        ("release claims stop using this repository's tag prefix",
         rules / "release_tag.py",
         "        ctx.run.tag_prefixes[key] = sorted(prefixes)",
         '        ctx.run.tag_prefixes[key] = [""]'),
        # A configured pattern can capture the WHOLE tag name - the installer
        # derives one for repositories tagging `release-1.2.3`. Trying this
        # repository's prefixes first makes that `release-release-1.2.3`.
        ("a captured tag name is not tried literally first", rules / "release_tag.py",
         "    if version in tags:\n        return version",
         "    if False:\n        return version"),
        # A claim names a SERIES more often than a tag: symfony names the 8.0
        # series and the tags are `v8.0.0`, `v8.0.1`.
        ("a claimed version stops matching a tag series", rules / "release_tag.py",
         '        series = sorted(tag for tag in tags if tag.startswith(exact + "."))',
         "        series = []"),
        # The rule's largest measured blind spot: requiring the commit in
        # backticks hid 32 real merge claims in one repository, written as
        # `PR #499 merged into main at 6ff1f4ac`, across 7,489 files.
        ("a merge claim must backtick its commit again", collect.parent / "extant/config.py",
         r'r"(`[^`\n]+`|[\w.\-/]+)\s+at\s+`?([0-9a-f]{7,40})`?(?![0-9a-f])"',
         r'r"(`[^`\n]+`|[\w.\-/]+)\s+at\s+`([0-9a-f]{7,40})`"'),
        # The boundary the closing backtick used to provide. Without it a
        # 46-character hex run matches its first 40.
        ("a longer hex run is truncated into a commit", collect.parent / "extant/config.py",
         r"`?([0-9a-f]{7,40})`?(?![0-9a-f])",
         r"`?([0-9a-f]{7,40})`?"),
        # "No such tag exists" is not a question git can settle - a version in
        # prose can name an npm release, a sub-package or a plugin - so it is
        # opt-in. On by default it was wrong 19 times in 26 across 15 projects
        # that write such claims.
        ("a claimed release is judged local without being told",
         rules / "release_tag.py",
         "            if resolved is None:\n"
         "                if ctx.config.release_claims_are_ours:",
         "            if resolved is None:\n"
         "                if True:"),
        ("the opt-in never fires even when it is set", rules / "release_tag.py",
         "            if resolved is None:\n"
         "                if ctx.config.release_claims_are_ours:",
         "            if resolved is None:\n"
         "                if False:"),
        # Git resolves a bare name by trying `refs/tags/` BEFORE
        # `refs/heads/`. Reading the table heads-first resolves a repository
        # holding a branch and a tag of the same name to a different commit
        # than `rev-parse` does.
        ("a bare ref name resolves heads before tags", refs,
         "    resolved = tags.get(ref) or heads.get(ref)",
         "    resolved = heads.get(ref) or tags.get(ref)"),
        # A cost contract: one ref scan answers what `tag -l`, a second
        # `for-each-ref` and per-ref `rev-parse` each asked. 8 spawns per
        # validate became 6, and 261 ms became 214.
        # The REPLACEMENT was retargeted onto the `_GIT` seam in Task 7, and
        # --check-only could not have caught it: that only verifies anchors.
        # Left naming `_git_soft`, this mutation still died - but of a
        # NameError, because the shim stopped importing that name. A mutation
        # killed by a crash proves the suite notices crashes, not that anything
        # pins the property in its label.
        ("the tag list goes back to its own subprocess", rules / "release_tag.py",
         "    return set(ref_table(ctx)[1])",
         '    return set(ctx.git.soft(ctx.repo, "tag", "-l").split())'),
        ("an annotated tag stops being peeled to its commit", refs,
         "            commit = peeled or obj",
         "            commit = obj"),
        # The tag list is per-CALL. A plain dict that is never reset becomes
        # permanent rather than merely slow, which is the failure `_OWN_REMOTE`
        # already had once: the answer stays whatever the first call saw.
        # REMOVED: "the tag list outlives the call that built it".
        #
        # It survived the full campaign of 2026-08-09, and tracing it showed
        # the mutation is INERT rather than the suite being blind. `validate`
        # saves the cache, clears it, and restores it on exit. Between two
        # calls the restore already returns it to empty, so deleting the clear
        # changes nothing - and mutating the restore instead is equally inert,
        # because the clear then covers it. The property is guaranteed twice
        # and no single-line mutation can observe it.
        #
        # A mutation that cannot change behaviour reports a gap that does not
        # exist, every run, forever. That is the same thing as a NOT APPLIED
        # result and is treated the same way: repaired, not recorded.
        # `tests/test_cache_lifetime.py` pins the behaviour itself instead - a
        # tag created between two calls is seen by the second.
        # A cost contract: reverting it gives identical findings and a tool
        # that got slower between releases. 200 release claims took 11.6
        # seconds without it and 1.2 with it.
        # REMOVED: "integration refs are rescanned once per claim".
        #
        # Also survived that campaign, and also for want of anything to
        # observe. It memoises over an ALREADY-cached ref table, so what it
        # saves is a handful of dict operations. Three closing attempts
        # failed: counting `ref_table` calls (cached underneath, built once
        # either way), counting `resolve_ref` calls (the merge-claim rule
        # resolves the named ref per claim for its own legitimate reasons, so
        # a four-claim document resolves the trunk four times with or without
        # this cache - that assertion failed on UNMUTATED code), and asserting
        # the cache is populated (it is written either way; only the read is
        # skipped).
        #
        # The saved work is indistinguishable from work other call sites do
        # anyway. Kept in the code because it costs nothing; dropped from the
        # campaign because a permanent false gap costs attention.
        # An integration ref that does not resolve cannot settle anything, and
        # returning it anyway made every caller answer "no" to a question it
        # never asked. symfony has no main and no master.
        # Retargeted when the list learned to memoise itself and the filter
        # moved into the assignment.
        # Retargeted when the caches moved onto a RunScope; the cache
        # is the same, the name it is reached through is not.
        ("integration refs include ones that do not exist", refs,
         "    ctx.run.integration[key] = [ref for ref in refs\n"
         "                                if resolve_ref(ctx, ref) is not None]",
         "    ctx.run.integration[key] = refs"),
        # `rev: ''` is pre-commit's own placeholder and `rev: 'v1.2.3'` is the
        # same pin as the bare spelling. 69 bare, 4 quoted, 2 empty across 30
        # repositories.
        ("a pin is read with its yaml quotes attached", rules / "pinned_ref.py",
         "            ref = match.group(1).strip(_PIN_QUOTES)\n"
         "            if ref:",
         "            ref = match.group(1)\n"
         "            if True:"),
        # Retargeted when the tag rule stopped asking about trunk and started
        # asking whether the tag is on ANY integration branch.
        # Retargeted a second time when the rule started asking about the tag
        # it RESOLVED the claim to rather than the string the author wrote.
        ("release-tag ancestry check dropped", rules / "release_tag.py",
         '            if not integrated_by(ctx, f"refs/tags/{resolved}"):',
         "            if False:"),
        ("path/branch guard removed (a file becomes a phantom branch)",
         rules / "branch.py",
         "            if looks_like_a_path(ctx, branch):\n"
         "                continue  # a file reference caught by a path-shaped pattern",
         "            if False:\n"
         "                continue  # a file reference caught by a path-shaped pattern"),
        ("path guard over-broad: skips anything containing a dot", sites,
         "    return bool(_FILEISH.search(token)) or (ctx.repo / token).exists()",
         '    return "." in token or (ctx.repo / token).exists()'),
        ("live-claim loses the path guard", rules / "live_claim.py",
         "            if looks_like_a_path(ctx, branch):\n                continue\n"
         "            exists = branch_exists(ctx, branch)",
         "            if False:\n                continue\n"
         "            exists = branch_exists(ctx, branch)"),

        # --- markdown --------------------------------------------------------
        ("external links get checked (needs the network)", rules / "md_link.py",
         '            if EXTERNAL.match(raw) or raw.startswith("#"):\n'
         '                continue\n            target = raw.split("#", 1)[0]',
         '            if raw.startswith("#"):\n'
         '                continue\n            target = raw.split("#", 1)[0]'),
        # Retargeted when dead-md-anchor grew to check fragments on OTHER
        # files: the fragment is now split off with partition rather than
        # sliced, and slugging moved behind _heading_text.
        ("anchors compared case-sensitively", rules / "md_anchor.py",
         "            fragment = fragment.lower()",
         "            fragment = fragment"),
        # Retargeted when `_slug_keeping_edges` was added for emoji headings:
        # it strips punctuation the same way, so the old one-line anchor
        # matched twice and probed neither reliably. The return line
        # disambiguates - only `_slug` trims the edges.
        ("slug keeps punctuation", text,
         '    text = re.sub(r"[^\\w\\s-]", "", _heading_text(title))\n'
         '    return re.sub(r"\\s", "-", text).strip("-")',
         "    text = _heading_text(title)\n"
         '    return re.sub(r"\\s", "-", text).strip("-")'),
        # A heading opening with an emoji anchors with a leading dash on
        # GitHub, because the emoji is dropped and the space after it still
        # becomes one. Trimming both spellings reported 58 working links as
        # dead across the held-out corpus.
        ("the untrimmed slug spelling is lost", text,
         '    return untrimmed if untrimmed != untrimmed.strip("-") else ""',
         '    return ""'),
        # The other half of the same function, and the reason it is written
        # this way. Returning the trimmed spelling as well duplicates `_slug`
        # and masks it - "slug keeps punctuation" SURVIVED while it did.
        ("the untrimmed slug also returns the trimmed one, masking _slug",
         text,
         '    return untrimmed if untrimmed != untrimmed.strip("-") else ""',
         "    return untrimmed"),
        ("cross-file anchors no longer checked", rules / "md_anchor.py",
         "            offered = _target_anchors(ctx, resolved)",
         "            offered = None"),
        ("rename chains no longer followed", refs,
         "    while current in mapping:",
         "    if current in mapping:"),
        # Retargeted when git calls moved behind the `_GIT` seam in Task 7. The
        # command is the same command; the name it is reached through is not.
        ("rename map narrowed by a pathspec again (a shipped bug)", refs,
         '        out = ctx.git.run(ctx.repo, "log", "--diff-filter=R", "--name-status",\n'
         '                          "--format=", "-n", "200")',
         '        out = ctx.git.run(ctx.repo, "log", "--diff-filter=R", "--name-status",\n'
         '                          "--format=", "-n", "200", "--", "nonexistent-path")'),
        ("claim rules stop ignoring fenced code", collect,
         "def _prose(text: str) -> str:",
         "def _prose(text: str) -> str:\n    return text"),
        ("case check accepts any spelling", sites,
         "    return (True, None) if actual == normalised else (False, actual)",
         "    return True, None"),

        # --- scoping / registry ----------------------------------------------
        # Indentation is written out in full rather than trimmed. A shorter
        # string is a SUBSTRING of the real line when the block moves inward,
        # so it keeps matching and silently mutates something adjacent. That
        # happened here when validate() gained a try/finally: one of these two
        # stopped matching outright and the other kept matching by accident.
        # Retargeted a THIRD time, when both guards moved out of `validate` into
        # `_rule_applies` so the sweep's per-rule denominator could ask the same
        # question the findings loop asks. `continue` became `return False` and
        # the body dedented by eight spaces, so both anchors matched nothing.
        # Neither test noticed, because a mutation that matches nothing probes
        # nothing and the suite stays green; `--check-only` in CI is what caught
        # it. Third time for this pair, which is the argument for that mode
        # existing at all.
        ("archive exemption ignored", collect,
         "    if (in_archive or not has_entries) and not rule.in_archive:\n"
         "        return False",
         "    if False:\n        return False"),
        # Anchored on the CONDITION alone. It used to include the dispatch line
        # that followed, and the rst work inserted a format check between the
        # two, so the pair stopped matching while the behaviour it probes was
        # untouched. A mutation should name the smallest thing it is about.
        ("has_entries ignored (entry rules run on extra docs)", collect,
         "    if (in_archive or not has_entries) and not rule.in_archive:\n"
         "        return False",
         "    if in_archive and not rule.in_archive:\n"
         "        return False"),

        # --- denominator ------------------------------------------------------
        # Retargeted when the denominator stopped being one entry in a central
        # dict and became the rule module's own `examined`, computed over the
        # same population its `check` reads.
        ("denominator lies: dead-sha always 1", rules / "sha.py",
         "    return len(find_sha_candidates(text)) + len(find_bare_sha_candidates(text))",
         "    return 1"),
        ("denominator drops a rule entirely", collect,
         '        "dead-md-anchor": _rule_md_anchor.examined(_ctx(repo), text),',
         ""),

        # --- selftest ---------------------------------------------------------
        ("selftest reports FIRED unconditionally", collect,
         "        if findings:\n            fired += 1",
         "        if True:\n            fired += 1"),
        ("every probe returns None", collect,
         "        probed = rule.probe(repo, text)  # type: ignore[operator]",
         "        probed = None"),

        # --- output formats ---------------------------------------------------
        ("github property escaping removed", collect,
         '        out = out.replace(":", "%3A").replace(",", "%2C")',
         "        pass"),
        ("github message escaping removed", collect,
         '    out = value.replace("%", "%25").replace("\\r", "%0D").replace("\\n", "%0A")',
         "    out = value"),
        # Retargeted when --suggest-fixes made stdout a patch channel too, so
        # the condition gained a second clause. Caught by --check-only at the
        # commit that moved it, which is the whole reason that mode exists.
        ("sarif diagnostics leak onto stdout", collect,
         '        stream = (sys.stderr if (args.format == "sarif" or args.suggest_fixes)\n'
         "                  else sys.stdout)",
         "        stream = sys.stdout"),
        ("suggested patch shares stdout with the findings", collect,
         '        stream = (sys.stderr if (args.format == "sarif" or args.suggest_fixes)',
         '        stream = (sys.stderr if (args.format == "sarif" or False)'),
        ("fingerprint folds in the line number", collect,
         '                "statusClaim/v1": _fingerprint(\n'
         "                    item.path, item.finding.kind, item.finding.detail),",
         '                "statusClaim/v1": _fingerprint(\n'
         "                    item.path, item.finding.kind,\n"
         '                    f"{item.finding.detail}:{item.finding.line}"),'),
        ("sarif drops partialFingerprints", collect,
         '            "partialFingerprints": {',
         '            "_dropped": {'),
        # Retargeted when the region gained a snippet and columns, which moved
        # its construction out of the literal and above the result dict.
        ("sarif region loses startLine", collect,
         '        region: dict[str, object] = {"startLine": max(1, item.finding.line)}',
         '        region: dict[str, object] = {}'),
        # The severity mapping is the reason `Located.gating` exists. Publishing
        # every finding as an error contradicted a sweep's own exit code.
        ("sarif calls every finding an error again", collect,
         '            "level": "error" if item.gating else "note",',
         '            "level": "error",'),
        # The denominator, which no machine consumer could see before.
        ("sarif stops reporting what was examined", collect,
         '    if examined is not None:',
         '    if False:'),

        # --- shas ----------------------------------------------------------
        # "secret scan misses openai keys" lived here until 0.14.0 removed the
        # rule. Deleted rather than retargeted: there is no code left for it to
        # name, and a mutation kept alive by pointing it at something else
        # would be testing a different thing under an old label.
        # Retargeted when the SHA shape tests moved to extant/commits.py, which
        # is where both rules that read them can reach without reaching through
        # each other. The names lost their underscore in the same move: a rule
        # module calling them is a sibling call.
        ("bare sha shape drops the letter requirement", commits,
         "def looks_like_bare_sha(token: str) -> bool:",
         "def looks_like_bare_sha(token: str) -> bool:\n"
         "    return bool(SHA_SHAPE.match(token))"),

        # --- config errors -----------------------------------------------------
        ("every TOML error blamed on regex quoting again", collect.parent / "extant/config.py",
         "    hint = next((h for needle, h in _HINTS if needle in text), _GENERIC_HINT)",
         "    hint = _ESCAPE_HINT"),

        # --- consistency (repository-scoped) -------------------------------------
        ("consistency never reports a disagreement",
         rules / "consistency.py",
         "        if len(seen) > 1:",
         "        if False:"),
        ("consistency reports agreement AS disagreement",
         rules / "consistency.py",
         "        if len(seen) > 1:",
         "        if len(seen) >= 1:"),
        ("consistency ignores a missing file",
         rules / "consistency.py",
         "            if not target.is_file():\n"
         "                findings.append(Finding(\n"
         "                    1, \"inconsistent-artifact\",\n"
         "                    f\"consistency check `{name}` reads `{relative}`, \"\n"
         "                    f\"which does not exist\",\n"
         "                ))\n"
         "                continue",
         "            if not target.is_file():\n                continue"),
        ("consistency ignores a pattern that matches nothing",
         rules / "consistency.py",
         "            if match is None:",
         "            if False and match is None:"),
        ("consistency reads the INSTALLED config, not the target repo's",
         rules / "consistency.py",
         "        consistency = _consistency_for(ctx)",
         "        consistency = ctx.config.consistency"),
        # Two routes to one file. The string guard at config load cannot see a
        # symlink or a case variant, so this is the check that asks the
        # filesystem. Both directions are mutated: blind, a self-comparing
        # block passes forever; universally on, every honest block is reported.
        ("consistency stops noticing two routes to one file",
         rules / "consistency.py",
         "        if len(present) >= 2 and len({_file_identity(repo / rel)\n"
         "                                      for rel in present}) < 2:",
         "        if False:"),
        ("every consistency block is called self-comparing",
         rules / "consistency.py",
         "        if len(present) >= 2 and len({_file_identity(repo / rel)\n"
         "                                      for rel in present}) < 2:",
         "        if len(present) >= 2:"),
        # The pattern bound. NOT mutated by removing the bound itself: that
        # would leave a catastrophic backtrack running unbounded and hang the
        # campaign rather than being killed by it. A mutation has to fail fast
        # to be a mutation. These two change the branches around it instead.
        ("a bounded consistency search stops reporting its timeout",
         rules / "consistency.py",
         '                    f"consistency check `{name}` gave up on `{relative}` after "',
         '                    f"consistency check `{name}` finished `{relative}` after "'),
        ("the consistency bound becomes always-on rather than opt-in",
         rules / "consistency.py",
         "    if timeout is None:\n        return pattern.search(content)",
         "    if False:\n        return pattern.search(content)"),

        # --- claims removed while still false --------------------------------
        # The haystack is PROSE, not raw text. Built from raw text, a claim
        # moved into a code fence stays findable and this mode goes as blind to
        # it as every claim rule already is.
        ("the deletion haystack stops blanking fenced code", collect,
         "            parts.append(_prose(handle.read()))",
         "            parts.append(handle.read())"),
        # And the other direction. `_strip_code` also blanks INLINE backticks,
        # which is where a claim is normally written - so this would empty the
        # haystack and report every claim in the document as deleted.
        ("the deletion haystack also blanks inline code", collect,
         "            parts.append(_prose(handle.read()))",
         "            parts.append(_strip_code(handle.read()))"),
        ("deletion checks only the primary document, not the archive", collect,
         "    return [d for d in (CONFIG.primary_doc, CONFIG.archive_doc,\n"
         "                        *CONFIG.extra_docs) if d]",
         "    return [d for d in (CONFIG.primary_doc,) if d]"),
        ("deletion re-reads documents that did not change", collect,
         "    for relative in _changed_between(repo, ref, documents):",
         "    for relative in documents:"),
        # The subject a claim is about. A rule that stops recording one is
        # invisible to `--deleted-since`, and the mode reports the skip rather
        # than hiding it - so the loss is quiet rather than silent, which is
        # still not good enough to leave unpinned.
        ("a rule stops recording which token its claim is about",
         rules / "md_link.py",
         '            findings.append(Finding(number, "dead-md-link", detail,\n'
         "                                    subject=target))",
         '            findings.append(Finding(number, "dead-md-link", detail))'),
        # SARIF's contract is that stdout is one valid document, always. Zero
        # bytes fails a CI upload rather than reading as "no results", so a
        # clean run looks exactly like a broken one.
        ("the deletion mode emits nothing when it has nothing to report", collect,
         "    else:\n"
         "        # ALWAYS, even with nothing to report.",
         "    elif gone:\n"
         "        # ALWAYS, even with nothing to report."),
        ("the deletion mode starts gating", collect,
         '              "why it never fails a run.", file=out)\n    return 0',
         '              "why it never fails a run.", file=out)\n'
         "    return 1 if gone else 0"),

        # --- search --------------------------------------------------------------
        ("search only looks at the live document", collect,
         "    for relative in (PRIMARY_DOC, ARCHIVE_DOC):\n"
         "        path = repo / relative\n"
         "        if not path.is_file():\n"
         "            continue\n"
         "        with open(path, encoding=\"utf-8\", newline=\"\") as fh:",
         "    for relative in (PRIMARY_DOC,):\n"
         "        path = repo / relative\n"
         "        if not path.is_file():\n"
         "            continue\n"
         "        with open(path, encoding=\"utf-8\", newline=\"\") as fh:"),
        ("search becomes case-sensitive", collect,
         "    needle = query.lower()",
         "    needle = query"),
        ("search matches every entry regardless of content", collect,
         '            if kind != "phase" or needle not in entry.lower():',
         '            if kind != "phase":'),

        # --- suggested fixes ------------------------------------------------------
        ("suggest-fixes offers a guess for a merely missing file", collect,
         "        moved = _renamed_to(repo, target)\n"
         "        if moved:\n"
         "            replacements.append((target, moved))",
         "        moved = _renamed_to(repo, target) or target + \".guess\"\n"
         "        if moved:\n"
         "            replacements.append((target, moved))"),
        ("suggest-fixes rewrites prose as well as references", collect,
         '        updated = updated.replace(f"]({old})", f"]({new})")\n'
         '        updated = updated.replace(f"`{old}`", f"`{new}`")',
         "        updated = updated.replace(old, new)"),
        ("suggest-fixes writes the file instead of emitting a patch", collect,
         "    if not replacements:\n        return \"\"",
         "    if not replacements:\n        return \"\"\n"
         "    (base / 'SIDE_EFFECT.txt').write_text('written', encoding='utf-8')"),

        # --- config discovery -----------------------------------------------------
        ("config is no longer searched for upward", detect.parent / "payload/extant/config.py",
         "    for directory in (current, *current.parents):",
         "    for directory in (current,):"),
        ("config search runs past the repository root", detect.parent / "payload/extant/config.py",
         '        if (directory / ".git").exists():\n            return None',
         '        if False:\n            return None'),
        # The 3.9/3.10 fallback. Both mutations are invisible on a modern
        # interpreter, which is the whole difficulty: the tests block the module
        # at import in a subprocess, so they fail here and would not otherwise.
        ("no parser is a hard import error again, not a fallback",
         detect.parent / "payload/extant/config.py",
         "        tomllib = None                                   # type: ignore[assignment]",
         "        raise"),
        ("a config file with no parser fails without saying how to fix it",
         detect.parent / "payload/extant/config.py",
         "    if tomllib is None:\n        raise ValueError(_NO_PARSER.format(path=path))",
         "    if False:\n        raise ValueError(_NO_PARSER.format(path=path))"),

        # --- install snippets ----------------------------------------------------
        # This rule is the newest and had no mutations at all, which is the state
        # every gap starts in. Its two false-positive guards matter more than the
        # positive case: a rule that flags a correct line is how a validator earns
        # a reputation for noise, and both guards are invisible to a test that
        # only checks that a dead pin is reported.
        # Disabled by emptying the loop rather than by blanking the message: the
        # first attempt replaced the text with `"" or f"..."`, which Python
        # evaluates straight back to the f-string. A mutation that changes
        # nothing SURVIVES every time and reads as a gap in the suite, which is
        # the harness lying rather than the tests failing. This shape also
        # leaves the DENOMINATOR at 1 while findings drop to 0, which is the
        # exact "examined but never reports" defect the project cares about.
        ("pinned-ref never fires", rules / "pinned_ref.py",
         "    for number, ref in _pinned_refs(ctx, text):",
         "    for number, ref in []:"),
        ("pinned-ref ignores the governing repo (flags third-party pins)",
         rules / "pinned_ref.py",
         "        if match and governing == own:",
         "        if match:"),
        ("pinned-ref stops normalising remotes (SSH never matches HTTPS)",
         rules / "pinned_ref.py",
         '    parts = [p for p in url.replace(":", "/").split("/") if p]',
         '    parts = [p for p in url.split("/") if p]'),
        ("pinned-ref keeps the .git suffix, so no remote ever matches",
         rules / "pinned_ref.py",
         '    if url.endswith(".git"):',
         "    if False:"),
        # NOT a no-origin mutation. Removing `if own is None: return []` changes
        # nothing, because `governing == None` never matches and no pin is
        # collected either way - the guard is a short-circuit, not a behaviour.
        # A mutation there survives forever and blames the tests for it. This
        # probes the reported line number instead, which is what a reader
        # actually navigates by.
        ("pinned-ref reports the wrong line number", rules / "pinned_ref.py",
         "    governing: str | None = None\n"
         "    for number, line in enumerate(text.splitlines(), start=1):",
         "    governing: str | None = None\n"
         "    for number, line in enumerate(text.splitlines(), start=2):"),

        # --- the installer and its presets ---------------------------------------
        # install.py had no mutations either, and it is where the 0.6.1 bug lived:
        # the preset that exists for projects WITHOUT a status document could not
        # be used on one. Every guard below was added because its absence shipped.
        ("preset document is not consulted when detection finds nothing",
         detect.parent / "install.py",
         "    if preset_doc and (repo / preset_doc).is_file():",
         "    if False and preset_doc and (repo / preset_doc).is_file():"),
        ("preset names extra documents the project does not have",
         detect.parent / "install.py",
         '    extras = [e for e in preset.get("extra_docs", []) if (repo / str(e)).is_file()]',
         '    extras = [str(e) for e in preset.get("extra_docs", [])]'),
        # Retargeted at the WHOLE guard. It used to replace only the
        # `is_file()` half, which cannot change behaviour on its own:
        # `_pattern_matches` returns False for a file it cannot read, so the
        # pattern half independently rejects an absent file. The mutation was
        # therefore unkillable by construction and survived every campaign,
        # reading as a permanent test gap - the same two-mechanisms-masking
        # shape that hid dead code in the tag-prefix logic.
        # Retargeted a SECOND time, when the dict comprehension became an
        # explicit loop so each source could be LOCATED before being read. The
        # guard is now the `if problems:` branch, and neutralising it emits
        # every check regardless of whether its files were found or matched.
        # Same lesson as the pair in the scoping section, which has now rotted
        # three times: a mutation names a line, and refactoring moves the line
        # without moving the mutation. `--check-only` is the only thing that
        # notices, which is why it runs in CI rather than in the campaign.
        ("preset emits a consistency check whose files are absent",
         detect.parent / "install.py",
         "            if problems:\n"
         "                skipped_why[check] = \", \".join(problems)",
         "            if False:\n"
         "                skipped_why[check] = \", \".join(problems)"),
        ("preset stops switching off the features it disables",
         detect.parent / "install.py",
         '    for key in preset.get("disable", []):          # type: ignore[union-attr]',
         "    for key in []:"),

        # --- the baseline -------------------------------------------------------
        # A ratchet is only as good as the things that stop it loosening, so
        # every mutation here breaks a CONSTRAINT rather than the suppression.
        # Suppression working is easy; suppression that cannot quietly grow to
        # cover everything is the whole design.
        ("baseline suppresses by kind, so every future finding is forgiven", collect,
         "                if fingerprint in baselined:",
         "                if any(e[\"kind\"] == finding.kind for e in baselined.values()):"),
        ("baseline stops stating how much it is hiding", collect,
         '            diag(f"{len(located)} new finding(s), {suppressed} suppressed by "',
         '            diag("" or f"{len(located)} new finding(s), {suppressed} hidden by "'),
        ("a missing baseline becomes an empty one", collect,
         "    if not path.is_file():\n        raise ValueError(",
         "    if not path.is_file():\n        return {}\n    if False:\n        raise ValueError("),
        ("re-recording honours the active baseline and shrinks the file", collect,
         "        if (args.baseline or args.baseline_check) and not args.write_baseline:",
         "        if args.baseline or args.baseline_check:"),
        ("baseline-check stops reporting entries that no longer occur", collect,
         "            stale = [entry for fingerprint, entry in sorted(baselined.items())\n"
         "                     if fingerprint not in matched]",
         "            stale = []"),

        # --- the cross-platform agent skill --------------------------------------
        # The newest code, which is where every gap starts. Setup writes agent
        # instructions to two paths from ONE set of observations, so the failure
        # that matters is not either file going missing: it is the two of them
        # describing different documents. This project shipping a document that
        # contradicts another document, via its own installer, would be the exact
        # thing it exists to catch.
        ("the cross-platform skill is never written",
         detect.parent / "install.py",
         "    skill_path = repo / AGENT_SKILL_DEST",
         "    skill_path = repo / (AGENT_SKILL_DEST + '.disabled')"),
        # Renders the Claude template to the standard path. Both files still
        # appear, both name the right document, and the only thing wrong is that
        # a non-Claude agent gets a file whose frontmatter it cannot use - which
        # is invisible to any check that merely counts files.
        ("the agent skill is rendered from the Claude template",
         detect.parent / "install.py",
         "    skill_text, skill_notes = render_command(obs, repo.name, AGENT_SKILL_TEMPLATE)",
         "    skill_text, skill_notes = render_command(obs, repo.name, COMMAND_TEMPLATE)"),
        ("render_command ignores the template it is given",
         detect.parent / "install.py",
         "    text = (SKILL_ROOT / template).read_text(encoding=\"utf-8\")",
         "    text = (SKILL_ROOT / COMMAND_TEMPLATE).read_text(encoding=\"utf-8\")"),
        ("the skill is copied verbatim, so placeholders survive",
         detect.parent / "install.py",
         "    skill_text, skill_notes = render_command(obs, repo.name, AGENT_SKILL_TEMPLATE)",
         "    skill_text, skill_notes = (SKILL_ROOT / AGENT_SKILL_TEMPLATE).read_text("
         "encoding=\"utf-8\"), []"),
        ("an existing hand-edited skill is silently overwritten",
         detect.parent / "install.py",
         "    if skill_path.exists() and not args.force:",
         "    if False:"),

        # --- Git LFS storage -----------------------------------------------
        # This rule talks to git through pipes, and both of its plumbing bugs
        # were invisible in the result: the survey reported 1 of 4 governed
        # files and still found the single real problem, so it looked perfect.
        ("the raw-blob check never fires", collect,
         "        if size is None or sha in pointers:", "        if True:"),
        ("check-attr loses -z, so git quotes any path with a space", collect,
         '["git", "check-attr", "-z", "--stdin", "filter"], cwd=repo,',
         '["git", "check-attr", "--stdin", "filter"], cwd=repo,'),
        ("the NUL join reverts to newlines (the Windows CR bug)", collect,
         'payload = ("\\0".join(blobs) + "\\0").encode("utf-8")',
         'payload = ("\\n".join(blobs) + "\\n").encode("utf-8")'),
        ("the LFS survey reads the index instead of the committed tree", collect,
         '            ["git", "ls-tree", "-r", "-z", "HEAD"], cwd=repo,',
         '            ["git", "ls-files", "-z"], cwd=repo,'),
        ("the LFS gate stops reading .gitattributes", collect,
         '    return any("filter=lfs" in line and not line.lstrip().startswith("#")\n'
         "               for line in text.splitlines())",
         "    return False"),
        # NOT a mutation on the size shortcut. Reading every governed blob
        # instead of only the small ones changes cost, never behaviour, so it
        # survives every time and reads as a gap the tests do not have.

        # --- the game-engine presets ---------------------------------------
        # Raw strings: these anchors contain regex escapes, and an unraw "\d"
        # is a SyntaxWarning today and an error in a future Python. There is a
        # lint in this repository for exactly that.
        ("godot version check moves to the README",
         detect.parent / "install.py",
         r'                "doc/setup_instructions.md": r"Godot version is[^\d]*(\d+\.\d+)",',
         r'                "README.md": r"Godot version is[^\d]*(\d+\.\d+)",'),
        ("unity badge pattern loses the build suffix",
         detect.parent / "install.py",
         r'                "README.md": r"Unity%20Version:-([\d.]+f\d+)",',
         r'                "README.md": r"Unity%20Version:-(\d+\.\d+)",'),

        # --- detect.py ----------------------------------------------------------
        ("find_documents returns only the first match", detect,
         "    return found",
         "    return found[:1]"),
        ("trunk detection ignores origin/HEAD", detect,
         '    head = _git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD").strip()',
         '    head = ""'),
        # Tag shape is MEASURED, and both directions matter. Ignoring the repo's
        # real prefixes leaves `release-1.2.3` unmatched, so the rule examines
        # nothing on a whole class of project; widening without evidence loosens
        # the pattern for everyone, which is where false positives come from.
        ("release-tag shape ignores the prefixes this repo actually uses", detect,
         '    extra = sorted(p for p in prefixes if p not in ("", "v"))',
         "    extra = []"),
        ("release-tag shape widens without evidence", detect,
         '    extra = sorted(p for p in prefixes if p not in ("", "v"))',
         '    extra = sorted({*prefixes, "release-"} - {"", "v"})'),

        # --- the whole-repo sweep -------------------------------------------
        # The first mutation here is the one this group exists for. Reading the
        # INDEX instead of HEAD's tree is a bug this project has now shipped
        # twice: once in `raw-lfs-blob`, and then again in `tracked_markdown`
        # after the first was found, fixed and written up. It is worth pinning
        # in both places precisely because knowing about it was not enough to
        # stop it recurring.
        #
        # Its failure mode is the worst one available. An incomplete checkout -
        # sparse, partial, or a Windows tree that hit MAX_PATH - leaves the
        # index empty while HEAD's tree is full, so the sweep reports a clean
        # repository having examined nothing. Measured on a helm clone: 0 files
        # swept against 96 in the tree, exit 0, no diagnostic.
        # Retargeted onto the `_GIT` seam; see the note at the rename map above.
        ("the sweep reads the index instead of the committed tree", refs,
         '    out = ctx.git.run(ctx.repo, "ls-tree", "-r", "-z", "--name-only", "HEAD")',
         '    out = ctx.git.run(ctx.repo, "ls-files", "-z")'),
        ("the sweep forgets every format except .md", refs,
         '                  if p.strip() and p.rsplit(".", 1)[-1] in ("md", "markdown", "mdx", "rst"))',
         '                  if p.strip() and p.rsplit(".", 1)[-1] in ("md",))'),
        # Both directions of the vetted/unvetted split, because it is the whole
        # design of the mode and each way of breaking it is silent in its own
        # way. Gating on everything turns 18 measured false positives on this
        # repository into build failures; gating on nothing makes `--sweep`
        # incapable of ever failing, which reads identically to a clean run.
        ("the sweep gates on unreviewed documents too", collect,
         '    return 1 if results["vetted"] else 0',
         '    return 1 if (results["vetted"] or results["unvetted"]) else 0'),
        ("the sweep gates on nothing at all", collect,
         '    return 1 if results["vetted"] else 0',
         "    return 0"),
        ("everything is vetted, so nothing is surveyed separately", collect,
         "    vetted = [p for p in paths if p in normalised]\n"
         "    return vetted, [p for p in paths if p not in normalised]",
         "    return list(paths), []"),
        # A file that could not be read is not a file with no findings. This
        # drops it on the floor exactly the way a bare `continue` would, which
        # is how the sweep would quietly under-report on any repository holding
        # a latin-1 document.
        ("unreadable files are skipped silently rather than counted", collect,
         '                unreadable.append(f"{relative} ({exc.__class__.__name__})")',
         "                pass"),
        ("the sweep denominator counts only what it gated on", collect,
         '    print(f"\\nswept {len(paths)} markdown file(s): "',
         '    print(f"\\nswept {len(vetted)} markdown file(s): "'),
        # An empty repository must SAY it swept nothing. Returning 0 without the
        # diagnostic is the project's signature failure: the reassuring silence
        # of a run that examined zero files.
        ("a repository with no markdown reports nothing at all", collect,
         '        print("swept 0 markdown files: git tracks none in this repository",\n'
         "              file=sys.stderr)",
         "        pass"),

        # --- exclude_paths ---------------------------------------------------
        # The one setting that can make a repository look clean by not looking
        # at it, so its guards get more mutations than its size suggests. A
        # skip-list fails silently in BOTH directions and this project has
        # already shipped one whose defaults excluded every file it was meant
        # to scan.
        ("a star crosses a separator, so docs/* takes the whole tree", collect,
         '            out.append("[^/]*")',
         '            out.append(".*")'),
        ("a bare pattern anchors at the root instead of any segment", collect,
         '        source = rf"^(?:.*/)?{core}(?:/.*)?$"',
         '        source = rf"^{core}(?:/.*)?$"'),
        ("a bare pattern matches half a segment", collect,
         '        source = rf"^(?:.*/)?{core}(?:/.*)?$"',
         '        source = rf".*{core}.*"'),
        ("an unusable pattern compiles to one that matches everything",
         collect,
         '    if not pattern or pattern.startswith("#"):\n        return None',
         '    if False:\n        return None'),
        ("a path is counted against every pattern it matches", collect,
         "                hit = pattern\n                break",
         "                hit = pattern"),
        ("the per-pattern counts stop being reported", collect,
         "        for pattern, count in sorted(excluded_counts.items()):",
         "        for pattern, count in []:"),
        ("a pattern that matched nothing is no longer named", collect,
         "        idle = sorted(p for p, n in excluded_counts.items() if not n)",
         "        idle = []"),
        ("excluding a configured document stops being refused", collect,
         "        conflicting = sorted((configured & present) - kept - {\"\"})",
         "        conflicting = []"),
        ("the conflict check keys on configured-but-missing again", collect,
         "        conflicting = sorted((configured & present) - kept - {\"\"})",
         "        conflicting = sorted(configured - kept - {\"\"})"),

        # --- generated sites and anchor namespaces ---------------------------
        # Detection decides whether a route-shaped link is a dead file or a page
        # a generator will build, and being wrong in either direction is
        # expensive. Blind, withastro/starlight reported 235 of its own working
        # links as dead. Universally on, every genuinely dead link in a plain
        # repository stops being reported.
        # Retargeted when detection stopped answering yes-or-no and began
        # recording WHICH top-level directories a generator governs. A
        # monorepo builds a site from `docs/` and still keeps ordinary
        # READMEs in `packages/`; suppressing routes across both silenced six
        # real defects.
        ("site detection goes blind, so routes are dead files again", sites,
         "            declared = any((directory / name).is_file()\n"
         "                           for name in _SITE_CONFIGS)",
         "            declared = False"),
        ("every repository is treated as a generated site", sites,
         "            declared = any((directory / name).is_file()\n"
         "                           for name in _SITE_CONFIGS)",
         "            declared = True"),
        # The root-only search is a shipped bug, not a hypothetical. jekyll/jekyll
        # keeps its own site under `docs/` with `docs/_config.yml`, and a search
        # that looked only at the root reported 138 of its routes as dead.
        # Retargeted twice now, both times because the tuple gained a name a
        # held-out repository declared its site in: `docs-website` from
        # haystack, `documentation` from svelte, `fern` from Skyvern.
        ("generator config is looked for at the root only", sites,
         '_SITE_DIRS = ("", "docs", "site", "www", "website", "docs-website",\n'
         '              "documentation", "fern")',
         '_SITE_DIRS = ("",)'),
        # Retargeted when the tuple gained docsify and went multi-line. The old
        # anchor named a single-line form that no longer exists, and
        # --check-only caught it at the commit that moved it - which is the
        # whole reason that mode is in CI rather than only in the campaign.
        ("a generator declared inside another file is missed", sites,
         '    ("mix.exs", "ex_doc"),',
         '    ("mix.exs", "never-matches-anything"),'),
        # The marker search walks _SITE_DIRS now, because docsify keeps its
        # index.html under docs/. Root-only was the shipped bug for jekyll,
        # whose _config.yml sits there too.
        # Relabelled, not just retargeted. The marker search used to be its
        # own loop over the directory list, so "root only" was separable from
        # the config search; both now share one walk, and the thing this can
        # still probe alone is whether markers are consulted at all.
        ("markers inside a file stop being consulted", sites,
         "                for name, marker in _SITE_MARKERS_IN_FILE:",
         "                for name, marker in ():"),
        # A generator declared nowhere but in its own filename convention.
        # svelte's pages are built by svelte.dev, so no config exists in the
        # repository at all and 64 of its own `/docs/svelte` links were
        # judged as files.
        ("a numbered documentation tree stops declaring a site", sites,
         "        scopes |= _numbered_docs_scopes(ctx)",
         "        scopes |= set()"),
        # aider keeps a Jekyll site at `aider/website/_config.yml`: a package
        # directory, and the site inside it. Searching only `website/` found
        # nothing, so the repository was judged plain and 29 of its own asset
        # links were reported dead.
        ("a site one directory deeper is never found", sites,
         '    for name in _SITE_DIRS:\n'
         '        if name:\n'
         '            dirs.extend(ctx.repo.glob(f"*/{name}"))',
         "    for name in ():\n"
         "        if name:\n"
         '            dirs.extend(ctx.repo.glob(f"*/{name}"))'),
        # The other half: the search is bounded to one extra level. Unbounded,
        # it scans every directory in the repository to answer a question asked
        # on every run, and a vendored copy four levels down silences the lot.
        ("the deeper search stops being bounded to one level", sites,
         '            dirs.extend(ctx.repo.glob(f"*/{name}"))',
         '            dirs.extend(ctx.repo.glob(f"**/{name}"))'),
        # Mintlify serves .mdx by route from one declaration. humanlayer
        # reported 5 of its own `/core/require-approval` links dead without it.
        # Anchored on the entry alone rather than on it being LAST in the
        # tuple, which is what went stale when `fern.config.json` was added
        # after it.
        ("mint.json stops counting as a generator", sites,
         '    "mint.json",\n',
         '    "mint.never-matches.json",\n'),
        ("fern.config.json stops counting as a generator", sites,
         '    "fern.config.json",\n',
         '    "fern.never-matches.json",\n'),
        # A `.html` target is a rendered page. Measured at 407 links across 20
        # repositories in two corpora, with ZERO resolving to a checked-in
        # file. Re-gating it on generator detection is what made rails report
        # 276 of its own guide links dead.
        ("a .html target is judged again unless a generator is declared",
         rules / "md_link.py",
         '            if target.endswith(".html"):\n                continue',
         "            if False:\n                continue"),
        # Next.js routes by file path. Without it, nextra reported 227 of its
        # own links dead.
        ("next.config stops counting as a generator", sites,
         '    "next.config.js", "next.config.ts", "next.config.mjs",',
         '    "next.config.never", "next.config.matches", "next.config.nothing",'),
        # The namespace is a property of the GENERATOR, and the measurement that
        # settled it cuts both ways. Applying a project-wide union everywhere
        # forgave two of encode/httpx's three genuinely dead anchors; applying it
        # nowhere left 168 of mystmd's findings naming labels that exist.
        # The third spelling of "where does this project keep its
        # generator config". Left one level shallower than the other two,
        # detection and the namespace disagree about the same repository.
        # Retargeted when the caches moved onto a RunScope; the cache
        # is the same, the name it is reached through is not.
        ("the namespace search looks less deep than detection does", sites,
         "        ctx.run.global_ns[key] = any((d / name).is_file()\n"
         "                                     for d in _site_dirs(ctx)\n"
         "                                     for name in _GLOBAL_ANCHOR_CONFIGS)",
         "        ctx.run.global_ns[key] = any((ctx.repo / d / name).is_file()\n"
         "                                     for d in _SITE_DIRS\n"
         "                                     for name in _GLOBAL_ANCHOR_CONFIGS)"),
        ("cross-reference namespace is the page everywhere", sites,
         "        ctx.run.global_ns[key] = any((d / name).is_file()\n"
         "                                     for d in _site_dirs(ctx)\n"
         "                                     for name in _GLOBAL_ANCHOR_CONFIGS)",
         "        ctx.run.global_ns[key] = False"),
        ("cross-reference namespace is the project everywhere", sites,
         "        ctx.run.global_ns[key] = any((d / name).is_file()\n"
         "                                     for d in _site_dirs(ctx)\n"
         "                                     for name in _GLOBAL_ANCHOR_CONFIGS)",
         "        ctx.run.global_ns[key] = True"),
        # The project union is built ON DEMAND, and this reverts it to eager.
        # Ordinarily a cost-only change gets NO mutation here - the `raw-lfs-blob`
        # size shortcut is excluded for exactly that reason, because a mutation
        # nothing can kill survives every campaign and reads as a test gap.
        # This one is different: it has a test that observes whether the union
        # was populated, so the mutation is killable and the campaign is what
        # keeps that test honest. Eagerly it cost roughly 400 ms per run at
        # 1600 files, on every repository carrying a conf.py.
        ("the project anchor union goes back to being built eagerly",
         rules / "md_anchor.py",
         "                if fragment in own or fragment in ambient_anchors():",
         "                if fragment in (own | ambient_anchors()):"),
        # Hugo's fragment convention, and the guard that keeps it Hugo's. Without
        # the `_` test every page in the project becomes an ambient anchor
        # source, which is the project-wide union arriving through the back door.
        ("hugo fragments stop being recognised as ambient anchors", sites,
         '                if not any(part.startswith("_") for part in rel.split("/")[:-1]):\n'
         "                    continue",
         "                continue"),
        ("every directory is treated as a hugo fragment directory", sites,
         '                if not any(part.startswith("_") for part in rel.split("/")[:-1]):\n'
         "                    continue",
         "                pass"),

        # --- repeated work ---------------------------------------------------
        # Cost contracts, and normally this file would not carry them: a change
        # that alters speed and not behaviour survives every campaign and reads
        # as a test gap. These four are here because each has a test that
        # observes it, so each is killable - and because a silent regression
        # would put back a 70 percent slowdown nobody could date afterwards.
        # Retargeted when the caches moved onto a RunScope; the cache
        # is the same, the name it is reached through is not.
        ("the remote is fetched once per document again", rules / "pinned_ref.py",
         "    key = str(ctx.repo)\n"
         "    if key not in ctx.run.own_remote:\n"
         "        ctx.run.own_remote[key] = _normalise_remote(\n"
         '            ctx.git.soft(ctx.repo, "remote", "get-url", "origin"))\n'
         "    return ctx.run.own_remote[key]",
         "    return _normalise_remote(\n"
         '        ctx.git.soft(ctx.repo, "remote", "get-url", "origin"))'),
        # `None` means "no origin", which is an ANSWER. Probed by truthiness it
        # is a miss forever, so the cache silently stops working on exactly the
        # repositories that have no remote.
        # Retargeted when the caches moved onto a RunScope; the cache
        # is the same, the name it is reached through is not.
        ("a cached no-origin answer is treated as a cache miss",
         rules / "pinned_ref.py",
         "    if key not in ctx.run.own_remote:",
         "    if not ctx.run.own_remote.get(key):"),
        # Retargeted when the caches became a RunScope. The sweep hands back one
        # OBJECT instead of clearing eleven names, and validate() decides whether
        # to reset by asking if it opened its own scope rather than by reading a
        # separate boolean - so both old anchors named lines that no longer
        # exist, and would have reported NOT APPLIED rather than a result.
        ("the sweep never gives its cache scope back", collect,
         "        _SCOPE = previous_scope",
         "        _released = previous_scope"),
        ("validate stops resetting its per-call caches", collect,
         "    if scope is not outer_scope:",
         "    if False:"),
        # There is deliberately NO mutation for dropping the run-scope half of
        # validate's `finally`, and the reason is worth more than the mutation
        # would be. One was added, it SURVIVED, and tracing it showed the gap
        # was not real: it is INERT, not unpinned.
        #
        # Leaving `_SCOPE` holding the scope validate built, instead of the
        # caller's, cannot change an answer. Every field on RunScope is keyed
        # by the repository path - `str(repo)`, `(str(repo), ref)`,
        # `f"{repo}\0{relative}"` - so any two scopes hold identical values for
        # identical keys. The one cache keyed without a repo, `(ref, sha)` in
        # validate_merge_claims, is a LOCAL dict and never reaches a scope.
        # The next validate() rebinds `_SCOPE` regardless, so the stale object
        # survives only until then, and the one caller in that window,
        # count_examined, reads data the same call just produced.
        #
        # Dropping the DOCUMENT half is a different matter and is pinned by
        # test_the_document_path_is_restored_after_validate.
        #
        # If a future change makes scope identity observable - a field keyed on
        # anything but the repository, or a reader between validate() and the
        # next one - this becomes a real gap and the mutation should come back.

        # --- reStructuredText ------------------------------------------------
        # Markdown's link syntax is not a subset of anything. Running those two
        # rules over rst does not degrade, it invents: 23 of numpy's findings
        # and all ten of Sphinx's came from reading `.rst` as though it were
        # markdown, and every one was false.
        ("rst files are read as markdown", text,
         '    return "rst" if suffix == "rst" else "markdown"',
         '    return "markdown"'),
        ("markdown-only rules stop being markdown-only", text,
         '_MARKDOWN_ONLY = {"dead-md-link", "dead-md-anchor"}',
         "_MARKDOWN_ONLY = set()"),
    ]


def install_restore_guard(backups: dict[Path, str]) -> None:
    """Put the source back if this process is killed part-way through.

    try/finally covers exceptions and nothing else. A campaign interrupted
    between writing a mutation and restoring it leaves BROKEN CODE ON DISK,
    indistinguishable from a deliberate edit - and it happened: a run stopped
    mid-mutation left `"dead-sha": 1` in the denominator, which would have been
    committed as a validator that always claims to have examined one reference.

    Restoring on SIGINT and SIGTERM closes the window that matters. A SIGKILL
    cannot be caught by anything, which is why the finished run also verifies
    the tree and says so.
    """
    import atexit
    import signal

    def restore(*_args: object) -> None:
        for path, original in backups.items():
            try:
                if path.read_text(encoding="utf-8") != original:
                    with open(path, "w", encoding="utf-8", newline="\n") as fh:
                        fh.write(original)
                    print(f"\nrestored {path.name} after interruption", file=sys.stderr)
            except OSError:
                pass

    atexit.register(restore)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda *_a: (restore(), sys.exit(130)))
        except (ValueError, OSError, AttributeError):
            pass    # not the main thread, or the platform lacks the signal


def run_suite(root: Path, python: str) -> bool:
    proc = subprocess.run(
        [python, "-m", "pytest", "-x", "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return proc.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]),
                        help="package root (defaults to this checkout)")
    parser.add_argument("--python", default=sys.executable,
                        help="interpreter used to run the suite")
    parser.add_argument("--check-only", action="store_true",
                        help="verify every mutation still matches, run no tests")
    parser.add_argument("--only", metavar="SUBSTRING[,SUBSTRING...]",
                        help="run only mutations whose label contains any of these")
    args = parser.parse_args()

    root = Path(args.repo).resolve()
    skill = root / "plugin/skills/extant"
    mutations = build_mutations(skill / "payload/extant_collect.py", skill / "detect.py")

    # A campaign is half an hour, which is too long to run after touching one
    # rule and therefore long enough that nobody does. `--only` re-verifies the
    # group belonging to whatever just changed.
    #
    # It prints the selection against the total, and REFUSES a filter that
    # selected nothing. A typo'd substring would otherwise run zero mutations
    # and report "0 survived", which is the healthiest-looking output this
    # harness can produce and means precisely nothing.
    if args.only:
        needles = [n.strip().lower() for n in args.only.split(",") if n.strip()]
        chosen = [m for m in mutations
                  if any(n in m[0].lower() for n in needles)]
        print(f"--only selects {len(chosen)} of {len(mutations)} mutations "
              f"from {len(needles)} pattern(s)")
        # Each pattern reports its own count. One typo among several would
        # otherwise be absorbed by the others: the total looks plausible, the
        # run is green, and the group somebody meant to re-verify was never
        # touched.
        for needle in needles:
            hits = sum(1 for m in mutations if needle in m[0].lower())
            print(f"  {needle!r}: {hits}" + ("  <- MATCHED NOTHING" if not hits else ""))
        if not chosen:
            print("nothing matched, so a run would prove nothing - refusing")
            return 1
        mutations = chosen

    # Existence FIRST. Reading before checking raised FileNotFoundError and
    # the careful message below never printed.
    paths = {path for _l, path, _o, _n in mutations}
    missing = [p for p in paths if not p.is_file()]
    if missing:
        for path in missing:
            print(f"missing source file: {path}")
        return 1
    backups = {path: path.read_text(encoding="utf-8") for path in paths}

    if args.check_only:
        # Seconds rather than half an hour, because it runs no tests. Mutations
        # rot alongside the code they point at: one silently stopped probing
        # anything when ancestry moved to a batched rev-list, and that was only
        # discovered at the next full campaign. This is cheap enough for CI, so
        # the rot is caught by the commit that causes it.
        stale = [f"{label} (matched {backups[path].count(old)}x)"
                 for label, path, old, _new in mutations
                 if backups[path].count(old) != 1]
        print(f"checked {len(mutations)} mutations against the current source: "
              f"{len(mutations) - len(stale)} match exactly once, {len(stale)} do not")
        for entry in stale:
            print(f"  STALE  {entry}")
        if stale:
            print()
            print("A mutation that matches nothing probes nothing, and a campaign")
            print("containing one reports a clean result it did not earn. Retarget")
            print("each of the above at the code that replaced what it named.")
        return 1 if stale else 0

    install_restore_guard(backups)

    print("NOTE: this rewrites the source in place, one mutation at a time.")
    print("      Do not edit the repository while it runs, and do not run it")
    print("      against a tree you have uncommitted work in.\n")

    print("baseline: ", end="", flush=True)
    if not run_suite(root, args.python):
        print("SUITE IS ALREADY RED - aborting, every result below would be noise")
        return 1
    print("green\n")

    survived: list[str] = []
    killed: list[str] = []
    not_applied: list[str] = []
    for i, (label, path, old, new) in enumerate(mutations, 1):
        original = backups[path]
        if original.count(old) != 1:
            not_applied.append(f"{label} (matched {original.count(old)}x)")
            print(f"{i:>2}/{len(mutations)}  NOT APPLIED  {label}")
            continue
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(original.replace(old, new, 1))
        try:
            green = run_suite(root, args.python)
        finally:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(original)
        (survived if green else killed).append(label)
        print(f"{i:>2}/{len(mutations)}  "
              f"{'SURVIVED **' if green else 'killed     '}  {label}")

    print(f"\nchecked {len(mutations)} mutations: {len(killed)} killed, "
          f"{len(survived)} SURVIVED, {len(not_applied)} not applied")
    if survived:
        print("\nTEST GAPS - behaviour changed and no test noticed:")
        for label in survived:
            print(f"  - {label}")
    if not_applied:
        print("\nHARNESS FAULTS - these prove nothing and must be repaired:")
        for label in not_applied:
            print(f"  - {label}")

    restored = all(p.read_text(encoding="utf-8") == b for p, b in backups.items())
    print(f"\nsource restored: {'clean' if restored else '** NOT RESTORED **'}")
    if not restored:
        return 2
    return 1 if (survived or not_applied) else 0


if __name__ == "__main__":
    sys.exit(main())
