"""ASGI entrypoint for `uvicorn main:app --reload`."""

from backend.main import app


__all__ = ["app"]
