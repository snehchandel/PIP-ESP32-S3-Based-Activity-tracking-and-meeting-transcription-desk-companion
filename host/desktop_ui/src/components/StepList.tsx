import { ArrowDown, ArrowUp, Check, CircleDot, Circle } from "lucide-react";
import { api } from "../api/client";
import { useLive } from "../api/live";
import type { Task } from "../api/types";
import { cn } from "../lib/utils";
import { Button } from "./ui/button";

/** Ordered micro-steps with keyboard-accessible reordering (Alt+Up / Alt+Down or the arrow buttons). */
export function StepList({ task, activeId }: { task: Task; activeId: string | null }) {
  const { run } = useLive();
  const move = (i: number, dir: -1 | 1) => {
    const ids = task.steps.map((s) => s.id);
    const j = i + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    void run(() => api.reorderSteps(task.id, ids));
  };
  return (
    <ol className="space-y-1.5" aria-label={`Steps for ${task.title}`}>
      {task.steps.map((s, i) => {
        const done = s.status === "COMPLETED";
        const active = s.id === activeId;
        return (
          <li key={s.id} tabIndex={0}
            onKeyDown={(e) => {
              if (e.altKey && e.key === "ArrowUp") { e.preventDefault(); move(i, -1); }
              if (e.altKey && e.key === "ArrowDown") { e.preventDefault(); move(i, 1); }
            }}
            className={cn("flex items-center gap-3 rounded-xl border px-3 py-2",
              active ? "border-ink bg-white" : "border-line bg-white/60", done && "opacity-55")}>
            {done ? <Check size={18} className="text-sage" aria-label="Completed" />
              : active ? <CircleDot size={18} className="text-amber" aria-label="Current step" />
              : <Circle size={18} className="text-muted" aria-label="Pending" />}
            <span className={cn("flex-1 text-sm", done && "line-through")}>{s.title}</span>
            <span className="tabular text-xs text-muted">{s.duration_min}m</span>
            {!done && !active && (
              <Button size="sm" variant="ghost" aria-label={`Complete ${s.title}`}
                onClick={() => run(() => api.completeStep(s.id))}><Check size={14} aria-hidden /></Button>
            )}
            <Button size="sm" variant="ghost" aria-label={`Move ${s.title} up`} disabled={i === 0}
              onClick={() => move(i, -1)}><ArrowUp size={14} aria-hidden /></Button>
            <Button size="sm" variant="ghost" aria-label={`Move ${s.title} down`} disabled={i === task.steps.length - 1}
              onClick={() => move(i, 1)}><ArrowDown size={14} aria-hidden /></Button>
          </li>
        );
      })}
    </ol>
  );
}
