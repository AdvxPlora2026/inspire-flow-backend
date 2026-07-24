# Backend Development Guidelines

> Best practices for backend development in this project.

---

## Overview

This directory contains guidelines for backend development. Fill in each file with your project's specific conventions.

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Module organization, FastAPI boundaries, and API contracts | Active |
| [Database Guidelines](./database-guidelines.md) | SQLAlchemy models, service-owned transactions, UTC types, and Alembic | Active |
| [Error Handling](./error-handling.md) | Domain errors, safe validation details, and the API error envelope | Active |
| [Quality Guidelines](./quality-guidelines.md) | uv, Ruff, pytest, and review requirements | Active |
| [Agent Tools](./agent-tools.md) | Internal Agent lifecycle, no-key search, and safe outbound webpage fetching | Active |
| [STT Worker](./stt-worker.md) | SenseVoice API, Celery isolation, encrypted jobs, readiness, and device contracts | Active |
| [Public Workshop and Brand Engagement](./public-workshop-and-engagement.md) | Publishing snapshots, field visibility, brands, engagement, idempotency, and Agent SSE | Active |
| [Logging Guidelines](./logging-guidelines.md) | Structured logging, log levels | To fill |

---

## How to Fill These Guidelines

For each guideline file:

1. Document your project's **actual conventions** (not ideals)
2. Include **code examples** from your codebase
3. List **forbidden patterns** and why
4. Add **common mistakes** your team has made

The goal is to help AI assistants and new team members understand how YOUR project works.

---

**Language**: All documentation should be written in **English**.
