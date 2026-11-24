import { Check, Coffee, Pause, Play, Scissors, SkipForward } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import { fmtMs, useLive } from "../api/live";
import { RescueDialog } from "./RescueDialog";
import { Button } from "./ui/button";
import { Badge, Card, Empty } from "./ui/primitives";

const STATE_COPY: Record<string, string> = {
  RUNNING: "Focusing", PAUSED: "Paused — no rush", IDLE_READY: "Ready when you are", STEP_DONE: "Step done!",
  BREAK: "On a break", LISTENING: "Listening…", TRANSCRIBING: "Transcribing…", THINKING: "Planning…",
  NEEDS_CONFIRMATION: "Waiting for a time check", ALARM_RINGING: "Alarm", SLEEP: "Resting",
};

export function FocusCard({ autoOpenSplit = false }: { autoOpenSplit?: boolean }) {
  const { state, run } = useLive();
  const [splitOpen, setSplitOpen] = useState(autoOpenSplit);
  const task = state?.active_task;
  const step = task?.steps.find((s) => s.id === state?.active_step_id);
  const t = state?.timer;

  if (!state || !task) {
    return (
      <Card aria-labelledby="focus-title">
        <h2 id="focus-title" className="mb-3 text-[15px] font-bold">Focus</h2>
        <Empty>No active task yet. Type a brain dump above (or hold KEY on PIP) and pick one thing.</Empty>
      </Card>
    );
  }
  const idx = task.steps.findIndex((s) => s.id === step?.id);
  const pct = t && t.total_ms ? Math.min(100, ((t.total_ms - t.remaining_ms) / t.total_ms) * 100) : 0;
  const running = t?.state === "RUNNING";
  const done = state.ui_state === "STEP_DONE";
  const onBreak = state.ui_state === "BREAK";

  return (
    <Card aria-labelledby="focus-title" className="relative overflow-hidden">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <h2 id="focus-title" className="text-[15px] font-bold">{task.title}</h2>
        {step && <Badge tone={step.is_starter ? "amber" : "neutral"}>
          Step {idx + 1}/{task.steps.length}{step.is_starter ? " · 2-min starter" : ""}</Badge>}
        <Badge tone={running ? "sage" : "neutral"} className="ml-auto">{STATE_COPY[state.ui_state] ?? state.ui_state}</Badge>
      </div>
      {onBreak ? (
        <p className="tabular my-4 text-center text-6xl font-black tracking-tight" aria-live="off">
          {fmtMs(state.break_remaining_ms)}</p>
      ) : (
        <p className="tabular my-4 text-center text-7xl font-black tracking-tight" aria-label="Time remaining"
          aria-live="off">{fmtMs(t?.remaining_ms ?? 0)}</p>
      )}
      <p className="min-h-12 text-center text-lg font-semibold leading-snug">
        {done ? `Done: ${state.done_title}` : onBreak ? "Stretch or grab some water." : step?.title ?? "All steps complete."}
      </p>
      {done && step && <p className="mt-1 text-center text-sm text-muted">Up next: {step.title} ({step.duration_min}m)</p>}
      <div className="my-4 h-2.5 overflow-hidden rounded-full bg-paper-2" role="progressbar" aria-label="Step progress"
        aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full rounded-full bg-ink transition-[width] duration-700" style={{ width: `${pct}%` }} />
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        {done ? (
          <>
            {step && <Button variant="primary" onClick={() => run(() => api.timer("next"))}>
              <SkipForward size={16} aria-hidden /> Start next step</Button>}
            <Button onClick={() => run(() => api.timer("break"))}><Coffee size={16} aria-hidden /> Take a 5-min break</Button>
          </>
        ) : onBreak ? (
          <Button variant="primary" onClick={() => run(() => api.timer("end-break"))}>I'm back</Button>
        ) : (
          <>
            <Button variant={running ? "outline" : "primary"} size="lg" disabled={!step}
              onClick={() => run(() => api.timer(running ? "pause" : "start"))} aria-keyshortcuts="Space">
              {running ? <><Pause size={18} aria-hidden /> Pause</> : <><Play size={18} aria-hidden /> {t?.started ? "Resume" : "Start"}</>}
            </Button>
            <Button size="lg" disabled={!step} onClick={() => step && run(() => api.completeStep(step.id))}>
              <Check size={18} aria-hidden /> Complete step</Button>
            <Button size="lg" variant="ghost" disabled={!step} onClick={() => setSplitOpen(true)} aria-keyshortcuts="S">
              <Scissors size={18} aria-hidden /> Cut in half</Button>
          </>
        )}
      </div>
      {task.if_then_cue && <p className="mt-4 text-center text-xs text-muted">Cue: {task.if_then_cue}</p>}
      {step && <RescueDialog open={splitOpen} onOpenChange={setSplitOpen} step={step}
        remainingMs={t?.remaining_ms ?? step.remaining_sec * 1000} />}
    </Card>
  );
}
