#!/usr/bin/env python3
"""
Iteration Wallet — Launcher
============================
Starts the FastAPI server and opens the UI in the default browser.

Usage:
    python app.py            # start on default port 7432
    python app.py --port 8080
    python app.py --no-browser
"""

import argparse
import logging
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from iteration_wallet.network_policy import NetworkPolicyError, require_loopback_host

# Source-bundle launch supports the bundled, independently versioned BlackBox
# source tree. Installed distributions resolve the pinned companion wheel.
SOURCE_ROOT = Path(__file__).resolve().parent
BLACKBOX_SOURCE = SOURCE_ROOT / "blackbox_source"
if BLACKBOX_SOURCE.is_dir():
    sys.path.insert(0, str(BLACKBOX_SOURCE))
sys.path.insert(0, str(SOURCE_ROOT))


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("iw.launcher")


def _open_browser(url: str, delay: float = 1.2) -> None:
    """Open the UI after a short delay to let the server start."""
    time.sleep(delay)
    webbrowser.open(url)



def _verify_companion_dependency() -> None:
    """Fail before the browser opens if the exact BlackBox companion is absent."""
    from iteration_wallet.version import BLACKBOX_CLIENT_SCHEMA, BLACKBOX_VERSION

    try:
        from blackbox_plugin import CLIENT_SCHEMA_VERSION, __version__ as installed_version
    except Exception as exc:
        raise SystemExit(
            "Iteration Wallet requires its bundled/pinned BlackBox companion. "
            "Run START_ITERATION_WALLET.bat or START_ITERATION_WALLET.ps1, or install "
            "the two release wheels together."
        ) from exc
    if installed_version != BLACKBOX_VERSION or CLIENT_SCHEMA_VERSION != BLACKBOX_CLIENT_SCHEMA:
        raise SystemExit(
            "BlackBox companion mismatch: "
            f"expected {BLACKBOX_VERSION} / {BLACKBOX_CLIENT_SCHEMA}, "
            f"found {installed_version} / {CLIENT_SCHEMA_VERSION}."
        )

def main() -> None:
    _verify_companion_dependency()
    parser = argparse.ArgumentParser(description="Iteration Wallet")
    parser.add_argument("--port", type=int, default=7432, help="Port to listen on (default: 7432)")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser automatically")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev mode)")
    args = parser.parse_args()

    try:
        bind_host, browser_host = require_loopback_host(args.host)
    except NetworkPolicyError as exc:
        parser.error(str(exc))
    url = f"http://{browser_host}:{args.port}"
    runtime_root = Path(os.environ.get("ITERATION_WALLET_ROOT", Path(__file__).parent / "wallet_home")).expanduser().resolve()
    os.environ["ITERATION_WALLET_ROOT"] = str(runtime_root)
    os.environ.setdefault("IW_OUBLIETTE_MODE", "disabled")
    os.environ.setdefault("IW_REQUIRE_PASSKEY", "required")
    os.environ["IW_WEBAUTHN_RP_ID"] = browser_host
    os.environ["IW_WEBAUTHN_ORIGINS"] = url

    print()
    print("  ⚿  Iteration Wallet — Rear View Foresight")
    print(f"     Vault UI  →  {url}")
    print(f"     API docs  →  {url}/docs")
    print()

    if not args.no_browser:
        t = threading.Thread(target=_open_browser, args=(url,), daemon=True)
        t.start()

    uvicorn.run(
        "iteration_wallet.server:app",
        host=bind_host,
        port=args.port,
        reload=args.reload,
        log_level="warning",  # suppress uvicorn noise; our logs handle it
    )


if __name__ == "__main__":
    main()
