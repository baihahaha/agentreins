"""Enforces the dependency rule in ARCHITECTURE.md and the core dependency policy.

A layer may only import from layers below it; core code may only use the standard
library and pydantic. This test fails CI if a module breaks either rule.
"""

import ast
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "agentreins"

ENGINES = {"tools", "context", "ledger"}
ALLOWED: dict[str, set[str]] = {
    "types": {"types"},
    "ports": {"types", "ports"},
    **{engine: {"types", "ports", *ENGINES} for engine in ENGINES},
    "runtime": {"types", "ports", *ENGINES, "runtime"},
    "session": {"types", "ports", *ENGINES, "runtime", "session"},
    "adapters": {"types", "ports", "adapters"},
    "testing": {"types", "ports", "adapters", "testing"},
}
CORE = set(ALLOWED) - {"adapters", "testing"}
CORE_THIRD_PARTY = {"pydantic"}


def _modules() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if p.parent != SRC)


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


@pytest.mark.parametrize("path", _modules(), ids=lambda p: str(p.relative_to(SRC)))
def test_module_respects_layers(path: Path) -> None:
    layer = path.relative_to(SRC).parts[0]
    assert layer in ALLOWED, f"unknown package {layer!r}: add it to ARCHITECTURE.md and this test"
    for name in _imports(path):
        parts = name.split(".")
        if parts[0] == "agentreins":
            target = parts[1] if len(parts) > 1 else "<public api>"
            assert target in ALLOWED[layer], f"{layer} must not import agentreins.{target}"
        elif layer in CORE:
            assert parts[0] in sys.stdlib_module_names | CORE_THIRD_PARTY, (
                f"core module imports third-party {parts[0]!r}; use an optional extra instead"
            )
