import type { ReactNode } from "react";

export function StatePanel({ title, children, actions, tone }: { title: string; children?: ReactNode; actions?: ReactNode; tone?: "alert" }) {
  return (
    <div className={`state-panel${tone === "alert" ? " state-panel--alert" : ""}`} role="status">
      <h2 className="state-title">{title}</h2>
      {children && <div className="state-body">{children}</div>}
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
