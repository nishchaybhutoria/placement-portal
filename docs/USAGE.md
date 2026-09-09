# Using Placement Portal locally

This guide describes the development/demo environment and the browser surfaces.
It is not a production runbook.

## Start the application

Google OAuth is the only production login. Development mode can register an
explicit email login command so a local environment does not need an OAuth
client.

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

Open <http://localhost:5173>.

The frontend development server proxies `/api`, `/auth`, `/me`, and
`/openapi.json` to the API on port 8000. This preserves the same-origin cookie
and CSRF model used behind Caddy.

Development login is deliberately constrained:

- it exists only when `DEV_LOGIN=1`;
- its form appears only when `/me` reports that it is enabled;
- insecure session cookies require development/test mode and development login;
- an address must match `ALLOWED_DOMAIN`.

## Demonstration seed

`make seed` creates a rich, idempotent fictional world containing cycles,
companies, jobs, applications, round state, attendance, offers, external
offers, overrides, discipline, and consistency findings.

Useful accounts are:

| Email | Demonstrates |
|---|---|
| `admin@example.edu` | Administrator navigation and all global controls |
| `coordinator@example.edu` | A student-role user with coordinator assignments |
| `asha.mehta@example.edu` | Active student with applications, history, and discipline examples |
| `esha.nair@example.edu` | Pending membership and an unanswered offer |
| `bikram.singh@example.edu` | Eligibility and revoked-history cases |
| `chitra.rao@example.edu` | Attached external internship case |
| `dev.patel@example.edu` | Unattached accepted external placement case |
| `farhan.khan@example.edu` | Accepted portal offer and expiry behavior |

These identities and all companies in `app.seed` are fictional test data.
Signing in with any other address on the allowed domain creates the same empty
first-login state as Google OAuth.

Switch accounts with **Sign out** in the sidebar.

## Synthetic lifecycle rehearsal

`make mock-seed` creates a second seed intended for the full Playwright
lifecycle and human workflow rehearsals. It uses only visibly synthetic
identities:

- `demo.coordinator01@example.edu`
- `demo.coordinator02@example.edu`
- `demo.student01@example.edu` through `demo.student11@example.edu`
- roll numbers `99000001` through `99000011`

Nine demo students have complete profiles. Demo Students 05 and 10 deliberately
start without declared profiles so first-login self-declaration can be tested.
The students retain varied programmes, branches, CPI boundaries, dual-major
state, and backlog counts; the values are designed to exercise policy, not to
represent real people.

```bash
make mock-seed
make mock-seed MOCK_SEED_ARGS="--minutes 45"
make mock-seed MOCK_SEED_ARGS="--reset"
```

The seed runs from the working tree rather than a potentially stale API image.
It is idempotent and writes through the same command executor as the browser.

## Student surfaces

### Dashboard — `/dashboard`

Shows current offers, upcoming rounds, placement state, discipline totals, and
read-only external offers. Students accept or decline open offers here.

### Profile — `/profile`

Initial declaration collects academic and contact fields. Student-managed
fields remain editable. Administratively owned values lock after declaration
and are corrected from the staff record or bulk upsert.

The resume library stores Google Drive links only. Applying copies the chosen
URL onto the application, preserving the submitted artifact even if the library
later changes.

### Cycles — `/cycles`

Shows joinable cycles and current membership status. Joining evaluates:

- registration window and active state;
- complete profile and at least one resume;
- the cycle join rule;
- consent; and
- the selected default resume.

Rejected and withdrawn memberships can request entry again. Re-entry reruns the
same gates rather than bypassing them.

### Jobs — `/cycles/:id/jobs` and `/jobs/:id`

Every published job in an active membership's cycle is visible. Cards and
details show the server's eligibility verdict and exact reasons. The detail
screen carries the application form and custom questions.

### Applications — `/applications`

Shows submission history, snapshots, current round, answers, resume, and the
server-computed edit/withdraw actions. A matching override changes the server
verdict; the frontend does not recalculate policy dates.

### Notifications — `/notifications`

Shows the student's durable notification feed and delivery status.

## Staff surfaces

Staff capability is assignment-derived. A coordinator is still a student-role
user and receives staff access only inside assigned cycles. Administrators can
access every cycle.

### Cycles

- `/staff/cycles` — cycle directory
- `/staff/cycles/:id` — policy, coordinators, membership funnel, archival
- `/staff/cycles/:id/approvals` — approve/reject memberships, outcome tags
- `/staff/cycles/:id/jobs` — job directory
- `/staff/cycles/:id/analytics` — cycle analytics
- `/staff/cycles/:id/external` — attach/detach external offers

### Job builder — `/staff/jobs/:id`

Edits basics, compensation, deadlines, eligibility, rounds, questions, and
publication state. All destructive or wide-impact operations show a server
preview before confirmation.

### Applicant board — `/staff/jobs/:id/board`

Select a round to manage attendance, venue/timing, advancing, waitlisting,
elimination, and finalization. Bulk operations return a result for every pasted
identifier. Stale concurrent changes are refused rather than overwritten.

### Offers — `/staff/jobs/:id/offers`

Extends offers, records open-cycle outcomes, terminates or re-extends offers,
and previews acceptance/restoration consequences.

### External offers — `/staff/external`

Records PPO and off-campus offers independently of cycles. Accepted external
offers participate in the same placed-state and cascade derivations as portal
offers. Matching offers can later be attached to dedicated cycles.

### Companies — `/staff/companies`

Maintains the company directory, contacts, deactivation/reactivation, and
administrator-only merges.

### Student record — `/staff/student/:enrollmentId`

Combines profile, memberships, application timelines and round ledgers, portal
and external offers, discipline, audit history, overrides, reinstatement, and
force-transition controls.

## Administrator surfaces

- `/admin/users` — role, activation, and new-enrollment controls
- `/admin/discipline` — strike and penalty award/revocation
- `/admin/taxonomies` — programmes, branches, sectors, minors, round types
- `/admin/settings` — global policy and notification settings
- `/admin/templates` — notification template preview/editing
- `/admin/overrides` — override register and cycle grants
- `/admin/findings` — consistency findings and on-demand checker
- `/admin/analytics` — portal analytics and exports
- `/admin/bulk-upsert` — staged/profile CSV/XLSX imports

## Previews, reasons, and audit

Writes use a two-step preview/confirm flow. Preview and execution invoke the
same backend decider; confirmation reloads and locks current state, so it may
still refuse if another actor changed the world after preview.

Rejections contain stable machine codes and user-facing explanations. The UI
uses server-provided action permissions instead of duplicating transition or
policy logic.

Application status changes append timeline events. Every command writes an
audit record, and override-influenced decisions record the grant IDs that
authorized them.

## API exploration

With the API running:

- OpenAPI document: <http://localhost:8000/openapi.json>
- Health: <http://localhost:8000/healthz>
- Readiness: <http://localhost:8000/readyz>

Command endpoints are generated under `/api/v1/commands/{name}` and screen
endpoints under `/api/v1/screens/{id}`. Browser cookies and CSRF protection are
part of the normal API contract; the UI is the recommended exploration client.

## Stopping and resetting

```bash
docker compose down
```

Use `make` to inspect the available reset and snapshot targets. Destructive
targets require the database name as confirmation and refuse remote database
URLs.
