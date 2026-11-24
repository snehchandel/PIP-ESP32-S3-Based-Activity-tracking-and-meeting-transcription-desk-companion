import type { Activity, Alarm, DayItems, FullState, Health, Place, Plan, PlanResult, Settings, VoiceSession, WeatherInfo } from "./types";

const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => req<Health>("GET", "/health"),
  state: () => req<FullState>("GET", "/state"),
  plan: (text: string, auto_commit = false, activity: Activity = "BRAIN_DUMP") =>
    req<PlanResult>("POST", "/tasks/plan", { text, auto_commit, activity }),
  commit: (plan: Plan, source_text: string, voice_session_id?: string) =>
    req<unknown>("POST", "/tasks/commit", { plan, source_text, activate: true, voice_session_id }),
  createTask: (title: string, target_date: string, start_hhmm?: string | null) =>
    req<unknown>("POST", "/tasks", { title, target_date, start_hhmm: start_hhmm || null }),
  patchTask: (id: string, body: { title?: string; target_date?: string; status?: string; start_hhmm?: string }) =>
    req<unknown>("PATCH", `/tasks/${id}`, body),
  deleteTask: (id: string) => req<unknown>("DELETE", `/tasks/${id}`),
  activateTask: (id: string) => req<FullState>("POST", `/tasks/${id}/activate`),
  completeStep: (id: string) => req<FullState>("POST", `/steps/${id}/complete`),
  splitStep: (id: string) => req<{ current_sec: number; next_sec: number }>("POST", `/steps/${id}/rescue-split`),
  reorderSteps: (task_id: string, step_ids: string[]) => req<unknown>("PATCH", "/steps/reorder", { task_id, step_ids }),
  timer: (action: "start" | "pause" | "resume" | "break" | "reset" | "end-break" | "next") =>
    req<FullState>("POST", `/timer/${action}`),
  alarms: () => req<Alarm[]>("GET", "/alarms"),
  createAlarm: (body: Record<string, unknown>) => req<Alarm>("POST", "/alarms", body),
  patchAlarm: (id: string, body: Record<string, unknown>) => req<Alarm>("PATCH", `/alarms/${id}`, body),
  deleteAlarm: (id: string) => req<unknown>("DELETE", `/alarms/${id}`),
  testAlarm: (id: string) => req<{ sent_to_device: boolean }>("POST", `/alarms/${id}/test`),
  ackAlarm: (snooze: boolean) => req<unknown>("POST", "/alarms/ack", { snooze }),
  addReminder: (title: string, due_local: string) => req<unknown>("POST", "/reminders", { title, due_local }),
  patchReminder: (id: string, body: { title?: string; due_local?: string; done?: boolean }) =>
    req<unknown>("PATCH", `/reminders/${id}`, body),
  deleteReminder: (id: string) => req<unknown>("DELETE", `/reminders/${id}`),
  promoteParked: (id: string) => req<unknown>("POST", `/parked/${id}/promote`),
  dismissParked: (id: string) => req<unknown>("DELETE", `/parked/${id}`),
  confirm: () => req<unknown>("POST", "/confirmation/confirm", {}),
  dismissConfirm: () => req<unknown>("POST", "/confirmation/dismiss"),
  calendar: (start: string, days: number) => req<DayItems[]>("GET", `/calendar?start=${start}&days=${days}`),
  simulateButton: (button: "KEY" | "BOOT", gesture: "SHORT" | "DOUBLE" | "HOLD", hold_ms = 0) =>
    req<unknown>("POST", "/device/simulate-button", { button, gesture, hold_ms }),
  diagnostics: () => req<{ linked: boolean; transport: string; diag: Record<string, unknown> | null }>(
    "GET", "/device/diagnostics"),
  voiceSessions: () => req<VoiceSession[]>("GET", "/voice/sessions"),
  settings: () => req<Settings>("GET", "/settings"),
  saveApiKey: (key: string) => req<Settings>("PUT", "/settings/api-key", { key }),
  deleteApiKey: () => req<Settings>("DELETE", "/settings/api-key"),
  testApiKey: (key?: string) => req<{ ok: boolean; detail: string }>("POST", "/settings/api-key/test", { key: key || null }),
  setVoice: (piper_voice: string) => req<Settings>("PUT", "/settings/preferences", { piper_voice }),
  preloadStt: () => req<Settings>("POST", "/speech/preload"),
  sayOnDevice: (text: string) => req<{ played_on_device: boolean }>("POST", "/speech/say", { text }),
  sayWavUrl: (text: string) => `${BASE}/speech/say.wav?text=${encodeURIComponent(text)}`,
  kimiModels: () => req<{ models: string[]; active: string | null; pinned: string | null }>("GET", "/settings/kimi-models"),
  setKimiModel: (model: string) => req<{ models: string[]; active: string | null; pinned: string | null }>("PUT", "/settings/kimi-model", { model }),
  weather: () => req<WeatherInfo>("GET", "/weather"),
  weatherSearch: (q: string) => req<Place[]>("GET", `/weather/search?q=${encodeURIComponent(q)}`),
  setWeatherLocation: (p: Place) => req<WeatherInfo>("PUT", "/weather/location", p),
  dismissError: () => req<unknown>("POST", "/error/dismiss"),
  exportDiagnostics: () => req<Record<string, unknown>>("GET", "/diagnostics/export"),
};
