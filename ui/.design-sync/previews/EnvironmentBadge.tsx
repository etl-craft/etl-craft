import { EnvironmentBadge } from 'etl-craft-ui';

export function Types() {
  return (
    <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
      <EnvironmentBadge env={{ type: 'PROD', name: null }} />
      <EnvironmentBadge env={{ type: 'TEST', name: 'nightly' }} />
      <EnvironmentBadge env={{ type: 'DEV', name: null }} />
    </div>
  );
}
