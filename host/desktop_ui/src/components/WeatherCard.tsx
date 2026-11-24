import { CloudSun, MapPin, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useLive } from "../api/live";
import type { Place, WeatherInfo } from "../api/types";
import { Button } from "./ui/button";
import { Card, CardTitle, Input } from "./ui/primitives";

const CODE = ["Clear", "Cloudy", "Rain", "Snow", "Storm", "Fog"];

export function fmtTemp(c10?: number): string {
  return c10 === undefined || c10 === null ? "—" : `${Math.round(c10 / 10)}°C`;
}

/** Outdoor weather location (Open-Meteo, no key). Only the chosen place's coordinates leave the PC. */
export function WeatherCard() {
  const { run, state } = useLive();
  const [w, setW] = useState<WeatherInfo | null>(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Place[]>([]);
  useEffect(() => { void api.weather().then(setW).catch(() => undefined); }, [state?.weather?.updated]);
  const loc = w?.location;
  const inside = state?.device.telemetry?.indoor_c10 as number | undefined;
  const insideHum = state?.device.telemetry?.indoor_hum as number | undefined;
  return (
    <Card aria-label="Weather">
      <CardTitle><span className="inline-flex items-center gap-2"><CloudSun size={16} aria-hidden /> Temperature & weather</span></CardTitle>
      <dl className="mb-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-sm">
        <dt className="text-muted">Inside (PIP sensor)</dt>
        <dd className="tabular font-semibold">{inside !== undefined && inside > -9999 ? `${fmtTemp(inside)} · ${insideHum}%` : "—"}</dd>
        <dt className="text-muted">Outside</dt>
        <dd className="tabular font-semibold">{w?.out_temp_c10 !== undefined
          ? `${fmtTemp(w.out_temp_c10)} · ${w.out_hum}% · ${CODE[w.out_code ?? 1]}` : "—"}</dd>
        <dt className="text-muted">Location</dt>
        <dd>{loc?.name ? `${loc.name}${loc.admin1 ? `, ${loc.admin1}` : ""}${loc.country ? `, ${loc.country}` : ""}` : "Not set"}</dd>
      </dl>
      {w?.error && <p className="mb-2 text-xs text-muted">Last update failed: {w.error}</p>}
      <form className="flex gap-2" onSubmit={async (e) => {
        e.preventDefault();
        setHits((await run(() => api.weatherSearch(q))) ?? []);
      }}>
        <label htmlFor="wx-q" className="sr-only">City</label>
        <Input id="wx-q" placeholder="Change city…" value={q} onChange={(e) => setQ(e.target.value)} />
        <Button type="submit" disabled={q.trim().length < 2}><Search size={15} aria-hidden /> Find</Button>
      </form>
      {hits.length > 0 && (
        <ul className="mt-2 space-y-1">
          {hits.map((h) => (
            <li key={`${h.latitude},${h.longitude}`}>
              <button className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-paper-2"
                onClick={async () => { const r = await run(() => api.setWeatherLocation(h)); if (r) { setW(r); setHits([]); setQ(""); } }}>
                <MapPin size={14} aria-hidden /> {h.name}{h.admin1 ? `, ${h.admin1}` : ""}, {h.country}</button>
            </li>))}
        </ul>
      )}
      <p className="mt-2 text-xs text-muted">Shown on PIP's top bar in °C with humidity; refreshed every 15 minutes.</p>
    </Card>
  );
}
