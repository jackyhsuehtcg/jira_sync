# Project Context

## Purpose
A one-way synchronization system that copies JIRA issues into Lark Base (Bitable)
with batch processing, multi-team configuration, dynamic field mapping, and
optional web/TUI tooling for monitoring and management.

## Tech Stack
- Python 3.8+
- Flask + Jinja2 templates for the web admin UI
- requests for HTTP, PyYAML + ruamel.yaml for config, watchdog for hot-reload
- SQLite for local caches/metrics/logs in data/
- HTML/CSS with Bootstrap 5 and Font Awesome in the web UI
- asyncio + curses for the sync monitor TUI

## Project Conventions

### Code Style
- Python modules are snake_case; classes are PascalCase
- Type hints are used in core modules; dataclasses used for config/result objects
- Docstrings use triple quotes; logging via logger module and per-component names
- Configuration lives in YAML files: config.yaml and schema.yaml

### Architecture Patterns
- Modular pipeline: SyncCoordinator -> SyncWorkflowManager -> SyncBatchProcessor
- Separate client layers for JIRA and Lark; processors for fields and users
- Config-driven behavior via config.yaml and schema.yaml (dynamic field mapping)
- Batch create/update for Lark with automatic splitting to respect API limits

### Testing Strategy
- No dedicated test suite checked in; pytest is listed as an optional dependency
- Validate behavior via CLI commands and dry-run mode before production runs
- Web UI provides config validation and operational tooling

### Git Workflow
- TBD: branching strategy, PR requirements, and commit message conventions

## Domain Context
- Sync direction is JIRA -> Lark Base only; Lark edits can be overwritten
- JQL is provided directly per table in config.yaml (no auto-composed filters)
- Lark Base tables are per team and per table; supports multi-team configs
- Issue Links can be filtered by key prefix via config rules
- Ticket fields must be hyperlink type and listed in field_mappings.ticket_fields
- Full-update mode batches JIRA fetches to avoid URL length limits

## Important Constraints
- Lark Base batch operations limited to 500 records per request
- JIRA JQL URL length limits require batching in full-update mode
- Requires valid JIRA and Lark credentials with permissions to read/write tables
- Network access is required to call JIRA and Lark APIs
- Config hot-reload watches config.yaml; keep YAML formatting/comments intact

## External Dependencies
- JIRA REST API
- Lark/Feishu Base (Bitable) API and wiki/app tokens
