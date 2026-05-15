import js from "@eslint/js";
import globals from "globals";

export default [
  js.configs.recommended,
  {
    files: ["src/lola_eval/_data/providers/**/*.js", "tests/node/**/*.js"],
    languageOptions: {
      globals: {
        ...globals.node,
      },
    },
  },
  {
    ignores: ["node_modules/"],
  },
];
