import { ArrowRight, Coffee, Pause, Play, SkipForward } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { fmtMs, useLive } from "../api/live";
import { cn } from "../lib/utils";
import { Button } from "./ui/button";
import { Card } from "./ui/primitives";

/* Today's slim "Now focusing" strip. The Focus page owns the full timer, the step controls and the step list;
   this only shows what is running and offers the one button you need right now (start/pause, next step, back
   from a break), so the two pages never show the same big timer twice. */
export function NowFocusing() {
  const { state, run } = useLive();
  const task = state?.active_task;
  const openFocus = (
    <Button asChild size="sm" variant="ghost">
      <Link to="/focus">Open Focus <ArrowRight size={15} aria-hidden /></Link>
    </Button>
  );

  if (!state || !task) {
    return (
      <Card aria-label="Now focusing" className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
        <p className="text-sm text-muted">Nothing in focus yet. Dump a thought above (or hold KEY on PIP) and pick one thing.</p>
        {openFocus}
      </Card>
    );
  }

  const t = state.timer;
  const step = task.steps.find((s) => s.id === state.active_step_id);
  const idx = task.steps.findIndex((s) => s.id === step?.id);
  const running = t.state === "RUNNING";
  const done = state.ui_state === "STEP_DONE";
  const onBreak = state.ui_state === "BREAK";
  const pct = t.total_ms ? Math.min(100, ((t.total_ms - t.remaining_ms) / t.total_ms) * 100) : 0;
  const label = onBreak ? "On a break" : done ? "Step done!" : running ? "Now focusing" : t.started ? "Paused" : "Up now";
  const line = done ? (step ? `Up next: ${step.title}` : `Done: ${state.done_title}`)
    : onBreak ? "Stretch or grab some water." : step?.title ?? "All steps complete.";
  const time = onBreak ? state.break_remaining_ms : t.remaining_ms;

  return (
    <Card aria-label="Now focusing" className="overflow-hidden px-5 py-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-semibold uppercase tracking-wide text-muted">
            <span className={cn(running && "text-sage", done && "text-amber-ink")}>{label}</span>
            {" · "}{task.title}{step && !onBreak ? ` · step ${idx + 1}/${task.steps.length}` : ""}</p>
          <p className="truncate text-[15px] font-semibold" title={line}>{line}</p>
        </div>
        {(step || onBreak) && !done && (
          <p className="tabular text-3xl font-black tracking-tight" aria-label="Time remaining" aria-live="off">{fmtMs(time)}</p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {done ? (
            <>
              {step && <Button size="sm" variant="primary" onClick={() => run(() => api.timer("next"))}>
                <SkipForward size={15} aria-hidden /> Start next step</Button>}
              <Button size="sm" onClick={() => run(() => api.timer("break"))}><Coffee size={15} aria-hidden /> Break</Button>
            </>
          ) : onBreak ? (
            <Button size="sm" variant="primary" onClick={() => run(() => api.timer("end-break"))}>I'm back</Button>
          ) : step ? (
            <Button size="sm" variant={running ? "outline" : "primary"} aria-keyshortcuts="Space"
              onClick={() => run(() => api.timer(running ? "pause" : "start"))}>
              {running ? <><Pause size={15} aria-hidden /> Pause</> : <><Play size={15} aria-hidden /> {t.started ? "Resume" : "Start"}</>}
            </Button>
          ) : null}
          {openFocus}
        </div>
      </div>
      {!done && !onBreak && step && (
        <div className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-paper-2" role="progressbar" aria-label="Step progress"
          aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
          <div className="h-full rounded-full bg-ink transition-[width] duration-700" style={{ width: `${pct}%` }} />
        </div>
      )}
    </Card>
  );
}
