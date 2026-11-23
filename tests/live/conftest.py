"""Live tests call real providers. They run only with ``pytest -m live``.

The key comes from the environment (CI: a repository secret) or, locally, from the
git-ignored ``.env`` file at the repo root. Without a key, live tests are skipped.
"""

import os
from pathlib import Path

import pytest

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _load_dotenv(path: Path) -> None:
    """Read ``KEY=value`` lines into the environment, never overriding what is set."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and name and not name.startswith("#"):
            os.environ.setdefault(name.strip(), value.strip())


_load_dotenv(ENV_FILE)


@pytest.fixture
def openai_api_key() -> str:
    """The OpenAI key for live tests; skips the test when none is configured."""
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        pytest.skip("OPENAI_API_KEY is not set (environment or .env)")
    return key
