import { Scissors } from "lucide-react";
import { api } from "../api/client";
import { fmtMs, useLive } from "../api/live";
import type { Step } from "../api/types";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";

/** Same rule as firmware + host: current = max(120, rem/2), next = max(120, rem - current). */
export function splitPreview(remainingSec: number): [number, number] {
  const cur = Math.max(120, Math.floor(remainingSec / 2));
  return [cur, Math.max(120, remainingSec - cur)];
}

export function RescueDialog({ open, onOpenChange, step, remainingMs }: {
  open: boolean; onOpenChange: (o: boolean) => void; step: Step; remainingMs: number;
}) {
  const { run } = useLive();
  const rem = Math.ceil(remainingMs / 1000);
  const [cur, nxt] = splitPreview(rem);
  const base = step.title.replace(/ \(first half\)$/, "");
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Cut this step in half"
      description="Too big right now? Shrink it. Nothing is deleted — the rest moves to the next step.">
      <div className="space-y-2">
        <div className="rounded-2xl border border-line bg-white p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Now</p>
          <p className="font-semibold">{base} (first half)</p>
          <p className="tabular text-sm text-ink-2">{fmtMs(cur * 1000)}</p>
        </div>
        <div className="rounded-2xl border border-dashed border-line bg-paper-2 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Inserted next</p>
          <p className="font-semibold">{base} (second half)</p>
          <p className="tabular text-sm text-ink-2">{fmtMs(nxt * 1000)}</p>
        </div>
        <p className="text-sm text-muted" data-testid="split-total">
          Total kept: <span className="tabular font-semibold text-ink">{fmtMs((cur + nxt) * 1000)}</span>
          {" "}(was {fmtMs(rem * 1000)}) — zero lost work.</p>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <Button onClick={() => onOpenChange(false)}>Keep as is</Button>
        <Button variant="primary" onClick={async () => {
          await run(() => api.splitStep(step.id));
          onOpenChange(false);
        }}><Scissors size={16} aria-hidden /> Cut in half</Button>
      </div>
    </Dialog>
  );
}
