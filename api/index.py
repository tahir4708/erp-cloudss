"""Vercel serverless entry point.

Vercel's @vercel/python runtime detects the ASGI ``app`` object exported here
and serves it as a serverless function. All ``/api/*`` routes are handled by
this FastAPI app; the static frontend is served directly by Vercel (see
``vercel.json``).
"""

import os
import sys

# Ensure the repo root is importable so ``backend`` resolves as a package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.main import app  # noqa: E402

__all__ = ["app"]
