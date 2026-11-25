import { BrainDumpBar } from "../components/BrainDumpBar";
import { NowFocusing } from "../components/NowFocusing";
import { DayPanel, ParkedPanel } from "../components/SidePanels";
import { PageHeader } from "../components/ui/primitives";

/* Today = the overview: what is running (a slim strip; the full timer and steps live on Focus), today, tomorrow
   and the parked tangents. */
export default function TodayView() {
  const greeting = new Date().getHours() < 12 ? "Good morning" : new Date().getHours() < 18 ? "Good afternoon" : "Good evening";
  return (
    <>
      <PageHeader title={greeting} subtitle={new Date().toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" })
        + " · one thing at a time"} />
      <div className="mb-5"><BrainDumpBar /></div>
      <div className="mb-5"><NowFocusing /></div>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <DayPanel title="Today" offset={0} />
        <div className="space-y-5">
          <DayPanel title="Tomorrow" offset={1} />
          <ParkedPanel />
        </div>
      </div>
    </>
  );
}
