"""Settings, read from environment variables (or a .env file in the project root)."""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional; plain env vars still work
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and edit it.")
    return url


def raw_data_dir() -> Path:
    path = Path(os.environ.get("RAW_DATA_DIR", PROJECT_ROOT / "data" / "raw"))
    path.mkdir(parents=True, exist_ok=True)
    return path
