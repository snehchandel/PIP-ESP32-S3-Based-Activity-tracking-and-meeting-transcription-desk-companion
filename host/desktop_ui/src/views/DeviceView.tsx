import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useLive } from "../api/live";
import { RlcdMirror } from "../components/RlcdMirror";
import { Button } from "../components/ui/button";
import { Badge, Card, CardTitle, PageHeader } from "../components/ui/primitives";

const FIELDS: [string, string][] = [
  ["fw_ver", "Firmware"], ["reset_reason", "Reset reason"], ["batt_pct", "Battery %"], ["batt_mv", "Battery mV"],
  ["free_heap_b", "Free heap (B)"], ["free_psram_b", "Free PSRAM (B)"], ["crc_errors", "CRC errors"],
  ["rtc_ok", "RTC"], ["display_ok", "Display"], ["audio_ok", "Audio"], ["i2c_addrs", "I²C devices"],
  ["offline_queue", "Offline queue"], ["state_rev", "Device revision"],
];

const HW_ONLY = new Set(["free_heap_b", "free_psram_b", "batt_mv", "batt_pct"]);

function fmt(v: unknown, key: string, isSim: boolean): string {
  if (isSim && HW_ONLY.has(key)) return "n/a (simulator)";
  if (v === undefined || v === null) return "—";
  if (typeof v === "boolean") return v ? "OK" : "not found";
  if (v === -1) return "n/a";
  return String(v);
}

export default function DeviceView() {
  const { health, state, run } = useLive();
  const [diag, setDiag] = useState<Record<string, unknown> | null>(null);
  const linked = health?.link_state === "TETHERED";
  const isSim = health?.device_transport === "SIMULATOR";
  useEffect(() => {
    if (!linked) return;
    void api.diagnostics().then((d) => setDiag(d.diag)).catch(() => undefined);
    const t = window.setInterval(() => void api.diagnostics().then((d) => setDiag(d.diag)).catch(() => undefined), 10000);
    return () => window.clearInterval(t);
  }, [linked]);
  const press = (b: "KEY" | "BOOT", g: "SHORT" | "DOUBLE" | "HOLD", ms = 0) => run(() => api.simulateButton(b, g, ms));
  const shown = linked ? diag : null;
  return (
    <>
      <PageHeader title="Device" subtitle="A live mirror of PIP's reflective screen, pixel for pixel." />
      <div className="grid gap-5 xl:grid-cols-[auto_minmax(0,1fr)]">
        <div className="space-y-4">
          <div className="max-w-full overflow-x-auto"><RlcdMirror scale={1.5} /></div>
          <Card aria-label="Device buttons">
            <CardTitle aside={isSim ? <Badge tone="sage">Simulator</Badge> : <Badge>{linked ? "Physical board" : "Offline"}</Badge>}>Buttons</CardTitle>
            {isSim && linked ? (
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={() => press("KEY", "SHORT")}>KEY · click</Button>
                <Button size="sm" onClick={() => press("KEY", "DOUBLE")}>KEY · double</Button>
                <Button size="sm" onClick={() => press("KEY", "HOLD", 900)}>KEY · hold (talk)</Button>
                <Button size="sm" onClick={() => press("BOOT", "SHORT")}>BOOT · click</Button>
                <Button size="sm" onClick={() => press("BOOT", "HOLD", 1300)}>BOOT · hold (split)</Button>
              </div>
            ) : (
              <p className="text-sm text-muted">{linked ? "Use the real KEY and BOOT buttons on PIP." : "Connect PIP or start sim_rlcd to use the buttons."}</p>
            )}
            <p className="mt-3 text-xs text-muted">KEY click: start/pause · double: agenda · hold: talk. BOOT click: done · hold 1.2 s: cut in half.</p>
          </Card>
        </div>
        <Card aria-label="Telemetry">
          <CardTitle>Telemetry</CardTitle>
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-sm">
            <dt className="text-muted">Link</dt><dd className="font-semibold">{linked ? "Tethered" : "Standalone / Disconnected"}</dd>
            <dt className="text-muted">Transport</dt><dd className="font-semibold">{health?.device_transport ?? "—"}</dd>
            <dt className="text-muted">Host revision</dt><dd className="tabular font-semibold">{state?.revision ?? "—"}</dd>
            <dt className="text-muted">PIP clock</dt><dd className="tabular font-semibold">
              {state?.device.heartbeat?.utc_epoch_s ? new Date(Number(state.device.heartbeat.utc_epoch_s) * 1000).toLocaleTimeString() : "—"}</dd>
            {FIELDS.map(([k, label]) => (
              <div key={k} className="contents"><dt className="text-muted">{label}</dt>
                <dd className="tabular font-semibold">{fmt(shown?.[k], k, Boolean(shown?.is_sim))}</dd></div>))}
          </dl>
        </Card>
      </div>
    </>
  );
}
