"""Every offline example runs (examples ending in _live.py need a real provider)."""

import runpy
from pathlib import Path

import pytest

EXAMPLES = sorted(
    p
    for p in (Path(__file__).resolve().parents[2] / "examples").glob("*.py")
    if not p.stem.endswith("_live")
)


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda p: p.name)
def test_example_runs(
    example: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)  # examples may create agentreins.db
    runpy.run_path(str(example), run_name="__main__")
    assert capsys.readouterr().out.strip()
