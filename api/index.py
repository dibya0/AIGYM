"""Vercel entry point: the sandbox API at /api/* (the dashboard is the static public/ directory)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # import paygym from the repo (bundled via includeFiles)

from paygym.sandbox.app import app  # noqa: E402,F401
