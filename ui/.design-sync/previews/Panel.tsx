import { Panel, Button } from 'etl-craft-ui';

export function Default() {
  return (
    <div style={{ width: 420, height: 180 }}>
      <Panel title="Recent runs" aside={<Button variant="ghost" size="sm">View all</Button>}>
        <div style={{ fontSize: 13 }}>#1042 succeeded · #1041 failed · #1040 running</div>
      </Panel>
    </div>
  );
}
