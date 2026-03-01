"""
main.py — Server launcher and entry point.

Run this file to start the SIET server and open the dashboard automatically:

    python main.py

The dashboard will open at http://127.0.0.1:8000/dashboard

This file does NOT contain application logic. See app.py for the FastAPI
application, service wiring, and startup sequence.

Direct uvicorn usage (without browser auto-open):
    uvicorn app:app --reload
"""

from __future__ import annotations

import threading
import time
import webbrowser

import uvicorn


DASHBOARD_URL = "http://127.0.0.1:8000/dashboard"
HOST = "127.0.0.1"
PORT = 8000


def _open_browser_after_startup(delay_seconds: float = 2.0) -> None:
    """
    Open the dashboard in the default browser after a short delay.

    The delay allows uvicorn to complete startup (schema init, model training)
    before the browser hits the server for the first time.
    """
    time.sleep(delay_seconds)
    print(f"\n  Opening dashboard → {DASHBOARD_URL}\n")
    webbrowser.open(DASHBOARD_URL)


def main() -> None:
    """Start the SIET server and open the admin dashboard."""
    print("=" * 60)
    print("  SIET — Space Utilisation Digital Twin")
    print("=" * 60)
    print(f"  Server  : http://{HOST}:{PORT}")
    print(f"  Dashboard: {DASHBOARD_URL}")
    print(f"  API docs : http://{HOST}:{PORT}/docs")
    print("=" * 60)
    print("  Press CTRL+C to stop\n")

    # Open browser in background thread after startup completes
    browser_thread = threading.Thread(
        target=_open_browser_after_startup,
        daemon=True,
    )
    browser_thread.start()

    # Start uvicorn — this blocks until CTRL+C
    uvicorn.run(
        "app:app",       # points to app.py → app object
        host=HOST,
        port=PORT,
        reload=True,     # hot-reload on file changes during development
        log_level="info",
    )


if __name__ == "__main__":
    main()
