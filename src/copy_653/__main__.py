"""Entry point for ``python -m copy_653``.

Starts the engine: HTTP + WebSocket on a local bind address, audio out via
PortAudio, and optional MIDI key input via ``copy_653.midi``.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from copy_653.config import DEFAULT_CONFIG_PATH
from copy_653.server import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_PORT_SEARCH_SPAN, run


def main() -> None:
    """Parse CLI options and run the Copy engine until interrupted."""
    parser = argparse.ArgumentParser(prog="copy-653", description="Copy engine.")
    parser.add_argument(
        "--host",
        "--listen",
        dest="host",
        default=None,
        help=(
            f"Host/interface to bind. Config default {DEFAULT_HOST}. "
            "Use 0.0.0.0 for LAN browser testing."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=(
            f"Port to bind. Config default {DEFAULT_PORT}. "
            f"If in use, the engine searches upward by up to "
            f"{DEFAULT_PORT_SEARCH_SPAN} ports before giving up."
        ),
    )
    parser.add_argument(
        "--port-search-span",
        type=int,
        default=None,
        help=(
            "How many consecutive ports to try before failing. "
            f"Config default {DEFAULT_PORT_SEARCH_SPAN}."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Config file to read. Default {DEFAULT_CONFIG_PATH}.",
    )
    args = parser.parse_args()

    try:
        asyncio.run(
            run(
                port=args.port,
                port_search_span=args.port_search_span,
                host=args.host,
                config_path=args.config,
            )
        )
    except KeyboardInterrupt:
        # Ctrl-C is the documented way to stop the engine in v0;
        # surface it as a clean exit rather than a stack trace.
        pass


if __name__ == "__main__":
    main()
