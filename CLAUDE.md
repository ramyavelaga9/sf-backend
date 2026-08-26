# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Self-contained Contacts REST API: **FastAPI** + **SQLAlchemy 2.0**, backed by an
**in-memory SQLite database** by default (via `StaticPool`, see Architecture below). No
external database, container, or migration step is needed to run or test it.

## Commands

```bash
# Setup
uv venv && uv pip install -e ".[dev]"        # or: python -m venv .venv && pip install -r requirements.txt

# Run the server (reads .env, binds 127.0.0.1:8000 by default)
.venv/bin/python -m app.main
.venv/bin/uvicorn app.main:app --reload      # with autoreload

# Tests
.venv/bin/python -m pytest
.venv/bin/python -m pytest tests/test_contacts_api.py::test_name  # single test
```

There is no configured linter/formatter/type-checker in this repo (no ruff/black/mypy
config present) — don't assume one.

Swagger UI is at `/docs`, ReDoc at `/redoc`, raw schema at `/openapi.json` when the
server is running.

## Architecture

**Request flow**: `routers/contacts.py` (HTTP layer: path/query validation, 404/409
translation) → `crud.py` (all DB queries/writes, plain SQLAlchemy `select`/session
calls, no ORM query building in the router) → `models.py` (the `Contact` ORM table).
Pydantic schemas in `schemas.py` are distinct per use: `ContactCreate` (POST),
`ContactReplace` (PUT — omitted optional fields are cleared to `null`), `ContactUpdate`
(PATCH — `model_dump(exclude_unset=True)` so omitted fields are left alone), and
`ContactRead` (response, adds `id`/`full_name`/timestamps). Keep this separation when
adding fields or endpoints — don't reuse one schema across create/replace/update.

**The in-memory database** (`app/database.py`): a plain in-memory SQLite DB normally
dies with the connection that opened it, so the engine is built with SQLAlchemy's
`StaticPool` when the URL contains `:memory:`, keeping one connection alive for the
process's lifetime so every request (including ones FastAPI runs on a worker thread)
sees the same data. `CONTACTS_DATABASE_URL` can instead point at a file
(`sqlite+pysqlite:///./contacts.db`) or Postgres (`postgresql+psycopg://...`) to
persist data — the same code path handles all three; only `_engine_kwargs` branches on
dialect.

**Startup lifecycle** (`app/main.py` `lifespan`): `init_db()` creates tables, then
`seed_if_empty()` (`app/seed.py`) inserts three sample contacts if the table is empty
and `CONTACTS_SEED_DATA=true` (the default). Data is lost whenever the process exits
under the in-memory default — this is intentional, not a bug to fix.

**Config** (`app/config.py`): all settings are env vars prefixed `CONTACTS_`
(`pydantic-settings`, also reads `.env`), cached via `lru_cache`. Add new settings here
rather than reading `os.environ` directly elsewhere.

**Email uniqueness**: enforced at the application layer, not just the DB unique
constraint — `crud._normalize_email` lowercases/strips before compare/store, and
routers call `_reject_duplicate_email` (excluding the record's own id on
PUT/PATCH) before writing, returning `409` rather than letting a DB `IntegrityError`
surface.

**Sort-field safety**: `list_contacts` (`crud.py`) validates `sort_by` against the
`SORTABLE_FIELDS` allow-list (also used to build the query-param regex in the router)
before doing `getattr(Contact, sort_by)` — never interpolate a client-supplied field
name into a query without going through that allow-list.

**Tests** (`tests/conftest.py`): force `CONTACTS_DATABASE_URL` to a fresh in-memory
DB and `CONTACTS_SEED_DATA=false` *before* importing `app.main`, and the `client`
fixture drops/recreates all tables per test — tests never see the seeded sample data
and don't share state with each other.
