import { useEffect } from "react";
import { Route, Routes, useNavigate } from "react-router-dom";
import { api } from "./api/client";
import { useLive } from "./api/live";
import { AppShell, NAV } from "./components/AppShell";
import AlarmsView from "./views/AlarmsView";
import CalendarView from "./views/CalendarView";
import DeviceView from "./views/DeviceView";
import FocusView from "./views/FocusView";
import MeetingsView from "./views/MeetingsView";
import SettingsView from "./views/SettingsView";
import TodayView from "./views/TodayView";
import VoiceView from "./views/VoiceView";

function isTyping(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
}

export default function App() {
  const nav = useNavigate();
  const { state, run } = useLive();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return;
      const idx = Number(e.key) - 1;
      if (idx >= 0 && idx < NAV.length) {
        nav(NAV[idx].to);
      } else if (e.code === "Space") {
        e.preventDefault();
        void run(() => api.timer(state?.timer.state === "RUNNING" ? "pause" : "start"));
      } else if (e.key === "n" || e.key === "N") {
        e.preventDefault();
        nav("/");
        window.setTimeout(() => document.getElementById("brain-dump-input")?.focus(), 30);
      } else if ((e.key === "s" || e.key === "S") && state?.active_step_id) {
        e.preventDefault();
        nav("/focus?split=1");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [nav, run, state?.timer.state, state?.active_step_id]);

  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<TodayView />} />
        <Route path="/calendar" element={<CalendarView />} />
        <Route path="/voice" element={<VoiceView />} />
        <Route path="/focus" element={<FocusView />} />
        <Route path="/meetings" element={<MeetingsView />} />
        <Route path="/alarms" element={<AlarmsView />} />
        <Route path="/device" element={<DeviceView />} />
        <Route path="/settings" element={<SettingsView />} />
        <Route path="*" element={<TodayView />} />
      </Routes>
    </AppShell>
  );
}
