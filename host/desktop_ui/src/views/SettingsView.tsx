import { Download, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useLive } from "../api/live";
import type { Settings } from "../api/types";
import { Button } from "../components/ui/button";
import { Badge, Card, CardTitle, PageHeader } from "../components/ui/primitives";

export default function SettingsView() {
  const { health, run } = useLive();
  const [s, setS] = useState<Settings | null>(null);
  const [diag, setDiag] = useState<Record<string, unknown> | null>(null);
  useEffect(() => {
    void api.settings().then(setS).catch(() => undefined);
    void api.diagnostics().then((d) => setDiag(d.diag)).catch(() => undefined);
  }, [health?.link_state]);
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
      <div className="grid gap-5 lg:grid-cols-2">
        <Card aria-label="Planner and speech">
          <CardTitle>Planner & speech</CardTitle>
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <dt className="text-muted">Planner</dt>
            <dd><Badge tone={s?.planner_mode === "KIMI" ? "amber" : "sage"}>
              {s?.planner_mode === "KIMI" ? `Kimi API (${s.kimi_model})` : "Local Rule Engine"}</Badge></dd>
            <dt className="text-muted">Speech-to-text</dt><dd>{s?.stt ?? "—"}</dd>
            <dt className="text-muted">Voice / TTS</dt><dd>{s?.tts ?? "—"}</dd>
            <dt className="text-muted">Timezone</dt><dd>{s?.timezone ?? "—"}</dd>
            <dt className="text-muted">Device transport</dt><dd>{s?.transport_setting ?? "—"} → {health?.device_transport ?? "—"}</dd>
            <dt className="text-muted">Service port</dt><dd className="tabular">127.0.0.1:{s?.host_port ?? "—"}</dd>
          </dl>
          <div className="mt-4 flex items-start gap-2 rounded-xl border border-line bg-paper-2 p-3 text-sm">
            <ShieldCheck size={18} className="mt-0.5 shrink-0 text-sage" aria-hidden />
            <p><span className="font-semibold">Privacy: </span>{s?.privacy ?? "…"} Transcripts are never written to logs.
              To use Kimi, set <code>MOONSHOT_API_KEY</code> in <code>.env</code> or Windows Credential Manager.</p>
          </div>
          {s && s.missed_alarms.length > 0 && <p className="mt-3 text-sm text-muted">
            {s.missed_alarms.length} alarm(s) passed while the app was closed — they were not rung late.</p>}
        </Card>
        <Card aria-label="Device diagnostics">
          <CardTitle aside={<Button size="sm" onClick={() => void exportJson()}><Download size={14} aria-hidden /> Export JSON</Button>}>
            Device report</CardTitle>
          <pre className="max-h-96 overflow-auto rounded-xl bg-ink p-3 text-xs leading-relaxed text-paper">
            {diag ? JSON.stringify(diag, null, 2) : "No DIAG_REPORT yet — PIP is not connected."}</pre>
        </Card>
      </div>
    </>
  );
}
