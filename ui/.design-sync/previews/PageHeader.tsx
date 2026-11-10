import { MemoryRouter, QueryClient, QueryClientProvider } from 'etl-craft-ui';
const client = new QueryClient();
const Wrap = ({ children }: { children: React.ReactNode }) => (
  <MemoryRouter><QueryClientProvider client={client}>{children}</QueryClientProvider></MemoryRouter>
);
import { PageHeader, Button } from 'etl-craft-ui';

export function Default() {
  return (
    <Wrap>
      <div style={{ width: 720 }}>
        <PageHeader title="sales_daily" subtitle="Loads daily sales into the warehouse" actions={<Button variant="primary">Run now</Button>} />
      </div>
    </Wrap>
  );
}

export function WithBack() {
  return (
    <Wrap>
      <div style={{ width: 720 }}>
        <PageHeader title="Run #1042" compact back={{ to: '/pipelines/sales_daily', label: 'sales_daily' }} />
      </div>
    </Wrap>
  );
}
