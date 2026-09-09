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

/** A count and noun with the grammar kept beside the number. */
export function counted(
  count: number,
  singular: string,
  plural = `${singular}s`,
): string {
  return `${count} ${count === 1 ? singular : plural}`;
}
