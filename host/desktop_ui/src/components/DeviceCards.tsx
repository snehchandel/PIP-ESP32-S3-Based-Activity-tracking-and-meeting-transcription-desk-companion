import { CheckCircle2, CloudUpload, Globe, Mic, RefreshCw, Wifi, WifiOff, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { AwayInfo, FirmwareInfo, NetworkInfo, WakeInfo } from "../api/types";
import { useLive } from "../api/live";
import { Button } from "./ui/button";
import { Badge, Card, CardTitle, Input, Label, Select } from "./ui/primitives";

const VIA_LABEL: Record<string, string> = { WIFI: "Wi-Fi", WIFI_AWAY: "Away link", USB_HARDWARE: "USB cable" };

/** Wi-Fi: PIP remembers several networks (home, office, a phone hotspot) and joins the strongest one in range.
 *  Passwords go straight to PIP and are never stored on the PC. */
export function ConnectionCard() {
  const { run, health } = useLive();
  const [n, setN] = useState<NetworkInfo | null>(null);
  const [ssid, setSsid] = useState("");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { void api.network().then(setN).catch(() => undefined); }, [health?.link_state, health?.device_transport]);
  const w = n?.wifi ?? {};
  const onUsb = n?.via === "USB_HARDWARE";
  const state = w.state ?? (n?.linked ? "unknown" : "—");
  return (
    <Card aria-label="Connection">
      <CardTitle aside={<Badge tone={n?.via?.startsWith("WIFI") ? "sage" : "neutral"}>{n?.linked ? (VIA_LABEL[n.via] ?? n.via) : "Not connected"}</Badge>}>
        Connection</CardTitle>
      <dl className="mb-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-sm">
        <dt className="text-muted">Wi-Fi</dt>
        <dd className="flex items-center gap-1.5 font-semibold">
          {state === "UP" ? <Wifi size={14} aria-hidden /> : <WifiOff size={14} aria-hidden />}
          {state === "UP" ? `Connected to ${w.ssid}` : state === "CONNECTING" ? `Joining ${w.ssid}…` : state === "FAILED"
            ? `Can't join ${w.ssid} (check the password)` : w.configured === false ? "Not set up" : String(state)}</dd>
        {w.ip && <><dt className="text-muted">Address</dt><dd className="tabular">{w.ip} · {w.host}</dd></>}
        {typeof w.rssi === "number" && w.rssi !== 0 && <><dt className="text-muted">Signal</dt><dd className="tabular">{w.rssi} dBm</dd></>}
        <dt className="text-muted">Paired with this PC</dt><dd>{n?.paired_on_pc && w.paired ? "Yes" : "Not yet (connect the USB cable once)"}</dd>
        {(w.networks?.length ?? 0) > 0 && <><dt className="text-muted">Saved networks</dt>
          <dd><ul aria-label="Saved networks" className="flex flex-wrap gap-1.5">{w.networks!.map((s) => (
            <li key={s} className="inline-flex items-center gap-1 rounded-full border border-line px-2 py-0.5 text-xs">
              {s}{s === w.ssid && state === "UP" ? " · in use" : ""}
              <button type="button" aria-label={`Forget ${s}`} title={`Forget ${s}`} disabled={busy || !n?.linked}
                className="text-muted hover:text-ink disabled:opacity-40"
                onClick={async () => { setBusy(true); const r = await run(() => api.forgetWifi(s)); setBusy(false); if (r) setN(r); }}>
                <X size={12} aria-hidden /></button></li>))}</ul></dd></>}
      </dl>
      <form className="space-y-2" onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        const r = await run(() => api.setWifi(ssid.trim(), pw));
        setBusy(false);
        setPw("");
        if (r) setN(r);
      }}>
        <div className="grid gap-2 sm:grid-cols-2">
          <div><Label htmlFor="wifi-ssid">Wi-Fi name</Label><Input id="wifi-ssid" value={ssid} autoComplete="off" onChange={(e) => setSsid(e.target.value)} /></div>
          <div><Label htmlFor="wifi-pw">Password</Label><Input id="wifi-pw" type="password" value={pw} autoComplete="new-password"
            onChange={(e) => setPw(e.target.value)} /></div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" variant="primary" disabled={!ssid.trim() || busy || !n?.linked}>{busy ? "PIP is joining…" : w.configured ? "Add network" : "Connect PIP to Wi-Fi"}</Button>
          {w.configured && <Button disabled={busy} onClick={async () => { const r = await run(() => api.forgetWifi()); if (r) setN(r); }}>Forget all networks</Button>}
        </div>
        <p className="text-xs text-muted">{onUsb ? "Do this once with the USB cable plugged in: it also pairs PIP with this PC. Afterwards you can unplug PIP and power it from any USB charger — it reconnects over Wi-Fi."
          : "2.4 GHz networks only, up to 5 saved. Add the office Wi-Fi or your phone's hotspot before you take PIP there. Passwords are sent to PIP and never stored on this PC."}</p>
      </form>
    </Card>
  );
}

const AWAY_STATE: Record<string, string> = {
  OFF: "Off", WAITING: "Standing by (on the cable or home Wi-Fi)", DIALING: "Calling this PC…", UP: "Connected over the internet",
  FAILED: "Can't reach this PC — retrying",
};

/** Away link (ADR-035): when PIP is on another network it dials this PC's public address, encrypted end to end. */
export function AwayCard() {
  const { run, health } = useLive();
  const [a, setA] = useState<AwayInfo | null>(null);
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");
  const [listen, setListen] = useState("18423");
  const [tls, setTls] = useState(true);
  const [busy, setBusy] = useState(false);
  const load = (r: AwayInfo) => {
    setA(r); setHost(r.host); setPort(r.port ? String(r.port) : ""); setListen(String(r.listen_port)); setTls(r.tls);
  };
  useEffect(() => { void api.away().then(load).catch(() => undefined); }, [health?.link_state, health?.device_transport]);
  if (!a || !a.available) return null;
  const save = async (enabled: boolean) => {
    setBusy(true);
    const r = await run(() => api.setAway(enabled, host.trim(), Number(port) || 0, Number(listen) || 18423, tls));
    setBusy(false);
    if (r) load(r);
  };
  const dev = a.device.state ?? "";
  const tone = health?.device_transport === "WIFI_AWAY" ? "sage" : "neutral";
  return (
    <Card aria-label="Away from home">
      <CardTitle aside={<Badge tone={tone}>{health?.device_transport === "WIFI_AWAY" ? "Linked" : a.enabled ? "On" : "Off"}</Badge>}>
        <span className="inline-flex items-center gap-1.5"><Globe size={15} aria-hidden /> Away from home</span></CardTitle>
      {a.enabled && <dl className="mb-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-sm">
        <dt className="text-muted">This PC</dt>
        <dd className="font-semibold">{a.listener.listening ? `Listening on port ${a.listener.port}` : a.listener.error || "Not listening"}</dd>
        {dev && <><dt className="text-muted">PIP</dt><dd className="font-semibold">{AWAY_STATE[dev] ?? dev}</dd></>}
        {!!a.listener.links && <><dt className="text-muted">Last call</dt>
          <dd className="tabular">{a.listener.last_link_at ? new Date(a.listener.last_link_at * 1000).toLocaleString() : "—"}</dd></>}
        {!!a.listener.rejected && <><dt className="text-muted">Refused</dt><dd className="tabular">{a.listener.rejected} unauthenticated connection(s)</dd></>}
      </dl>}
      <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); void save(true); }}>
        <div><Label htmlFor="away-via">How this PC is reachable</Label>
          <Select id="away-via" value={tls ? "funnel" : "forward"} onChange={(e) => setTls(e.target.value === "funnel")}>
            <option value="funnel">Tailscale Funnel (or another TLS tunnel)</option>
            <option value="forward">Port forward on my router</option></Select></div>
        <div className="grid gap-2 sm:grid-cols-[1fr_6rem_6rem]">
          <div><Label htmlFor="away-host">Public address of this PC</Label>
            <Input id="away-host" value={host} placeholder="my-pc.tail1234.ts.net" autoComplete="off" onChange={(e) => setHost(e.target.value)} /></div>
          <div><Label htmlFor="away-port">Public port</Label>
            <Input id="away-port" inputMode="numeric" value={port} placeholder="10000" onChange={(e) => setPort(e.target.value)} /></div>
          <div><Label htmlFor="away-listen">Local port</Label>
            <Input id="away-listen" inputMode="numeric" value={listen} onChange={(e) => setListen(e.target.value)} /></div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" variant="primary" disabled={busy || !host.trim()}>{a.enabled ? "Save" : "Turn on"}</Button>
          {a.enabled && <Button disabled={busy} onClick={() => void save(false)}>Turn off</Button>}
        </div>
        <p className="text-xs text-muted">When PIP is on another Wi-Fi (office, phone hotspot) it calls this PC over the internet.{" "}
          {tls ? <>Make the local port reachable first:{" "}
            <code>tailscale funnel --bg --tls-terminated-tcp={port || "10000"} tcp://localhost:{listen || "18423"}</code>{" "}
            (Funnel allows public ports 443, 8443 and 10000), then enter this PC's <code>*.ts.net</code> name.</>
            : <>Forward the public port on your router to this PC's local port (TCP), and enter your public IP or
              dynamic-DNS name.</>}{" "}
          The link is encrypted with the key PIP shares only with this PC. This PC must be on with PIP running.</p>
      </form>
    </Card>
  );
}

/** Firmware updates without the command line: pick the latest build (or upload a .bin) and press Update. */
export function FirmwareCard() {
  const { run, health } = useLive();
  const [f, setF] = useState<FirmwareInfo | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const running = f?.status.state === "SENDING" || f?.status.state === "REBOOTING";
  useEffect(() => { void api.firmware().then(setF).catch(() => undefined); }, [health?.link_state]);
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => void api.firmware().then(setF).catch(() => undefined), 1000);
    return () => window.clearInterval(t);
  }, [running]);
  const cur = f?.device.version;
  const options = (["build", "upload"] as const).filter((k) => f?.available[k] && !f.available[k]?.error);
  return (
    <Card aria-label="Firmware">
      <CardTitle aside={<Badge>{cur ? `v${cur}` : "unknown"}</Badge>}>Firmware</CardTitle>
      {f?.device.ota?.slot && <p className="mb-2 text-xs text-muted">Running from {f.device.ota.slot} · built {f.device.ota.built} · last update: {f.device.ota.last}</p>}
      <ul className="mb-3 space-y-1.5">
        {options.map((k) => {
          const a = f!.available[k]!;
          const newer = a.version !== cur;
          return (
            <li key={k} className="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-white/60 px-3 py-2 text-sm">
              <span className="font-semibold">v{a.version}</span>
              <span className="text-xs text-muted">{k === "build" ? "latest build on this PC" : "uploaded file"} · {a.date} {a.time} · {Math.round((a.size ?? 0) / 1024)} KB</span>
              {!newer && <Badge tone="sage">installed</Badge>}
              <Button size="sm" variant={newer ? "primary" : "outline"} className="ml-auto" disabled={running || !f?.linked}
                onClick={async () => { const r = await run(() => api.updateFirmware(k)); if (r) setF(r); }}>
                <RefreshCw size={14} aria-hidden /> {newer ? "Update PIP" : "Reinstall"}</Button>
            </li>);
        })}
        {options.length === 0 && <li className="text-sm text-muted">No firmware image found. Upload a pip_firmware.bin below.</li>}
      </ul>
      {f && f.status.state !== "IDLE" && (
        <div className="mb-3" role="status">
          <div className="h-2.5 overflow-hidden rounded-full bg-paper-2"><div className="h-full rounded-full bg-ink-2" style={{ width: `${f.status.progress}%` }} /></div>
          <p className="mt-1 flex items-center gap-1 text-xs">{f.status.state === "DONE" && <CheckCircle2 size={13} className="text-sage" aria-hidden />}
            {f.status.message}</p>
        </div>
      )}
      <input ref={file} type="file" accept=".bin" className="hidden" aria-label="Firmware image file (.bin)" onChange={async (e) => {
        const fl = e.target.files?.[0];
        if (!fl) return;
        const r = await run(() => api.uploadFirmware(fl));
        if (r) setF(r);
        e.target.value = "";
      }} />
      <Button size="sm" disabled={running} onClick={() => file.current?.click()}><CloudUpload size={14} aria-hidden /> Upload .bin</Button>
      <p className="mt-2 text-xs text-muted">Works over USB or Wi-Fi (about 10-20 s). PIP checks the image, restarts into it, and goes back to the
        previous version by itself if the new one doesn't start properly.</p>
    </Card>
  );
}

/** Hands-free: say the wake word, PIP starts listening and stops when you go quiet. */
export function WakeWordCard() {
  const { run, health } = useLive();
  const [w, setW] = useState<WakeInfo | null>(null);
  const [test, setTest] = useState<string | null>(null);
  useEffect(() => { void api.wake().then(setW).catch(() => undefined); }, [health?.link_state]);
  if (!w) return null;
  const save = async (enabled: boolean, word: string) => { const r = await run(() => api.setWake(enabled, word)); if (r) setW(r); };
  return (
    <Card aria-label="Wake word">
      <CardTitle aside={<Badge tone={w.device.ready ? "sage" : "neutral"}>{w.device.ready ? "Listening on PIP" : health?.link_state === "TETHERED" ? "Not ready" : "PIP offline"}</Badge>}>
        Wake word</CardTitle>
      <div className="mb-3 flex items-center gap-2 text-sm">
        <input id="wake-on" type="checkbox" className="h-4 w-4 accent-[#18181b]" checked={w.enabled}
          onChange={(e) => void save(e.target.checked, w.word)} />
        <label htmlFor="wake-on">Say a wake word instead of holding KEY</label>
      </div>
      <Label htmlFor="wake-word">Word</Label>
      <div className="flex gap-2">
        <Select id="wake-word" value={w.word} disabled={!w.enabled} onChange={(e) => void save(w.enabled, e.target.value)}>
          {Object.entries(w.words).map(([k, label]) => <option key={k} value={k}>{label}</option>)}</Select>
        <Button disabled={!w.enabled || health?.link_state !== "TETHERED"} onClick={async () => {
          setTest("Testing…");
          const r = await run(() => api.testWake());
          setTest(r ? (r.detected ? `PIP recognised "${r.phrase}"` : `PIP did not react to "${r.phrase}"`) : null);
        }}><Mic size={14} aria-hidden /> Test</Button>
      </div>
      {test && <p className="mt-2 text-xs" role="status">{test}</p>}
      <p className="mt-2 text-xs text-muted">Runs entirely on PIP: the microphone audio never leaves the device until it hears the word.
        After the word PIP listens until you stop talking (about a second of quiet), then plans it like a brain dump.
        The words are Espressif's stock models — a custom "Hey PIP" would need a separately trained model.</p>
    </Card>
  );
}
