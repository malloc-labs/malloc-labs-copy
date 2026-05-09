# Copy

A CW (morse code) listening environment. Audio-first, deferred verification, structurally absent mentor. The notebook is part of the system.

This is the implementation home for **Copy**, part of [Malloc Labs](https://malloc.org.uk).

## Design

- [docs/philosophy.md](docs/philosophy.md) — design contracts and methodology
- [docs/specification.md](docs/specification.md) — v0 system specification

## Run

```sh
git clone git@github.com:malloc-labs/malloc-labs-copy.git
cd malloc-labs-copy
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m copy_653
```

The engine is not yet implemented. The current scaffold runs `python -m copy_653` and prints a banner, verifying the package layout loads.

## Naming

The package is named `copy_653`; the distribution is `copy-653`. See [docs/specification.md](docs/specification.md) §10.1 for the convention.

## License

[GPL-3.0-or-later](LICENSE).
