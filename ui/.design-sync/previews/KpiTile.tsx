import { KpiTile } from 'etl-craft-ui';

export function Tones() {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 160px)', gap: 12 }}>
      <KpiTile label="Runs today" value="48" hint="+6 vs yesterday" tone="ok" />
      <KpiTile label="Failed" value="3" hint="2 need attention" tone="bad" />
      <KpiTile label="Late starts" value="1" tone="warn" />
    </div>
  );
}
