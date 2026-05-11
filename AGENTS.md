# Repository Guidelines

## Project Structure & Module Organization

This repository is the Copy component of the broader `/srv/work/malloc-labs` workspace. It contains the `copy-653` Python package and a static browser UI. Python source lives in `src/copy_653/`: audio synthesis is under `audio/`, HTTP/WebSocket serving under `server/`, sequence logic under `sequence/`, and letter/audio helpers under `letters/`. Tests mirror those areas in `tests/`. Static pages and scripts live in `web/`, shared CSS in `web/css/`, documentation in `docs/`, and audio/font assets in `assets/`.

## Build, Test, and Development Commands

- `source /srv/work/malloc-labs/venvs/ml-copy-653/bin/activate`: use the shared project venv for local work.
- `pip install -e ".[dev]"`: refresh the package plus pytest tooling when dependencies change.
- `python -m copy_653`: start the local engine; it binds to `127.0.0.1:8653` or the next available port.
- `python -m copy_653 --port 9000`: run the server on a specific port.
- `pytest`: run the full test suite.
- `ruff check src tests` and `black --check src tests`: match CI lint and formatting checks.
- `pre-commit run --all-files`: run all repository hooks, including Black, Ruff, markdownlint, YAML formatting, and gitleaks.

## Coding Style & Naming Conventions

Target Python 3.11+. Format Python with Black at 100 columns and lint with Ruff, as configured in `pyproject.toml`. Use 4-space indentation, `snake_case` for functions/modules, `PascalCase` for classes, and descriptive test names such as `test_rejects_unknown_symbol`. The importable package is `copy_653`; the distribution and CLI use `copy-653`.

## Testing Guidelines

Use pytest. Keep tests close to the subsystem they validate and name files `test_*.py`. Add or update tests for behavioral changes, especially audio parameter validation, sequence generation, WebSocket protocol behavior, and symbol/audio mapping. CI runs pytest on Python 3.11, 3.12, and 3.13.

## Commit & Pull Request Guidelines

Recent history follows Conventional Commits, for example `feat(web): ...`, `fix(server): ...`, `style: ...`, and `chore(assets): ...`. Keep commits scoped and imperative. Pull requests should describe the change, note test commands run, link issues when applicable, and include screenshots or browser notes for UI changes.

## Security & Configuration Tips

Do not commit secrets or local config; gitleaks runs in hooks and CI. Audio playback uses sustained tones, so keep hardware volume low when testing playback, especially with headphones. Local runtime config belongs under `~/.local/share/copy_653/config.toml`, not in the repository.
