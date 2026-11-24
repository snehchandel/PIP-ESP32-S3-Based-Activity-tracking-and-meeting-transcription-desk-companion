import { BellRing, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import { useLive } from "../api/live";
import type { Alarm } from "../api/types";
import { Button } from "../components/ui/button";
import { Badge, Card, CardTitle, Empty, Input, Label, PageHeader, Select } from "../components/ui/primitives";

const DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"];
interface Form { id?: string; title: string; local_hhmm: string; schedule_kind: "ONCE" | "RECURRING"; fire_date: string;
  days: string[]; audio_mode: "CHIME" | "TTS" | "WAV"; audio_path: string; tts_script: string; snooze_min: number;
  task_id: string; enabled: boolean }
const EMPTY: Form = { title: "", local_hhmm: "09:00", schedule_kind: "ONCE", fire_date: "", days: ["MO", "TU", "WE", "TH", "FR"],
  audio_mode: "CHIME", audio_path: "", tts_script: "", snooze_min: 5, task_id: "", enabled: true };

function fromAlarm(a: Alarm): Form {
  return { id: a.id, title: a.title, local_hhmm: a.local_hhmm, schedule_kind: a.schedule_kind, fire_date: "",
    days: (a.rrule_days ?? "").split(",").filter(Boolean), audio_mode: a.audio_mode, audio_path: a.audio_path ?? "",
    tts_script: a.tts_script ?? "", snooze_min: a.snooze_min, task_id: a.task_id ?? "", enabled: !!a.enabled };
}

export default function AlarmsView() {
  const { state, run, health } = useLive();
  const [f, setF] = useState<Form>(EMPTY);
  const [note, setNote] = useState<string | null>(null);
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((x) => ({ ...x, [k]: v }));
  const save = async () => {
    const body = { title: f.title, local_hhmm: f.local_hhmm, schedule_kind: f.schedule_kind,
      fire_date: f.schedule_kind === "ONCE" && f.fire_date ? f.fire_date : null,
      rrule_days: f.schedule_kind === "RECURRING" ? f.days.join(",") : null, audio_mode: f.audio_mode,
      audio_path: f.audio_path || null, tts_script: f.tts_script || null, snooze_min: f.snooze_min,
      task_id: f.task_id || null, enabled: f.enabled };
    const r = await run(() => (f.id ? api.patchAlarm(f.id, body) : api.createAlarm(body)));
    if (r) { setF(EMPTY); setNote("Saved."); }
  };
  const ttsFallback = f.audio_mode !== "CHIME" && !health?.tts_mode.startsWith("Piper");
  return (
    <>
      <PageHeader title="Alarms" subtitle={`Gentle alarms that also ring on PIP when it's offline · ${state?.timezone ?? ""}`} />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <Card aria-label="Alarm list">
          <CardTitle>Your alarms</CardTitle>
          {!state || state.alarms.length === 0 ? <Empty>No alarms yet.</Empty> : (
            <ul className="space-y-2">
              {state.alarms.map((a) => (
                <li key={a.id} className="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-white/60 px-3 py-2">
                  <span className="tabular text-xl font-black">{a.local_hhmm}</span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold">{a.title}</p>
                    <p className="text-xs text-muted">{a.schedule_kind === "ONCE" ? (a.fire_utc ? new Date(a.fire_utc).toLocaleDateString() : "once")
                      : (a.rrule_days ?? "").replaceAll(",", " ")} · {a.audio_mode.toLowerCase()}</p>
                  </div>
                  {!a.enabled && <Badge>off</Badge>}
                  {a.ack_state === "SNOOZED" && <Badge tone="amber">snoozed</Badge>}
                  <Button size="sm" onClick={async () => {
                    const r = await run(() => api.testAlarm(a.id));
                    if (r) setNote(r.sent_to_device ? "Ringing on PIP now." : "Ringing here — PIP is not connected.");
                  }}><BellRing size={14} aria-hidden /> Test on device</Button>
                  <Button size="sm" variant="ghost" aria-label={`Edit ${a.title}`} onClick={() => setF(fromAlarm(a))}><Pencil size={14} aria-hidden /></Button>
                  <Button size="sm" variant="ghost" aria-label={`Delete ${a.title}`} onClick={() => run(() => api.deleteAlarm(a.id))}><Trash2 size={14} aria-hidden /></Button>
                </li>))}
            </ul>
          )}
          {note && <p className="mt-3 text-sm text-muted" role="status">{note}</p>}
        </Card>
        <Card aria-label={f.id ? "Edit alarm" : "New alarm"}>
          <CardTitle>{f.id ? "Edit alarm" : "New alarm"}</CardTitle>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void save(); }}>
            <div><Label htmlFor="al-title">Title</Label><Input id="al-title" value={f.title} onChange={(e) => set("title", e.target.value)} required /></div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label htmlFor="al-time">Time</Label><Input id="al-time" type="time" value={f.local_hhmm} onChange={(e) => set("local_hhmm", e.target.value)} required /></div>
              <div><Label htmlFor="al-kind">Repeat</Label>
                <Select id="al-kind" value={f.schedule_kind} onChange={(e) => set("schedule_kind", e.target.value as Form["schedule_kind"])}>
                  <option value="ONCE">Once</option><option value="RECURRING">Weekly</option></Select></div>
            </div>
            {f.schedule_kind === "ONCE" ? (
              <div><Label htmlFor="al-date">Date (blank = next occurrence)</Label><Input id="al-date" type="date" value={f.fire_date} onChange={(e) => set("fire_date", e.target.value)} /></div>
            ) : (
              <fieldset><legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Days</legend>
                <div className="flex flex-wrap gap-1">{DAYS.map((d) => (
                  <Button key={d} size="sm" variant={f.days.includes(d) ? "primary" : "outline"} aria-pressed={f.days.includes(d)}
                    onClick={() => set("days", f.days.includes(d) ? f.days.filter((x) => x !== d) : [...f.days, d])}>{d}</Button>))}</div>
              </fieldset>
            )}
            <div className="grid grid-cols-2 gap-3">
              <div><Label htmlFor="al-audio">Sound</Label>
                <Select id="al-audio" value={f.audio_mode} onChange={(e) => set("audio_mode", e.target.value as Form["audio_mode"])}>
                  <option value="CHIME">Chime</option><option value="TTS">Piper voice (TTS)</option><option value="WAV">Local WAV</option></Select></div>
              <div><Label htmlFor="al-snooze">Snooze (min)</Label><Input id="al-snooze" type="number" min={1} max={60} value={f.snooze_min} onChange={(e) => set("snooze_min", Number(e.target.value))} /></div>
            </div>
            {f.audio_mode === "TTS" && <div><Label htmlFor="al-tts">Spoken message</Label><Input id="al-tts" value={f.tts_script} onChange={(e) => set("tts_script", e.target.value)} /></div>}
            {f.audio_mode === "WAV" && <div><Label htmlFor="al-wav">WAV file path</Label><Input id="al-wav" value={f.audio_path} onChange={(e) => set("audio_path", e.target.value)} /></div>}
            {ttsFallback && <Badge tone="amber">Offline fallback: PIP will play its built-in chime</Badge>}
            <div><Label htmlFor="al-task">Linked task</Label>
              <Select id="al-task" value={f.task_id} onChange={(e) => set("task_id", e.target.value)}>
                <option value="">None</option>{state?.tasks.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}</Select></div>
            <div className="flex items-center gap-2 text-sm">
              <input id="al-enabled" type="checkbox" className="h-4 w-4 accent-[#18181b]" checked={f.enabled}
                onChange={(e) => set("enabled", e.target.checked)} />
              <label htmlFor="al-enabled">Enabled</label>
            </div>
            <div className="flex gap-2">
              <Button type="submit" variant="primary" disabled={!f.title.trim() || (f.schedule_kind === "RECURRING" && f.days.length === 0)}>
                <Plus size={16} aria-hidden /> {f.id ? "Save changes" : "Add alarm"}</Button>
              {f.id && <Button onClick={() => setF(EMPTY)}>Cancel</Button>}
            </div>
          </form>
        </Card>
      </div>
    </>
  );
}
