/** @type {import('tailwindcss').Config} */
// Config Tailwind CSS pour Menu IG Bas — build local (V2.87.0, issue #94).
// Le CSS compilé est embarqué dans le repo (`tailwind.css`) et servi par
// GitHub Pages. Plus aucune dépendance CDN runtime.

// V3 (refonte design 1A) — couleurs de marque branchées sur les variables CSS
// de tailwind-input.css : une seule source de vérité, clair ET sombre.
const token = name => `rgb(var(--${name}) / <alpha-value>)`;

module.exports = {
  // Scan index.html pour ne garder que les classes effectivement utilisées
  // (tree-shaking). Sans ça, le CSS pèse ~3 MB ; avec, ~100-200 KB minifié.
  content: ["./index.html"],
  // V2.16.0 — Mode sombre via classe `dark` sur <html> (toggle manuel,
  // pas media query stricte).
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        canvas: token("canvas"),
        surface: { DEFAULT: token("surface"), 2: token("surface-2") },
        ink: token("ink"),
        muted: token("muted"),
        line: token("line"),
        brand: { DEFAULT: token("brand"), soft: token("brand-soft"), on: token("on-brand") },
        sage: { DEFAULT: token("sage"), soft: token("sage-soft") },
        terracotta: { DEFAULT: token("terracotta"), soft: token("terracotta-soft") },
        danger: { DEFAULT: token("danger"), soft: token("danger-soft") },
      },
      fontFamily: {
        ui: "var(--font-ui)",
        title: "var(--font-title)",
      },
      borderRadius: { card: "var(--radius-card)" },
      boxShadow: { card: "var(--shadow-card)" },
    },
  },
  plugins: [],
};
