import { AlarmClock, ArrowUpRight, Bell, CalendarArrowDown, CalendarArrowUp, Check, CircleParking, GripVertical, ListTodo,
  Loader2, X } from "lucide-react";
import { useState } from "react";
import type { DragEvent } from "react";
import { api } from "../api/client";
import { useLive } from "../api/live";
import type { FullState } from "../api/types";
import { cn, localTime, todayIso } from "../lib/utils";
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

/* Drag and drop between Today, Tomorrow and Parked tangents (the row buttons do the same from the keyboard). */
const MIME = "application/x-pip-item";
type Dragged = { kind: Row["kind"] | "parked"; id: string; from: string };

function startDrag(e: DragEvent, item: Dragged) {
  e.dataTransfer.setData(MIME, JSON.stringify(item));
  e.dataTransfer.effectAllowed = "move";
}

function useDropZone(accept: (d: Dragged) => boolean, onDrop: (d: Dragged) => void) {
  const [over, setOver] = useState(false);
  const read = (e: DragEvent): Dragged | null => {
    try { return JSON.parse(e.dataTransfer.getData(MIME)) as Dragged; } catch { return null; }
  };
  return {
    over,
    props: {
      onDragOver: (e: DragEvent) => {
        if (!e.dataTransfer.types.includes(MIME)) return;
        e.preventDefault(); // the payload is only readable on drop: accept here, filter there
        e.dataTransfer.dropEffect = "move";
        setOver(true);
      },
      onDragLeave: () => setOver(false),
      onDrop: (e: DragEvent) => {
        e.preventDefault();
        setOver(false);
        const d = read(e);
        if (d && accept(d)) onDrop(d);
      },
    },
  };
}

export function DayPanel({ title, offset }: { title: string; offset: number }) {
  const { state, run } = useLive();
  const day = todayIso(offset);
  const drop = useDropZone((d) => d.from !== day && (d.kind !== "parked" || offset === 0),
    (d) => void run(() => (d.kind === "parked" ? api.promoteParked(d.id) : api.agendaMove(d.kind, d.id, day))));
  if (!state) return null;
  const rows = rowsFor(state, day);
  const other = offset === 0 ? todayIso(1) : todayIso(0);
  return (
    <Card aria-label={title} {...drop.props} className={cn(drop.over && "ring-2 ring-amber")}>
      <CardTitle aside={<span className="text-xs text-muted">{rows.length} item{rows.length === 1 ? "" : "s"}</span>}>
        {title}</CardTitle>
      {rows.length === 0 ? <Empty>{drop.over ? "Drop it here." : "Nothing here. That's okay."}</Empty> : (
        <ul className="space-y-1.5">
          {rows.map((r) => {
            const Icon = ICON[r.kind];
            return (
              <li key={r.id} draggable={!r.done} onDragStart={(e) => startDrag(e, { kind: r.kind, id: r.id, from: day })}
                data-testid="agenda-row" title={r.done ? undefined : "Drag to Tomorrow, Today or Parked tangents"}
                className={cn("group flex items-center gap-2.5 rounded-xl border border-line bg-white/60 px-3 py-2",
                  !r.done && "cursor-grab active:cursor-grabbing")}>
                {!r.done && <GripVertical size={14} aria-hidden className="-ml-1.5 shrink-0 text-line group-hover:text-muted" />}
                <Icon size={16} className="text-muted" aria-label={r.kind} />
                <span className={`flex-1 text-sm ${r.done ? "text-muted line-through" : ""}`}>{r.title}</span>
                {r.when && <span className="tabular text-xs text-muted">{r.when}</span>}
                {r.kind === "reminder" && !r.done && (
                  <Button size="sm" variant="ghost" aria-label={`Mark ${r.title} done`}
                    onClick={() => run(() => api.patchReminder(r.id, { done: true }))}><Check size={14} aria-hidden /></Button>
                )}
                {r.kind === "task" && !r.done && state.active_task?.id !== r.id && offset === 0 && (
                  <Button size="sm" variant="ghost" aria-label={`Focus on ${r.title}`}
                    onClick={() => run(() => api.activateTask(r.id))}><ArrowUpRight size={14} aria-hidden /></Button>
                )}
                {!r.done && (
                  <Button size="sm" variant="ghost" aria-label={`Move ${r.title} to ${offset === 0 ? "tomorrow" : "today"}`}
                    title={offset === 0 ? "Move to tomorrow" : "Move to today"}
                    onClick={() => run(() => api.agendaMove(r.kind, r.id, other))}>
                    {offset === 0 ? <CalendarArrowDown size={14} aria-hidden /> : <CalendarArrowUp size={14} aria-hidden />}</Button>
                )}
                {!r.done && (
                  <Button size="sm" variant="ghost" aria-label={`Park ${r.title}`} title="Park for later"
                    onClick={() => run(() => api.agendaPark(r.kind, r.id))}><CircleParking size={14} aria-hidden /></Button>
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
  const [busy, setBusy] = useState<string | null>(null);
  const drop = useDropZone((d) => d.kind !== "parked", (d) => {
    const kind = d.kind;
    if (kind !== "parked") void run(() => api.agendaPark(kind, d.id));
  });
  if (!state) return null;
  const promote = async (id: string) => {
    setBusy(id);
    await run(() => api.promoteParked(id)); // a thought is broken into steps by Kimi (~20-40 s)
    setBusy(null);
  };
  return (
    <Card aria-label="Parked tangents" {...drop.props} className={cn(drop.over && "ring-2 ring-amber")}>
      <CardTitle aside={<span className="text-xs text-muted">safe for later</span>}>Parked tangents</CardTitle>
      {state.parked.length === 0 ? <Empty>{drop.over ? "Drop it here - it waits safely."
        : "No tangents parked. Your lane is clear. Drag anything here to park it."}</Empty> : (
        <ul className="space-y-1.5">
          {state.parked.map((p) => (
            <li key={p.id} draggable onDragStart={(e) => startDrag(e, { kind: "parked", id: p.id, from: "parked" })}
              title="Drag onto Today to start it" data-testid="parked-row"
              className="group flex cursor-grab items-center gap-2 rounded-xl border border-line bg-white/60 px-3 py-2">
              <GripVertical size={14} aria-hidden className="-ml-1.5 shrink-0 text-line group-hover:text-muted" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{p.title}</p>
                {p.source_text && <p className="truncate text-xs text-muted">“{p.source_text}”</p>}
              </div>
              {p.task_id ? (
                <Button size="sm" disabled={busy !== null} onClick={() => void promote(p.id)}
                  title="Carries on where you left off" aria-label={`Resume ${p.title}`}>Resume</Button>
              ) : (
                <Button size="sm" disabled={busy !== null} onClick={() => void promote(p.id)}
                  title="Kimi breaks it into concrete steps" aria-label={`Promote ${p.title} to active`}>
                  {busy === p.id ? <><Loader2 size={14} className="animate-spin" aria-hidden /> Planning…</> : "Promote"}</Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => run(() => api.dismissParked(p.id))}
                aria-label={`Let go of ${p.title}`}><X size={14} aria-hidden /></Button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
