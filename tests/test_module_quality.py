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

# test_every_module_declares_its_surface, test_no_module_reaches_past_another_
# modules_surface and test_rules_are_leaves deliberately do NOT live here.
# Removed per the coordinator's plan fix: the first two pass while examining
# zero non-__init__ modules (there is nothing to check until Task 2 creates
# git.py and friends), and the third asserts 13 rule modules that only exist
# from Task 9 onward. A gate that passes while examining nothing is the
# defect this whole file exists to prevent, so writing them here would have
# been the same mistake this project keeps finding in itself. Task 2 Step 5b
# adds the first two; Task 9 Step 6d adds the third.
