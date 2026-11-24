import { CheckCheck, HelpCircle, Mic, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../api/client";
import { useLive } from "../api/live";
import type { Activity, Plan, PlanResult, VoiceSession } from "../api/types";

const ACTIVITIES: [Activity, string][] = [["CALENDAR", "Calendar"], ["BRAIN_DUMP", "Brain dump"], ["FOCUS", "Focus"], ["ALARMS", "Alarms"]];
import { Button } from "../components/ui/button";
import { Badge, Card, CardTitle, Empty, Input, PageHeader, Textarea } from "../components/ui/primitives";

// Live statuses from a voice capture on the device (typed dumps never show a badge here).
const DEVICE_VOICE = new Set(["LISTENING", "TRANSCRIBING", "STT_ERROR", "EMPTY"]);
const DEVICE_VOICE_COPY: Record<string, string> = {
  LISTENING: "PIP is listening…", TRANSCRIBING: "Transcribing…", STT_ERROR: "Couldn't transcribe — try typing",
  EMPTY: "Didn't catch that",
};

function PlanEditor({ plan, onChange }: { plan: Plan; onChange: (p: Plan) => void }) {
  const t = plan.active_task;
  return (
    <div className="space-y-4">
      {t && (
        <div>
          <label htmlFor="plan-title" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Active task</label>
          <Input id="plan-title" value={t.title} onChange={(e) => onChange({ ...plan, active_task: { ...t, title: e.target.value } })} />
          <ol className="mt-2 space-y-1.5">
            {t.steps.map((s, i) => (
              <li key={i} className="flex items-center gap-2">
                <span className="w-5 text-right text-xs text-muted">{i + 1}.</span>
                <Input aria-label={`Step ${i + 1} title`} value={s.title} onChange={(e) => {
                  const steps = t.steps.map((x, j) => (j === i ? { ...x, title: e.target.value } : x));
                  onChange({ ...plan, active_task: { ...t, steps } });
                }} />
                <Input aria-label={`Step ${i + 1} minutes`} type="number" min={s.is_starter ? 2 : 5} max={s.is_starter ? 5 : 25}
                  className="w-20" value={s.duration_min} onChange={(e) => {
                    const steps = t.steps.map((x, j) => (j === i ? { ...x, duration_min: Number(e.target.value) } : x));
                    onChange({ ...plan, active_task: { ...t, steps } });
                  }} />
                {s.is_starter && <Badge tone="amber">starter</Badge>}
              </li>
            ))}
          </ol>
        </div>
      )}
      {plan.scheduled.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Scheduled</p>
          <ul className="space-y-1.5">
            {plan.scheduled.map((s, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-white px-3 py-2 text-sm">
                <Badge>{s.kind.toLowerCase()}</Badge><span className="flex-1 font-medium">{s.title}</span>
                <span className="tabular text-xs text-muted">{s.due_local?.replace("T", " ") ?? s.when_text}</span>
                {s.needs_confirmation && <Badge tone="amber">needs a time check</Badge>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {plan.parked.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Parked tangents</p>
          <ul className="space-y-1.5">
            {plan.parked.map((p, i) => (
              <li key={i} className="flex items-center gap-2 rounded-xl border border-dashed border-line px-3 py-2 text-sm">
                <span className="flex-1">{p.title}</span>
                <Button size="sm" variant="ghost" aria-label={`Drop ${p.title}`}
                  onClick={() => onChange({ ...plan, parked: plan.parked.filter((_, j) => j !== i) })}>
                  <Trash2 size={14} aria-hidden /></Button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {plan.clarification_question && <p className="rounded-xl bg-amber-soft px-3 py-2 text-sm text-amber-ink">
        {plan.clarification_question}</p>}
    </div>
  );
}

export default function VoiceView() {
  const { run, state } = useLive();
  const loc = useLocation() as { state?: { text?: string } };
  const [text, setText] = useState(loc.state?.text ?? "");
  const [result, setResult] = useState<PlanResult | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [sessions, setSessions] = useState<VoiceSession[]>([]);
  const [committed, setCommitted] = useState(false);
  const [activity, setActivity] = useState<Activity>("BRAIN_DUMP");
  const voice = state?.voice;

  useEffect(() => { void api.voiceSessions().then(setSessions).catch(() => undefined); }, [voice?.status, committed]);

  const parse = async () => {
    const r = await run(() => api.plan(text, false, activity));
    if (r) { setResult(r); setPlan(r.plan); setCommitted(false); }
  };
  const accept = async () => {
    if (!plan || !result) return;
    const ok = await run(() => api.commit(plan, result.transcript, result.voice_session_id));
    if (ok !== undefined) setCommitted(true);
  };
  return (
    <>
      <PageHeader title="Brain Dump" subtitle="Type or hold KEY on PIP. Review the plan before anything is saved." />
      <div className="grid gap-5 lg:grid-cols-2">
        <Card aria-label="Brain dump input">
          <CardTitle aside={voice && DEVICE_VOICE.has(voice.status) ? <Badge tone="amber"><Mic size={12} aria-hidden />
            {DEVICE_VOICE_COPY[voice.status]}</Badge> : null}>
            What's on your mind?</CardTitle>
          <label htmlFor="dump-text" className="sr-only">Brain dump text</label>
          <Textarea id="dump-text" rows={6} value={text} onChange={(e) => setText(e.target.value)}
            placeholder="Everything in your head, in any order. PIP picks one lane and parks the rest." />
          <div className="mt-3 flex flex-wrap gap-2">
            <div role="radiogroup" aria-label="What is it about?" className="flex flex-wrap gap-1">
              {ACTIVITIES.map(([id, label]) => (
                <Button key={id} size="sm" role="radio" aria-checked={activity === id}
                  variant={activity === id ? "primary" : "outline"} onClick={() => setActivity(id)}>{label}</Button>))}
            </div>
            <Button variant="amber" disabled={!text.trim()} onClick={() => void parse()}><Sparkles size={16} aria-hidden /> Break it down</Button>
          </div>
          <div className="mt-6"><CardTitle id="recent-title">Recent sessions</CardTitle></div>
          {sessions.length === 0 ? <Empty>No sessions yet.</Empty> : (
            <ul className="space-y-1.5" aria-labelledby="recent-title">
              {sessions.slice(0, 6).map((s) => (
                <li key={s.id} className="rounded-xl border border-line bg-white/60 px-3 py-2 text-sm">
                  <div className="flex items-center gap-2"><Badge>{s.status.toLowerCase()}</Badge>
                    <span className="text-xs text-muted">{s.planner_mode}</span></div>
                  <p className="mt-1 line-clamp-2">{s.transcript}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card aria-label="Parsed plan">
          <CardTitle aside={result && <Badge>{result.planner_mode}</Badge>}>Parsed plan</CardTitle>
          {!plan || !result ? <Empty>Your plan will appear here for review.</Empty> : (
            <>
              <p className="mb-3 text-sm text-muted">Transcript: “{result.transcript}”</p>
              <PlanEditor plan={plan} onChange={setPlan} />
              <div className="mt-4 flex flex-wrap gap-2">
                <Button variant="primary" disabled={committed} onClick={() => void accept()}>
                  <CheckCheck size={16} aria-hidden /> {committed ? "Saved" : "Accept all"}</Button>
                <Button onClick={() => { setText(`${text}\n`); document.getElementById("dump-text")?.focus(); }}>Edit text</Button>
                <Button variant="ghost" onClick={() => setText(`${text} — I mean: `)}>
                  <HelpCircle size={16} aria-hidden /> Request clarification</Button>
              </div>
            </>
          )}
        </Card>
      </div>
    </>
  );
}
