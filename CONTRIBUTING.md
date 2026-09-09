# Contributing

Thank you for helping improve Placement Portal.

## Development setup

You need Docker, Python 3.14 with [uv](https://docs.astral.sh/uv/), Node.js 26,
and [pnpm](https://pnpm.io/).

```bash
cp .env.example .env
make db-setup
make seed
DEV_LOGIN=1 SESSION_COOKIE_SECURE=0 docker compose up -d --wait api
cd frontend && pnpm install && pnpm dev
```

Open <http://localhost:5173>. See [`docs/USAGE.md`](docs/USAGE.md) for the demo
accounts and browser workflows.

## Before opening a pull request

```bash
make check
make e2e
```

`make check` runs backend linting, static types, architectural checks, database
migrations, backend tests, the frontend production build, and frontend tests.
`make e2e` rebuilds the browser-test images and runs the Playwright flows.

Do not weaken, skip, or mark an existing test as expected to fail in order to
make a change pass.

## Architecture rules

The detailed design is in [`docs/LLD.md`](docs/LLD.md). These invariants are
non-negotiable:

1. Every business write is a named command executed by `core/executor.py`.
2. Only the executor commits business transactions.
3. Authoritative cascades are in-transaction state operations; deferred jobs
   are only for idempotent side effects.
4. Every application status change emits an append-only event.
5. Derived facts such as placed state and offer-cap usage remain queries, not
   cached columns.
6. A preview and its execution use the same decision function.
7. Domain functions and command deciders are pure and deterministic.
8. Authorization is checked before loading and again against loaded scope.
9. Decisions enforcing numeric or existence invariants use locked state and a
   database backstop.
10. The portal stores links, not uploaded files.
11. Rejections use structured reason codes from `core/errors.py`.
12. Timestamps are UTC `timestamptz`; identifiers are UUIDs; emails are never
    keys.

When behavior is unclear, fail closed and call out the ambiguity rather than
inventing policy silently.

## Commands and screens

Adding a command or screen requires updating the registry contracts and their
exhaustive tests. A write normally needs:

- typed command input and output;
- a loader that acquires the required locks;
- a pure decider returning a `Plan` or `Rejection`;
- preview-parity and authorization coverage;
- screen invalidation wiring in `frontend/src/api/screenDeps.ts`;
- regenerated OpenAPI client types when the schema changes.

Run `make gen-client` after API schema changes. Never hand-edit
`frontend/src/api/gen/schema.d.ts`.

## Database changes

Use Alembic and keep migrations deterministic. Runtime code must not use owner
credentials or bypass append-only grants. Test both an empty upgrade and any
required populated-state migration behavior.

## Privacy and test data

Never commit production exports, credentials, application documents, or real
student identities. Demo and end-to-end identities must be visibly synthetic
and follow the conventions enforced by `backend/tests/test_public_hygiene.py`.
Use IANA example domains for fictional external organizations.

## Pull requests

Keep changes focused. Describe the behavior changed, tests run, migrations, new
dependencies, and any operator action required. Security reports do not belong
in public issues; follow [`SECURITY.md`](SECURITY.md).
