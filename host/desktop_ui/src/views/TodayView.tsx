import { useLive } from "../api/live";
import { BrainDumpBar } from "../components/BrainDumpBar";
import { FocusCard } from "../components/FocusCard";
import { DayPanel, ParkedPanel } from "../components/SidePanels";
import { StepList } from "../components/StepList";
import { Card, CardTitle, PageHeader } from "../components/ui/primitives";

export default function TodayView() {
  const { state } = useLive();
  const greeting = new Date().getHours() < 12 ? "Good morning" : new Date().getHours() < 18 ? "Good afternoon" : "Good evening";
  return (
    <>
      <PageHeader title={greeting} subtitle={new Date().toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" })
        + " · one thing at a time"} />
      <div className="mb-5"><BrainDumpBar /></div>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <div className="space-y-5">
          <FocusCard />
          {state?.active_task && (
            <Card aria-label="Micro-steps">
              <CardTitle aside={<span className="text-xs text-muted">Alt+↑/↓ to reorder</span>}>Micro-steps</CardTitle>
              <StepList task={state.active_task} activeId={state.active_step_id} />
            </Card>
          )}
        </div>
        <div className="space-y-5">
          <DayPanel title="Today" offset={0} />
          <DayPanel title="Tomorrow" offset={1} />
          <ParkedPanel />
        </div>
      </div>
    </>
  );
}
