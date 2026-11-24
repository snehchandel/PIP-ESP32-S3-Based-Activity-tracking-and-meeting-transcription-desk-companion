import { useSearchParams } from "react-router-dom";
import { useLive } from "../api/live";
import { FocusCard } from "../components/FocusCard";
import { StepList } from "../components/StepList";
import { Card, CardTitle, Empty, PageHeader } from "../components/ui/primitives";
import { splitPreview } from "../components/RescueDialog";
import { fmtMs } from "../api/live";

/** Step Rescue Editor panel: the active step, a live split preview, and the full step list. */
export default function FocusView() {
  const { state } = useLive();
  const [params] = useSearchParams();
  const step = state?.active_task?.steps.find((s) => s.id === state.active_step_id);
  const rem = Math.ceil((state?.timer.remaining_ms ?? 0) / 1000);
  const [cur, nxt] = splitPreview(rem);
  return (
    <>
      <PageHeader title="Focus" subtitle="Feeling stuck? Cut the step in half — the work moves, it never disappears." />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <FocusCard autoOpenSplit={params.get("split") === "1"} />
        <Card aria-label="Rescue preview">
          <CardTitle>Rescue preview</CardTitle>
          {step ? (
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <dt className="text-muted">Remaining now</dt><dd className="tabular font-semibold">{fmtMs(rem * 1000)}</dd>
              <dt className="text-muted">First half</dt><dd className="tabular font-semibold">{fmtMs(cur * 1000)}</dd>
              <dt className="text-muted">Second half</dt><dd className="tabular font-semibold">{fmtMs(nxt * 1000)}</dd>
              <dt className="text-muted">Total preserved</dt><dd className="tabular font-semibold">{fmtMs((cur + nxt) * 1000)}</dd>
            </dl>
          ) : <Empty>No active step to rescue.</Empty>}
          <p className="mt-4 text-xs text-muted">On PIP: hold BOOT for 1.2 s to cut the current step in half.</p>
        </Card>
      </div>
      {state?.active_task && (
        <Card className="mt-5" aria-label="All steps">
          <CardTitle>All steps</CardTitle>
          <StepList task={state.active_task} activeId={state.active_step_id} />
        </Card>
      )}
    </>
  );
}
