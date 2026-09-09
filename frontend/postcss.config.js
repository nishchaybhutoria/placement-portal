// Tailwind 4 ships its PostCSS plugin as its own package, and prefixes with
// Lightning CSS internally — autoprefixer is no longer part of the pipeline.
export default {
  plugins: { "@tailwindcss/postcss": {} },
};
