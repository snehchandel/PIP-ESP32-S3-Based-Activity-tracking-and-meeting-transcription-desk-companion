import { AlarmClock, ArrowUpRight, Bell, Check, ListTodo, X } from "lucide-react";
import { api } from "../api/client";
import { useLive } from "../api/live";
import type { FullState } from "../api/types";
import { localTime, todayIso } from "../lib/utils";
import { Button } from "./ui/button";
import { Card, CardTitle, Empty } from "./ui/primitives";

interface Row { id: string; title: string; when: string; kind: "task" | "reminder" | "alarm"; done: boolean }

function rowsFor(s: FullState, dayIso: string): Row[] {
  const rows: Row[] = [];
  for (const t of s.tasks) {
    if (t.target_date === dayIso) rows.push({ id: t.id, title: t.title, when: "", kind: "task", done: t.status === "COMPLETED" });
  }
  for (const r of s.reminders) {
    const d = new Date(r.due_utc);
    if (todayIsoOf(d) === dayIso) rows.push({ id: r.id, title: r.title, when: localTime(r.due_utc), kind: "reminder", done: !!r.done });
  }
  for (const a of s.alarms) {
    if (a.schedule_kind === "ONCE" && a.fire_utc && a.enabled && todayIsoOf(new Date(a.fire_utc)) === dayIso) {
      rows.push({ id: a.id, title: a.title, when: a.local_hhmm, kind: "alarm", done: false });
    }
  }
  return rows.sort((x, y) => Number(x.done) - Number(y.done) || (x.when || "99").localeCompare(y.when || "99"));
}

function todayIsoOf(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const ICON = { task: ListTodo, reminder: Bell, alarm: AlarmClock };

export function DayPanel({ title, offset }: { title: string; offset: number }) {
  const { state, run } = useLive();
  if (!state) return null;
  const rows = rowsFor(state, todayIso(offset));
  return (
    <Card aria-label={title}>
      <CardTitle aside={<span className="text-xs text-muted">{rows.length} item{rows.length === 1 ? "" : "s"}</span>}>
        {title}</CardTitle>
      {rows.length === 0 ? <Empty>Nothing here. That's okay.</Empty> : (
        <ul className="space-y-1.5">
          {rows.map((r) => {
            const Icon = ICON[r.kind];
            return (
              <li key={r.id} className="flex items-center gap-2.5 rounded-xl border border-line bg-white/60 px-3 py-2">
                <Icon size={16} className="text-muted" aria-label={r.kind} />
                <span className={`flex-1 text-sm ${r.done ? "text-muted line-through" : ""}`}>{r.title}</span>
                {r.when && <span className="tabular text-xs text-muted">{r.when}</span>}
                {r.kind === "reminder" && !r.done && (
                  <Button size="sm" variant="ghost" aria-label={`Mark ${r.title} done`}
                    onClick={() => run(() => api.patchReminder(r.id, { done: true }))}><Check size={14} aria-hidden /></Button>
                )}
                {r.kind === "task" && !r.done && state.active_task?.id !== r.id && (
                  <Button size="sm" variant="ghost" aria-label={`Focus on ${r.title}`}
                    onClick={() => run(() => api.activateTask(r.id))}><ArrowUpRight size={14} aria-hidden /></Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

export function ParkedPanel() {
  const { state, run } = useLive();
  if (!state) return null;
  return (
    <Card aria-label="Parked tangents">
      <CardTitle aside={<span className="text-xs text-muted">safe for later</span>}>Parked tangents</CardTitle>
      {state.parked.length === 0 ? <Empty>No tangents parked. Your lane is clear.</Empty> : (
        <ul className="space-y-1.5">
          {state.parked.map((p) => (
            <li key={p.id} className="flex items-center gap-2 rounded-xl border border-line bg-white/60 px-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{p.title}</p>
                {p.source_text && <p className="truncate text-xs text-muted">“{p.source_text}”</p>}
              </div>
              <Button size="sm" onClick={() => run(() => api.promoteParked(p.id))} aria-label={`Promote ${p.title} to active`}>
                Promote</Button>
              <Button size="sm" variant="ghost" onClick={() => run(() => api.dismissParked(p.id))}
                aria-label={`Let go of ${p.title}`}><X size={14} aria-hidden /></Button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
