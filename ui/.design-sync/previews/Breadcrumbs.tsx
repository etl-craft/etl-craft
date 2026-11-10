import { MemoryRouter, QueryClient, QueryClientProvider } from 'etl-craft-ui';
const client = new QueryClient();
const Wrap = ({ children }: { children: React.ReactNode }) => (
  <MemoryRouter><QueryClientProvider client={client}>{children}</QueryClientProvider></MemoryRouter>
);
import { Breadcrumbs } from 'etl-craft-ui';

export function Trail() {
  return <Wrap><Breadcrumbs trail={[{ label: 'Pipelines', to: '/pipelines' }, { label: 'sales_daily', to: '/pipelines/sales_daily' }, { label: 'Run #1042' }]} /></Wrap>;
}
