#! /usr/bin/env python3
# python3 ts=4space
"""Report definitions and constants that nothing in this repository references.

Two checks, both purely static over the AST:

  functions  every `def`, cross checked against every reference anywhere in the
             repository. Reachability is transitive: a function called only from
             another unreachable function is unreachable too.

  constants  every upper case module level name in constants.py, against the
             same reference set.

A reference is an attribute access, a bare name, or a string constant, so
dispatch-by-string and getattr(obj, "name") do not produce false positives.
Dunders and test_* are treated as entry points: the interpreter and pytest's
collection call them without naming them.

Anything reported that is deliberately kept should carry a docstring beginning
"NOT CALLED" (functions) or a "# NOT USED" comment (constants); with --strict
those are the only ones tolerated, and anything else makes this exit non-zero.

Usage:
    python3 tools/find_dead_code.py [--strict] [path ...]
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import sys
from collections.abc import Iterable, Iterator

DEFAULT_ROOTS: tuple[str, ...] = (".", "rl_scan_artifactory", "tools", "tests", "livetest")
# roots read without their subdirectories: livetest/work holds a venv after a run
FLAT_ROOTS: frozenset[pathlib.Path] = frozenset({pathlib.Path("."), pathlib.Path("livetest")})
CONSTANTS_FILE: str = "rl_scan_artifactory/constants.py"
ENTRY_POINT_NAMES: frozenset[str] = frozenset({"main", "process"})
# ast.NodeVisitor dispatches on the node class name, so these are never named
ENTRY_POINT_PREFIXES: tuple[str, ...] = ("__", "test_", "visit_")
# a pytest fixture is requested by parameter name, never by a reference to the def
ENTRY_POINT_DECORATOR_PARTS: tuple[str, ...] = ("fixture",)

NOT_CALLED_MARKER: str = "NOT CALLED"
NOT_USED_MARKER: str = "# NOT USED"
DEAD_STORE_MARKER: str = "# DEAD STORE OK"


class Definition:
    """One `def`, where it is and whether it says it is deliberately kept."""

    def __init__(
        self,
        name: str,
        path: pathlib.Path,
        lineno: int,
        class_name: str | None,
        documented: bool,
        called_by_decorator: bool = False,
    ) -> None:
        self.name = name
        self.path = path
        self.lineno = lineno
        self.class_name = class_name
        self.documented = documented
        self.called_by_decorator = called_by_decorator

    def __str__(self) -> str:
        where = f"{self.class_name}.{self.name}" if self.class_name else self.name
        return f"{self.path}:{self.lineno} {where}"


class Collector(ast.NodeVisitor):
    """Collect definitions, and the references made inside each one."""

    def __init__(
        self,
        path: pathlib.Path,
    ) -> None:
        self.path = path
        self.definitions: dict[str, Definition] = {}
        self.references_in: dict[str, set[str]] = {}
        self.module_references: set[str] = set()

        self._class_stack: list[str] = []
        self._function_stack: list[str] = []

    def visit_ClassDef(
        self,
        node: ast.ClassDef,
    ) -> None:
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(
        self,
        node: ast.FunctionDef,
    ) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(
        self,
        node: ast.AsyncFunctionDef,
    ) -> None:
        self._visit_function(node)

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        # the marker may follow a summary line, so look anywhere in the docstring
        doc = ast.get_docstring(node) or ""
        self.definitions.setdefault(
            node.name,
            Definition(
                name=node.name,
                path=self.path,
                lineno=node.lineno,
                class_name=self._class_stack[-1] if self._class_stack else None,
                documented=NOT_CALLED_MARKER in doc,
                called_by_decorator=has_entry_point_decorator(node),
            ),
        )

        self._function_stack.append(node.name)
        self.generic_visit(node)
        self._function_stack.pop()

    def _use(
        self,
        name: str,
    ) -> None:
        if self._function_stack:
            self.references_in.setdefault(self._function_stack[-1], set()).add(name)
            return
        self.module_references.add(name)

    def visit_Attribute(
        self,
        node: ast.Attribute,
    ) -> None:
        self._use(node.attr)
        self.generic_visit(node)

    def visit_Name(
        self,
        node: ast.Name,
    ) -> None:
        self._use(node.id)
        self.generic_visit(node)

    def visit_Constant(
        self,
        node: ast.Constant,
    ) -> None:
        # a name used as a string: getattr(o, "x"), a dispatch table, a mark
        if isinstance(node.value, str):
            self._use(node.value)


class DeadStore:
    """A value assigned and then replaced on every path before anything reads it."""

    def __init__(
        self,
        name: str,
        path: pathlib.Path,
        lineno: int,
        function: str,
        documented: bool,
    ) -> None:
        self.name = name
        self.path = path
        self.lineno = lineno
        self.function = function
        self.documented = documented

    def __str__(self) -> str:
        return f"{self.path}:{self.lineno} {self.function}() assigns {self.name}, then replaces it"


def assigned_name(
    node: ast.stmt,
) -> str | None:
    """The plain local name this statement assigns, if that is all it does."""
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        if isinstance(target, ast.Name):
            return target.id
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
        return node.target.id

    return None


def reads(
    node: ast.AST,
    name: str,
) -> bool:
    """Does this node read `name` anywhere, rather than only assign to it?"""
    for inner in ast.walk(node):
        if isinstance(inner, ast.Name) and inner.id == name and isinstance(inner.ctx, ast.Load):
            return True

    return False


def replaces_before_reading(
    branch: list[ast.stmt],
    name: str,
) -> bool:
    """Does this branch assign `name` before anything in it reads `name`?"""
    for statement in branch:
        if assigned_name(statement) == name and not reads(statement, name):
            return True
        if reads(statement, name):
            return False

    return False


def dead_stores_in(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    path: pathlib.Path,
    lines: list[str],
) -> list[DeadStore]:
    """Assignments whose value cannot reach a reader.

    Two shapes only, both narrow enough to be right rather than merely suggestive:

      x = a        immediately followed by  x = b
      x = a        immediately followed by  if ...: x = b   else: x = c

    In the second, both branches must assign before reading, so every path
    replaces the value. This is the shape that hid `is_uploaded` in the docker
    processor: computed in one method, carried through a dict, and overwritten on
    arrival by the only thing that actually knew the answer.
    """
    found: list[DeadStore] = []

    for node in ast.walk(function):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue

        for index, statement in enumerate(body[:-1]):
            name = assigned_name(statement)
            if name is None:
                continue

            following = body[index + 1]

            replaced = False
            if assigned_name(following) == name and not reads(following, name):
                replaced = True
            elif isinstance(following, ast.If) and following.orelse:
                replaced = replaces_before_reading(following.body, name) and replaces_before_reading(
                    following.orelse,
                    name,
                )

            if not replaced:
                continue

            comment = lines[statement.lineno - 1] if statement.lineno <= len(lines) else ""
            found.append(
                DeadStore(
                    name=name,
                    path=path,
                    lineno=statement.lineno,
                    function=function.name,
                    documented=DEAD_STORE_MARKER in comment,
                ),
            )

    return found


def dead_stores(
    paths: list[pathlib.Path],
) -> list[DeadStore]:
    found: list[DeadStore] = []

    for path in paths:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()

        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found += dead_stores_in(node, path, lines)

    return sorted(found, key=lambda item: (str(item.path), item.lineno))


def python_files(
    roots: Iterable[str],
) -> Iterator[pathlib.Path]:
    seen: set[pathlib.Path] = set()

    for root in roots:
        base = pathlib.Path(root)
        if not base.exists():
            continue

        found = base.glob("*.py") if base in FLAT_ROOTS else base.rglob("*.py")
        for path in found:
            if "__pycache__" in path.parts:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            yield path


def has_entry_point_decorator(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    """A decorator that makes something else call this, e.g. @pytest.fixture."""
    for decorator in node.decorator_list:
        for inner in ast.walk(decorator):
            name = ""
            if isinstance(inner, ast.Name):
                name = inner.id
            elif isinstance(inner, ast.Attribute):
                name = inner.attr

            if any(part in name.lower() for part in ENTRY_POINT_DECORATOR_PARTS):
                return True

    return False


def is_entry_point(
    name: str,
) -> bool:
    """Called by something other than a reference to its name in this repository."""
    return name.startswith(ENTRY_POINT_PREFIXES) or name in ENTRY_POINT_NAMES


def unreachable_definitions(
    paths: list[pathlib.Path],
) -> list[Definition]:
    definitions: dict[str, Definition] = {}
    references_in: dict[str, set[str]] = {}
    module_references: set[str] = set()

    for path in paths:
        collector = Collector(path)
        collector.visit(ast.parse(path.read_text(encoding="utf-8")))

        for name, definition in collector.definitions.items():
            definitions.setdefault(name, definition)
        for name, used in collector.references_in.items():
            references_in.setdefault(name, set()).update(used)
        module_references.update(collector.module_references)

    live: set[str] = {
        n for n, d in definitions.items() if is_entry_point(n) or d.called_by_decorator or n in module_references
    }

    frontier: set[str] = set(live)
    while frontier:
        following: set[str] = set()
        for name in frontier:
            for referenced in references_in.get(name, set()):
                if referenced in definitions and referenced not in live:
                    live.add(referenced)
                    following.add(referenced)
        frontier = following

    return [definitions[n] for n in sorted(definitions) if n not in live]


def unused_constants(
    paths: list[pathlib.Path],
    constants_file: pathlib.Path,
) -> list[tuple[str, int, bool]]:
    if not constants_file.exists():
        return []

    lines = constants_file.read_text(encoding="utf-8").splitlines()
    tree = ast.parse("\n".join(lines))

    declared: dict[str, int] = {}
    for statement in tree.body:
        name: str | None = None
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            name = statement.target.id
        elif (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            name = statement.targets[0].id

        if name is not None and name.isupper():
            declared[name] = statement.lineno

    counted: dict[str, int] = {}
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            key: str | None = None
            if isinstance(node, ast.Name):
                key = node.id
            elif isinstance(node, ast.Attribute):
                key = node.attr
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                key = node.value

            if key is not None:
                counted[key] = counted.get(key, 0) + 1

    out: list[tuple[str, int, bool]] = []
    for name, lineno in sorted(declared.items(), key=lambda item: item[1]):
        if counted.get(name, 0) > 1:  # more than its own definition
            continue

        # one comment may head a group of constants, so look back to the blank
        # line that starts the block
        documented = False
        index = lineno - 1
        while index >= 0 and lines[index].strip():
            if NOT_USED_MARKER in lines[index]:
                documented = True
                break
            index -= 1

        out.append((name, lineno, documented))

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non zero on anything unreachable that is not documented as deliberate",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=list(DEFAULT_ROOTS),
        help="roots to scan (default: the whole repository)",
    )
    args = parser.parse_args()

    paths = list(python_files(args.paths))
    if not paths:
        print("no python files found", file=sys.stderr)
        return 2

    definitions = unreachable_definitions(paths)
    constants = unused_constants(paths, pathlib.Path(CONSTANTS_FILE))
    stores = dead_stores(paths)

    undocumented = 0

    print(f"unreachable definitions: {len(definitions)}")
    for definition in definitions:
        mark = " " if definition.documented else "!"
        if not definition.documented:
            undocumented += 1
        print(f" {mark} {definition}")

    print(f"\nunused constants: {len(constants)}")
    for name, lineno, documented in constants:
        mark = " " if documented else "!"
        if not documented:
            undocumented += 1
        print(f" {mark} {CONSTANTS_FILE}:{lineno} {name}")

    print(f"\ndead stores: {len(stores)}")
    for store in stores:
        mark = " " if store.documented else "!"
        if not store.documented:
            undocumented += 1
        print(f" {mark} {store}")

    if undocumented:
        print(
            f"\n{undocumented} item(s) marked '!' are unreachable and say nothing about it.",
            "Either delete them, or say why they are kept: a docstring starting",
            "'NOT CALLED', a '# NOT USED' comment on a constant, or a",
            "'# DEAD STORE OK' comment on an assignment that is deliberate.",
            sep="\n",
        )

    if args.strict and undocumented:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
