# Changelog

All notable changes to this project are documented in this file.

## [0.4.0] - 2026-03-09

### Added

- Web-managed Telegram runtime configuration stored outside the public output directory.
- Telegram progress push updates during download/transcription phases.
- History pagination, search, filtering, and deletion support in the Web API.
- Web API tests for history listing, deletion, and Telegram settings management.

### Changed

- Web UI moved from a single overloaded panel to a lightweight workspace layout:
  task center, history, and system settings.
- Job detail area now supports deleting finished jobs and triggering secondary transcription.
- Telegram bot can now be started and stopped from the Web UI.

## [0.3.0] - 2026-03-09

### Added

- Docker deployment files: `Dockerfile`, `docker-compose.yml`, and `.dockerignore`.
- GitHub issue templates and pull request template.
- Structured error classification with user-facing hints for common download and transcription failures.
- Error classification tests.

### Changed

- Web UI now returns structured API errors with `error_code` and `error_hint`.
- Web result panel now shows user-facing hints and expandable technical details.
- Telegram bot now sends friendlier failure messages with hints when available.
- Export script now includes Docker and repository-governance files.

## [0.2.0] - 2026-03-09

### Added

- GitHub Actions CI for compile checks and unit tests.
- GitHub Release workflow triggered by `v*` tags.
- `CONTRIBUTING.md` for local setup, checks, and release steps.
- Web API tests for job creation and re-transcription flow.
- Telegram bot routing tests for authorization, `/web`, and valid-link handling.

### Changed

- Transcription output now applies simplified-Chinese normalization and a small mainland wording normalization layer.
- Package version is now sourced as `0.2.0`.
- FastAPI app version now follows the package version.

## [0.1.0] - 2026-03-09

### Added

- CLI, Web UI, and Telegram bot entry points.
- Douyin download pipeline with browser-assisted fallback.
- Local file-based job manifests and transcription pipeline.
