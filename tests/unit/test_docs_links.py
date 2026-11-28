"""Links in the docs point to files that exist, and line links stay inside the file.

Catches docs left behind when code moves: a line link into a Python file must land on a
definition (``def``, ``class``, an assignment). It cannot tell whether it is the *right*
definition; updating the internals page in the same PR as the code is the rule for that
(CLAUDE.md).
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PAGES = sorted([*ROOT.glob("docs/**/*.md"), *ROOT.glob("*.md")])
# def / class / decorator at any indent, or an assignment at the start of a line
# (an indented "name=value" is a keyword argument, not a definition).
DEFINITION = re.compile(r"\s*(async def|def|class)\s+\w+|\s*@|\w+\s*(:[^=]*)?=")
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
            lines = path.read_text().splitlines()
            assert int(line) <= len(lines), f"{target}#L{line}: file has only {len(lines)} lines"
            if path.suffix == ".py":
                text = lines[int(line) - 1]
                assert DEFINITION.match(text), (
                    f"{target}#L{line} points at {text.strip()[:60]!r}, not a definition: "
                    "the code moved, update the link"
                )
