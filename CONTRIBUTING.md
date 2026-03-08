# Contributing

## Development Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .[web,asr]
```

Optional local tools:

- `ffmpeg`
- `yt-dlp`

## Project Layout

- `src/douyin_pipeline/`: runtime code
- `tests/`: unit and interface-level tests
- `.github/workflows/`: CI and release workflows
- `scripts/`: local maintenance scripts

## Before Opening a Pull Request

Run these checks locally:

```bash
python -m compileall src tests
python -m unittest discover -s tests -v
python -m douyin_pipeline doctor --skip-asr
```

If you changed transcription logic, also verify one real Chinese sample manually.

## Coding Rules

- Keep the project lightweight.
- Prefer small, explicit modules over generic abstractions.
- Do not add scraping or anti-detection features outside the documented project boundary.
- Preserve Python `>=3.9` compatibility.

## Commit Scope

- Keep commits narrow and reviewable.
- Separate runtime behavior changes from docs-only changes when practical.

## Release Process

1. Update version in `pyproject.toml` and `src/douyin_pipeline/__init__.py`.
2. Update `CHANGELOG.md`.
3. Run local checks.
4. Merge to `main`.
5. Create and push a tag like `v0.2.0`.

Pushing a `v*` tag triggers the GitHub Release workflow.
