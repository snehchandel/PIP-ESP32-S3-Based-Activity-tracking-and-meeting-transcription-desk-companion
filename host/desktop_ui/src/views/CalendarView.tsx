import { ChevronLeft, ChevronRight, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { useLive } from "../api/live";
import type { DayItems } from "../api/types";
import { Button } from "../components/ui/button";
import { Badge, Card, Input, PageHeader, Select } from "../components/ui/primitives";
import { cn, todayIso } from "../lib/utils";

type Mode = "month" | "week" | "day";
const KIND = ["task", "reminder", "alarm"];

function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function rangeFor(mode: Mode, anchor: string): [string, number] {
  const d = new Date(`${anchor}T12:00:00`);
  if (mode === "day") return [anchor, 1];
  if (mode === "week") return [addDays(anchor, -((d.getDay() + 6) % 7)), 7];
  const first = `${anchor.slice(0, 8)}01`;
  const lead = (new Date(`${first}T12:00:00`).getDay() + 6) % 7;
  return [addDays(first, -lead), 42];
}

export default function CalendarView() {
  const { state, run } = useLive();
  const [mode, setMode] = useState<Mode>("week");
  const [anchor, setAnchor] = useState(todayIso());
  const [days, setDays] = useState<DayItems[]>([]);
  const [selected, setSelected] = useState(todayIso());
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<"task" | "reminder">("task");
  const [time, setTime] = useState("09:00");
  const [start, count] = rangeFor(mode, anchor);

  const load = useCallback(() => api.calendar(start, count).then(setDays).catch(() => undefined), [start, count]);
  useEffect(() => { void load(); }, [load, state?.revision]);

  const step = mode === "month" ? 30 : mode === "week" ? 7 : 1;
  const sel = days.find((d) => d.date === selected);
  const add = async () => {
    if (!title.trim()) return;
    await run(() => (kind === "task" ? api.createTask(title.trim(), selected) : api.addReminder(title.trim(), `${selected}T${time}`)));
    setTitle("");
    void load();
  };
  const offset = new Date().getTimezoneOffset();
  return (
    <>
      <PageHeader title="Calendar" subtitle={`Times shown in ${state?.timezone ?? "local time"} (UTC${offset <= 0 ? "+" : "-"}${Math.abs(offset / 60)}) · DST handled automatically`}
        actions={<div className="flex items-center gap-1" role="group" aria-label="Calendar range">
          {(["month", "week", "day"] as Mode[]).map((m) => (
            <Button key={m} size="sm" variant={mode === m ? "primary" : "outline"} aria-pressed={mode === m} onClick={() => setMode(m)}>
              {m[0].toUpperCase() + m.slice(1)}</Button>))}
          <Button size="icon" aria-label="Previous" onClick={() => setAnchor(addDays(anchor, -step))}><ChevronLeft size={16} /></Button>
          <Button size="sm" onClick={() => { setAnchor(todayIso()); setSelected(todayIso()); }}>Today</Button>
          <Button size="icon" aria-label="Next" onClick={() => setAnchor(addDays(anchor, step))}><ChevronRight size={16} /></Button>
        </div>} />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Card aria-label="Calendar grid" className="p-3">
          <div className={cn("grid gap-1.5", mode === "day" ? "grid-cols-1" : "grid-cols-7")}>
            {days.map((d) => {
              const dt = new Date(`${d.date}T12:00:00`);
              const out = mode === "month" && d.date.slice(0, 7) !== anchor.slice(0, 7);
              return (
                <button key={d.date} onClick={() => setSelected(d.date)} aria-pressed={selected === d.date}
                  aria-label={`${dt.toDateString()}, ${d.items.length} items`}
                  className={cn("min-h-20 rounded-xl border p-1.5 text-left align-top", mode === "month" ? "min-h-20" : "min-h-40",
                    selected === d.date ? "border-ink bg-white" : "border-line bg-white/50 hover:bg-white", out && "opacity-45")}>
                  <span className={cn("text-xs font-bold", d.date === todayIso() && "rounded-full bg-amber px-1.5 text-white")}>
                    {mode === "month" ? dt.getDate() : dt.toLocaleDateString([], { weekday: "short", day: "numeric" })}</span>
                  <span className="mt-1 block space-y-0.5">
                    {d.items.slice(0, mode === "month" ? 2 : 6).map((i) => (
                      <span key={i.id} className={cn("block truncate rounded px-1 text-[11px]", i.done ? "text-muted line-through" : "bg-paper-2")}>
                        {i.hhmm && <span className="tabular">{i.hhmm} </span>}{i.title}</span>))}
                    {d.items.length > (mode === "month" ? 2 : 6) && <span className="block text-[11px] text-muted">+{d.items.length - (mode === "month" ? 2 : 6)} more</span>}
                  </span>
                </button>
              );
            })}
          </div>
        </Card>
        <Card aria-label="Selected day">
          <h2 className="mb-3 text-[15px] font-bold">{new Date(`${selected}T12:00:00`).toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" })}</h2>
          <ul className="mb-4 space-y-1.5">
            {(sel?.items ?? []).map((i) => (
              <li key={i.id} className="flex items-center gap-2 rounded-xl border border-line bg-white/60 px-3 py-2 text-sm">
                <Badge>{KIND[i.kind]}</Badge><span className="flex-1">{i.title}</span>
                {i.hhmm && <span className="tabular text-xs text-muted">{i.hhmm}</span>}
                {i.kind === 0 && (
                  <Input type="date" aria-label={`Reschedule ${i.title}`} className="h-8 w-36" value={selected}
                    onChange={(e) => void run(() => api.patchTask(i.id, { target_date: e.target.value }))} />)}
                <Button size="sm" variant="ghost" aria-label={`Delete ${i.title}`} onClick={() => void run(() =>
                  i.kind === 0 ? api.deleteTask(i.id) : i.kind === 1 ? api.deleteReminder(i.id) : api.deleteAlarm(i.id))}>
                  <Trash2 size={14} aria-hidden /></Button>
              </li>))}
            {(sel?.items.length ?? 0) === 0 && <li className="text-sm text-muted">Free day.</li>}
          </ul>
          <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); void add(); }} aria-label="Add to this day">
            <div className="flex gap-2">
              <Select aria-label="Item type" value={kind} onChange={(e) => setKind(e.target.value as "task" | "reminder")} className="w-32">
                <option value="task">Task</option><option value="reminder">Reminder</option></Select>
              {kind === "reminder" && <Input aria-label="Time" type="time" value={time} onChange={(e) => setTime(e.target.value)} className="w-32" />}
            </div>
            <div className="flex gap-2">
              <Input aria-label="Title" placeholder="What?" value={title} onChange={(e) => setTitle(e.target.value)} />
              <Button type="submit" variant="primary" disabled={!title.trim()}><Plus size={16} aria-hidden /> Add</Button>
            </div>
          </form>
        </Card>
      </div>
    </>
  );
}
