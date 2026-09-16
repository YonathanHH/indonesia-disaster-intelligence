/** Small shared presentational primitives. */
import type { ReactNode } from "react";

export function Badge({ prio }: { prio: string }) {
  return <span className={`badge b-${prio}`}>{prio}</span>;
}

export function SectionHead({
  title,
  count,
  note,
  children,
}: {
  title: string;
  count?: number | string;
  note?: string;
  children?: ReactNode;
}) {
  return (
    <div className="panelhead">
      <span className="title">{title}</span>
      {count != null && <span className="count">{count}</span>}
      {note && <span className="sect note" style={{ margin: 0 }}>{note}</span>}
      <span className="grow" />
      {children && <div className="tools">{children}</div>}
    </div>
  );
}

export function SkeletonRows({ n = 5, h = 44 }: { n?: number; h?: number }) {
  return (
    <div style={{ padding: "10px 12px", display: "flex", flexDirection: "column", gap: 8 }} aria-busy="true" aria-label="Loading">
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="skel" style={{ height: h }} />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  sub,
  action,
}: {
  title: string;
  sub?: string;
  action?: ReactNode;
}) {
  return (
    <div className="emptystate" role="status">
      <div className="es-t">{title}</div>
      {sub && <div className="es-s">{sub}</div>}
      {action}
    </div>
  );
}
