/* Shared meeting formatting: speaker colours, clock times, "when" lines (Meetings list + graph). */

export const SPEAKER_COLORS = ["#2563eb", "#d97706", "#059669", "#9333ea", "#dc2626", "#0891b2", "#65a30d", "#db2777"];
export const speakerColor = (key: string) =>
  SPEAKER_COLORS[(Number(key.slice(1)) - 1 + SPEAKER_COLORS.length) % SPEAKER_COLORS.length];

export function clock(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const mmss = `${String(Math.floor(s / 60) % 60).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  return s >= 3600 ? `${Math.floor(s / 3600)}:${mmss}` : mmss;
}

export function when(m: { started_at: string; ended_at?: string | null }): string {
  const a = new Date(m.started_at);
  const day = a.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric", year: "numeric" });
  const t = (d: Date) => d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return `${day} · ${t(a)}${m.ended_at ? `–${t(new Date(m.ended_at))}` : ""}`;
}

export function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}
