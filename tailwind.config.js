/** @type {import('tailwindcss').Config} */
// Config Tailwind CSS pour Menu IG Bas — build local (V2.87.0, issue #94).
// Le CSS compilé est embarqué dans le repo (`tailwind.css`) et servi par
// GitHub Pages. Plus aucune dépendance CDN runtime.
module.exports = {
  // Scan index.html pour ne garder que les classes effectivement utilisées
  // (tree-shaking). Sans ça, le CSS pèse ~3 MB ; avec, ~100-200 KB minifié.
  content: ["./index.html"],
  // V2.16.0 — Mode sombre via classe `dark` sur <html> (toggle manuel,
  // pas media query stricte).
  darkMode: "class",
  theme: {
    extend: {},
  },
  plugins: [],
};
