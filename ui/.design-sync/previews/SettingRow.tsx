import { SettingRow, Button } from 'etl-craft-ui';

export function Default() {
  return (
    <div style={{ width: 680, border: '1px solid #e5e7eb', borderRadius: 8 }}>
      <SettingRow title="Automatic starts" hint="Start runs on the schedule without an operator.">
        <Button variant="outline" size="sm">Turn off</Button>
      </SettingRow>
    </div>
  );
}
