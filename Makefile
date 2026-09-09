SHELL := /bin/bash

# `make` on its own prints the menu. It used to run `dev`, which is
# `docker compose up --build` -- a foreground rebuild of the whole stack, and
# on the production host the exact thing the --no-build deployment doctrine
# exists to prevent. One mistyped command should not redeploy a portal.
.DEFAULT_GOAL := help

CDS_APP_DB_PASSWORD ?= cds_app
POSTGRES_USER ?= cds
POSTGRES_DB ?= cds
MIGRATION_DATABASE_URL ?= postgresql+asyncpg://cds:cds@127.0.0.1:5432/cds
DATABASE_URL ?= postgresql+asyncpg://cds_app:$(CDS_APP_DB_PASSWORD)@127.0.0.1:5432/cds
QUEUE_SCHEMA_DATABASE_URL ?= postgresql://cds:cds@127.0.0.1:5432/cds
PROCRASTINATE_DATABASE_URL ?= postgresql://cds_app:$(CDS_APP_DB_PASSWORD)@127.0.0.1:5432/cds
TEST_MIGRATION_DATABASE_URL ?= postgresql+asyncpg://cds:cds@127.0.0.1:5433/cds_test
TEST_DATABASE_URL ?= postgresql+asyncpg://cds_app:$(CDS_APP_DB_PASSWORD)@127.0.0.1:5433/cds_test
TEST_QUEUE_SCHEMA_DATABASE_URL ?= postgresql://cds:cds@127.0.0.1:5433/cds_test
TEST_PROCRASTINATE_DATABASE_URL ?= postgresql://cds_app:$(CDS_APP_DB_PASSWORD)@127.0.0.1:5433/cds_test
TEST_SESSION_SECRET ?= cds-test-suite-session-secret-32-chars

.PHONY: dev db migrate migrate-only queue-schema queue-schema-only db-setup seed mock-seed \
	test-db test-schema test lint type forbid docs-check \
	check gen-client frontend-install frontend-check frontend-build backend-build build \
	prod-images ops-check backup-wal backup-base backup-dump drill e2e

##@ Develop

dev: ## Run the whole stack in the foreground, rebuilding images
	docker compose up --build

db: ## Start only PostgreSQL, and wait for it
	docker compose up -d --wait db

# The schema work is split from the stack bring-up. `queue-schema` and
# `migrate` keep their `db` dependency and behave exactly as before; the
# `-only` halves exist for `mock-nuke`, which cannot afford one -- by the time
# it migrates, the database it would be waiting for has already been dropped,
# and a failed `compose up` would strand it with no schema at all.
queue-schema-only:
	cd backend && MIGRATION_DATABASE_URL="$(MIGRATION_DATABASE_URL)" QUEUE_SCHEMA_DATABASE_URL="$(QUEUE_SCHEMA_DATABASE_URL)" uv run --frozen python -m app.queue_schema

migrate-only: queue-schema-only
	cd backend && MIGRATION_DATABASE_URL="$(MIGRATION_DATABASE_URL)" CDS_APP_DB_PASSWORD="$(CDS_APP_DB_PASSWORD)" uv run --frozen alembic upgrade head

queue-schema: db queue-schema-only

migrate: queue-schema migrate-only ## Apply the queue schema and every Alembic revision

db-setup: migrate ## Start the database and migrate it

# The development seed, run from the *working tree* for the same reason
# `mock-seed` is: `docker compose exec api python -m app.seed` executes
# whatever was baked into the running container, and an image that predates
# your checkout seeds an older world without saying so. That is not a
# hypothetical -- it happened to `mock-seed`, silently, and seeded the previous
# twelve-account cast. Pass flags with SEED_ARGS.
seed: require-local-db ## Seed the development world from the working tree
	@set -euo pipefail; \
		secret="$${SESSION_SECRET:-$$(sed -n 's/^SESSION_SECRET=//p' .env 2>/dev/null | head -1)}"; \
		cd backend && DATABASE_URL="$(DATABASE_URL)" \
			PROCRASTINATE_DATABASE_URL="$(PROCRASTINATE_DATABASE_URL)" \
			SESSION_SECRET="$${secret:-$(MOCK_SCHEMA_SESSION_SECRET)}" \
			uv run --frozen python -m app.seed $(SEED_ARGS)

# The mock live-run world (backend/app/mock_seed.py): a second, additional
# seed for a room of human testers, safe to run alongside or instead of
# `python -m app.seed`. Pass flags with MOCK_SEED_ARGS, e.g.
# `make mock-seed MOCK_SEED_ARGS="--reset --minutes 45"`.
# Runs the seed in the *working tree*, not in the api image. `docker compose
# exec api` runs whatever was baked into the running container: during this
# target's own verification that was a six-day-old image, and it silently
# seeded the previous twelve-account cast instead of the expected synthetic one.
# Nobody would have noticed until the rehearsal accounts tried to log in. This
# is the same stale-image hazard guarded against by the browser gate.
#
# The seed reaches the database through its published 127.0.0.1 port, so it
# needs no image rebuild and no running api. SESSION_SECRET is only needed to
# construct Settings; the real one is preferred when the shell or .env has it,
# so seeded session rows stay valid against the running API.
mock-seed: require-local-db ## Seed the synthetic eleven-student rehearsal cast
	@set -euo pipefail; \
		secret="$${SESSION_SECRET:-$$(sed -n 's/^SESSION_SECRET=//p' .env 2>/dev/null | head -1)}"; \
		cd backend && DATABASE_URL="$(DATABASE_URL)" \
			PROCRASTINATE_DATABASE_URL="$(PROCRASTINATE_DATABASE_URL)" \
			SESSION_SECRET="$${secret:-$(MOCK_SCHEMA_SESSION_SECRET)}" \
			uv run --frozen python -m app.mock_seed $(MOCK_SEED_ARGS)

# A rehearsal has no undo unless a restore point is taken before the first
# login, so these targets keep snapshot and restore mechanics executable.
#
# Snapshots are custom-format dumps under $(SNAPSHOT_DIR), which is gitignored:
# they contain a whole seeded world including people's names and are not
# repository content.
SNAPSHOT_DIR ?= .snapshots

# Host-side alembic and the queue schema import app.worker, which builds the
# command registry, which constructs Settings -- and Settings requires a
# session secret even though neither step ever signs anything. mock-seed runs
# inside the api container and uses the real secret from Compose. This value
# satisfies that bootstrap and nothing else.
MOCK_SCHEMA_SESSION_SECRET ?= cds-mock-nuke-schema-bootstrap-secret

# Every target below rewrites or destroys the database it is pointed at, so
# each refuses to run unless DATABASE_URL names a local host. There is
# deliberately no override flag: a remote CDS database is never the right
# target for a restore or a nuke, and the one time that guard matters is the
# time somebody is in a hurry.
#
# But "local" is not "disposable", and on the production host the production
# database *is* local -- Compose binds it to 127.0.0.1 and nowhere else. This
# guard alone would happily drop it. That is why these also take the typed
# confirmation: the host check stops you pointing them at another machine, and
# the confirmation stops you running them on this one by accident.
##@ Reset the database

.PHONY: mock-snapshot mock-restore mock-nuke db-fresh require-local-db append-only-grants \
	help status preflight deploy logs logs-worker backup-now launch-probe \
	confirm-destructive restore-logical restore-pitr

require-local-db:
	@host="$$(printf '%s' '$(DATABASE_URL)' | sed -E 's#^[a-z0-9+.-]+://[^@]*@\[?([^]:/?]+)\]?.*#\1#')"; \
		case "$$host" in \
			127.0.0.1|localhost|::1) ;; \
			*) echo "refusing: DATABASE_URL host is '$$host', not a local database" >&2; exit 1 ;; \
		esac

# Written to a .partial file and renamed only on success, so a dump that failed
# half way cannot be mistaken later for a restore point.
mock-snapshot: require-local-db ## Take a local restore point before the mock run
	@set -euo pipefail; \
		mkdir -p "$(SNAPSHOT_DIR)"; \
		file="$(SNAPSHOT_DIR)/cds-$$(date -u +%Y%m%dT%H%M%SZ).dump"; \
		docker compose exec -T db pg_dump -Fc -U "$(POSTGRES_USER)" -d "$(POSTGRES_DB)" > "$$file.partial"; \
		mv "$$file.partial" "$$file"; \
		echo "snapshot: $$file ($$(du -h "$$file" | cut -f1))"

# Restores the newest snapshot, or SNAPSHOT=<path> for a specific one. Other
# sessions are terminated first: an idle pooled connection holds no table lock,
# but one mid-request does, and `--clean` would then block instead of failing.
# The API and worker reconnect on their own.
mock-restore: require-local-db confirm-destructive ## Restore the newest local snapshot
	@set -euo pipefail; \
		file="$(SNAPSHOT)"; \
		if [ -z "$$file" ]; then \
			file="$$(ls -1 "$(SNAPSHOT_DIR)"/*.dump 2>/dev/null | sort | tail -1 || true)"; \
		fi; \
		if [ -z "$$file" ]; then \
			echo "no snapshot in $(SNAPSHOT_DIR); run 'make mock-snapshot' first" >&2; exit 1; \
		fi; \
		if [ ! -f "$$file" ]; then echo "no such snapshot: $$file" >&2; exit 1; fi; \
		echo "restoring $$file"; \
		docker compose exec -T db psql -q -v ON_ERROR_STOP=1 -U "$(POSTGRES_USER)" -d "$(POSTGRES_DB)" \
			-c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity \
				WHERE datname = current_database() AND pid <> pg_backend_pid()" > /dev/null; \
		docker compose exec -T db pg_restore --clean --if-exists --exit-on-error \
			-U "$(POSTGRES_USER)" -d "$(POSTGRES_DB)" < "$$file"; \
		echo "restored: $$file"
	$(MAKE) append-only-grants

# The other direction: throw the world away and rebuild it from nothing. This
# is the target migration 0012 asks for by name when it refuses a populated
# application_events table.
# An empty portal, which is what you want before running a real process with
# real people: schema, grants, the taxonomies students must pick from, and the
# administrators you name. No cycles, no jobs, no students, no applications.
#
# It is not *entirely* empty on purpose. A database with no administrator and
# no programs or branches is one nobody can log into and nothing can be
# registered against, which is not a fresh start, it is a brick.
db-fresh: require-local-db confirm-destructive ## DROP the database: empty portal, admin and taxonomies only
	@set -euo pipefail; \
		if [ -z "$(ADMIN)" ]; then \
			echo "usage: make db-fresh ADMIN=you@example.edu [ADMIN2=...]" >&2; \
			echo "the administrator is the only account this creates; without one" >&2; \
			echo "nobody can sign in to the portal you are about to build" >&2; \
			exit 1; \
		fi; \
		echo "dropping and recreating $(POSTGRES_DB)"; \
		docker compose exec -T db psql -q -v ON_ERROR_STOP=1 -U "$(POSTGRES_USER)" -d postgres \
			-c "DROP DATABASE IF EXISTS $(POSTGRES_DB) WITH (FORCE)" \
			-c "CREATE DATABASE $(POSTGRES_DB) OWNER $(POSTGRES_USER)"
	docker compose run --rm --build migrate
	$(MAKE) append-only-grants
	docker compose run --rm --no-deps --build api python -m app.seed --no-demo \
		--admin-email "$(ADMIN)" $(if $(ADMIN2),--admin-email "$(ADMIN2)")
	@echo ""
	@echo "empty portal ready. Sign in as $(ADMIN) and build the cycle by hand."

mock-nuke: require-local-db confirm-destructive ## DROP the database and reseed the eleven-person MOCK CAST (not empty)
	@set -euo pipefail; \
		echo "dropping and recreating $(POSTGRES_DB)"; \
		docker compose exec -T db psql -q -v ON_ERROR_STOP=1 -U "$(POSTGRES_USER)" -d postgres \
			-c "DROP DATABASE IF EXISTS $(POSTGRES_DB) WITH (FORCE)" \
			-c "CREATE DATABASE $(POSTGRES_DB) OWNER $(POSTGRES_USER)"
	docker compose run --rm --build migrate
	$(MAKE) append-only-grants
	docker compose run --rm --no-deps --build api python -m app.mock_seed $(MOCK_SEED_ARGS)

# Append-only history is a database permission, and a logical restore repeals
# it silently. `pg_dump` records an ACL as GRANTs and never as REVOKEs, while
# migration 0002 leaves ALTER DEFAULT PRIVILEGES granting cds_app full CRUD on
# every newly created table -- so `pg_restore` recreates application_events and
# audit_log with DELETE and UPDATE, and the dump's own "GRANT SELECT,INSERT"
# adds nothing that takes them back. Verified here rather than assumed: a
# restore that leaves history deletable is worse than no restore point.
#
# 0002 is the source of truth for this list; if it grows, this grows with it.
# The production fallback carries the same treatment: `restore-logical` calls
# `assert_append_only_grants`, and `make drill` re-proves it independently.
append-only-grants: require-local-db ## Re-assert and verify the append-only history grants
	@set -euo pipefail; \
		docker compose exec -T db psql -q -v ON_ERROR_STOP=1 \
			-U "$(POSTGRES_USER)" -d "$(POSTGRES_DB)" \
			-c "REVOKE ALL PRIVILEGES ON TABLE application_events FROM cds_app" \
			-c "GRANT SELECT, INSERT ON TABLE application_events TO cds_app" \
			-c "REVOKE ALL PRIVILEGES ON TABLE audit_log FROM cds_app" \
			-c "GRANT SELECT, INSERT ON TABLE audit_log TO cds_app"; \
		ok="$$(docker compose exec -T db psql -qtA \
			-U "$(POSTGRES_USER)" -d "$(POSTGRES_DB)" -c \
			"SELECT count(*) FROM (SELECT table_name FROM information_schema.role_table_grants \
			 WHERE grantee = 'cds_app' AND table_name IN ('application_events', 'audit_log') \
			 GROUP BY table_name HAVING string_agg(privilege_type, ',' ORDER BY privilege_type) \
			 = 'INSERT,SELECT') verified")"; \
		if [ "$$ok" != "2" ]; then \
			echo "append-only grants are not SELECT,INSERT on both history tables ($$ok/2)" >&2; \
			exit 1; \
		fi; \
		echo "append-only verified: cds_app holds SELECT,INSERT only on application_events and audit_log"

##@ Test and gate

test-db:
	SESSION_SECRET="$(TEST_SESSION_SECRET)" docker compose --profile test up -d --wait --force-recreate test-db

test-schema: test-db
	cd backend && SESSION_SECRET="$(TEST_SESSION_SECRET)" MIGRATION_DATABASE_URL="$(TEST_MIGRATION_DATABASE_URL)" QUEUE_SCHEMA_DATABASE_URL="$(TEST_QUEUE_SCHEMA_DATABASE_URL)" uv run --frozen python -m app.queue_schema
	cd backend && MIGRATION_DATABASE_URL="$(TEST_MIGRATION_DATABASE_URL)" CDS_APP_DB_PASSWORD="$(CDS_APP_DB_PASSWORD)" uv run --frozen alembic upgrade head
	cd backend && MIGRATION_DATABASE_URL="$(TEST_MIGRATION_DATABASE_URL)" CDS_APP_DB_PASSWORD="$(CDS_APP_DB_PASSWORD)" uv run --frozen alembic check

test: test-schema ## Backend tests only
	cd backend && DATABASE_URL="$(TEST_DATABASE_URL)" PROCRASTINATE_DATABASE_URL="$(TEST_PROCRASTINATE_DATABASE_URL)" TEST_DATABASE_URL="$(TEST_DATABASE_URL)" TEST_MIGRATION_DATABASE_URL="$(TEST_MIGRATION_DATABASE_URL)" TEST_PROCRASTINATE_DATABASE_URL="$(TEST_PROCRASTINATE_DATABASE_URL)" uv run --frozen pytest

lint: ## ruff
	cd backend && uv run --frozen ruff check .

type: ## pyright
	cd backend && uv run --frozen pyright

forbid: ## Enforce the architectural invariants in CONTRIBUTING.md
	uv run --project backend --frozen python scripts/forbid.py --root .

check: lint type forbid docs-check ops-check test frontend-check ## The merge gate: lint, types, docs, ops, tests, frontend

docs-check: ## Validate local links in public Markdown files
	uv run --project backend --frozen python scripts/check_docs.py

ops-check: ## Validate compose, Caddy, Prometheus rules and dashboards
	./ops/tests/test_ops.sh

##@ Operate

backup-wal: ## Sync archived WAL to the remote now
	docker compose run --rm --no-deps backup /opt/backup/bin/record-backup-metrics wal_sync /opt/backup/bin/wal-sync

backup-base: ## Take and upload a physical base backup now
	docker compose run --rm --no-deps backup /opt/backup/bin/record-backup-metrics base_backup /opt/backup/bin/base-backup

backup-dump: ## Take and upload a logical dump now
	docker compose run --rm --no-deps backup /opt/backup/bin/record-backup-metrics logical_dump /opt/backup/bin/logical-dump

drill: ## Full restore rehearsal: PITR, counts, checker, logical fallback, append-only proof
	./ops/drill/run.sh

# Browser gates use separate ephemeral databases. The original F5 fixture and
# the named mock-run cast are each seeded exactly once; no lifecycle mutation
# can leak between suites. Teardown remains unconditional on failures.
#
# The responsive suite runs against the F5 world, in the same bring-up as the
# critical flows: it is read-only, so it needs no world of its own, and the
# 390px viewport it declares itself is the only thing that makes it different.
##@ Test and gate (continued)

e2e: ## The browser gate: critical flows, 390px responsive, full lifecycle
	@set -euo pipefail; \
		export SESSION_SECRET="$(TEST_SESSION_SECRET)"; \
		export COMPOSE_PROJECT_NAME="cds-portal-e2e"; \
		artifacts="frontend/e2e-artifacts/$$(date -u +%Y%m%dT%H%M%SZ)"; \
		mkdir -p "$$artifacts"; \
		suite=critical; \
		cleanup() { \
			docker compose --profile e2e logs --no-color --no-log-prefix e2e-worker \
				> "$$artifacts/$$suite-worker.log" 2>&1 || true; \
			docker compose --profile e2e down --volumes --remove-orphans; \
		}; \
		trap cleanup EXIT; \
		docker compose --profile e2e build e2e-web e2e-api e2e-worker e2e-seed e2e-migrate e2e; \
		docker compose --profile e2e up --no-build -d --wait e2e-web; \
		docker compose --profile e2e run --rm --no-deps e2e \
			pnpm exec playwright test e2e/critical-flows.spec.ts; \
		docker compose --profile e2e run --rm --no-deps e2e \
			pnpm exec playwright test e2e/responsive.spec.ts; \
		cleanup; \
		suite=lifecycle; \
		export E2E_SEED_COMMAND="python -m app.mock_seed --minutes 60"; \
		docker compose --profile e2e up --no-build -d --wait e2e-web; \
		docker compose --profile e2e run --rm --no-deps e2e \
			pnpm exec playwright test e2e/lifecycle.spec.ts

##@ Build

frontend-install:
	cd frontend && pnpm install --frozen-lockfile

# Regenerates src/api/gen/schema.d.ts by importing the FastAPI app, so no
# database and no running service are needed in CI. Set OPENAPI_URL to read a
# running server instead; see the header of frontend/scripts/gen-client.mjs for
# why the live server is opt-in rather than probed.
gen-client: frontend-install ## Regenerate the OpenAPI client from the live app
	cd frontend && pnpm gen

# The production bundle. `pnpm build` is `tsc --noEmit && vite build`, so this
# typechecks as well -- which is why frontend-check calls it instead of calling
# typecheck separately. Building is not the same check as typechecking: Rollup
# resolves and tree-shakes what tsc only reads, so a bundle can fail to build
# from code that typechecks cleanly.
frontend-build: frontend-install
	cd frontend && pnpm build

# The backend "build" is its container image -- Python has no compile step, so
# lint + type + test are the equivalent gate and `check` already runs them. This
# target exists because the image is what actually ships, and a Dockerfile can
# break (a missing COPY, an unresolvable pin) while every test passes.
backend-build:
	docker compose build api

# Build the exact production images used by Compose. API, worker, and alert
# relay share one Dockerfile but are all named so Compose validates each service.
# --pull is the difference between a deploy and a deploy that ships old CVEs.
# Every base here is a *moving* tag -- python:3.14-slim, alpine:3.21,
# node:26-alpine, caddy:2.11.4-alpine -- and without --pull the host keeps
# whatever copy it first fetched, forever. The apt layer sits below FROM, so a
# refreshed base re-runs it and the chain patches itself; a frozen base freezes
# that too, silently, while the host's own dnf-automatic keeps patching around
# it. Base tags are deliberately not pinned by digest: on a single
# institution-run host, picking up security rebuilds automatically is worth
# more than byte-identical rebuilds, and nobody here is going to run a bot that
# bumps digests.
prod-images: ## Build the shipping images, re-pulling bases so they cannot go stale
	docker compose build --pull migrate api worker alert-relay backup caddy

# Everything that ships, both halves.
build: backend-build frontend-build

# The F1 gate: the client must regenerate cleanly, the frontend must typecheck
# *and* build against what was regenerated, and the vitest suite must pass
# (client wrappers, reasons parity, and every screen rendered against payloads
# captured from a seeded database).
frontend-check: frontend-install
	@before=$$(mktemp); \
		cp frontend/src/api/gen/schema.d.ts $$before; \
		cd frontend && pnpm gen; \
		cd ..; \
		cmp -s $$before frontend/src/api/gen/schema.d.ts || \
			{ rm -f $$before; echo "generated client is stale — run 'make gen-client'"; exit 1; }; \
		rm -f $$before
	cd frontend && pnpm build
	cd frontend && pnpm test

##@ Recover

# Recovery procedures stay executable as targets rather than command blocks
# somebody retypes during an incident. Deployment-private runbooks should cite
# these targets instead of duplicating their flags.

# Restoring overwrites the database it is pointed at. The guard is the one
# GitHub uses for deleting a repository: type the name. It cannot be muscle
# memory, and it survives being scripted, because CONFIRM= can be passed.
confirm-destructive:
	@set -euo pipefail; \
		if [ "$(CONFIRM)" = "$(POSTGRES_DB)" ]; then exit 0; fi; \
		if [ ! -t 0 ]; then \
			echo "refusing: pass CONFIRM=$(POSTGRES_DB) to run this without a terminal" >&2; \
			exit 1; \
		fi; \
		printf 'This overwrites the database "%s". Type its name to continue: ' "$(POSTGRES_DB)"; \
		read -r answer; \
		if [ "$$answer" != "$(POSTGRES_DB)" ]; then echo "aborted" >&2; exit 1; fi

restore-logical: confirm-destructive ## Restore the newest logical dump
	docker compose run --rm --build migrate
	docker compose run --rm --no-deps --build backup /opt/backup/bin/restore-logical
	docker compose run --rm --no-deps --build api python -m ops.check_consistency

# PITR needs a target instant and the volume the base backup lives in; both are
# incident-specific, so they are arguments rather than defaults.
restore-pitr: confirm-destructive ## Point-in-time restore to TARGET=<ISO-8601 UTC>
	@set -euo pipefail; \
		if [ -z "$(TARGET)" ]; then \
			echo "usage: make restore-pitr TARGET=2026-08-23T08:00:14.922960Z" >&2; exit 1; \
		fi; \
		volume="$$(docker volume ls --filter label=com.docker.compose.volume=backup_cache \
			--format '{{.Name}}' | head -1)"; \
		if [ -z "$$volume" ]; then echo "no backup_cache volume found" >&2; exit 1; fi; \
		echo "restoring to $(TARGET) from $$volume"; \
		PITR_TARGET_TIME="$(TARGET)" SOURCE_BACKUP_VOLUME="$$volume" \
			DRILL_EXPECTED_DIR="$$(mktemp -d)" \
			docker compose --project-directory ops/drill -f ops/drill/docker-compose.yml \
			up --build -d --wait db; \
		echo "recovered database is up in the drill project; verify counts before any cutover"


##@ Inspect

# The drift check answers the question behind every stale-image failure this
# project has had: is what is running what is in the repository? It compares
# each container's image build time against the last commit touching that
# image's build context. An unreadable build time or absent git history means
# "unknown", which is not the same as "stale", so those report nothing rather
# than crying wolf.
status: ## What is the state of things: services, health, backups, recovery reach, findings
	@set -uo pipefail; \
		printf '\n== services ==\n'; \
		docker compose ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}' 2>/dev/null || true; \
		printf '\n== health ==\n'; \
		for probe in healthz readyz; do \
			body="$$(curl -fsS "http://127.0.0.1:$${API_PORT:-8000}/$$probe" 2>/dev/null || echo unreachable)"; \
			printf '  %-8s %s\n' "$$probe" "$$body"; \
		done; \
		printf '\n== images ==\n'; \
		docker compose images 2>/dev/null \
			| awk 'NR == 1 { next } \
				{ built = ""; for (i = 7; i <= NF; i++) built = built $$i " "; \
				  printf "  %-26s %-14s %s\n", $$1, $$5, built }' || true; \
		printf '\n== is what is running what is in the repository? ==\n'; \
		drifted=0; \
		for pair in "api:backend" "worker:backend" "migrate:backend" "backup:ops/backup" "caddy:frontend"; do \
			service="$${pair%%:*}"; context="$${pair#*:}"; \
			image="$$(docker compose images "$$service" --format json 2>/dev/null \
				| sed -n 's/.*"ID":"sha256:\([0-9a-f]*\)".*/\1/p' | head -1)"; \
			[ -n "$$image" ] || continue; \
			built="$$(docker image inspect --format '{{.Created}}' "$$image" 2>/dev/null)"; \
			[ -n "$$built" ] || continue; \
			built_at="$$(date -d "$$built" +%s 2>/dev/null || echo 0)"; \
			changed_at="$$(git log -1 --format=%ct -- "$$context" 2>/dev/null || echo 0)"; \
			[ "$$built_at" != "0" ] && [ "$$changed_at" != "0" ] || continue; \
			if [ "$$changed_at" -gt "$$built_at" ]; then \
				printf '  DRIFT %-10s image predates the last commit touching %s\n' "$$service" "$$context"; \
				drifted=1; \
			fi; \
		done; \
		if [ "$$drifted" = "0" ]; then printf '  every running image is newer than its source\n'; \
		else printf '\n  Run make deploy. A stale api is loud; a stale backup reports\n'; \
			printf '  success while doing the old thing, which is how this bites.\n'; fi; \
		printf '\n== schema ==\n'; \
		head="$$(docker compose exec -T db psql -qtA -U "$(POSTGRES_USER)" -d "$(POSTGRES_DB)" \
			-c 'SELECT version_num FROM alembic_version' 2>/dev/null || echo unknown)"; \
		printf '  migration head   %s\n' "$$head"; \
		printf '\n== backups ==\n'; \
		docker compose run --rm --no-deps --entrypoint sh backup -c \
			'metrics=/backups/metrics/web/metrics; \
			now=$$(date -u +%s); \
			for kind in wal_sync base_backup logical_dump; do \
				success=$$(sed -n "s/^cds_backup_last_success_timestamp_seconds{kind=\"$$kind\"} //p" $$metrics 2>/dev/null | tail -1); \
				fails=$$(sed -n "s/^cds_backup_consecutive_failures{kind=\"$$kind\"} //p" $$metrics 2>/dev/null | tail -1); \
				if [ -z "$$success" ] || [ "$$success" = "0" ]; then \
					printf "  %-14s never run yet\n" "$$kind"; \
				else \
					age=$$(( (now - success) / 3600 )); \
					printf "  %-14s last success %sh ago" "$$kind" "$$age"; \
					if [ "$${fails:-0}" != "0" ]; then printf "  (%s failures since)" "$$fails"; fi; \
					printf "\n"; \
				fi; \
			done; \
			remote_count() { \
				out=$$(rclone lsf --files-only $$2 "$${RCLONE_ROOT%/}/$$1" 2>/dev/null) || { echo unreachable; return; }; \
				printf "%s" "$$(printf "%s" "$$out" | grep -c .)"; \
			}; \
			printf "\n"; \
			printf "  %-14s local %-5s remote %s\n" "base" \
				"$$(ls -1 /backups/base/*.tar.gz 2>/dev/null | wc -l)" \
				"$$(remote_count base "--include base-*.tar.gz")"; \
			printf "  %-14s local %-5s remote %s\n" "dumps" \
				"$$(ls -1 /backups/dumps/*.dump 2>/dev/null | wc -l)" \
				"$$(remote_count dumps "--include dump-*.dump")"; \
			printf "  %-14s local %-5s remote %s\n" "wal" \
				"$$(ls -1 /wal_archive 2>/dev/null | wc -l)" \
				"$$(remote_count wal "")"; \
			oldest=$$(ls -1t /backups/base/*.meta 2>/dev/null | tail -1); \
			if [ -n "$$oldest" ]; then \
				printf "\n  %-14s %s\n" "reach" "$$(basename "$$oldest" .tar.gz.meta)"; \
			fi' 2>/dev/null || printf '  (backup container unavailable)\n'; \
		printf '\n== consistency ==\n'; \
		open="$$(docker compose exec -T db psql -qtA -U "$(POSTGRES_USER)" -d "$(POSTGRES_DB)" \
			-c "SELECT count(*) FROM consistency_findings WHERE status = 'open'" 2>/dev/null || echo unknown)"; \
		printf '  open findings    %s\n\n' "$$open"

# The values that are invisible until a student hits them. Every one of these
# has a safe production answer, and every one of them is easy to leave wrong
# after a rehearsal.
preflight: ## Check the production .env for the settings that fail silently
	@set -uo pipefail; \
		fail=0; \
		value() { sed -n "s/^$$1=//p" .env 2>/dev/null | head -1; }; \
		expect() { \
			actual="$$(value "$$1")"; \
			if [ "$$actual" = "$$2" ]; then printf '  ok    %-22s %s\n' "$$1" "$$actual"; \
			elif [ -z "$$actual" ]; then \
				printf '  FAIL  %-22s not pinned (defaults to %s, which is right --\n' "$$1" "$$2"; \
				printf '        %-22s set it anyway: a value absent from .env is one\n' ""; \
				printf '        %-22s the second operator cannot review)\n' ""; \
				fail=1; \
			else printf '  FAIL  %-22s is %s, want %s\n' "$$1" "$$actual" "$$2"; fail=1; fi; \
		}; \
		present() { \
			actual="$$(value "$$1")"; \
			if [ -n "$$actual" ]; then printf '  ok    %-22s set\n' "$$1"; \
			else printf '  FAIL  %-22s unset\n' "$$1"; fail=1; fi; \
		}; \
		printf '\nChecking .env against production expectations.\n'; \
		printf 'A development box fails this by design: DEV_LOGIN=1 is the point of one.\n'; \
		printf '\n== .env ==\n'; \
		if [ ! -f .env ]; then echo "  FAIL  no .env in $$(pwd)"; exit 1; fi; \
		expect DEV_LOGIN 0; \
		expect SESSION_COOKIE_SECURE 1; \
		expect DEV_EMAIL_OUTPUT 0; \
		expect BACKUP_REMOTE_ENABLED 1; \
		present SESSION_SECRET; \
		present GOOGLE_CLIENT_ID; \
		present GOOGLE_CLIENT_SECRET; \
		perms="$$(stat -c '%a' .env 2>/dev/null)"; \
		if [ "$$perms" = "600" ]; then printf '  ok    %-22s %s\n' "permissions" "$$perms"; \
		else printf '  FAIL  %-22s %s (want 600)\n' "permissions" "$$perms"; fail=1; fi; \
		printf '\n== email ==\n'; \
		backend="$$(value NOTIFICATION_BACKEND)"; \
		printf '  note  %-22s %s\n' "NOTIFICATION_BACKEND" "$${backend:-console}"; \
		if [ "$$backend" = "ses" ]; then \
			env_sender="$$(value SES_SENDER)"; \
			db_sender="$$(docker compose exec -T db psql -qtA -U "$(POSTGRES_USER)" \
				-d "$(POSTGRES_DB)" -c \
				"SELECT value #>> '{}' FROM settings WHERE key = 'ses_sender'" 2>/dev/null)"; \
			printf '  %-6s %-22s %s\n' "note" "SES_SENDER (.env)" "$${env_sender:-unset}"; \
			printf '  %-6s %-22s %s\n' "note" "ses_sender (database)" "$${db_sender:-unset}"; \
			if [ -z "$$db_sender" ] && [ -z "$$env_sender" ]; then \
				printf '  FAIL  no sender in either place; SES delivery will raise\n'; fail=1; \
			elif [ -n "$$db_sender" ] && [ -n "$$env_sender" ] && [ "$$db_sender" != "$$env_sender" ]; then \
				printf '  warn  the database setting wins; the .env value is only its fallback\n'; \
			fi; \
		fi; \
		printf '\n== clock ==\n'; \
		if command -v timedatectl >/dev/null 2>&1; then \
			synced="$$(timedatectl show -p NTPSynchronized --value 2>/dev/null)"; \
			if [ "$$synced" = "yes" ]; then printf '  ok    %-22s yes\n' "NTP synchronised"; \
			else printf '  FAIL  %-22s %s\n' "NTP synchronised" "$${synced:-unknown}"; fail=1; fi; \
		else printf '  note  timedatectl unavailable; check the clock by hand\n'; fi; \
		printf '\n'; \
		if [ "$$fail" != "0" ]; then echo "preflight failed" >&2; exit 1; fi; \
		echo "preflight passed"

logs: ## Tail every service (LINES=200 to change the depth)
	docker compose logs --tail=$${LINES:-200} -f

logs-worker: ## Tail the worker, where deferred work and notifications land
	docker compose logs --tail=$${LINES:-200} -f worker

backup-now: backup-wal backup-base backup-dump ## Run all three backup jobs immediately

launch-probe: ## Prove real delivery end to end: make launch-probe TO=you@example.edu
	@set -euo pipefail; \
		if [ -z "$(TO)" ]; then \
			echo "usage: make launch-probe TO=<an inbox you control>" >&2; exit 1; \
		fi; \
		docker compose run --rm --no-deps --build api \
			python -m ops.launch_probe --recipient "$(TO)"

##@ Deploy

# The release gate keeps migrations ahead of serving so the stack cannot start
# against a schema it has not migrated.
# RELEASE is derived here rather than remembered. It is the SHA every
# structured log line is attributed to, it has exactly one correct value, and a
# human editing .env before each deploy is a step that will eventually be
# skipped -- leaving a month of logs blaming the wrong commit for a bug. A
# shell variable takes precedence over the .env file in Compose substitution,
# so exporting it here beats whatever the file says, and the file's value
# becomes a fallback for hand-run containers rather than a thing to maintain.
deploy: ## Build images, run the migration gate, restart the stack, verify health
	@set -euo pipefail; \
		echo "== commit =="; git rev-parse --short HEAD; \
		if [ -n "$$(git status --porcelain)" ]; then \
			echo "refusing: the working tree is dirty; deploy a committed state" >&2; exit 1; \
		fi; \
		if ! $(MAKE) --no-print-directory preflight; then \
			echo "" >&2; \
			echo "refusing: this .env is not production-shaped, and deploy is the" >&2; \
			echo "production path. On a development host use 'make dev' instead --" >&2; \
			echo "or set BACKUP_REMOTE_ENABLED=0 locally, which is only ever right" >&2; \
			echo "on a laptop: a production backup service that cannot reach its" >&2; \
			echo "remote is supposed to be unhealthy." >&2; \
			exit 1; \
		fi; \
		docker network inspect cds-observability >/dev/null 2>&1 || docker network create cds-observability; \
		export RELEASE="$$(git rev-parse HEAD)"; \
		echo "RELEASE=$$RELEASE"; \
		$(MAKE) prod-images; \
		docker compose up -d --wait db; \
		docker compose run --rm migrate; \
		if ! docker compose up -d --no-build --force-recreate --wait api worker alert-relay backup caddy; then \
			echo "" >&2; \
			echo "== why a service is unhealthy ==" >&2; \
			for service in api worker alert-relay backup caddy; do \
				state="$$(docker compose ps --format '{{.Service}} {{.Health}}' 2>/dev/null \
					| awk -v s="$$service" '$$1 == s { print $$2 }')"; \
				if [ "$$state" != "healthy" ]; then \
					echo "" >&2; echo "-- $$service ($${state:-not running}) --" >&2; \
					docker compose logs --no-color --tail=15 "$$service" >&2 || true; \
				fi; \
			done; \
			exit 1; \
		fi; \
		docker compose ps; \
		$(MAKE) --no-print-directory status

##@ Help

help: ## Print this menu
	@awk 'BEGIN { FS = ":.*## " } \
		/^##@ / { printf "\n\033[1m%s\033[0m\n", substr($$0, 5); next } \
		/^[a-zA-Z0-9_-]+:.*## / { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 } \
		' $(MAKEFILE_LIST); \
		printf "\n  Destructive targets ask you to type the database name.\n"; \
		printf "  Development guidance: README.md · product usage: docs/USAGE.md\n\n"
