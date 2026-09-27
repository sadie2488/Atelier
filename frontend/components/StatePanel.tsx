import type { ReactNode } from "react";

export function StatePanel({ title, children, actions }: { title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="state-panel" role="status">
      <h2 className="state-title">{title}</h2>
      {children && <p className="state-body">{children}</p>}
      {actions && <div className="state-actions">{actions}</div>}
    </div>
  );
}

export function Loader({ label }: { label: string }) {
  return (
    <div className="loader" role="status" aria-live="polite">
      <div className="loader-bar"><span /></div>
      <p>{label}</p>
    </div>
  );
}
