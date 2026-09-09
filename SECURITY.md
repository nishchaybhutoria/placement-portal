# Security policy

## Supported versions

Security fixes are applied to the latest commit on `main`. No older release
line is currently maintained.

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability.

Use **Security → Report a vulnerability** in this GitHub repository to open a
private security advisory. Include:

- the affected route, command, screen, or deployment component;
- reproduction steps using synthetic data;
- the expected and observed authorization or data behavior;
- likely impact; and
- a suggested remediation, if available.

Do not include production credentials, student records, database dumps, access
tokens, or other personal data. A minimal synthetic reproduction is preferred.

The maintainer will acknowledge a complete report as soon as practical,
coordinate a fix and disclosure window, and credit the reporter unless they
prefer to remain anonymous.

## Automated checks

CI runs Gitleaks, CodeQL, dependency lockfile scanning, and production-image
vulnerability scans. High or critical findings block the API and backup images. The official
Caddy image is scanned in report-only mode because newly disclosed Go-module
findings can temporarily precede a patched upstream image; operators must still
review that report before deployment.

## Scope

Reports about authentication, authorization, cross-cycle access, command
preview/execution mismatches, data exposure, append-only history, backups,
notification content, dependency vulnerabilities, and deployment defaults are
welcome.

The repository is provided without a hosted bug-bounty program or a guarantee
of response time.
