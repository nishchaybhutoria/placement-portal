/**
 * `pnpm gen` — regenerate the typed API client from the backend's OpenAPI schema.
 *
 * The schema comes from importing the backend app directly — no server and no
 * database. Set $OPENAPI_URL to read a running server instead.
 *
 * The live server is deliberately opt-in. It used to be the default, probed at
 * http://127.0.0.1:8000, which made the generated file depend on whether a dev
 * server happened to be listening *and* on how that server was configured: a
 * developer running `make dev` with DEV_LOGIN set regenerated a client carrying
 * a `dev_login` route that CI, importing the app with a clean environment, does
 * not produce. The F1 gate then fails on a diff nobody wrote. A generated
 * artifact must not depend on ambient state.
 *
 * CI runs this and then `tsc --noEmit`, so a backend contract change that the
 * frontend has not absorbed fails the build (the build contract F1).
 */
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const outFile = resolve(here, "../src/api/gen/schema.d.ts");
const url = process.env.OPENAPI_URL;

async function fromServer() {
  const response = await fetch(url, { signal: AbortSignal.timeout(3000) });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function fromApp() {
  const stdout = execFileSync(
    "uv",
    ["run", "--frozen", "python", "-c", "import json;from app.main import app;print(json.dumps(app.openapi()))"],
    {
      cwd: resolve(repoRoot, "backend"),
      encoding: "utf8",
      maxBuffer: 64 * 1024 * 1024,
      env: {
        ...process.env,
        // Import-time settings only; nothing connects.
        SESSION_SECRET: process.env.SESSION_SECRET ?? "x".repeat(32),
        DATABASE_URL:
          process.env.DATABASE_URL ?? "postgresql+asyncpg://x:x@127.0.0.1:5432/x",
      },
    },
  );
  return JSON.parse(stdout);
}

let schema;
let source;
if (url) {
  // Explicitly asked for; a failure here is an error rather than a silent
  // fallback, so `OPENAPI_URL=... pnpm gen` cannot quietly generate from
  // somewhere other than where it was told.
  schema = await fromServer();
  source = url;
} else {
  schema = fromApp();
  source = "backend/app.main:app (offline)";
}

const ast = await openapiTS(schema, { alphabetize: true });
const banner = `/**
 * GENERATED FILE — DO NOT EDIT.
 * Run \`pnpm gen\` to regenerate from the backend OpenAPI schema.
 * Source: ${source}
 */

`;

mkdirSync(dirname(outFile), { recursive: true });
rmSync(outFile, { force: true });
writeFileSync(outFile, banner + astToString(ast));
const paths = Object.keys(schema.paths ?? {}).length;
console.log(`gen-client: wrote ${outFile} (${paths} paths) from ${source}`);
