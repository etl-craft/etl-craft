import { Button } from 'etl-craft-ui';

export function Variants() {
  return (
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
      <Button variant="primary">Run pipeline</Button>
      <Button variant="outline">View runs</Button>
      <Button variant="ghost">Cancel</Button>
      <Button variant="danger">Pause</Button>
      <Button variant="dangerSolid">Delete project</Button>
    </div>
  );
}

export function Sizes() {
  return (
    <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
      <Button size="sm">Small</Button>
      <Button size="md">Medium</Button>
      <Button size="icon" aria-label="Refresh">↻</Button>
    </div>
  );
}
