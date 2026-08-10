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
    floor = int(2784 * 0.95)
    print(f"checked {len(files)} files: {comments} comment lines, "
          f"{docs} docstring lines, {total} total against a floor of {floor}")
    assert total >= floor, (
        f"explanation fell from 2784 to {total}. Something was dropped in a "
        f"move; find it rather than lowering this floor.")


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
            if not (node.module or "").startswith("extant"):
                continue
            for alias in node.names:
                if alias.name.startswith("_"):
                    violations.append(
                        f"{path.name}:{node.lineno} imports {node.module}.{alias.name}")
    print(f"checked {len(_modules())} modules for cross-boundary private imports")
    assert not violations, violations

# test_rules_are_leaves deliberately does NOT live here. Removed per the
# coordinator's plan fix: it asserts 13 rule modules that only exist from
# Task 9 onward, and a gate that passes (or fails outright) while examining a
# population that does not exist yet is the defect this whole file exists to
# prevent. test_every_module_declares_its_surface and
# test_no_module_reaches_past_another_modules_surface were deferred for the
# same reason with a smaller population - there was nothing to check until
# Task 2 created git.py - and Step 5b added them here once that population
# existed. Task 9 Step 6d adds test_rules_are_leaves the same way.
