"""
backend/main.py — Compatibility shim.

The application has been restructured so that:
  - app.py     (project root) = FastAPI application object and startup logic
  - main.py    (project root) = server launcher (run with: python main.py)

This file exists only to preserve import compatibility for any code that
references backend.main directly (e.g. legacy test helpers).

For all new code, import from the project root:
    from app import app, create_app
"""

from app import app, create_app, _startup as startup  # noqa: F401

__all__ = ["app", "create_app", "startup"]
