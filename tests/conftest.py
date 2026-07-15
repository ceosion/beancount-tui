import shutil
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).parent.parent / "examples" / "example.beancount"


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    """A throwaway copy of the example ledger, safe to mutate."""
    path = tmp_path / "ledger.beancount"
    shutil.copy(EXAMPLE, path)
    return path
