# The browsers ship inside this image, so its tag has to move with
# @playwright/test in package.json — a mismatch fails as a missing executable.
FROM mcr.microsoft.com/playwright:v1.63.0-noble

RUN npm install --global pnpm@11.22.0

WORKDIR /workspace/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend/playwright.config.ts ./
COPY frontend/e2e ./e2e

CMD ["pnpm", "test:e2e"]
