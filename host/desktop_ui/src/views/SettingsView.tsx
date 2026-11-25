import { Download, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useLive } from "../api/live";
import type { Settings } from "../api/types";
import { AiUsageCard } from "../components/AiUsageCard";
import { WakeWordCard } from "../components/DeviceCards";
import { ApiKeyCard, MeetingAiCard, SpeechCard, VocabularyCard } from "../components/SettingsCards";
import { WeatherCard } from "../components/WeatherCard";
import { Button } from "../components/ui/button";
import { Card, CardTitle, PageHeader } from "../components/ui/primitives";

export default function SettingsView() {
  const { health, run, refresh } = useLive();
  const [s, setS] = useState<Settings | null>(null);
  const [diag, setDiag] = useState<Record<string, unknown> | null>(null);
  useEffect(() => {
    void api.settings().then(setS).catch(() => undefined);
    void api.diagnostics().then((d) => setDiag(d.diag)).catch(() => undefined);
  }, [health?.link_state]);
  const update = (next: Settings) => { setS(next); void refresh(); };
  const exportJson = async () => {
    const data = await run(() => api.exportDiagnostics());
    if (!data) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `pip-diagnostics-${new Date().toISOString().slice(0, 19).replaceAll(":", "")}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <>
      <PageHeader title="Settings & Diagnostics" />
      {!s ? <p className="text-sm text-muted">Loading…</p> : (
        <div className="grid gap-5 lg:grid-cols-2">
          <ApiKeyCard s={s} onChange={update} />
          <AiUsageCard />
          <SpeechCard s={s} onChange={update} />
          <VocabularyCard />
          <MeetingAiCard />
          <WakeWordCard />
          <WeatherCard />
          <Card aria-label="System">
            <CardTitle>System</CardTitle>
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
              <dt className="text-muted">Timezone</dt><dd>{s.timezone}</dd>
              <dt className="text-muted">Device</dt><dd>{health?.device_transport === "USB_HARDWARE" ? "PIP over USB"
                : health?.device_transport === "SIMULATOR" ? "Simulator" : "Not connected (plug PIP in — it links automatically)"}</dd>
              <dt className="text-muted">App address</dt><dd className="tabular">http://127.0.0.1:{s.host_port}</dd>
            </dl>
            <div className="mt-4 flex items-start gap-2 rounded-xl border border-line bg-paper-2 p-3 text-sm">
              <ShieldCheck size={18} className="mt-0.5 shrink-0 text-sage" aria-hidden />
              <p><span className="font-semibold">Privacy: </span>{s.privacy} Transcripts are never written to logs.</p>
            </div>
            {s.missed_alarms.length > 0 && <p className="mt-3 text-sm text-muted">
              {s.missed_alarms.length} alarm(s) passed while the app was closed — they were not rung late.</p>}
          </Card>
          <Card aria-label="Device diagnostics">
            <CardTitle aside={<Button size="sm" onClick={() => void exportJson()}><Download size={14} aria-hidden /> Export JSON</Button>}>
              Device report</CardTitle>
            <pre className="max-h-80 overflow-auto rounded-xl bg-ink p-3 text-xs leading-relaxed text-paper">
              {diag ? JSON.stringify(diag, null, 2) : "No device report yet — PIP is not connected."}</pre>
          </Card>
        </div>
      )}
    </>
  );
}
