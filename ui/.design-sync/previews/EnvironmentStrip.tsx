import { EnvironmentStrip } from 'etl-craft-ui';

export function Production() {
  return <div style={{ width: 720 }}><EnvironmentStrip env={{ type: 'PROD', name: null }} /></div>;
}

export function Test() {
  return <div style={{ width: 720 }}><EnvironmentStrip env={{ type: 'TEST', name: 'nightly' }} /></div>;
}
