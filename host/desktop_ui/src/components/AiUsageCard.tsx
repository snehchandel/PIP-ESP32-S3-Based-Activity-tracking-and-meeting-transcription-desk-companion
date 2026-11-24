import { AlertTriangle, CircleCheck, OctagonAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useLive } from "../api/live";
import type { AiUsage, AiUsageDay } from "../api/types";
import { Button } from "./ui/button";
import { Card, CardTitle, Input, Label } from "./ui/primitives";

const usd = (v: number) => (v >= 1 ? `$${v.toFixed(2)}` : v >= 0.01 ? `$${v.toFixed(3)}` : `$${v.toFixed(4)}`);
const tok = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n));
const day = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString([], { month: "short", day: "numeric" });

/** Daily Kimi spend: one series (no legend), thin bars rounded at the data end, recessive grid, hover tooltip. */
function DailyChart({ days }: { days: AiUsageDay[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 600, H = 150, L = 44, B = 22, T = 8;
  const max = Math.max(0.001, ...days.map((d) => d.cost_usd));
  const step = niceStep(max);
  const top = Math.ceil(max / step) * step;
  const bw = (W - L) / days.length;
  const y = (v: number) => T + (H - T - B) * (1 - v / top);
  const h = hover !== null ? days[hover] : null;
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img"
        aria-label={`Kimi cost per day for the last ${days.length} days, up to ${usd(max)}`}>
        {[0, 1, 2, 3].map((k) => {
          const v = (top / 3) * k;
          return (
            <g key={k}>
              <line x1={L} x2={W} y1={y(v)} y2={y(v)} stroke="var(--color-line)" strokeWidth={1} />
              <text x={L - 6} y={y(v) + 4} textAnchor="end" fontSize={11} fill="var(--color-muted)">{usd(v)}</text>
            </g>
          );
        })}
        {days.map((d, i) => {
          const x = L + i * bw + 1, w = Math.max(2, bw - 2), y0 = y(0), y1 = y(d.cost_usd);
          const r = Math.min(4, w / 2, y0 - y1);
          return (
            <g key={d.date} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={L + i * bw} y={T} width={bw} height={H - T - B} fill="transparent" />
              {d.cost_usd > 0 && (
                <path d={`M${x},${y0} V${y1 + r} Q${x},${y1} ${x + r},${y1} H${x + w - r} Q${x + w},${y1} ${x + w},${y1 + r} V${y0} Z`}
                  fill={hover === i ? "var(--color-ink)" : "var(--color-ink-2)"} />
              )}
            </g>
          );
        })}
        {[0, Math.floor(days.length / 2), days.length - 1].map((i, k) => days[i] && (
          <text key={i} x={k === 2 ? W : k === 0 ? L : L + i * bw + bw / 2} y={H - 6}
            textAnchor={k === 2 ? "end" : k === 0 ? "start" : "middle"} fontSize={11} fill="var(--color-muted)">
            {day(days[i].date)}</text>
        ))}
      </svg>
      {h && hover !== null && (
        <div className="pointer-events-none absolute top-0 z-10 rounded-lg border border-line bg-white px-2.5 py-1.5 text-xs shadow-md"
          style={{ left: `clamp(0px, calc(${((L + hover * bw) / W) * 100}% - 60px), calc(100% - 150px))` }}>
          <p className="font-semibold">{day(h.date)}</p>
          <p className="tabular">{usd(h.cost_usd)} · {h.calls} call{h.calls === 1 ? "" : "s"}</p>
          <p className="tabular text-muted">{tok(h.prompt_tokens)} in ({tok(h.cached_tokens)} cached) · {tok(h.completion_tokens)} out</p>
        </div>
      )}
    </div>
  );
}

function niceStep(max: number): number {
  const raw = max / 3, p = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= raw) ?? raw;
}

export function AiUsageCard() {
  const { run } = useLive();
  const [u, setU] = useState<AiUsage | null>(null);
  const [cap, setCap] = useState("");
  const [price, setPrice] = useState({ input: "", cached: "", output: "" });
  const load = (next: AiUsage) => {
    setU(next);
    setCap(next.cap_usd ? String(next.cap_usd) : "");
    const p = next.prices[next.active_model ?? ""];
    if (p) setPrice({ input: String(p.input), cached: String(p.cached), output: String(p.output) });
  };
  useEffect(() => { void api.aiUsage().then(load).catch(() => undefined); }, []);
  if (!u) return <Card aria-label="AI usage"><CardTitle>AI usage &amp; budget</CardTitle><p className="text-sm text-muted">Loading…</p></Card>;
  const pct = u.cap_used !== null ? Math.min(1, u.cap_used) : null;
  const state = u.cap_state;
  const StateIcon = state === "REACHED" ? OctagonAlert : state === "WARN" ? AlertTriangle : CircleCheck;
  return (
    <Card aria-label="AI usage and budget" className="lg:col-span-2">
      <CardTitle aside={<span className="text-xs text-muted">Model: {u.active_model ?? "—"}</span>}>AI usage &amp; budget</CardTitle>
      <div className="grid gap-5 md:grid-cols-[220px_minmax(0,1fr)]">
        <div className="space-y-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">This month</p>
            <p className="tabular text-3xl font-black">{usd(u.month.cost_usd)}</p>
            <p className="tabular text-xs text-muted">{u.month.calls} call{u.month.calls === 1 ? "" : "s"} · {tok(u.month.prompt_tokens)} in · {tok(u.month.completion_tokens)} out</p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">Today</p>
            <p className="tabular text-lg font-bold">{usd(u.today.cost_usd)}</p>
            <p className="tabular text-xs text-muted">{u.today.calls} call{u.today.calls === 1 ? "" : "s"} · {tok(u.today.prompt_tokens + u.today.completion_tokens)} tokens</p>
          </div>
          {pct !== null && (
            <div>
              <div className="h-2.5 overflow-hidden rounded-full bg-paper-2" role="progressbar" aria-valuenow={Math.round(pct * 100)}
                aria-valuemin={0} aria-valuemax={100} aria-label="Share of monthly cap used">
                <div className="h-full rounded-full bg-ink-2" style={{ width: `${pct * 100}%` }} /></div>
              <p className={`mt-1 flex items-center gap-1 text-xs font-semibold ${state === "REACHED" ? "text-[#8a3b2e]"
                : state === "WARN" ? "text-amber-ink" : "text-sage"}`}>
                <StateIcon size={13} aria-hidden />
                {state === "REACHED" ? "Cap reached — planning paused" : state === "WARN" ? "Over 80 % of the cap" : "Within budget"}
                <span className="font-normal text-muted">· {Math.round(pct * 100)} % of {usd(u.cap_usd ?? 0)}</span></p>
            </div>
          )}
        </div>
        <div className="min-w-0">
          <DailyChart days={u.days} />
          <details className="mt-1 text-xs">
            <summary className="cursor-pointer text-muted">Show as table</summary>
            <table className="mt-2 w-full tabular">
              <thead><tr className="text-left text-muted"><th>Day</th><th>Calls</th><th>In</th><th>Cached</th><th>Out</th><th className="text-right">Cost</th></tr></thead>
              <tbody>{u.days.filter((d) => d.calls).reverse().map((d) => (
                <tr key={d.date} className="border-t border-line"><td>{day(d.date)}</td><td>{d.calls}</td><td>{tok(d.prompt_tokens)}</td>
                  <td>{tok(d.cached_tokens)}</td><td>{tok(d.completion_tokens)}</td><td className="text-right">{usd(d.cost_usd)}</td></tr>))}
              </tbody>
            </table>
          </details>
        </div>
      </div>
      <div className="mt-4 grid gap-4 border-t border-line pt-4 md:grid-cols-2">
        <form onSubmit={async (e) => { e.preventDefault(); const r = await run(() => api.setAiBudget(cap ? Number(cap) : null)); if (r) load(r); }}>
          <Label htmlFor="ai-cap">Monthly cap (USD) — planning stops when it's reached</Label>
          <div className="flex gap-2">
            <Input id="ai-cap" type="number" min={0} step="0.5" placeholder="No cap" value={cap} onChange={(e) => setCap(e.target.value)} />
            <Button type="submit" variant="primary">Save</Button>
            {u.cap_usd !== null && <Button onClick={async () => { const r = await run(() => api.setAiBudget(null)); if (r) load(r); }}>No cap</Button>}
          </div>
        </form>
        {u.active_model && (
          <form onSubmit={async (e) => {
            e.preventDefault();
            const r = await run(() => api.setAiPrice(u.active_model as string, Number(price.input), Number(price.cached), Number(price.output)));
            if (r) load(r);
          }}>
            <Label>Price of {u.active_model} (USD per million tokens)</Label>
            <div className="flex gap-2">
              {(["input", "cached", "output"] as const).map((k) => (
                <Input key={k} aria-label={`${k} price`} type="number" min={0} step="0.01" value={price[k]} title={k}
                  onChange={(e) => setPrice({ ...price, [k]: e.target.value })} />))}
              <Button type="submit">Save</Button>
            </div>
            <p className="mt-1 text-xs text-muted">input · cached input · output — check Moonshot's price page if they change.</p>
          </form>
        )}
      </div>
    </Card>
  );
}
