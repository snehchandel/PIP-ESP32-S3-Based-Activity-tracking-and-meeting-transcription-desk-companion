import { AlarmClock, CalendarDays, Check, Cpu, Crosshair, Mic, Settings, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { api } from "../api/client";
import { useLive } from "../api/live";
import { cn } from "../lib/utils";
import { PipMark } from "./PipMark";
import { StatusPill } from "./StatusPill";
import { Button } from "./ui/button";

export const NAV = [
  { to: "/", label: "Today", icon: Sun },
  { to: "/calendar", label: "Calendar", icon: CalendarDays },
  { to: "/voice", label: "Brain Dump", icon: Mic },
  { to: "/focus", label: "Focus", icon: Crosshair },
  { to: "/alarms", label: "Alarms", icon: AlarmClock },
  { to: "/device", label: "Device", icon: Cpu },
  { to: "/settings", label: "Settings", icon: Settings },
];

function AlarmBanner() {
  const { state, run } = useLive();
  const [now, setNow] = useState(() => Date.now());
  const r = state?.ringing;
  useEffect(() => {
    if (!r?.test) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [r?.test]);
  if (!r) return null;
  const left = r.test && r.expires_at_ms ? Math.max(0, Math.ceil((r.expires_at_ms - now) / 1000)) : null;
  return (
    <div role="alert" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#f2cfae]
      bg-amber-soft px-4 py-3">
      <p className="text-sm font-semibold text-amber-ink">
        {r.test ? "Test alarm" : "Alarm"} · {r.hhmm} — {r.title}
        {left !== null && <span className="ml-2 font-normal">(closes by itself in {left} s)</span>}</p>
      <div className="flex gap-2">
        {!r.test && <Button size="sm" onClick={() => run(() => api.ackAlarm(true))}>Snooze 5 min</Button>}
        <Button size="sm" variant="primary" onClick={() => run(() => api.ackAlarm(false))}>Dismiss</Button>
      </div>
    </div>
  );
}

function ErrorBanner() {
  const { state, run } = useLive();
  const e = state?.error;
  if (!e) return null;
  return (
    <div role="alert" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#e7c2b8]
      bg-[#fbeee9] px-4 py-3">
      <p className="text-sm"><span className="font-semibold text-[#8a3b2e]">{e.title}.</span> {e.text}</p>
      <Button size="sm" variant="primary" onClick={() => run(() => api.dismissError())}>Dismiss</Button>
    </div>
  );
}

function AckBanner() {
  // "Alarm set: Wed 05:00" - shown for a few seconds after PIP schedules something
  const { state } = useLive();
  const a = state?.ack;
  const [hidden, setHidden] = useState<number | null>(null);
  useEffect(() => {
    if (!a) return;
    const t = window.setTimeout(() => setHidden(a.id), 8000);
    return () => window.clearTimeout(t);
  }, [a]);
  if (!a || hidden === a.id) return null;
  return (
    <div role="status" className="mb-4 flex items-center gap-2 rounded-2xl border border-[#cfe3d3] bg-[#eef6ef] px-4 py-3">
      <Check size={16} aria-hidden className="text-[#2f6b3b]" />
      <p className="text-sm font-semibold text-[#2f6b3b]">{a.text}</p>
    </div>
  );
}

function ConfirmBanner() {
  const { state, run } = useLive();
  const p = state?.pending_confirmation;
  if (!p) return null;
  return (
    <div role="status" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-line
      bg-white px-4 py-3">
      <p className="text-sm"><span className="font-semibold">Confirm time:</span> {p.question}</p>
      <div className="flex gap-2">
        <Button size="sm" onClick={() => run(() => api.dismissConfirm())}>Not now — park it</Button>
        <Button size="sm" variant="primary" onClick={() => run(() => api.confirm())}>Confirm</Button>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { error } = useLive();
  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-30 border-b border-line bg-paper/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1240px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-2.5">
            <PipMark size={30} />
            <div className="leading-tight">
              <p className="text-lg font-black tracking-tight">PIP</p>
              <p className="hidden text-[11px] text-muted sm:block">Plan · Focus · Achieve</p>
            </div>
          </div>
          <nav aria-label="Main" className="order-3 -mx-1 flex w-full gap-1 overflow-x-auto pb-1 lg:order-2 lg:w-auto lg:flex-1
            lg:justify-center lg:pb-0">
            {NAV.map((n, i) => (
              <NavLink key={n.to} to={n.to} end={n.to === "/"} aria-keyshortcuts={String(i + 1)}
                className={({ isActive }) => cn("flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-semibold",
                  isActive ? "bg-ink text-paper" : "text-ink-2 hover:bg-paper-2")}>
                <n.icon size={15} aria-hidden /> {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="order-2 ml-auto lg:order-3"><StatusPill /></div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[1240px] flex-1 px-4 py-6 sm:px-6">
        <AlarmBanner />
        <ErrorBanner />
        <AckBanner />
        <ConfirmBanner />
        {error && <p role="alert" className="mb-4 rounded-xl border border-line bg-white px-4 py-2 text-sm text-ink-2">
          {error}</p>}
        {children}
      </main>
      <footer className="border-t border-line px-6 py-3 text-center text-xs text-muted">
        Shortcuts: <kbd>Space</kbd> timer · <kbd>N</kbd> brain dump · <kbd>S</kbd> split step · <kbd>1–7</kbd> views
      </footer>
    </div>
  );
}
