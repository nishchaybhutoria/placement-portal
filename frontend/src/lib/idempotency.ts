/** A fresh client-side key for one bulk intent.
 *
 * `randomUUID` is secure-context-only in browsers. Compose and LAN development
 * can be plain HTTP, where `getRandomValues` remains available and gives the
 * same collision resistance without making a screen crash during render.
 */
export function newIdempotencyKey(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

/**
 * A bounded, stable batch key for one selection (`core/executor.run_bulk`).
 *
 * The obvious key for "this exact selection" is the selection itself, and that
 * is what the approvals queue used to send. It breaks silently at scale:
 * `run_bulk` stores `${batch_key}:${chunk}` in `idempotency_keys.key`, which
 * carries a UNIQUE btree, and Postgres refuses an index entry over 2704 bytes
 * -- after compression, which is why this failed so confusingly. Ticked rows
 * are membership UUIDs and do not compress: seventy-one fit, seventy-two do
 * not, and the operator gets an unreasoned 500 telling them to replay a key
 * that can never be stored. Pasted rows are roll numbers and institute emails
 * sharing a domain, compress by about two thirds, and sailed past five
 * thousand characters -- so the same screen failed or succeeded on the shape
 * of the identifiers rather than on how many there were.
 *
 * So the parts are digested instead of concatenated. The key keeps the two
 * properties RND-2 wants -- a retry of the same intent replays rather than
 * re-applying, and a different selection is a different batch -- at a fixed
 * length. A digest collision cannot silently replay the wrong result: the
 * executor also compares the request fingerprint (`core/idempotency.reserve`)
 * and a mismatch is a clean `idempotency_conflict` rejection.
 */
export function batchKeyFor(prefix: string, parts: readonly string[]): string {
  return `${prefix}-${digest([...parts].sort().join(","))}`;
}

/** cyrb53, as two 32-bit halves. Synchronous, because `crypto.subtle` is not. */
function digest(value: string): string {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    h1 = Math.imul(h1 ^ code, 2654435761);
    h2 = Math.imul(h2 ^ code, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  const combined = 4294967296 * (2097151 & h2) + (h1 >>> 0);
  // Length is also part of the identity: a digest alone cannot tell "no rows"
  // from "one row", and an empty batch is a real, meaningful call.
  return `${value.length.toString(36)}${combined.toString(36)}`;
}
