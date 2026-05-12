"""Entry point for ``python -m copy_653``.

Starts the engine: HTTP + WebSocket on localhost, audio out via
PortAudio. MIDI in is not yet wired (spec §8.1; see ``copy_653.midi``).
"""

from __future__ import annotations

import argparse
import asyncio

from copy_653.server import DEFAULT_PORT, DEFAULT_PORT_SEARCH_SPAN, run


def main() -> None:
    """Parse CLI options and run the Copy engine until interrupted."""
    parser = argparse.ArgumentParser(prog="copy-653", description="Copy engine.")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=(
            f"Localhost port to bind. Default {DEFAULT_PORT}. "
            f"If in use, the engine searches upward by up to "
            f"{DEFAULT_PORT_SEARCH_SPAN} ports before giving up."
        ),
    )
    parser.add_argument(
        "--port-search-span",
        type=int,
        default=DEFAULT_PORT_SEARCH_SPAN,
        help="How many consecutive ports to try before failing.",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run(port=args.port, port_search_span=args.port_search_span))
    except KeyboardInterrupt:
        # Ctrl-C is the documented way to stop the engine in v0;
        # surface it as a clean exit rather than a stack trace.
        pass


if __name__ == "__main__":
    main()
