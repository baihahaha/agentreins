"""Links in the docs point to files that exist, and line links stay inside the file.

Catches docs left behind when code is moved or shortened. It cannot tell whether a
line link still points at the *right* line; updating the internals page in the same PR
as the code is the rule for that (CLAUDE.md).
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PAGES = sorted([*ROOT.glob("docs/**/*.md"), *ROOT.glob("*.md")])
LINK = re.compile(r"\]\(([^)#\s]+)(?:#L(\d+)(?:-L\d+)?)?\)")


def _local_links(page: Path) -> list[tuple[str, str | None]]:
    links = [(m.group(1), m.group(2)) for m in LINK.finditer(page.read_text())]
    return [(t, line) for t, line in links if "://" not in t and not t.startswith("mailto:")]


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(ROOT)))
def test_local_links_resolve(page: Path) -> None:
    for target, line in _local_links(page):
        path = (page.parent / target).resolve()
        assert path.exists(), f"{target} does not exist"
        if line is not None:
            lines = len(path.read_text().splitlines())
            assert int(line) <= lines, f"{target}#L{line}: file has only {lines} lines"
