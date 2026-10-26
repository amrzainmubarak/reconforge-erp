import type { ReactNode } from "react";

export function StudioPageHeader({ title, description }: { title: string; description?: string }) {
  return <header className="studio-page-header"><h1>{title}</h1>{description && <p>{description}</p>}</header>;
}

/** A named, keyboard-reachable viewport keeps wide financial tables usable. */
export function StudioTableViewport({ label, children }: { label: string; children: ReactNode }) {
  return <div className="studio-table-viewport finance-table" role="region" aria-label={label} tabIndex={0}>{children}</div>;
}
