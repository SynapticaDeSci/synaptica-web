import os
import tempfile
from pathlib import Path
import sys

import pytest

# Ensure `uv run pytest tests` can import the repo-root Python packages.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Configure isolated SQLite database and Pinata credentials before app imports
_temp_dir = Path(tempfile.mkdtemp(prefix="providai-tests-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_temp_dir / 'test.db'}")
os.environ.setdefault("PINATA_API_KEY", "test-api-key")
os.environ.setdefault("PINATA_SECRET_KEY", "test-secret-key")
os.environ.setdefault("AGENT_SUBMIT_ALLOW_HTTP", "1")


@pytest.fixture(scope="session", autouse=True)
def _prepare_database():
    """Create all tables in the isolated SQLite database."""
    from shared.database import Base, engine

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
