import js from "@eslint/js";
import globals from "globals";
import hooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["../src/etl_craft/api/spa/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: { globals: globals.browser },
    plugins: { "react-hooks": hooks },
    rules: {
      ...hooks.configs.recommended.rules,
      // TanStack Table's hook returns unmemoizable functions; the compiler skips that one component.
      "react-hooks/incompatible-library": "off",
    },
  },
  {
    // Shared pieces live in src/components; pages compose them instead of re-writing them.
    files: ["src/pages/**/*.tsx"],
    rules: {
      "no-restricted-syntax": [
        "error",
        { selector: "JSXOpeningElement[name.name='h1']", message: "Use <PageHeader> from components/common." },
        { selector: "JSXOpeningElement[name.name='select']", message: "Use <SelectField> from components/common." },
        { selector: "JSXAttribute[name.name='aria-label'][value.value=/[Ll]egend|[Vv]iew key/]", message: "Use the shared legend component; pages supply entries." },
        { selector: "JSXOpeningElement[name.name='dl']", message: "Use <FactList> and <Fact> from components/common." },
        { selector: "JSXAttribute[name.name='role'][value.value='alert']", message: "Use <Notice> from components/common." },
        { selector: "TemplateLiteral[quasis.0.value.raw=/^\\/projects\\//]", message: "Build in-app paths with lib/routes." },
        { selector: "JSXAttribute[name.name='className'] Literal[value=/(^|\\s)(max-sm:)?h-(7|9|10|11)(\\s|$)/]", message: "A control takes its height from the token: use h-control (the same in every row)." },
      ],
    },
  },
  {
    // Components that are not controls (chart bars, graph nodes, grid headers, touch sizes) may size themselves.
    files: ["src/components/**/*.tsx"],
    ignores: ["src/components/{charts,run-grid,diagram-node,task-mapping,dropdown,app-shell}.tsx"],
    rules: {
      "no-restricted-syntax": [
        "error",
        { selector: "JSXAttribute[name.name='className'] Literal[value=/(^|\\s)(max-sm:)?h-(7|9|10|11)(\\s|$)/]", message: "A control takes its height from the token: use h-control (the same in every row)." },
      ],
    },
  },
);
