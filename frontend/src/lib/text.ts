const ACRONYMS = new Map([
  ["cpi", "CPI"],
  ["csv", "CSV"],
  ["ctc", "CTC"],
  ["id", "ID"],
  ["inr", "INR"],
  ["lpa", "LPA"],
  ["nirf", "NIRF"],
  ["ppo", "PPO"],
  ["rti", "RTI"],
  ["url", "URL"],
  ["xlsx", "XLSX"],
]);

/** Turn a wire-format enum or field name into operator-facing copy. */
export function humanise(value: string): string {
  return value
    .split("_")
    .map((word, index) => {
      const acronym = ACRONYMS.get(word.toLowerCase());
      if (acronym) return acronym;
      return index === 0
        ? word.charAt(0).toUpperCase() + word.slice(1)
        : word.toLowerCase();
    })
    .join(" ");
}

const UUID = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i;

/** Machine identifiers belong in links and command inputs, not visible copy. */
export function isUuid(value: unknown): value is string {
  return typeof value === "string" && UUID.test(value);
}

/** A count and noun with the grammar kept beside the number. */
export function counted(
  count: number,
  singular: string,
  plural = `${singular}s`,
): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

/**
 * An annual CTC for reading: stored in rupees, published in lakhs.
 *
 * The portal records what the office typed -- ₹18,53,500 stays ₹18,53,500 --
 * and every surface that shows it says 18.54 LPA, which is how the figure is
 * quoted. Returns null when there is nothing to show, so a caller can fall
 * back to its own empty state rather than rendering "null LPA".
 */
export function lakhs(rupees: string | number | null | undefined): string | null {
  if (rupees === null || rupees === undefined || rupees === "") return null;
  const value = Number(rupees);
  if (!Number.isFinite(value)) return null;
  const inLakhs = value / 100000;
  // A round figure reads better without the decimals: "18 LPA", not "18.00".
  return `₹${Number.isInteger(inLakhs) ? inLakhs : inLakhs.toFixed(2)} LPA`;
}
