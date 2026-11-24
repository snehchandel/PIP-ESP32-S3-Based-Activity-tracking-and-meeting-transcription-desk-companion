import { ChevronLeft, ChevronRight, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useLive } from "../api/live";
import type { CalItem, DayItems } from "../api/types";
import { TimeGrid } from "../components/TimeGrid";
import { Button } from "../components/ui/button";
import { Badge, Card, Input, Label, PageHeader, Select } from "../components/ui/primitives";
import { cn, todayIso } from "../lib/utils";

type Mode = "month" | "week" | "day";
const KIND = ["Task", "Reminder", "Alarm"];

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

function ItemEditor({ item, date, onDone }: { item: CalItem; date: string; onDone: () => void }) {
  const { run } = useLive();
  const nav = useNavigate();
  const [d, setD] = useState(date);
  const [t, setT] = useState(item.hhmm);
  const save = async () => {
    if (item.kind === 0) await run(() => api.patchTask(item.id, { target_date: d, start_hhmm: t }));
    else if (item.kind === 1) await run(() => api.patchReminder(item.id, { due_local: `${d}T${t || "09:00"}` }));
    onDone();
  };
  const remove = async () => {
    await run(() => (item.kind === 0 ? api.deleteTask(item.id) : api.deleteReminder(item.id)));
    onDone();
  };
  return (
    <div className="rounded-2xl border border-ink bg-white p-3" aria-label={`Edit ${item.title}`}>
      <div className="mb-2 flex items-center gap-2"><Badge>{KIND[item.kind]}</Badge>
        <p className="flex-1 truncate font-semibold">{item.title}</p>
        {item.kind !== 2 && <span className="tabular text-xs text-muted">{item.duration_min} min</span>}</div>
      {item.kind === 2 ? (
        <div className="flex items-center justify-between gap-2 text-sm text-muted">
          <span>{item.recurring ? "Weekly alarm" : "Alarm"} at <span className="tabular">{item.hhmm}</span></span>
          <Button size="sm" onClick={() => nav("/alarms")}>Edit in Alarms</Button></div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            <div><Label htmlFor="ed-date">Date</Label><Input id="ed-date" type="date" value={d} onChange={(e) => setD(e.target.value)} /></div>
            <div><Label htmlFor="ed-time">{item.kind === 0 ? "Time (blank = anytime)" : "Time"}</Label>
              <Input id="ed-time" type="time" value={t} onChange={(e) => setT(e.target.value)} /></div>
          </div>
          <div className="mt-3 flex gap-2">
            <Button size="sm" variant="primary" onClick={() => void save()}>Save</Button>
            {item.kind === 0 && t && <Button size="sm" onClick={() => setT("")}>Make anytime</Button>}
            <Button size="sm" variant="danger" className="ml-auto" aria-label={`Delete ${item.title}`} onClick={() => void remove()}>
              <Trash2 size={14} aria-hidden /> Delete</Button>
          </div>
        </>
      )}
    </div>
  );
}

export default function CalendarView() {
  const { state, run } = useLive();
  const [mode, setMode] = useState<Mode>("week");
  const [anchor, setAnchor] = useState(todayIso());
  const [days, setDays] = useState<DayItems[]>([]);
  const [selected, setSelected] = useState(todayIso());
  const [picked, setPicked] = useState<{ item: CalItem; date: string } | null>(null);
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<"task" | "reminder">("task");
  const [time, setTime] = useState("");
  const [start, count] = rangeFor(mode, anchor);

  const load = useCallback(() => api.calendar(start, count).then(setDays).catch(() => undefined), [start, count]);
  useEffect(() => { void load(); }, [load, state?.revision]);

  const step = mode === "month" ? 30 : mode === "week" ? 7 : 1;
  const add = async () => {
    if (!title.trim()) return;
    await run(() => (kind === "task" ? api.createTask(title.trim(), selected, time || null)
      : api.addReminder(title.trim(), `${selected}T${time || "09:00"}`)));
    setTitle("");
    void load();
  };
  const sel = days.find((d) => d.date === selected);
  const offset = -new Date().getTimezoneOffset() / 60;
  return (
    <>
      <PageHeader title="Calendar"
        subtitle={`${state?.timezone ?? "Local time"} (UTC${offset >= 0 ? "+" : ""}${offset}) · daylight saving handled automatically`}
        actions={<div className="flex items-center gap-1" role="group" aria-label="Calendar range">
          {(["month", "week", "day"] as Mode[]).map((m) => (
            <Button key={m} size="sm" variant={mode === m ? "primary" : "outline"} aria-pressed={mode === m} onClick={() => setMode(m)}>
              {m[0].toUpperCase() + m.slice(1)}</Button>))}
          <Button size="icon" aria-label="Previous" onClick={() => setAnchor(addDays(anchor, -step))}><ChevronLeft size={16} /></Button>
          <Button size="sm" onClick={() => { setAnchor(todayIso()); setSelected(todayIso()); }}>Today</Button>
          <Button size="icon" aria-label="Next" onClick={() => setAnchor(addDays(anchor, step))}><ChevronRight size={16} /></Button>
        </div>} />
      {/* week view gets the full width (like Outlook); the day panel then sits underneath */}
      <div className={cn("grid gap-5", mode !== "week" && "xl:grid-cols-[minmax(0,1fr)_340px]")}>
        <Card aria-label="Calendar grid" className="min-w-0 p-3">
          {mode === "month" ? (
            <div className="grid grid-cols-7 gap-1.5">
              {days.map((d) => {
                const dt = new Date(`${d.date}T12:00:00`);
                const out = d.date.slice(0, 7) !== anchor.slice(0, 7);
                return (
                  <button key={d.date} onClick={() => setSelected(d.date)} onDoubleClick={() => { setAnchor(d.date); setMode("day"); }}
                    aria-pressed={selected === d.date} aria-label={`${dt.toDateString()}, ${d.items.length} items`}
                    className={cn("min-h-24 rounded-xl border p-1.5 text-left", selected === d.date ? "border-ink bg-white"
                      : "border-line bg-white/50 hover:bg-white", out && "opacity-45")}>
                    <span className={cn("text-xs font-bold", d.date === todayIso() && "rounded-full bg-amber px-1.5 text-white")}>{dt.getDate()}</span>
                    <span className="mt-1 block space-y-0.5">
                      {d.items.slice(0, 4).map((i) => (
                        <span key={i.id} title={i.title}
                          className={cn("block truncate rounded-[4px] border-l-[3px] px-1 py-px text-xs",
                            ["border-l-ink bg-[#eef0f3]", "border-l-sage bg-sage-soft", "border-l-amber bg-amber-soft"][i.kind],
                            i.done && "text-muted line-through opacity-60")}>
                          {i.hhmm ? <span className="tabular font-semibold">{i.hhmm} </span> : null}{i.title}</span>))}
                      {d.items.length > 4 && <span className="block text-xs font-semibold text-muted">+{d.items.length - 4} more</span>}
                    </span>
                  </button>
                );
              })}
            </div>
          ) : (
            <TimeGrid days={days} selectedId={picked?.item.id ?? null}
              onSelect={(item, date) => { setPicked({ item, date }); setSelected(date); }}
              onSlot={(date, hhmm) => { setSelected(date); setTime(hhmm); setPicked(null);
                window.setTimeout(() => document.getElementById("cal-title")?.focus(), 20); }} />
          )}
        </Card>
        <Card aria-label="Selected day">
          <h2 className="mb-3 text-[15px] font-bold">{new Date(`${selected}T12:00:00`).toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" })}</h2>
          {picked && <div className="mb-4"><ItemEditor key={picked.item.id} item={picked.item} date={picked.date}
            onDone={() => { setPicked(null); void load(); }} /></div>}
          <ul className="mb-4 space-y-1.5">
            {(sel?.items ?? []).map((i) => (
              <li key={i.id}>
                <button onClick={() => setPicked({ item: i, date: selected })}
                  className={cn("flex w-full items-center gap-2 rounded-xl border border-line bg-white/60 px-3 py-2 text-left text-sm hover:bg-white",
                    picked?.item.id === i.id && "border-ink")}>
                  <span className="tabular w-11 shrink-0 text-xs font-semibold text-muted">{i.hhmm || "any"}</span>
                  <span className={cn("flex-1 truncate", i.done && "text-muted line-through")}>{i.title}</span>
                  <Badge>{KIND[i.kind].toLowerCase()}</Badge>
                </button>
              </li>))}
            {(sel?.items.length ?? 0) === 0 && <li className="text-sm text-muted">Free day.</li>}
          </ul>
          <form className="space-y-2 border-t border-line pt-3" onSubmit={(e) => { e.preventDefault(); void add(); }} aria-label="Add to this day">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">Add on this day</p>
            <div className="flex gap-2">
              <Select aria-label="Item type" value={kind} onChange={(e) => setKind(e.target.value as "task" | "reminder")} className="w-32">
                <option value="task">Task</option><option value="reminder">Reminder</option></Select>
              <Input aria-label="Time" type="time" value={time} onChange={(e) => setTime(e.target.value)} className="w-32" />
            </div>
            <div className="flex gap-2">
              <Input id="cal-title" aria-label="Title" placeholder={time ? `What at ${time}?` : "What? (no time = anytime)"} value={title}
                onChange={(e) => setTitle(e.target.value)} />
              <Button type="submit" variant="primary" disabled={!title.trim()}><Plus size={16} aria-hidden /> Add</Button>
            </div>
            <p className="text-xs text-muted">Tip: click any hour in Week or Day view to schedule there.</p>
          </form>
        </Card>
      </div>
    </>
  );
}
