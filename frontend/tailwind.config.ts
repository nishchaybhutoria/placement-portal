import type { Config } from "tailwindcss";

/**
 * Tailwind bindings for the design system.
 *
 * Every value here resolves to a CSS custom property defined in `src/index.css`,
 * which is in turn transcribed from `docs/design/DESIGN.md`. No literal colour
 * may appear in this file either — the token layer is the one place they live.
 *
 * `<alpha-value>` lets Tailwind compose opacity onto a token
 * (`bg-primary/90` → `hsl(218.7 15.6% 39.0% / 0.9)`), which is how the hover
 * and active states in DESIGN.md §8 are expressed.
 */
const token = (name: string) => `hsl(var(--${name}) / <alpha-value>)`;

/** DESIGN.md §3 — each semantic family is fg / subtle fill / border. */
const semantic = (name: string) => ({
  DEFAULT: token(name),
  subtle: token(`${name}-subtle`),
  border: token(`${name}-border`),
});

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // core roles — DESIGN.md §2
        background: token("background"),
        foreground: token("foreground"),
        card: { DEFAULT: token("card"), foreground: token("card-foreground") },
        popover: { DEFAULT: token("popover"), foreground: token("popover-foreground") },
        primary: { DEFAULT: token("primary"), foreground: token("primary-foreground") },
        secondary: { DEFAULT: token("secondary"), foreground: token("secondary-foreground") },
        muted: { DEFAULT: token("muted"), foreground: token("muted-foreground") },
        accent: { DEFAULT: token("accent"), foreground: token("accent-foreground") },
        destructive: { DEFAULT: token("destructive"), foreground: token("destructive-foreground") },
        border: token("border"),
        // DESIGN.md §2: `border` draws content separators, `border-strong`
        // draws the boundary of anything you can operate (WCAG 1.4.11).
        "border-strong": token("border-strong"),
        input: token("input"),
        ring: token("ring"),

        // semantic status layer — DESIGN.md §3 (DRAFT)
        success: semantic("success"),
        warning: semantic("warning"),
        danger: semantic("danger"),
        info: semantic("info"),
        neutral: semantic("neutral"),
        brand: semantic("brand"),
      },

      // DESIGN.md §5 — Public Sans throughout; no monospace by doctrine.
      fontFamily: {
        sans: ["Public Sans", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      fontSize: {
        display: ["30px", { lineHeight: "36px", fontWeight: "600", letterSpacing: "-0.02em" }],
        "headline-lg": ["24px", { lineHeight: "32px", fontWeight: "600", letterSpacing: "-0.01em" }],
        "headline-md": ["20px", { lineHeight: "28px", fontWeight: "600" }],
        "body-lg": ["16px", { lineHeight: "24px", fontWeight: "400" }],
        "body-md": ["14px", { lineHeight: "20px", fontWeight: "400" }],
        "body-sm": ["12px", { lineHeight: "16px", fontWeight: "400" }],
        "label-caps": ["11px", { lineHeight: "16px", fontWeight: "700", letterSpacing: "0.05em" }],
        "label-sm": ["11px", { lineHeight: "16px", fontWeight: "500" }],
      },

      // DESIGN.md §6 — 4px rhythm. Named steps carry the doctrine's intent;
      // Tailwind's numeric scale (already 4px-based) stays available.
      spacing: {
        "gap-tight": "4px",
        "gap-md": "8px",
        "gap-lg": "16px",
        "container-padding": "24px",
        "section-margin": "32px",
        "table-cell-x": "16px",
        "table-cell-y": "12px",
        sidebar: "256px",
        control: "36px",
        chip: "22px",
      },

      // DESIGN.md §7 — 4px default. `full` is for avatars and spinners only;
      // pills and circular chips are prohibited.
      borderRadius: {
        sm: "2px",
        DEFAULT: "var(--radius)",
        md: "6px",
        lg: "8px",
        xl: "12px",
        full: "9999px",
      },

      // DESIGN.md §7 — the single sanctioned shadow, for modal overlays only.
      boxShadow: {
        overlay: "0 0 4px 0 hsl(var(--foreground) / 0.1)",
      },
    },
  },
  plugins: [],
} satisfies Config;
