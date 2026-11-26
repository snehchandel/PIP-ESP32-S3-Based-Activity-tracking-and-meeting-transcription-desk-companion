import { ChevronLeft, ChevronRight, Plus, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useLive } from "../api/live";
import type { CalItem, DayItems } from "../api/types";
import { TimeGrid } from "../components/TimeGrid";
import type { CalChange } from "../components/TimeGrid";
import { Button } from "../components/ui/button";
import { Badge, Card, Input, Label, PageHeader, Select } from "../components/ui/primitives";
import { cn, todayIso } from "../lib/utils";

type Mode = "month" | "week" | "day";
const KIND = ["Task", "Reminder", "Alarm", "From meeting"];

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

/* The editor sits at the top of the sticky side panel, right next to the grid (on narrow windows it floats over the
   bottom of the screen), so the block being edited stays in view: no scrolling away from the calendar. */
/* An action item from a meeting that has a date but no decision yet: move its date, or make it a task, a reminder
   or a parked tangent, or dismiss it - right here on the calendar. */
function MeetingItemEditor({ item, date, onDone }: { item: CalItem; date: string; onDone: () => void }) {
  const { run } = useLive();
  const nav = useNavigate();
  const [d, setD] = useState(date);
  const [t, setT] = useState(item.hhmm);
  const mid = item.meeting_id ?? "";
  const idx = item.index ?? 0;
  const make = async (as: "task" | "reminder" | "park") => {
    await run(() => api.convertActions(mid, [{ index: idx, as, date: d, ...(t ? { time: t } : {}) }]));
    onDone();
  };
  return (
    <section aria-label={`Decide ${item.title}`} className="rounded-2xl border border-dashed border-[#6d5fc7] bg-white p-4
      max-xl:fixed max-xl:inset-x-4 max-xl:bottom-4 max-xl:z-40 max-xl:mx-auto max-xl:max-w-lg max-xl:shadow-xl">
      <div className="mb-1 flex items-center gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">From a meeting</p>
        {item.mine ? <Badge tone="sage">yours</Badge> : item.owner ? <Badge>{item.owner}</Badge> : <Badge>no owner</Badge>}
        <Button size="icon" variant="ghost" className="ml-auto -mr-2 -mt-1 h-7 w-7" aria-label="Close" onClick={onDone}>
          <X size={15} aria-hidden /></Button>
      </div>
      <p className="mb-1 break-words font-semibold leading-snug">{item.title}</p>
      <p className="mb-3 text-xs text-muted">{item.meeting}{item.exact === false ? " · approximate date" : ""}</p>
      <div className="grid grid-cols-2 gap-2">
        <div><Label htmlFor="mi-date">Date</Label><Input id="mi-date" type="date" value={d} onChange={(e) => setD(e.target.value)} /></div>
        <div><Label htmlFor="mi-time">Time (optional)</Label><Input id="mi-time" type="time" value={t} onChange={(e) => setT(e.target.value)} /></div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant="primary" onClick={() => void make("task")}>Make task</Button>
        <Button size="sm" onClick={() => void make("reminder")}>Make reminder</Button>
        <Button size="sm" onClick={() => void make("park")}>Park</Button>
        {(d !== date || t !== item.hhmm) && <Button size="sm" variant="ghost" onClick={async () => {
          await run(() => api.patchAction(mid, idx, { due_date: d, due_time: t })); onDone(); }}>Just move it</Button>}
      </div>
      <div className="mt-2 flex gap-2 border-t border-line pt-2">
        <Button size="sm" variant="ghost" onClick={async () => { await run(() => api.patchAction(mid, idx, { status: "dismissed" })); onDone(); }}>
          Not for me</Button>
        <Button size="sm" variant="ghost" className="ml-auto" onClick={() => nav("/meetings")}>Open meetings</Button>
      </div>
    </section>
  );
}

function ItemEditor({ item, date, onDone }: { item: CalItem; date: string; onDone: () => void }) {
  const { run } = useLive();
  const nav = useNavigate();
  const [d, setD] = useState(date);
  const [t, setT] = useState(item.hhmm);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onDone(); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onDone]);
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
    <section aria-label={`Edit ${item.title}`} className="rounded-2xl border border-ink bg-white p-4 shadow-[0_1px_0_#0000000a]
      max-xl:fixed max-xl:inset-x-4 max-xl:bottom-4 max-xl:z-40 max-xl:mx-auto max-xl:max-w-lg max-xl:shadow-xl">
      <div className="mb-1 flex items-center gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted">Editing</p>
        <Badge>{KIND[item.kind]}</Badge>
        <Button size="icon" variant="ghost" className="ml-auto -mr-2 -mt-1 h-7 w-7" aria-label="Close editor" title="Close (Esc)"
          onClick={onDone}><X size={15} aria-hidden /></Button>
      </div>
      <p className="mb-1 break-words font-semibold leading-snug">{item.title}</p>
      <p className="tabular mb-3 text-xs text-muted">
        {new Date(`${date}T12:00:00`).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" })}
        {item.hhmm ? ` · ${item.hhmm}` : " · anytime"}{item.kind !== 2 ? ` · ${item.duration_min} min` : ""}</p>
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
    </section>
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
  const [others, setOthers] = useState(false);
  const [start, count] = rangeFor(mode, anchor);

  const load = useCallback(() => api.calendar(start, count, others).then(setDays).catch(() => undefined), [start, count, others]);
  useEffect(() => { void load(); }, [load, state?.revision]);

  const step = mode === "month" ? 30 : mode === "week" ? 7 : 1;
  const change = async ({ item, date, hhmm, minutes, resized }: CalChange) => {
    // optimistic: move the block right away, then save (Outlook-style drag)
    setDays((ds) => ds.map((d) => ({ ...d, items: d.date === date
      ? [...d.items.filter((i) => i.id !== item.id), { ...item, hhmm, duration_min: item.kind === 0 ? minutes : item.duration_min }]
      : d.items.filter((i) => i.id !== item.id) })));
    if (item.kind === 0) {
      await run(() => api.patchTask(item.id, { target_date: date, start_hhmm: hhmm, ...(resized ? { block_min: minutes } : {}) }));
    } else if (item.kind === 1) {
      await run(() => api.patchReminder(item.id, { due_local: `${date}T${hhmm}` }));
    } else if (item.kind === 3 && item.meeting_id) {
      await run(() => api.patchAction(item.meeting_id ?? "", item.index ?? 0, { due_date: date, due_time: hhmm }));
    }
    setSelected(date);
    void load();
  };
  const add = async () => {
    if (!title.trim()) return;
    await run(() => (kind === "task" ? api.createTask(title.trim(), selected, time || null)
      : api.addReminder(title.trim(), `${selected}T${time || "09:00"}`)));
    setTitle("");
    void load();
  };
  const closeEditor = useCallback(() => { setPicked(null); void load(); }, [load]);
  // follow the picked item through drags and reloads so the editor always shows where it is now
  const pickedDay = picked && days.find((d) => d.items.some((i) => i.id === picked.item.id));
  const editing = picked && (pickedDay
    ? { item: pickedDay.items.find((i) => i.id === picked.item.id) ?? picked.item, date: pickedDay.date } : picked);
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
          <label className="ml-2 flex items-center gap-1.5 text-xs text-muted" title="Action items from meetings that belong to other people">
            <input type="checkbox" aria-label="Show other people's action items from meetings" checked={others}
              onChange={(e) => setOthers(e.target.checked)} /> Others' meeting items</label>
        </div>} />
      {/* Outlook-style: the grid and a sticky side panel (editor, the selected day, add) sit side by side in every mode,
          so editing an event never means scrolling away from the calendar. */}
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px] xl:items-start">
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
                            ["border-l-ink bg-[#eef0f3]", "border-l-sage bg-sage-soft", "border-l-amber bg-amber-soft",
                              "border border-dashed border-[#8b7fd6] border-l-[#6d5fc7] bg-white"][i.kind],
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
              onSelect={(item, date) => { setPicked({ item, date }); setSelected(date); }} onChange={(c) => void change(c)}
              onSlot={(date, hhmm) => { setSelected(date); setTime(hhmm); setPicked(null);
                window.setTimeout(() => document.getElementById("cal-title")?.focus(), 20); }} />
          )}
        </Card>
        <aside aria-label="Day details" className="min-w-0 space-y-4 xl:sticky xl:top-20 xl:max-h-[calc(100vh-6rem)] xl:overflow-y-auto">
          {editing && (editing.item.kind === 3
            ? <MeetingItemEditor key={`${editing.item.id}|${editing.date}|${editing.item.hhmm}`} item={editing.item}
                date={editing.date} onDone={closeEditor} />
            : <ItemEditor key={`${editing.item.id}|${editing.date}|${editing.item.hhmm}`} item={editing.item}
                date={editing.date} onDone={closeEditor} />)}
          <Card aria-label="Selected day" className="p-4">
            <h2 className="mb-3 text-[15px] font-bold">{new Date(`${selected}T12:00:00`).toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" })}
              <span className="ml-2 text-xs font-normal text-muted">{sel?.items.length ?? 0} item{(sel?.items.length ?? 0) === 1 ? "" : "s"}</span></h2>
            <ul className={cn("-mx-1 mb-4 space-y-1.5 overflow-y-auto px-1", editing ? "max-h-[26vh]" : "max-h-[40vh]")}
              aria-label="Items on this day">
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
              <p className="text-xs text-muted">Tip: click any hour in Week or Day view to schedule there. Click a block to
                edit it here; drag it to move it; drag a task's top or bottom edge to change its length. Dashed blocks are
                action items from meetings you haven't decided on yet.</p>
            </form>
          </Card>
        </aside>
      </div>
    </>
  );
}
