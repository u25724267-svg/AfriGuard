"""
Safe environment loading for AfriGuard.

Only the project-root `.env` is loaded. Existing process environment values win,
so CI, Docker, and shell-provided secrets cannot be silently overwritten by a
local file.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ENV_PATH = PROJECT_ROOT / ".env"


def load_project_env(env_path: Path | None = None) -> bool:
    """
    Load AfriGuard's project-root `.env` file if present.

    Args:
        env_path: Optional explicit path, mainly for tests.

    Returns:
        True if a dotenv file was found and loaded, otherwise False.
    """
    path = env_path or PROJECT_ENV_PATH
    if not path.exists():
        return False

    load_dotenv(dotenv_path=path, override=False)
    return True
