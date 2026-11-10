import { Card, CardHeader, CardTitle, CardFooter, Button } from 'etl-craft-ui';

export function Summary() {
  return (
    <Card style={{ width: 360 }}>
      <CardHeader>
        <CardTitle>sales_daily</CardTitle>
      </CardHeader>
      <div style={{ padding: '0 16px 12px', fontSize: 13 }}>Last run succeeded at 02:14 UTC, 1.2M rows loaded.</div>
      <CardFooter>
        <Button variant="outline" size="sm">Open pipeline</Button>
      </CardFooter>
    </Card>
  );
}
