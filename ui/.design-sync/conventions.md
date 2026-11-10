# etl-craft UI: conventions for building with these components

**Wrap any page that uses routing or data components in both providers.** Breadcrumbs and PageHeader need a router; FormAction and RowActions need a query client. Without them the card renders empty.

```tsx
import { MemoryRouter, QueryClient, QueryClientProvider } from 'etl-craft-ui';
const client = new QueryClient();
<MemoryRouter><QueryClientProvider client={client}>{page}</QueryClientProvider></MemoryRouter>
```

**Styling is Tailwind utility classes over theme tokens.** No CSS modules, no inline theme objects. Use the token names, not raw hex:

| Role | Classes |
|---|---|
| Surface / page | `bg-bg`, `bg-surface`, `bg-sidebar` |
| Text | `text-fg`, `text-muted`, `text-sidebar-fg` |
| Borders | `border-border`, `border-border-strong` |
| Status | `text-ok`/`bg-ok-bg`, `text-bad`/`bg-bad-bg`, `text-warn`/`bg-warn-bg`, `text-run`/`bg-run-bg`, `text-idle`/`bg-idle-bg` |
| Accent | `bg-accent`, `text-accent-fg` |
| Fonts | Body text is Inter by default; `font-mono` (JetBrains Mono) for IDs, SQL and logs |

Dark mode is the `data-theme="dark"` attribute on an ancestor. Do not hard-code colours; the tokens switch with the theme.

**Read these before styling:** `styles.css` (theme tokens and imports), `_ds_bundle.css` (component styles), and each component's `.prompt.md`.

**Build snippet** (a status panel from the library parts):

```tsx
import { Panel, KpiTile, StatusBadge, Button } from 'etl-craft-ui';
<div className="flex gap-3">
  <KpiTile label="Failed" value="3" tone="bad" />
  <Panel title="Recent runs" aside={<Button variant="ghost" size="sm">View all</Button>}>
    <StatusBadge status="FAILED" />
  </Panel>
</div>
```
