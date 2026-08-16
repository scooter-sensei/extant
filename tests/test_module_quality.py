"""What stops this package becoming one big file again.

The reason extant_collect.py reached 6,249 lines is that nothing ever said
stop. A split with no ceiling is a one-time tidy that resets the clock, so the
ceiling ships with the split rather than after the next one.
"""
from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

PAYLOAD = Path(__file__).resolve().parent.parent / "plugin" / "skills" / "extant" / "payload"
PACKAGE = PAYLOAD / "extant"

# The largest projected module is cli.py at about 675 lines, plus the 10 to 15
# per cent a module gains carrying its own imports. 900 leaves headroom without
# being a ceiling nothing could ever hit.
CEILING = 900


def _modules() -> list[Path]:
    return sorted(p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts)


def test_no_module_outgrows_the_reason_for_this_package() -> None:
    modules = _modules()
    assert modules, "no modules found; this test would pass vacuously"
    sizes = {p.relative_to(PACKAGE).as_posix():
             len(p.read_text(encoding="utf-8").splitlines()) for p in modules}
    print(f"checked {len(sizes)} modules against a {CEILING}-line ceiling; "
          f"largest is {max(sizes.values())}")
    over = {n: s for n, s in sizes.items() if s > CEILING}
    assert not over, (
        f"these modules are over {CEILING} lines: {over}. Split one, or argue "
        f"here for a higher ceiling - but argue, do not raise it quietly.")


def test_the_package_has_no_import_cycles() -> None:
    """Twenty-five modules can develop a cycle; one file cannot.

    A cycle usually surfaces as an ImportError in whichever module happens to
    be imported first, which makes it look like a problem with that module.
    """
    graph = {}
    for path in _modules():
        name = path.relative_to(PACKAGE).with_suffix("").as_posix().replace("/", ".")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        deps = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("extant"):
                deps.add((node.module or "")[len("extant."):] or "__init__")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("extant."):
                        deps.add(alias.name[len("extant."):])
        graph[name] = deps
    assert graph, "no modules parsed; this test would pass vacuously"
    print(f"checked {len(graph)} modules for import cycles")

    seen, stack, cycles = set(), [], []

    def walk(node: str) -> None:
        if node in stack:
            cycles.append(" -> ".join(stack[stack.index(node):] + [node]))
            return
        if node in seen:
            return
        seen.add(node)
        stack.append(node)
        for dep in sorted(graph.get(node, ())):
            if dep in graph:
                walk(dep)
        stack.pop()

    for name in sorted(graph):
        walk(name)
    assert not cycles, f"import cycles: {cycles}"


def test_no_star_imports() -> None:
    """A star import makes a module's public surface unanswerable without
    running it, which is the opposite of what this package is for."""
    offenders = []
    for path in _modules() + [PAYLOAD / "extant_collect.py"]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and any(
                    a.name == "*" for a in node.names):
                offenders.append(f"{path.name}:{node.lineno}")
    print(f"checked {len(_modules()) + 1} files for star imports")
    assert not offenders, offenders


def test_the_explanation_survived_the_move() -> None:
    """Comments and docstrings must not evaporate in relocation.

    44.6 per cent of the original file was explanation, and nearly every
    comment records the bug that caused the line beside it. Losing that is a
    quality regression no other test in this repository would notice.
    """
    comments = docs = 0
    files = _modules() + [PAYLOAD / "extant_collect.py"]
    for path in files:
        src = path.read_text(encoding="utf-8")
        comments += sum(1 for t in tokenize.generate_tokens(io.StringIO(src).readline)
                        if t.type == tokenize.COMMENT)
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                text = ast.get_docstring(node, clean=False)
                if text:
                    docs += len(text.splitlines())
    total = comments + docs
    # Measured on extant_collect.py before the split: 1413 comment lines and
    # 1371 docstring lines. The code moves wholesale, so the total across the
    # shim and the package should hold. The 5 per cent allowance is for
    # genuinely duplicated headers, not for pruning.
    #
    # The second term is NOT slack. Task 5 moved `extant_config.py` into the
    # package as `extant/config.py`, and the population this walks is the
    # package plus the shim - so a file carrying 274 lines of explanation
    # (measured at c0a3e90, its last commit outside the package) joined the
    # count without a single line being written. Left at 2784 the floor would
    # have gained 274 lines of margin overnight, which is a guard quietly
    # losing its grip rather than a codebase quietly improving. Raising it by
    # exactly what arrived keeps the sensitivity the number was chosen for,
    # and newly holds config.py's own explanation to the same standard.
    floor = int((2784 + 274) * 0.95)
    print(f"checked {len(files)} files: {comments} comment lines, "
          f"{docs} docstring lines, {total} total against a floor of {floor}")
    assert total >= floor, (
        f"explanation fell to {total}, below the floor of {floor}. Something "
        f"was dropped in a move; find it rather than lowering this floor.")


def test_every_module_declares_its_surface() -> None:
    """__all__ is the module's answer to 'what may siblings touch'.

    Without it the answer is 'everything, by convention', which is how 65
    private names came to be referenced across boundaries that did not exist
    yet.
    """
    assert len(_modules()) >= 2, (
        "fewer than two modules found - this gate passes vacuously on a "
        "package that is only __init__.py, which is why it lands in Task 2 "
        "rather than Task 1")
    # __init__.py is exempt (its own docstring says it deliberately holds a
    # version and nothing else), so the population actually inspected is
    # everything else - computed once here so the printed denominator matches
    # the loop below instead of counting __init__.py as checked when the
    # loop always skips it.
    checked = [p for p in _modules() if p.name != "__init__.py"]
    missing = []
    for path in checked:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [t.id for node in tree.body
                 if isinstance(node, ast.Assign)
                 for t in node.targets if isinstance(t, ast.Name)]
        if "__all__" not in names:
            missing.append(path.name)
    print(f"checked {len(checked)} modules for __all__")
    assert not missing, f"no __all__ in: {missing}"


def test_no_module_reaches_past_another_modules_surface() -> None:
    """Importing a sibling's underscore name is reaching through the wall.

    If a name is needed elsewhere it is public and belongs in __all__; if it is
    not, nobody outside should be naming it.
    """
    assert len(_modules()) >= 2, (
        "fewer than two modules found - this gate passes vacuously on a "
        "package that is only __init__.py, which is why it lands in Task 2 "
        "rather than Task 1")
    violations = []
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = node.module or ""
            # Exact package name or a dotted submodule only - NOT a bare
            # startswith("extant") prefix check. That looser form also matches
            # "extant_collect", the shim module OUTSIDE this package
            # (plugin/skills/extant/payload/extant_collect.py, not
            # .../extant/*.py), so `from extant_collect import _PHASE_TASK`
            # would misread an ordinary shim reference as one sibling module
            # reaching past another's surface. This gate polices siblings
            # inside this package; extant_collect is not one.
            if not (module == "extant" or module.startswith("extant.")):
                continue
            for alias in node.names:
                if alias.name.startswith("_"):
                    violations.append(
                        f"{path.name}:{node.lineno} imports {node.module}.{alias.name}")
    print(f"checked {len(_modules())} modules for cross-boundary private imports")
    assert not violations, violations

def test_rules_are_leaves() -> None:
    """Only the registry may import a rule.

    Three rule-to-rule dependencies existed before the split: md_link and
    path_pointer both reached into live_claim for rename detection, and merge
    reached into sha for object resolution. Each was shared machinery housed in
    whichever rule happened to need it first.

    Task 9 found three more the plan had not: the SHA-token and merge-claim
    scanners, which `dead-sha` and `false-merge-claim` share because the
    document's tokens must be resolved in ONE batch; the branch-token probe,
    which `stale-live-claim` called on `unknown-branch` outright; and the
    one-capture substitution four probes use. They went to extant/commits.py
    and extant/probes.py rather than being imported sideways.

    The `== 13` is the denominator that makes this real, and it is exactly why
    this gate could not live in Task 1: that task creates no rule modules, so
    the assertion fails outright rather than passing vacuously.
    """
    offenders = []
    for path in _modules():
        if path.name == "registry.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            module = getattr(node, "module", "") or ""
            if isinstance(node, ast.ImportFrom) and module.startswith("extant.rules"):
                offenders.append(f"{path.name}:{node.lineno} imports {module}")
    # `rules/__init__.py` is excluded, because it is the package marker rather
    # than a rule. Left in, this counted 14 and the number would have had to be
    # 14 - a denominator naming a population it does not describe, which is the
    # thing this file exists to refuse.
    rules = [p for p in _modules()
             if p.parent.name == "rules" and p.name != "__init__.py"]
    assert len(rules) == 13, f"found {len(rules)} rule modules, expected 13"
    print(f"checked {len(_modules())} modules; {len(rules)} of them are rules")
    assert not offenders, offenders
