import { Bell, CalendarPlus, CircleCheck, CircleParking, Play, X } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import { useLive } from "../api/live";
import type { ActionItem, MeetingDetail } from "../api/types";
import { cn } from "../lib/utils";
import { Button } from "./ui/button";
import { Badge, Input } from "./ui/primitives";

/* A meeting's action items, decided one by one or in bulk: tick the ones you want, then make them tasks (on their
   date), reminders (a ping at that date/time) or parked tangents - or say "not for me". Items with a date also
   show on the Calendar until you decide. Yours (Settings -> Meetings -> your name) come first and are pre-ticked. */

const STATUS: Record<string, string> = { task: "task", reminder: "reminder", parked: "parked", dismissed: "not for me" };

function toSeconds(at?: string | null): number | null {
  const m = at?.match(/^(?:(\d+):)?(\d{1,2}):(\d{2})$/);
  return m ? Number(m[1] ?? 0) * 3600 + Number(m[2]) * 60 + Number(m[3]) : null;
}

export function ActionItems({ m, onSeek, reload }: { m: MeetingDetail; onSeek: (t: number) => void; reload: () => void }) {
  const { run } = useLive();
  const items = m.summary?.action_items ?? [];
  const open = (a: ActionItem) => (a.status ?? "new") === "new" && !a.done;
  const [picked, setPicked] = useState<Set<number>>(() => new Set(items.map((a, i) => (open(a) && a.mine ? i : -1)).filter((i) => i >= 0)));
  const [dates, setDates] = useState<Record<number, { d: string; t: string }>>({});
  const [busy, setBusy] = useState(false);
  if (items.length === 0) return null;
  const when = (i: number, a: ActionItem) => dates[i] ?? { d: a.due_date ?? "", t: a.due_time ?? "" };
  const toggle = (i: number) => setPicked((p) => { const n = new Set(p); if (n.has(i)) n.delete(i); else n.add(i); return n; });
  const sel = [...picked].filter((i) => open(items[i]));
  const order = items.map((_, i) => i).sort((x, y) => Number(!open(items[x])) - Number(!open(items[y]))
    || Number(!items[x].mine) - Number(!items[y].mine));

  const convert = async (as: "task" | "reminder" | "park") => {
    setBusy(true);
    await run(() => api.convertActions(m.id, sel.map((i) => {
      const w = when(i, items[i]);
      return { index: i, as, ...(w.d ? { date: w.d } : {}), ...(w.t ? { time: w.t } : {}) };
    })));
    setBusy(false);
    setPicked(new Set());
    reload();
  };
  const dismiss = async () => {
    setBusy(true);
    for (const i of sel) await run(() => api.patchAction(m.id, i, { status: "dismissed" }));
    setBusy(false);
    setPicked(new Set());
    reload();
  };
  const saveDate = async (i: number) => {
    const w = dates[i];
    if (!w) return;
    await run(() => api.patchAction(m.id, i, { due_date: w.d, due_time: w.t }));
    reload();
  };

  return (
    <div>
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted">Action items</span>
        <button className="text-xs font-semibold text-muted underline" onClick={() =>
          setPicked(new Set(items.map((a, i) => (open(a) && a.mine ? i : -1)).filter((i) => i >= 0)))}>Select mine</button>
        <button className="text-xs font-semibold text-muted underline" onClick={() =>
          setPicked(new Set(items.map((a, i) => (open(a) ? i : -1)).filter((i) => i >= 0)))}>All open</button>
        {picked.size > 0 && <button className="text-xs font-semibold text-muted underline" onClick={() => setPicked(new Set())}>None</button>}
      </div>
      <ul className="space-y-1.5" aria-label="Action items">
        {order.map((i) => {
          const a = items[i];
          const w = when(i, a);
          const t = toSeconds(a.said_at);
          const decided = !open(a);
          return (
            <li key={i} className={cn("rounded-lg border bg-white/60 px-2.5 py-2", picked.has(i) && !decided ? "border-ink" : "border-line",
              decided && "opacity-70")}>
              <div className="flex items-start gap-2">
                <input type="checkbox" className="mt-1" aria-label={`Select: ${a.task}`} disabled={decided}
                  checked={picked.has(i) && !decided} onChange={() => toggle(i)} />
                <div className="min-w-0 flex-1">
                  <p className={cn("text-sm leading-snug", a.done && "line-through")}>
                    {a.done && <CircleCheck size={13} className="mr-1 inline text-sage" aria-label="done" />}{a.task}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted">
                    {a.mine ? <Badge tone="sage">yours</Badge> : a.owner ? <Badge>{a.owner}</Badge> : <Badge>no owner</Badge>}
                    {a.due && <span title="As said in the meeting">“{a.due}”</span>}
                    {t !== null && <button className="inline-flex items-center gap-0.5 hover:text-ink" onClick={() => onSeek(t)}
                      aria-label={`Play from ${a.said_at}`}><Play size={11} aria-hidden />{a.said_at}</button>}
                    {decided && <Badge tone="ink">{STATUS[a.status ?? ""] ?? (a.done ? "done" : a.status)}</Badge>}
                    {decided && a.status === "dismissed" && <button className="underline" onClick={async () => {
                      await run(() => api.patchAction(m.id, i, { status: "new" })); reload(); }}>undo</button>}
                  </div>
                </div>
                {!decided && (
                  <div className="flex shrink-0 flex-col items-end gap-1">
                    <Input type="date" aria-label={`Date for ${a.task}`} value={w.d} className="h-7 w-36 py-0 text-xs"
                      onChange={(e) => setDates((x) => ({ ...x, [i]: { ...w, d: e.target.value } }))} onBlur={() => void saveDate(i)} />
                    <Input type="time" aria-label={`Time for ${a.task}`} value={w.t} className="h-7 w-36 py-0 text-xs"
                      onChange={(e) => setDates((x) => ({ ...x, [i]: { ...w, t: e.target.value } }))} onBlur={() => void saveDate(i)} />
                    {a.due_date && a.due_exact === false && !a.due_user && <span className="text-[11px] text-muted">approximate</span>}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      <div className="mt-2 flex flex-wrap items-center gap-2" role="group" aria-label="Do with the selected items">
        <span className="text-xs text-muted">{sel.length ? `${sel.length} selected:` : "Tick items, then:"}</span>
        <Button size="sm" variant="primary" disabled={busy || !sel.length} onClick={() => void convert("task")}
          title="A task on its date (today if it has none)"><CalendarPlus size={14} aria-hidden /> Make tasks</Button>
        <Button size="sm" disabled={busy || !sel.length} onClick={() => void convert("reminder")}
          title="A ping on its date and time (09:00 if no time)"><Bell size={14} aria-hidden /> Reminders</Button>
        <Button size="sm" disabled={busy || !sel.length} onClick={() => void convert("park")}
          title="Into Parked tangents, no date"><CircleParking size={14} aria-hidden /> Park</Button>
        <Button size="sm" variant="ghost" disabled={busy || !sel.length} onClick={() => void dismiss()}>
          <X size={14} aria-hidden /> Not for me</Button>
      </div>
    </div>
  );
}
