# SPDX-License-Identifier: GPL-3.0-or-later
"""Production ownership and file conventions, independent of runtime imports."""

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1] / "src" / "stenographer"


def _sources():
    return [p for p in ROOT.rglob("*.py") if "protocols" not in p.parts]


def _import_names(node, path):
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if not isinstance(node, ast.ImportFrom):
        return []
    module = node.module or ""
    if node.level:
        package = ("stenographer", *path.relative_to(ROOT).parent.parts)
        prefix = package[: len(package) - node.level + 1]
        module = ".".join((*prefix, module)) if module else ".".join(prefix)
    return [module, *(f"{module}.{alias.name}" for alias in node.names)]


def test_production_has_only_responsibility_roots():
    assert {p.name for p in ROOT.glob("*.py")} == {"__init__.py", "_version.py"}
    assert {p.name for p in ROOT.iterdir() if p.is_dir() and p.name != "__pycache__"} == {
        "lib",
        "cli",
        "overlay",
        "assets",
    }


def test_library_does_not_import_frontends():
    violations = []
    for path in (ROOT / "lib").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = _import_names(node, path)
            if any(name.startswith(("stenographer.cli", "stenographer.overlay")) for name in names):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not violations, violations


def test_native_modules_are_only_imported_inside_platform_boundaries():
    native = {
        "evdev",
        "pywayland",
        "Xlib",
        "fcntl",
        "termios",
        "pty",
        "pwd",
        "grp",
        "winreg",
        "msvcrt",
        "win32api",
        "AppKit",
    }
    violations = []
    for path in _sources():
        if "platform" in path.relative_to(ROOT).parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names = _import_names(node, path)
            if any(name.split(".")[0] in native for name in names):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            if any(
                name.startswith(
                    (
                        "stenographer.lib.platform.linux",
                        "stenographer.lib.platform.windows",
                        "stenographer.lib.platform.macos",
                        "stenographer.overlay.platform.linux",
                        "stenographer.overlay.platform.windows",
                        "stenographer.overlay.platform.macos",
                    )
                )
                for name in names
            ):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not violations, violations


def test_ordinary_classes_have_dedicated_files():
    violations = []
    for path in _sources():
        tree = ast.parse(path.read_text())
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
        ordinary = []
        for cls in classes:
            dataclass = any("dataclass" in ast.unparse(d) for d in cls.decorator_list)
            exception = cls.name.endswith("Error") or any(
                ast.unparse(b) in {"Exception", "BaseException"} for b in cls.bases
            )
            if exception:
                if path.name != "errors.py":
                    violations.append(f"{path.relative_to(ROOT)}: exception {cls.name}")
            elif not dataclass:
                ordinary.append(cls)
        if ordinary and (len(classes) != 1 or functions):
            violations.append(f"{path.relative_to(ROOT)}: ordinary class shares definitions")
        if any(isinstance(n, ast.ClassDef) and n not in classes for n in ast.walk(tree)):
            violations.append(f"{path.relative_to(ROOT)}: nested class")
    assert not violations, violations
