import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      // Intentional here: fetch-on-mount hooks and plain <img> for backend-served cutouts.
      "react-hooks/set-state-in-effect": "off",
      "@next/next/no-img-element": "off",
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Vendored @mediapipe/tasks-vision wasm runtime (scripts/copy-mediapipe-wasm.mjs) -- generated,
    // not source we own.
    "public/mediapipe/**",
  ]),
]);

export default eslintConfig;
