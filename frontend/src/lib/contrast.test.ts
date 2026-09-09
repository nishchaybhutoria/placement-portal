import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(process.cwd(), "src/index.css"), "utf8");
const families = ["success", "warning", "danger", "info", "neutral", "brand"];

describe("semantic colour contrast", () => {
  for (const mode of ["light", "dark"] as const) {
    it(`${mode} status text clears WCAG AA on its subtle fill`, () => {
      const block = mode === "light" ? rule(":root") : rule(".dark");
      for (const family of families) {
        const foreground = variable(block, family);
        const background = variable(block, `${family}-subtle`);
        expect(contrast(foreground, background), `${family} in ${mode}`).toBeGreaterThanOrEqual(4.5);
      }
    });
  }
});

/**
 * WCAG 1.4.11: a control's boundary needs 3:1 against the surface behind it.
 *
 * The solid destructive button is the one that terminates offers and cancels
 * jobs, and in dark its `#93000a` fill is 1.84:1 against `card` — no visible
 * edge at all. DESIGN.md §8 therefore gives it a border: its own fill in light,
 * where the fill already reads as the boundary, and `destructive-foreground` in
 * dark. Pinned here so the palette cannot quietly take it back.
 */
describe("destructive button boundary", () => {
  const surfaces = ["card", "background", "popover"] as const;

  it("light: the destructive fill is its own boundary", () => {
    const block = rule(":root");
    for (const surface of surfaces) {
      expect(
        contrast(variable(block, "destructive"), variable(block, surface)),
        `destructive on ${surface}`,
      ).toBeGreaterThanOrEqual(3);
    }
  });

  it("dark: the fill cannot be, so the border carries it", () => {
    const block = rule(".dark");
    for (const surface of surfaces) {
      expect(
        contrast(variable(block, "destructive-foreground"), variable(block, surface)),
        `destructive-foreground border on ${surface}`,
      ).toBeGreaterThanOrEqual(3);
    }
  });
});

/**
 * The shipped core palette — DESIGN.md §2, the layer that is not DRAFT.
 *
 * The suite above tests twelve pairs from the semantic layer §3 marks DRAFT
 * and, until this block existed, none at all from the layer every screen
 * actually renders. §2's own headline claim went unverified in CI for the same
 * reason: nothing read it.
 */
describe("core role contrast", () => {
  const textPairs: [string, string][] = [
    ["foreground", "background"],
    ["card-foreground", "card"],
    ["popover-foreground", "popover"],
    ["primary-foreground", "primary"],
    ["secondary-foreground", "secondary"],
    ["muted-foreground", "muted"],
    ["accent-foreground", "accent"],
    ["destructive-foreground", "destructive"],
  ];

  for (const mode of ["light", "dark"] as const) {
    it(`${mode}: every core text pair clears WCAG AA`, () => {
      const block = rule(mode === "light" ? ":root" : ".dark");
      for (const [foreground, background] of textPairs) {
        expect(
          contrast(variable(block, foreground), variable(block, background)),
          `${foreground} on ${background} in ${mode}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    });

    /**
     * WCAG 1.4.11, the non-text half — and the reason there are two border
     * tokens. `border` is decorative and deliberately below 3:1: darkening
     * every card edge and table rule to clear it would turn §1's tonal
     * layering into a wireframe. `border-strong` and `input` draw the boundary
     * of things you can operate, and those must clear it against every surface
     * a control sits on.
     */
    it(`${mode}: an operable boundary clears 3:1 on every surface`, () => {
      const block = rule(mode === "light" ? ":root" : ".dark");
      const surfaces = mode === "light"
        ? ["card", "background", "muted"]
        : ["card", "background", "popover"];
      for (const token of ["border-strong", "input"] as const) {
        for (const surface of surfaces) {
          expect(
            contrast(variable(block, token), variable(block, surface)),
            `${token} on ${surface} in ${mode}`,
          ).toBeGreaterThanOrEqual(3);
        }
      }
    });

    it(`${mode}: the decorative border stays decorative`, () => {
      // Pinned deliberately: if somebody darkens `border` to "fix contrast",
      // they have made the palette change §2 rejected, and this says so
      // rather than letting it pass as an improvement.
      const block = rule(mode === "light" ? ":root" : ".dark");
      expect(
        contrast(variable(block, "border"), variable(block, "card")),
      ).toBeLessThan(3);
    });
  }
});

function rule(selector: string): string {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`Missing ${selector} token block`);
  const end = css.indexOf("\n  }", start);
  return css.slice(start, end);
}

function variable(block: string, name: string): [number, number, number] {
  const match = block.match(new RegExp(`--${name}:\\s*([\\d.]+)\\s+([\\d.]+)%\\s+([\\d.]+)%`));
  if (!match?.[1] || !match[2] || !match[3]) throw new Error(`Missing --${name}`);
  return hslToRgb(Number(match[1]), Number(match[2]) / 100, Number(match[3]) / 100);
}

function hslToRgb(hue: number, saturation: number, lightness: number): [number, number, number] {
  const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
  const segment = ((hue % 360) + 360) % 360 / 60;
  const second = chroma * (1 - Math.abs((segment % 2) - 1));
  const [red, green, blue] =
    segment < 1 ? [chroma, second, 0] :
    segment < 2 ? [second, chroma, 0] :
    segment < 3 ? [0, chroma, second] :
    segment < 4 ? [0, second, chroma] :
    segment < 5 ? [second, 0, chroma] : [chroma, 0, second];
  const offset = lightness - chroma / 2;
  return [red + offset, green + offset, blue + offset];
}

function contrast(first: [number, number, number], second: [number, number, number]): number {
  const brighter = Math.max(luminance(first), luminance(second));
  const darker = Math.min(luminance(first), luminance(second));
  return (brighter + 0.05) / (darker + 0.05);
}

function luminance(colour: [number, number, number]): number {
  const [red, green, blue] = colour.map((channel) =>
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4,
  ) as [number, number, number];
  return red * 0.2126 + green * 0.7152 + blue * 0.0722;
}
