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
    # The anchor and slug machinery left text.py for its own module when
    # text.py hit its line ceiling. Three anchors below moved with the code -
    # the same follow-the-code rule the notes above describe - and their TEXT
    # is unchanged, because a pure move changes where a line lives and not
    # what it says.
    anchors = collect.parent / "extant/anchors.py"
    sites = collect.parent / "extant/sites.py"
    # Task 10 emptied the shim. The formatters, the ambient run state and the
    # three modes each got a module, so an anchor that used to name
    # extant_collect.py now names the file the code lives in - the same
    # follow-the-code rule the two notes above describe. Eight anchors needed
    # `report`, and one of those eight also needed its TEXT rewritten:
    # `_fingerprint` lost its underscore when extant/cli.py, a different module
    # now, became a caller across the boundary.
    report = collect.parent / "extant/report.py"
    session = collect.parent / "extant/session.py"
    sweep = collect.parent / "extant/sweep.py"
    # The only irreversible write in the system, and it had no anchor here at
    # all until 2026-09-09 - so neither the conservation guard that stands
    # between a splitter bug and a truncated status document, nor the
    # terminator handling, was ever watched failing.
    entries_mod = collect.parent / "extant/entries.py"
    # The shell installer, which had no anchor either. Its failure mode is the
    # one this project cares about most and the one it already shipped once:
    # a hook reported as installed that can never run.
    hooks_install = collect.parent / "hooks/install"
    cli = collect.parent / "extant/cli.py"
    # The gating modes left extant/cli.py when `run_validate` reached 295 lines
    # against a 303-line ceiling and `--check-text` still had to be written.
    # Nine anchors moved with the code, and every one of them reported STALE
    # rather than passing - which is the whole reason --check-only exists, and
    # the third time this file has recorded the same lesson. Mutations rot
    # alongside the code they point at.
    gate = collect.parent / "extant/gate.py"
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
        # The claim scanner reads the whole document so a claim wrapped at the
        # margin is seen at all, and this is the guard that stops the same
        # `\s+` walking across a paragraph break or through the spaces prose()
        # leaves where a fence was. Removing it invents claims nobody wrote,
        # which is the direction that gets a validator switched off - and it is
        # invisible to every document whose claims happen to fit on one line,
        # which is most of them.
        # Retargeted when the bound stopped counting `"\n"` and started
        # counting line breaks in every spelling. The old anchor named a
        # `.count("\\n")` that no longer exists, and both of these reported
        # STALE rather than passing - which is the only reason the retarget
        # happened in the commit that caused it.
        ("a merge claim may span a paragraph break", commits,
         "        if line_breaks(match.group(0)) > 1:\n            continue",
         "        if False:\n            continue"),
        # The same bound on the release-claim scanner, which reads the whole
        # document for the same reason and can walk the same whitespace. Its
        # own defect was the sharper one: `examined` and `probe` already
        # scanned whole text while `check` went line by line, so a wrapped
        # claim was COUNTED by the denominator and never read - which prints as
        # examined-and-clean rather than as zero.
        ("a release claim may span a paragraph break", rules / "release_tag.py",
         "        if line_breaks(match.group(0)) > 1:\n            continue",
         "        if False:\n            continue"),
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
        # Retargeted when the scan moved into `_live_sites`: the newest entry
        # is held by a `break` now rather than by a `newest_checked` flag, so
        # the way to make the rule read every phase entry is to fall through.
        ("live-claim checks EVERY entry, not just the newest",
         rules / "live_claim.py",
         "        break        # the newest phase entry, and never another",
         "        continue     # the newest phase entry, and never another"),
        # Dedented one level when `check` stopped nesting its own scan inside a
        # per-entry loop and started reading `_branch_sites`. Same statement.
        ("branch rule loses the merge-history rescue", rules / "branch.py",
         "        if branch_exists(ctx, branch) or named_in_merge_history(ctx, branch):",
         "        if branch_exists(ctx, branch):"),
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
        # Retargeted when `check` stopped nesting a per-line loop inside a
        # per-match one and read the shared scanner instead: the body it names
        # lost a level of indentation, and all three release-tag anchors below
        # matched nothing until they followed it.
        ("a claimed release is judged local without being told",
         rules / "release_tag.py",
         "        if resolved is None:\n"
         "            if ctx.config.release_claims_are_ours:",
         "        if resolved is None:\n"
         "            if True:"),
        ("the opt-in never fires even when it is set", rules / "release_tag.py",
         "        if resolved is None:\n"
         "            if ctx.config.release_claims_are_ours:",
         "        if resolved is None:\n"
         "            if False:"),
        # Git resolves a bare name by trying `refs/tags/` BEFORE
        # `refs/heads/`. Reading the table heads-first resolves a repository
        # holding a branch and a tag of the same name to a different commit
        # than `rev-parse` does.
        # Retargeted when qualified refs started resolving from the table too.
        # The precedence line moved into `_from_table` and became a `return`;
        # nothing about the property changed, and the anchor reported STALE
        # rather than passing, which is the only reason it was noticed.
        ("a bare ref name resolves heads before tags", refs,
         "    return tags.get(ref) or heads.get(ref)",
         "    return heads.get(ref) or tags.get(ref)"),
        # The other half of the same change, and the one with a wrong ANSWER
        # rather than a slow one behind it: a qualified ref looked up in either
        # table resolves `refs/tags/x` to a branch called `x` on a repository
        # carrying both.
        ("a qualified ref resolves in whichever table has the name", refs,
         '    if ref.startswith("refs/tags/"):\n'
         '        return tags.get(ref[len("refs/tags/"):])\n'
         '    if ref.startswith("refs/heads/"):\n'
         '        return heads.get(ref[len("refs/heads/"):])',
         '    for _prefix in ("refs/tags/", "refs/heads/"):\n'
         "        if ref.startswith(_prefix):\n"
         "            ref = ref[len(_prefix):]"),
        # The peel now records a ref only when what it would return IS a
        # commit. Dropped, a tag naming a tree or a blob resolves to that
        # object's id - which is not a commit, appears in no rev-list, and is
        # the divergence from `^{commit}` this table used to claim it did not
        # have.
        ("the ref table stops checking what kind of object it peeled to", refs,
         '            if (peeled_kind or kind) != "commit":\n'
         "                continue",
         "            pass"),
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
         '        if not integrated_by(ctx, f"refs/tags/{resolved}"):',
         "        if False:"),
        ("path/branch guard removed (a file becomes a phantom branch)",
         rules / "branch.py",
         "            if looks_like_a_path(ctx, branch):\n"
         "                continue  # a file reference caught by a path-shaped pattern",
         "            if False:\n"
         "                continue  # a file reference caught by a path-shaped pattern"),
        ("path guard over-broad: skips anything containing a dot", sites,
         "    return bool(_FILEISH.search(token)) or (ctx.repo / token).exists()",
         '    return "." in token or (ctx.repo / token).exists()'),
        # Retargeted with the scan: the guard sits in `_live_sites` now, one
        # level deeper, and what follows it is the append rather than the
        # branch lookup `check` used to do inline.
        ("live-claim loses the path guard", rules / "live_claim.py",
         "                if looks_like_a_path(ctx, branch):\n"
         "                    continue\n                sites.append(",
         "                if False:\n"
         "                    continue\n                sites.append("),

        # --- markdown --------------------------------------------------------
        # Both halves of MD_LINK were quadratic, and bounding one is not enough:
        # with only the link-text bound in place the `[a](` shape still cost
        # 23.5s of its measured 23.8s. So there are two anchors, not one - a
        # single anchor would let either bound be removed silently.
        # Each replacement stays SELF-CONSISTENT - it removes one bound and
        # leaves `_MD_LINK_SPAN` at 4096 - because the test builds its strings
        # from that constant. Mutating the constant instead of the pattern
        # would have the test allocate a string of whatever size the mutation
        # named, which is a harness that runs out of memory rather than a
        # mutation that gets killed.
        ("the link text is unbounded again", text,
         '    r"\\[[^\\]]{0,%d}\\]\\(\\s*([^)\\s]{1,%d}?)\\s*\\)"'
         ' % (_MD_LINK_SPAN, _MD_LINK_SPAN))',
         '    r"\\[[^\\]]*\\]\\(\\s*([^)\\s]{1,%d}?)\\s*\\)"'
         ' % (_MD_LINK_SPAN,))'),
        ("the link target is unbounded again", text,
         '    r"\\[[^\\]]{0,%d}\\]\\(\\s*([^)\\s]{1,%d}?)\\s*\\)"'
         ' % (_MD_LINK_SPAN, _MD_LINK_SPAN))',
         '    r"\\[[^\\]]{0,%d}\\]\\(\\s*([^)\\s]+?)\\s*\\)"'
         ' % (_MD_LINK_SPAN,))'),
        # Retargeted with the scanner: this refusal moved to
        # `text.link_sites`. md_link.py still has an EXTERNAL check, in
        # `probe`, at a different indent - that one splices a corrupted
        # target and decides nothing, so it is not the site this names.
        # Retargeted again on 2026-09-12, when the unconditional refusals
        # became `_link_target`, the one reader every link SHAPE goes
        # through - so this now proves the refusal for a reference
        # definition and an HTML attribute as well as an inline link.
        ("external links get checked (needs the network)", text,
         '    if EXTERNAL.match(raw) or raw.startswith("#"):\n'
         '        return None',
         '    if raw.startswith("#"):\n'
         '        return None'),
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
        ("slug keeps punctuation", anchors,
         '    text = re.sub(r"[^\\w\\s-]", "", _heading_text(title))\n'
         '    return re.sub(r"\\s", "-", text).strip("-")',
         "    text = _heading_text(title)\n"
         '    return re.sub(r"\\s", "-", text).strip("-")'),
        # A heading opening with an emoji anchors with a leading dash on
        # GitHub, because the emoji is dropped and the space after it still
        # becomes one. Trimming both spellings reported 58 working links as
        # dead across the held-out corpus.
        ("the untrimmed slug spelling is lost", anchors,
         '    return untrimmed if untrimmed != untrimmed.strip("-") else ""',
         '    return ""'),
        # The other half of the same function, and the reason it is written
        # this way. Returning the trimmed spelling as well duplicates `_slug`
        # and masks it - "slug keeps punctuation" SURVIVED while it did.
        ("the untrimmed slug also returns the trimmed one, masking _slug",
         anchors,
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
        ("claim rules stop ignoring fenced code", text,
         "def prose(doc: DocScope, text: str) -> str:",
         "def prose(doc: DocScope, text: str) -> str:\n    return text"),
        ("case check accepts any spelling", sites,
         "            result = (True, None) if actual == normalised else (False, actual)",
         "            result = (True, None)"),

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
        ("archive exemption ignored", session,
         "    if (in_archive or not has_entries) and not rule.in_archive:\n"
         "        return False",
         "    if False:\n        return False"),
        # Anchored on the CONDITION alone. It used to include the dispatch line
        # that followed, and the rst work inserted a format check between the
        # two, so the pair stopped matching while the behaviour it probes was
        # untouched. A mutation should name the smallest thing it is about.
        ("has_entries ignored (entry rules run on extra docs)", session,
         "    if (in_archive or not has_entries) and not rule.in_archive:\n"
         "        return False",
         "    if in_archive and not rule.in_archive:\n"
         "        return False"),

        # --- denominator ------------------------------------------------------
        # Retargeted when the denominator stopped being one entry in a central
        # dict and became the rule module's own `examined`, computed over the
        # same population its `check` reads. Retargeted again when that
        # population moved into `_sha_sites`, so both halves read one scanner
        # instead of `examined` re-running the two candidate scans itself.
        ("denominator lies: dead-sha always 1", rules / "sha.py",
         "    return len(_sha_sites(ctx, text))",
         "    return 1"),
        # Retargeted when `count_examined` stopped being a dict of thirteen entries
        # and became a fold over the registry. A rule is dropped from the
        # denominator by skipping one, not by deleting a line.
        ("denominator drops a rule entirely", collect.parent / "extant/registry.py",
         "    for rule in RULES:",
         "    for rule in RULES[1:]:"),

        # --- selftest ---------------------------------------------------------
        ("selftest reports FIRED unconditionally", session,
         "        if findings:\n            fired += 1",
         "        if True:\n            fired += 1"),
        ("every probe returns None", session,
         "        probed = rule.probe(ctx, text)  # type: ignore[operator]",
         "        probed = None"),

        # --- output formats ---------------------------------------------------
        ("github property escaping removed", report,
         '        out = out.replace(":", "%3A").replace(",", "%2C")',
         "        pass"),
        ("github message escaping removed", report,
         '    out = value.replace("%", "%25").replace("\\r", "%0D").replace("\\n", "%0A")',
         "    out = value"),
        # Retargeted when --suggest-fixes made stdout a patch channel too, so
        # the condition gained a second clause. Caught by --check-only at the
        # commit that moved it, which is the whole reason that mode exists.
        # Retargeted a second time when run_validate was pulled out of
        # `main()` as its own function: the block dedented by one level (4
        # spaces) with it, and a mutation anchors on exact text.
        # Retargeted a THIRD time when the gating modes moved to
        # extant/gate.py and this became `_diagnostic_stream` - one function
        # answering the question for both of them, so the choice is now a
        # `return` rather than an assignment.
        # An out-of-repo document has no repository-relative path, so
        # `finding.rel` falls back to the absolute one and the encoder escapes
        # the drive colon - publishing `D%3A/elsewhere/doc.md`, a VALID
        # relative reference naming a file the repository does not contain.
        # Worse than the invalid URI it replaced, because an invalid one is
        # rejected loudly and this resolves quietly to nothing. Found by the
        # gap audit of the fix that changed that field's encoding.
        ("sarif publishes a document from outside the repository", cli,
         '        if args.format == "sarif":\n            target = Path(args.validate)',
         "        if False:\n            target = Path(args.validate)"),
        ("sarif diagnostics leak onto stdout", gate,
         '    return (sys.stderr if (args.format == "sarif" or args.suggest_fixes)\n'
         "            else sys.stdout)",
         "    return sys.stdout"),
        ("suggested patch shares stdout with the findings", gate,
         '    return (sys.stderr if (args.format == "sarif" or args.suggest_fixes)',
         '    return (sys.stderr if (args.format == "sarif" or False)'),
        ("fingerprint folds in the line number", report,
         '                "statusClaim/v1": fingerprint(\n'
         "                    item.path, item.finding.kind, item.finding.detail),",
         '                "statusClaim/v1": fingerprint(\n'
         "                    item.path, item.finding.kind,\n"
         '                    f"{item.finding.detail}:{item.finding.line}"),'),
        ("sarif drops partialFingerprints", report,
         '            "partialFingerprints": {',
         '            "_dropped": {'),
        # Retargeted when the region gained a snippet and columns, which moved
        # its construction out of the literal and above the result dict.
        ("sarif region loses startLine", report,
         '        region: dict[str, object] = {"startLine": max(1, item.finding.line)}',
         '        region: dict[str, object] = {}'),
        # The severity mapping is the reason `Located.gating` exists. Publishing
        # every finding as an error contradicted a sweep's own exit code.
        ("sarif calls every finding an error again", report,
         '            "level": "error" if item.gating else "note",',
         '            "level": "error",'),
        # The denominator, which no machine consumer could see before.
        ("sarif stops reporting what was examined", report,
         '    if examined is not None:',
         '    if False:'),
        # SARIF 3.4.3 requires a URI, and a repository path frequently is not
        # one. `#` is the sharp case: unencoded, a consumer reads
        # `source/F#/LICENSE.md` as the path `source/F` plus a fragment, so the
        # alert names a file that does not exist - and an invalid document can
        # be rejected whole, taking every finding in it with it.
        ("sarif emits a repository path that is not a uri", report,
         '                    "artifactLocation": {"uri": _sarif_uri(item.path)},',
         '                    "artifactLocation": {"uri": item.path},'),
        # The other half: encoding MORE than RFC 3986 requires is conformant
        # but not free, because a consumer matching literally would stop
        # recognising the paths that already work.
        ("sarif over-encodes a path that is already a uri", report,
         '    segments = [quote(segment, safe=_PCHAR_SAFE) for segment in path.split("/")]',
         '    segments = [quote(segment, safe="") for segment in path.split("/")]'),

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
        ("the deletion haystack stops blanking fenced code", sweep,
         "                parts.append(markup.prose(session.document(), handle.read()))",
         "                parts.append(handle.read())"),
        # And the other direction. `_strip_code` also blanks INLINE backticks,
        # which is where a claim is normally written - so this would empty the
        # haystack and report every claim in the document as deleted.
        ("the deletion haystack also blanks inline code", sweep,
         "                parts.append(markup.prose(session.document(), handle.read()))",
         "                parts.append(markup.strip_code(session.document(), handle.read()))"),
        # Retargeted on 2026-09-09, when the four disagreeing spellings of a
        # configured document name collapsed into `_normalise` and this
        # function started using it. The anchor named the un-normalised tuple
        # and matched nothing afterwards - reported STALE rather than passing,
        # which is the only reason the retarget happened in the commit that
        # caused it. Mutations rot alongside the code they point at.
        ("deletion checks only the primary document, not the archive", sweep,
         "    return [_normalise(d) for d in (session.CONFIG.primary_doc,\n"
         "                                    session.CONFIG.archive_doc,\n"
         "                                    *session.CONFIG.extra_docs) if d]",
         "    return [_normalise(d) for d in (session.CONFIG.primary_doc,) if d]"),
        # The character-set strip that demoted `.github/CONTRIBUTING.md` to the
        # unreviewed half. `str.lstrip` takes a SET, so this is the bug exactly
        # as it shipped, and the mutation is indistinguishable from the fix on
        # every configured name that does not begin with a dot - which is most
        # of them, and is why nothing noticed.
        #
        # Retargeted on 2026-09-09, when the audit found the repair had been
        # made in `sweep.py` and NOT in `gate.py`, so `--verify` still reported
        # its findings under `./docs/NOTES.md` - a path git does not track, and
        # therefore a `--format=github` annotation matching no line of the
        # diff. The normaliser moved to `config.load_config`, where the setting
        # is read, so no consumer can forget it. The anchor followed the code.
        ("a configured name is stripped of dots as well as of `./`",
         collect.parent / "extant/config.py",
         '    while name.startswith("./"):\n        name = name[2:]',
         '    name = name.lstrip("./")'),
        ("deletion re-reads documents that did not change", sweep,
         "    for relative in _changed_between(repo, ref, documents):",
         "    for relative in documents:"),
        # The subject a claim is about. A rule that stops recording one is
        # invisible to `--deleted-since`, and the mode reports the skip rather
        # than hiding it - so the loss is quiet rather than silent, which is
        # still not good enough to leave unpinned.
        # Dedented one level when `check` stopped nesting its own scan inside
        # a per-line loop and started reading `_link_sites`. The code is the
        # same statement; only the indentation this matches by moved.
        ("a rule stops recording which token its claim is about",
         rules / "md_link.py",
         '        findings.append(Finding(number, "dead-md-link", detail,\n'
         "                                subject=target))",
         '        findings.append(Finding(number, "dead-md-link", detail))'),
        # SARIF's contract is that stdout is one valid document, always. Zero
        # bytes fails a CI upload rather than reading as "no results", so a
        # clean run looks exactly like a broken one.
        ("the deletion mode emits nothing when it has nothing to report", sweep,
         "    else:\n"
         "        # ALWAYS, even with nothing to report.",
         "    elif gone:\n"
         "        # ALWAYS, even with nothing to report."),
        ("the deletion mode starts gating", sweep,
         '              "why it never fails a run.", file=out)\n    return 0',
         '              "why it never fails a run.", file=out)\n'
         "    return 1 if gone else 0"),

        # --- search --------------------------------------------------------------
        # Retargeted when the read gained a `try:` for the undecodable case -
        # the lines are the same, one indent deeper.
        ("search only looks at the live document", cli,
         "    for relative in (session.PRIMARY_DOC, session.ARCHIVE_DOC):\n"
         "        path = repo / relative\n"
         "        if not path.is_file():\n"
         "            continue\n"
         "        try:\n"
         "            with open(path, encoding=\"utf-8\", newline=\"\") as fh:",
         "    for relative in (session.PRIMARY_DOC,):\n"
         "        path = repo / relative\n"
         "        if not path.is_file():\n"
         "            continue\n"
         "        try:\n"
         "            with open(path, encoding=\"utf-8\", newline=\"\") as fh:"),
        ("search becomes case-sensitive", cli,
         "    needle = query.lower()",
         "    needle = query"),
        ("search matches every entry regardless of content", cli,
         '            if kind != "phase" or needle not in entry.lower():',
         '            if kind != "phase":'),

        # --- suggested fixes ------------------------------------------------------
        # `suggest_renames` moved to extant/gate.py with the mode that calls
        # it. The TEXT of these three is unchanged - the function was
        # transplanted rather than rewritten - so only the file moved.
        # Retargeted when the patch stopped replacing on the RESOLVED target
        # and started replacing on the spelling the document actually uses.
        # The old anchor named `replacements.append((target, moved))`, which no
        # longer exists; a mutation kept alive by pointing it at something else
        # would be testing a different thing under an old label.
        ("suggest-fixes offers a guess for a merely missing file", gate,
         "        moved = renamed_to(ctx, target)\n        if moved:",
         "        moved = renamed_to(ctx, target) or target + \".guess\"\n"
         "        if moved:"),
        # THE INVARIANT. Without it `--suggest-fixes` offered to rewrite a link
        # split across a newline that `--validate` had just reported clean - a
        # patch for a finding that does not exist.
        ("a patch is offered with no finding behind it", gate,
         "        if target not in linked or resolve_reference(ctx, base, target)[0]:",
         "        if resolve_reference(ctx, base, target)[0]:"),
        # The two strings the shared scanner returns are not interchangeable:
        # one RESOLVES and one is REPLACED. Swapping them makes the patch look
        # for a string the document does not contain.
        ("the patch replaces on the resolved target, not the written spelling", gate,
         "            replacements.append((raw, moved + raw[len(path_part):]))",
         "            replacements.append((target, moved))"),
        ("the shared scanner drops the spelling the document uses", text,
         "                sites.append((number, raw, target, html))",
         "                sites.append((number, target, target, html))"),
        ("suggest-fixes rewrites prose as well as references", gate,
         '        updated = updated.replace(f"]({old})", f"]({new})")\n'
         '        updated = updated.replace(f"`{old}`", f"`{new}`")',
         "        updated = updated.replace(old, new)"),
        ("suggest-fixes writes the file instead of emitting a patch", gate,
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
        # The four `cli` anchors in this group all dedented by one level (4
        # spaces) when run_validate was pulled out of `main()` as its own
        # function; see the note beside the sarif/stdout pair above.
        # They then split across two files. The bookkeeping - what was
        # recorded, what matched, how much was hidden - became
        # `report.Collector`, which is what let `run_validate` be split at all;
        # the two that only PRINT it went to extant/gate.py with the mode.
        ("baseline suppresses by kind, so every future finding is forgiven", report,
         "            if mark in self.baselined:",
         "            if any(e[\"kind\"] == finding.kind\n"
         "                   for e in self.baselined.values()):"),
        ("baseline stops stating how much it is hiding", gate,
         '        diag(f"{len(found.located)} new finding(s), {found.suppressed} "\n'
         '             f"suppressed by {rel(repo, baseline_path)}")',
         '        diag(f"suppressed by {rel(repo, baseline_path)}")'),
        ("a missing baseline becomes an empty one", report,
         "    if not path.is_file():\n        raise ValueError(",
         "    if not path.is_file():\n        return {}\n    if False:\n        raise ValueError("),
        # Inverted when it became `_open_baseline`, which returns early rather
        # than loading conditionally. The fault it reintroduces is the same
        # one: reading a baseline while WRITING one, so each re-recording
        # keeps only what the previous baseline had missed.
        ("re-recording honours the active baseline and shrinks the file", gate,
         "    if not (args.baseline or args.baseline_check) or args.write_baseline:",
         "    if not (args.baseline or args.baseline_check):"),
        ("baseline-check stops reporting entries that no longer occur", report,
         "        return [entry for mark, entry in sorted(self.baselined.items())\n"
         "                if mark not in self.matched]",
         "        return []"),

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
        ("the raw-blob check never fires", rules / "lfs.py",
         "        if size is None or sha in pointers:", "        if True:"),
        ("check-attr loses -z, so git quotes any path with a space",
         rules / "lfs.py",
         '["git", "check-attr", "-z", "--stdin", "filter"], cwd=ctx.repo,',
         '["git", "check-attr", "--stdin", "filter"], cwd=ctx.repo,'),
        ("the NUL join reverts to newlines (the Windows CR bug)", rules / "lfs.py",
         'payload = ("\\0".join(blobs) + "\\0").encode("utf-8")',
         'payload = ("\\n".join(blobs) + "\\n").encode("utf-8")'),
        ("the LFS survey reads the index instead of the committed tree",
         rules / "lfs.py",
         '            ["git", "ls-tree", "-r", "-z", "HEAD"], cwd=ctx.repo,',
         '            ["git", "ls-files", "-z"], cwd=ctx.repo,'),
        ("the LFS gate stops reading .gitattributes", rules / "lfs.py",
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

        # Found auditing --wide-docs rather than by a test failing, which is why
        # it earns an anchor: the archive sits BESIDE the primary document, so a
        # project that keeps one has it tracked at the root where this
        # enumerates. `gate.py` already validates it on its own pass, with
        # `in_archive=True` so a retired entry is not judged as a live claim -
        # and naming it in extra_docs gave one file two passes with different
        # semantics, printing every finding in it twice against a denominator
        # that counted the document once.
        ("--wide-docs pins the archive as an extra document too",
         detect.parent / "install.py",
         '    settled = {str(o.value) for o in obs\n'
         '               if o.key in ("primary_doc", "archive_doc") and o.value}',
         '    settled = {str(o.value) for o in obs\n'
         '               if o.key in ("primary_doc",) and o.value}'),

        # The schemeless-URL arm on EXTERNAL, which five link call sites read.
        # Both directions matter and they fail differently, so both are probed.
        # Removing it reinstates 26 false positives found on two corpora no rule
        # was designed on; widening it to any `host.tld` reads `README.md` as a
        # Moldovan hostname and silences every link rule at once, which is the
        # shape that looks clean forever.
        ("a schemeless URL is read as a relative path again", text,
         r'    rf"|(?:[a-z0-9-]+\.)+(?:{_TLD})(?:[/?#]|$)"        # example.com[/path]',
         r'    rf"|(?!x)x"                                        # example.com[/path]'),
        ("the schemeless arm widens to any dotted suffix", text,
         '_TLD = ("com|org|net|edu|gov|mil|io|ai|dev|app|cloud|tech|club|blog|wiki"',
         '_TLD = ("[a-z]{2,}"  # noqa'),

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
        # The DEGRADED MODE, which is the whole risk in --wide-docs. An
        # unclassified enumeration is not a weaker version of this policy, it is
        # the one the measurement rejected: 0.081 findings per pinned path
        # against the 0.106 the installer already manages, because 52 of the 73
        # findings "just add the root" collects are root CHANGELOG.md. So the
        # mutation is not "the guard is skipped" - that raises TypeError and any
        # test would catch it - but "the guard falls back", which is the shape
        # somebody would actually write and which looks like it works.
        ("--wide-docs falls back to unclassified enumeration", detect,
         "    classify, why = _strata_classifier()\n"
         "    if classify is None:\n"
         "        return None, [",
         "    classify, why = _strata_classifier()\n"
         "    if classify is None:\n"
         "        classify = lambda path: \"ordinary\"\n"
         "    if False:\n"
         "        return None, ["),
        # Depth is the whole question, and 4 is a cliff rather than a slope: 16
        # more findings for 2,220 more pinned paths, because dead-md-link's
        # false positives concentrate at depth 4 to 7. A default that drifts one
        # level either way is a different policy under the same flag name.
        ("--wide-docs quietly reaches one level deeper", detect,
         "        if 2 <= len(parts) <= depth + 1 and parts[0].lower() in DOC_DIRS:",
         "        if 2 <= len(parts) <= depth + 2 and parts[0].lower() in DOC_DIRS:"),

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
        ("the sweep gates on unreviewed documents too", sweep,
         '    return 1 if (results["vetted"] or RULE_ERRORS or unreturned) else 0',
         '    return 1 if (results["unvetted"] or RULE_ERRORS or unreturned) else 0'),
        ("the sweep gates on nothing at all", sweep,
         '    return 1 if (results["vetted"] or RULE_ERRORS or unreturned) else 0',
         "    return 0"),
        ("everything is vetted, so nothing is surveyed separately", sweep,
         "    vetted = [p for p in paths if p in normalised]\n"
         "    return vetted, [p for p in paths if p not in normalised]",
         "    return list(paths), []"),
        # THE MUTATION IS THE BUG AS IT SHIPPED, restored exactly. For eight
        # releases `_worker_init` assigned `session.CONFIG` and stopped there,
        # which reads as installing the parent's settings and installs nothing:
        # every rule takes its patterns from the built Config on
        # `session._ACTIVE`, and only `_apply_config` writes that. A spawned
        # worker had therefore built `_ACTIVE` from whatever `load_config` found
        # beside `extant/session.py` at import - this repository's own settings
        # when run from a checkout, and the DEFAULTS in a pip or pre-commit
        # install, where nothing sits above site-packages.
        #
        # Nothing here pointed at this function, and that is why it survived.
        # The suite's parallel-versus-serial agreement test could not see it
        # either: its helper made the same mistake, so both paths ran on
        # defaults and agreed. The anchor exists so the fix is watched failing
        # rather than trusted.
        ("a survey worker keeps its own configuration, not its parent's", sweep,
         "    session.install_config(config)         # type: ignore[arg-type]",
         "    session.CONFIG = config                # type: ignore[assignment]"),
        # --- reference resolution, which must not vary by platform --------
        # The backslash is the whole of it. `Path(x).parts` split on it under
        # Windows and not under POSIX, so a Windows-spelled pointer - which
        # `path_pointer`'s default pattern deliberately admits - resolved on a
        # laptop and was reported dead on the ubuntu CI leg. This mutation is
        # killed on EVERY platform, which the `Path().parts` it replaced would
        # not have been: that one is invisible on Windows, and a mutation only
        # the other leg can catch is exactly the shape this campaign cannot
        # measure. See the unit test for why the assertion is on the splitter.
        ("a reference is split on the forward slash alone", sites,
         '    for chunk in relative.replace("\\\\", "/").split("/"):',
         '    for chunk in relative.split("/"):'),
        # The `..` walk, restored to unbounded. It was the LAST of the three
        # ways PHASE 6's audit found to leave the repository, the other two
        # being an absolute path and a drive letter, and it answered a question
        # about this repository with whatever else sat above it on the machine.
        # Measured over 176 repositories before it was bounded: 12 of 77,879
        # relative references climb out, none of them resolve, and running both
        # behaviours over all 77,879 changed ZERO verdicts.
        ("a reference may climb above the repository root again", sites,
         '            if part == ".." and depth is not None:',
         "            if False:"),
        # The other half, and it is a separate anchor on purpose: answering 0
        # for a base that is not below the repository would refuse every `..`
        # for `--validate` on a file outside it, which trades the
        # machine-dependence above for a false positive. One anchor could not
        # tell the two mistakes apart.
        ("a base outside the repository is treated as being at its root", sites,
         "    except ValueError:\n        return None\n\n\ndef _actual_case",
         "    except ValueError:\n        return 0\n\n\ndef _actual_case"),
        # The filesystem-root probe, restored. It answers a question about the
        # repository by looking at whatever else is on the machine, so a dead
        # root-relative link is silenced for whoever happens to have that path
        # and reported for everyone else. Measured over 176 repositories before
        # it was removed: it changes no verdict on any of them, because the only
        # absolute targets real documents cite are generator routes.
        # Anchored WITH the `else:` beneath it, because `result = (False, None)`
        # alone matches the unresolved-case branch as well and --check-only
        # reported it 2x. A mutation that matches twice probes neither site.
        ("an absolute target is answered by the machine's filesystem", sites,
         "        result = (False, None)\n    else:",
         "        result = (Path(raw).exists(), None)\n    else:"),
        # The anchor rule building its own path again instead of asking the one
        # function that owns the question. `Path(repo) / "C:/x"` is `C:/x`, so
        # this reads a markdown file anywhere on the machine and puts its
        # absolute path into a finding.
        ("the anchor rule resolves a cross-file target itself",
         rules / "md_anchor.py",
         "            if not resolve_reference(ctx, root, relative)[0]:",
         "            if not (root / relative).is_file():"),
        # The on-disk spelling the rooted probe found, thrown away again. The
        # finding still fires; it goes back to saying "does not exist" about a
        # file that does, which sends the reader looking for a missing document
        # instead of fixing two letters.
        ("a root-relative link forgets the case it should have used",
         rules / "md_link.py",
         "        actual_case = actual_case or rooted_case",
         "        actual_case = actual_case"),
        # --- the installer ------------------------------------------------
        # Restores the bug exactly: every hook looks appendable, so a file
        # ending in `exit 0` gets the block appended behind it and a success
        # line printed for a check that can never fire. Invisible on any hook
        # that does not end that way, which is most of them.
        ("a hook that ends in exit is still reported as installed",
         hooks_install,
         "    [ -f \"$1\" ] && grep -qE '^(exit|exec)([[:space:]]|$)' \"$1\"",
         "    false"),
        # --- the irreversible write --------------------------------------
        # The conservation guard itself. Without it a bug in `split_entries`
        # truncates the status document and reports success, which is the most
        # expensive silent failure available in this system.
        ("the archive stops checking that it conserves every line", entries_mod,
         "    if lost:\n        raise RuntimeError(",
         "    if False:\n        raise RuntimeError("),
        # The archive is a second file with a terminator of its own. Taking the
        # primary's rewrites every line of it as a side effect of retiring two
        # entries, and against a CR-only archive it produces a file holding
        # both CR and LF - worse than either, and asked for by nobody.
        ("the archive is written in the primary document's terminator",
         entries_mod,
         "        fh.write(archived_text.replace(\"\\n\", archive_newline))",
         "        fh.write(archived_text.replace(\"\\n\", newline))"),
        # A file that could not be read is not a file with no findings. This
        # drops it on the floor exactly the way a bare `continue` would, which
        # is how the sweep would quietly under-report on any repository holding
        # a latin-1 document.
        ("unreadable files are skipped silently rather than counted", sweep,
         '        return (relative, [], f"{relative} ({exc.__class__.__name__})", {}, [])',
         "        return (relative, [], None, {}, [])"),
        ("the sweep denominator counts only what it gated on", sweep,
         '    print(f"\\nswept {len(paths)} markdown file(s): "',
         '    print(f"\\nswept {len(vetted)} markdown file(s): "'),
        # An empty repository must SAY it swept nothing. Returning 0 without the
        # diagnostic is the project's signature failure: the reassuring silence
        # of a run that examined zero files.
        ("a repository with no markdown reports nothing at all", sweep,
         '    print("swept 0 markdown files: git tracks none in this repository",\n'
         "          file=sys.stderr)",
         "    pass"),
        # The same silence one level up, in the WIRE format. An empty
        # stdout also describes a tool that crashed or an upload aimed
        # at the wrong path, and GitHub rejects an empty SARIF file, so
        # a project whose glob matched nothing got a failed upload
        # rather than a report reading zero. Found by
        # tests/harnesses/fuzz.py, pinned by tests/test_fuzz_findings.py.
        ("an empty survey emits no machine document", sweep,
         '    if fmt != "text":',
         "    if False:"),

        # --- exclude_paths ---------------------------------------------------
        # The one setting that can make a repository look clean by not looking
        # at it, so its guards get more mutations than its size suggests. A
        # skip-list fails silently in BOTH directions and this project has
        # already shipped one whose defaults excluded every file it was meant
        # to scan.
        ("a star crosses a separator, so docs/* takes the whole tree", sweep,
         '            out.append("[^/]*")',
         '            out.append(".*")'),
        ("a bare pattern anchors at the root instead of any segment", sweep,
         '        source = rf"^(?:.*/)?{core}(?:/.*)?$"',
         '        source = rf"^{core}(?:/.*)?$"'),
        ("a bare pattern matches half a segment", sweep,
         '        source = rf"^(?:.*/)?{core}(?:/.*)?$"',
         '        source = rf".*{core}.*"'),
        ("an unusable pattern compiles to one that matches everything",
         sweep,
         '    if not pattern or pattern.startswith("#"):\n        return None',
         '    if False:\n        return None'),
        ("a path is counted against every pattern it matches", sweep,
         "                hit = pattern\n                break",
         "                hit = pattern"),
        ("the per-pattern counts stop being reported", sweep,
         "        for pattern, count in sorted(excluded_counts.items()):",
         "        for pattern, count in []:"),
        ("a pattern that matched nothing is no longer named", sweep,
         "        idle = sorted(p for p, n in excluded_counts.items() if not n)",
         "        idle = []"),
        ("excluding a configured document stops being refused", sweep,
         "        conflicting = sorted((configured & present) - kept - {\"\"})",
         "        conflicting = []"),
        ("the conflict check keys on configured-but-missing again", sweep,
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
        # Retargeted, not rewritten: the refusal moved to `text.link_sites`
        # when the scanner was shared with gate.suggest_renames. Same line,
        # same meaning, new home.
        ("a .html target is judged again unless a generator is declared",
         text,
         '    if target.endswith(".html"):\n        return None',
         "    if False:\n        return None"),
        # --- the 2026-09-12 widenings ------------------------------------
        # Each admits a shape that was read by nothing, and each carries a
        # refusal beside it. The admissions are anchored so the shape cannot
        # quietly stop being read - a scanner that drops an arm reports the
        # same silence as a document with no such link - and the refusals
        # are anchored because a suppression that stops firing deletes
        # nothing visible: it reports findings that are false.
        ("a reference-style definition is no longer read", text,
         '        if "[" in line and "]:" in line:\n'
         '            definition = _REFERENCE_DEFINITION.match(line)',
         '        if False:\n'
         '            definition = _REFERENCE_DEFINITION.match(line)'),
        ("a footnote definition is read as a link", text,
         'r"^ {0,3}\\[(?!\\^)[^\\]]{1,%d}\\]:',
         'r"^ {0,3}\\[[^\\]]{1,%d}\\]:'),
        ("an HTML href or src is no longer read", text,
         '        if "<" in line:\n'
         '            raws += [(raw, True) for raw in _html_references(line)',
         '        if False:\n'
         '            raws += [(raw, True) for raw in _html_references(line)'),
        ("a templated HTML attribute is resolved as a path", text,
         '                     if "{" not in raw and "}" not in raw]',
         '                     ]'),
        # The walk resumes after the tag's `>`. Resuming at the tag's own end
        # instead re-reads every overlapping opening and is the quadratic the
        # walk exists to remove; the timing test is what catches it.
        ("the HTML walk re-reads overlapping tags", text,
         "        position = closed + 1",
         "        position = opened.end()"),
        ("HTML inside a generated site tree is judged as a file",
         rules / "md_link.py",
         "            if in_site:\n                continue",
         "            if False:\n                continue"),
        ("a line range is read by its start again", rules / "line_pointer.py",
         "        if (cited if end is None else end) <= total:",
         "        if cited <= total:"),
        ("a backticked SHA range is read as one token", commits,
         "    found = _SHA_RANGE.match(token)\n"
         "    return (found.group(1), found.group(3)) if found else (token,)",
         "    return (token,)"),
        ("the rewriter leaves both ends of a range dead", commits,
         "        ends = _range_ends(token)\n"
         "        if not any(looks_like_sha(end) for end in ends):",
         "        ends = (token,)\n"
         "        if not any(looks_like_sha(end) for end in ends):"),
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
         "            if fragment in own or fragment in ambient_anchors():",
         "            if fragment in (own | ambient_anchors()):"),
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
        # Retargeted again when the remote started being READ rather than
        # spawned for. The memo is unchanged and so is what this probes; the
        # expression it wraps gained a fast path in front of the spawn, so the
        # anchor named a line that no longer exists.
        ("the remote is fetched once per document again", rules / "pinned_ref.py",
         "    key = str(ctx.repo)\n"
         "    if key not in ctx.run.own_remote:",
         "    key = str(ctx.repo)\n"
         "    if True:"),
        # The guard on the config fast path, which is the whole of why reading
        # the file is not a one-line change. `configparser` disagrees with git
        # about quoted values and inline comments, and so does anything that
        # takes the text after `=` at face value - and the disagreement
        # survives `_normalise_remote` into a WRONG `owner/name` rather than
        # into an error, which is a rule silently checking somebody else's
        # repository.
        ("the config fast path answers for syntax it cannot parse",
         collect.parent / "extant/git.py",
         "        if not _PLAIN_VALUE.match(value):\n"
         "            return None           # a spelling this refuses to guess at",
         "        pass"),
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
        ("the sweep never gives its cache scope back", session,
         "        _SCOPE = previous_scope",
         "        _released = previous_scope"),
        ("validate stops resetting its per-call caches", session,
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
        # The blanking loops promise that a span taken from the stripped text
        # lands on the same characters in the original, and two probes splice
        # on exactly that. Rebuilding the terminator instead of carrying it
        # through breaks the promise on CRLF only - 1627 characters on this
        # repository's own document - which is why the suite never saw it and
        # CI structurally could not: the runners check out LF, where the sole
        # casualty is the final newline. Aimed at the CRLF branch itself, so
        # this fails on the platform the defect actually reaches.
        ("stripped text stops preserving CRLF terminators", text,
         '    if raw.endswith("\\r\\n"):\n        return raw[:-2], "\\r\\n"',
         '    if raw.endswith("\\r\\n"):\n        return raw[:-2], "\\n"'),
        # One anchor for both claim scanners, because both bound themselves
        # with `line_breaks`. Counting `\n` alone is right for LF and for CRLF
        # - which contains one - and silently wrong for a bare `\r`: the bound
        # never trips, so the guard against a claim borrowing from the next
        # paragraph is not a guard, and every claim reports line 1. Raised by a
        # review of the merge scanner; the release scanner had it too and was
        # not named, which is why this aims at the shared helper.
        ("line breaks are counted as newlines alone", text,
         r'LINE_BREAK = re.compile(r"\r\n|[\n\r]")',
         r'LINE_BREAK = re.compile(r"\n")'),
        ("rst files are read as markdown", text,
         '    return "rst" if suffix == "rst" else "markdown"',
         '    return "markdown"'),
        ("markdown-only rules stop being markdown-only", text,
         'MARKDOWN_ONLY = {"dead-md-link", "dead-md-anchor"}',
         "MARKDOWN_ONLY = set()"),
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
