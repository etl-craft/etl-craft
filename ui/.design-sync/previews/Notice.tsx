import { Notice } from 'etl-craft-ui';

export function Variants() {
  return (
    <div style={{ display: 'grid', gap: 12, width: 420 }}>
      <Notice>Changes apply to the next run.</Notice>
      <Notice info>Auto-start is paused for this project.</Notice>
      <Notice mono>ERROR connection refused: craft.localhost:5432</Notice>
    </div>
  );
}
