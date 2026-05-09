"""Demo entry point for the audio module.

Lets the developer hear synthesised CW from the command line::

    python -m copy_653.audio.demo K
    python -m copy_653.audio.demo KMK
    python -m copy_653.audio.demo K --config /tmp/test_config.toml

Audio parameters are loaded from the config file (see
:mod:`copy_653.config`) — if no config exists, defaults from
:class:`AudioParameters` are used. The ``--config`` flag overrides
the default location for one-off experiments.

Provided as a verification path for the audio module — not a
learner-facing feature.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from copy_653.audio import playback, synth
from copy_653.config import load_audio_parameters


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: parse args, load config, synthesise, play."""
    parser = argparse.ArgumentParser(
        prog="copy_653.audio.demo",
        description="Synthesise and play one or more CW symbols.",
    )
    parser.add_argument(
        "symbols",
        help="A string of symbols to play, e.g. 'K' or 'KMK'.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=(
            "Path to a TOML config file. Defaults to "
            "~/.local/share/copy_653/config.toml; missing file is fine "
            "(falls back to AudioParameters defaults)."
        ),
    )
    args = parser.parse_args(argv)

    params = load_audio_parameters(args.config)
    samples = synth.synthesize_sequence(list(args.symbols), params)
    playback.play(samples, params)


if __name__ == "__main__":
    main()
