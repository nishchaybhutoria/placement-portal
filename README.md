# Placement Portal

A placement and internship workflow system for students and career-services
teams. It covers cycle registration, eligibility, job applications, interview
rounds, offers, external outcomes, discipline, audited exceptions, analytics,
and exports.

The application was developed for IIT Gandhinagar's Career Development
Services workflow, while checked-in defaults and demo data use reserved
example domains. The source code is independently maintained and released
under the Apache License 2.0; institutional names and marks are not part of
that license.

> **Project status:** pre-1.0 and production-oriented. The command model and
> core workflows are extensively tested, but adopters must review policy,
> identity, notification, backup, and regulatory requirements for their own
> institution.

## Highlights

- Google OAuth with an institution-domain allowlist and server-side sessions.
- Separate durable identities and academic enrollments for returning students.
- Declarative eligibility rules with human-readable failure reasons.
- Full applicant-tracking rounds, attendance, venue/timing, and bulk results.
- Portal and external offers with placement gates and acceptance cascades.
- Explicit, scoped, expiring policy overrides with audit attribution.
- Strike and penalty workflows with threshold conversion and appeals.
- Screen-shaped APIs for student, coordinator, and administrator workflows.
- Placement analytics, canned reports, and asynchronous exports.
- Append-only application and audit history enforced by database grants.

The complete exception-coverage audit is in
[`docs/OVERRIDES.md`](docs/OVERRIDES.md).

## Architecture

Placement Portal is a modular monolith:

```text
Browser → Caddy → FastAPI ─┬→ PostgreSQL 16
                            └→ Procrastinate worker → email
```

Every business mutation is a named command. A loader acquires authoritative
state and locks, a pure decider returns a plan, and one executor applies state
changes, timeline events, audit rows, and queued side effects in a single
PostgreSQL transaction. Dry-run previews use the same decision function as
execution.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the implementation model
and [`docs/LLD.md`](docs/LLD.md) for contracts and conventions.

## Technology

- Python 3.14, FastAPI, Pydantic, SQLAlchemy, Alembic, and asyncpg
- PostgreSQL 16 and Procrastinate
- React 18, TypeScript, Vite, Tailwind CSS, and TanStack Query
- Caddy and Docker Compose
- pytest, Vitest, and Playwright

## Run locally

Prerequisites:

- Docker with Compose
- Python 3.14 and [uv](https://docs.astral.sh/uv/)
- Node.js 26 and [pnpm](https://pnpm.io/)

```bash
cp .env.example .env
chmod 600 .env
make db-setup
make seed
APP_ENV=development DEV_LOGIN=1 SESSION_COOKIE_SECURE=0 \
  docker compose up -d --wait api
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

Open <http://localhost:5173> and use the synthetic accounts documented in
[`docs/USAGE.md`](docs/USAGE.md). Development login is compiled into the route
registry only when explicitly enabled and is rejected with insecure cookies
outside development/test environments.

`make` prints the available development, test, inspection, and deployment
targets.

## Verification

Run the complete merge gate:

```bash
make check
```

It checks Python linting and types, architectural restrictions, database
migrations, operations configuration, all backend tests, the frontend
production build, and frontend tests.

Run the browser suites separately:

```bash
make e2e
```

The browser gate rebuilds its images before executing critical, responsive, and
full-lifecycle Playwright flows against synthetic data.

## Documentation

| Document | Purpose |
|---|---|
| [`docs/USAGE.md`](docs/USAGE.md) | Local demo accounts and browser workflows |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Architecture as implemented |
| [`docs/BEHAVIOR.md`](docs/BEHAVIOR.md) | Product behavior and stable requirement IDs |
| [`docs/LLD.md`](docs/LLD.md) | Data model, command contracts, and conventions |
| [`docs/OVERRIDES.md`](docs/OVERRIDES.md) | Real-exception backend/frontend coverage audit |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Development process and architectural invariants |
| [`SECURITY.md`](SECURITY.md) | Private vulnerability-reporting policy |

Production runbooks and infrastructure-specific observability procedures are
intentionally maintained outside the public repository. The executable
Compose, backup, recovery, and monitoring machinery remains checked in and
covered by validation tests.

## Privacy

Never use production exports or real student identities for development,
demonstration, tests, screenshots, or bug reports. The rehearsal seed and
browser lifecycle use numbered synthetic identities, and CI enforces that
convention.

The portal stores profile and recruitment data in PostgreSQL. It stores resume
URLs, not uploaded files. Operators remain responsible for access control,
retention, backups, incident response, and applicable privacy law.

## Security

Please report vulnerabilities privately as described in
[`SECURITY.md`](SECURITY.md). Do not include credentials or personal data in a
report.

## Contributing

Contributions are welcome. Read [`CONTRIBUTING.md`](CONTRIBUTING.md), keep
changes focused, and run both `make check` and `make e2e` before opening a pull
request.

## License

Copyright 2026 Nishchay Bhutoria.

Licensed under the [Apache License 2.0](LICENSE). See [`NOTICE`](NOTICE) for
attribution and trademark information.
