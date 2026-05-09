"""Demo entry point for the audio module.

Lets the developer hear synthesised CW from the command line::

    python -m copy_653.audio.demo K
    python -m copy_653.audio.demo KMK

Everything runs with default :class:`AudioParameters`. Provided as a
verification path for the audio module — not a learner-facing
feature.
"""

from __future__ import annotations

import argparse

from copy_653.audio import playback, synth
from copy_653.audio.parameters import AudioParameters


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: parse args, synthesise, play."""
    parser = argparse.ArgumentParser(
        prog="copy_653.audio.demo",
        description="Synthesise and play one or more CW symbols.",
    )
    parser.add_argument(
        "symbols",
        help="A string of symbols to play, e.g. 'K' or 'KMK'.",
    )
    args = parser.parse_args(argv)

    params = AudioParameters()
    samples = synth.synthesize_sequence(list(args.symbols), params)
    playback.play(samples, params)


if __name__ == "__main__":
    main()
