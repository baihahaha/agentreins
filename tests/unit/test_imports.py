"""Every module imports cleanly (catches circular imports and runtime-only type errors)."""

import importlib
import pkgutil

import pytest

import agentreins

MODULES = sorted(m.name for m in pkgutil.walk_packages(agentreins.__path__, "agentreins."))


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name: str) -> None:
    importlib.import_module(name)
