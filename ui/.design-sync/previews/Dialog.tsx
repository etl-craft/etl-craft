import { Dialog, Button } from 'etl-craft-ui';

export function Default() {
  return (
    <Dialog open onClose={() => {}} labelledBy="dlg-title" className="p-5">
      <div style={{ display: 'grid', gap: 12, width: 360 }}>
        <h2 id="dlg-title" style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>Edit schedule</h2>
        <p style={{ margin: 0, fontSize: 13 }}>The new schedule applies from the next start.</p>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <Button variant="ghost">Cancel</Button>
          <Button variant="primary">Save</Button>
        </div>
      </div>
    </Dialog>
  );
}
