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
