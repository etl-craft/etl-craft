import { ConfirmDialog } from 'etl-craft-ui';

export function Reason() {
  return (
    <ConfirmDialog
      open
      title="Pause sales_daily"
      action="Pause"
      effect="Stops scheduled starts until resumed."
      projectCode="sales"
      env={{ type: 'PROD', name: null }}
      error=""
      busy={false}
      askReason
      canSubmit
      onConfirm={() => {}}
      onClose={() => {}}
    />
  );
}
