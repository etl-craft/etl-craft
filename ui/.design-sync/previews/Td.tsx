import { Table, Th, Td } from 'etl-craft-ui';

export function Runs() {
  return (
    <Table>
      <thead>
        <tr><Th>Run</Th><Th>Pipeline</Th><Th>Status</Th><Th>Duration</Th></tr>
      </thead>
      <tbody>
        <tr><Td>#1042</Td><Td>sales_daily</Td><Td>SUCCESS</Td><Td>4m 12s</Td></tr>
        <tr><Td>#1041</Td><Td>customers_sync</Td><Td>FAILED</Td><Td>1m 03s</Td></tr>
        <tr><Td>#1040</Td><Td>sales_daily</Td><Td>RUNNING</Td><Td>2m 40s</Td></tr>
      </tbody>
    </Table>
  );
}
