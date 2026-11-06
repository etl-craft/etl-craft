---
name: web-design-guidelines
description: Review etl-craft's browser UI (the React sources under ui/src) against the Web Interface Guidelines and report findings as file:line. Use before a pull request that changes a page or a component under ui/src, or when asked to review the UI's design, UX or accessibility.
---

# web-design-guidelines

Vendored from [vercel-labs/web-interface-guidelines](https://github.com/vercel-labs/web-interface-guidelines)
at `434b7f9` (MIT, see `LICENSE`); the rules
are in `rules.md` and are read from there, never fetched at run time.

## How to use

1. Read `rules.md` and the files to review (default: `ui/src/pages/**`,
   `ui/src/components/**`, `ui/src/index.css`).
2. Report findings grouped by file in `file:line` form, as `rules.md` describes.
3. Fix what is mechanical; list the rest with the reason.
4. Render the changed pages with the repo's Playwright (light, dark, 390 px) and look at them.

## What applies here

The UI is React with Tailwind and shared components (`ui/src/components`); pages compose them,
and `ui/eslint.config.js` refuses copies. Skip the rules written for server-rendered HTML
and read their intent against the shared components instead.

Project decisions take precedence over these rules:

- Headings and buttons use sentence case, as in the approved Databricks-style layout, not
  Title Case.
- Times are formatted with `formatTime` in the person's chosen timezone, so pages and
  exports agree; do not reformat them with `Intl` elsewhere.
- Status colours follow the shared tokens in `core/static/catalog.css` (green succeeded, red
  failed, blue running, grey waiting, slate stopped; amber only for retries and warnings), and
  every state keeps its symbol and word.
- Destructive actions confirm through the shared dialog with the exact scope and effect.
