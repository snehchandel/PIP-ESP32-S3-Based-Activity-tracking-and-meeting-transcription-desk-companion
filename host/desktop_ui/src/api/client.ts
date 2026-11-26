import type { Activity, AiUsage, Alarm, FirmwareInfo, GpuPack, NetworkInfo, WakeInfo, DayItems, FullState, Health, MeetingActionRow, MeetingAnswer, MeetingDetail, MeetingGraph, MeetingHit, MeetingList, MeetingSettings, LocalModels, MeetingSummary, Place, Plan, PlanResult, Settings, Speaker, VoiceProfile, VoiceSession, WeatherInfo } from "./types";

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
  patchTask: (id: string, body: { title?: string; target_date?: string; status?: string; start_hhmm?: string; block_min?: number }) =>
    req<unknown>("PATCH", `/tasks/${id}`, body),
  parkTask: (id: string) => req<{ parked_id: string }>("POST", `/tasks/${id}/park`),
  agendaMove: (kind: "task" | "reminder" | "alarm", id: string, date: string) =>
    req<{ moved: boolean }>("POST", "/agenda/move", { kind, id, date }),
  agendaPark: (kind: "task" | "reminder" | "alarm", id: string) =>
    req<{ parked_id: string }>("POST", "/agenda/park", { kind, id }),
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
  calendar: (start: string, days: number, others = false) =>
    req<DayItems[]>("GET", `/calendar?start=${start}&days=${days}${others ? "&others=true" : ""}`),
  simulateButton: (button: "KEY" | "BOOT", gesture: "SHORT" | "DOUBLE" | "HOLD", hold_ms = 0) =>
    req<unknown>("POST", "/device/simulate-button", { button, gesture, hold_ms }),
  diagnostics: () => req<{ linked: boolean; transport: string; diag: Record<string, unknown> | null }>(
    "GET", "/device/diagnostics"),
  voiceSessions: () => req<VoiceSession[]>("GET", "/voice/sessions"),
  settings: () => req<Settings>("GET", "/settings"),
  aiUsage: () => req<AiUsage>("GET", "/ai/usage"),
  network: () => req<NetworkInfo>("GET", "/device/network"),
  setWifi: (ssid: string, password: string) => req<NetworkInfo>("PUT", "/device/wifi", { ssid, password }),
  forgetWifi: () => req<NetworkInfo>("DELETE", "/device/wifi"),
  wake: () => req<WakeInfo>("GET", "/device/wake"),
  setWake: (enabled: boolean, word: string) => req<WakeInfo>("PUT", "/device/wake", { enabled, word }),
  testWake: () => req<{ word: string; phrase: string; detected: boolean }>("POST", "/device/wake/test"),
  firmware: () => req<FirmwareInfo>("GET", "/firmware"),
  updateFirmware: (source: "build" | "upload") => req<FirmwareInfo>("POST", "/firmware/update", { source }),
  uploadFirmware: async (file: File): Promise<FirmwareInfo> => {
    const res = await fetch(`${BASE}/firmware/upload`, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail; } catch { /* non-JSON */ }
      throw new ApiError(res.status, String(detail));
    }
    return (await res.json()) as FirmwareInfo;
  },
  setAiBudget: (monthly_cap_usd: number | null) => req<AiUsage>("PUT", "/ai/budget", { monthly_cap_usd }),
  setAiPrice: (model: string, input: number, cached: number, output: number) =>
    req<AiUsage>("PUT", "/ai/prices", { model, input, cached, output }),
  saveApiKey: (key: string) => req<Settings>("PUT", "/settings/api-key", { key }),
  deleteApiKey: () => req<Settings>("DELETE", "/settings/api-key"),
  testApiKey: (key?: string) => req<{ ok: boolean; detail: string }>("POST", "/settings/api-key/test", { key: key || null }),
  setVoice: (piper_voice: string) => req<Settings>("PUT", "/settings/preferences", { piper_voice }),
  setAlarmVoice: (style: "female" | "male", voice: string) =>
    req<Settings>("PUT", "/settings/preferences", { [`alarm_voice_${style}`]: voice }),
  wakeScript: (title: string, note = "") =>
    req<{ script: string; words: number; seconds: number }>("POST", "/alarms/script", { title, note }),
  preloadStt: () => req<Settings>("POST", "/speech/preload"),
  gpuPack: () => req<GpuPack>("GET", "/settings/gpu-pack"),
  installGpuPack: () => req<GpuPack>("POST", "/settings/gpu-pack"),
  removeGpuPack: () => req<GpuPack>("DELETE", "/settings/gpu-pack"),
  restartApp: () => req<{ restarting: boolean }>("POST", "/app/restart"),
  sayOnDevice: (text: string) => req<{ played_on_device: boolean }>("POST", "/speech/say", { text }),
  sayWavUrl: (text: string, voice?: string | null) =>
    `${BASE}/speech/say.wav?text=${encodeURIComponent(text)}${voice ? `&voice=${encodeURIComponent(voice)}` : ""}`,
  kimiModels: () => req<{ models: string[]; active: string | null; pinned: string | null }>("GET", "/settings/kimi-models"),
  setKimiModel: (model: string) => req<{ models: string[]; active: string | null; pinned: string | null }>("PUT", "/settings/kimi-model", { model }),
  weather: () => req<WeatherInfo>("GET", "/weather"),
  weatherSearch: (q: string) => req<Place[]>("GET", `/weather/search?q=${encodeURIComponent(q)}`),
  setWeatherLocation: (p: Place) => req<WeatherInfo>("PUT", "/weather/location", p),
  dismissError: () => req<unknown>("POST", "/error/dismiss"),
  // meetings
  meetings: () => req<MeetingList>("GET", "/meetings"),
  meeting: (id: string) => req<MeetingDetail>("GET", `/meetings/${id}`),
  patchMeeting: (id: string, body: { title?: string; notes?: string }) => req<unknown>("PATCH", `/meetings/${id}`, body),
  deleteMeeting: (id: string) => req<unknown>("DELETE", `/meetings/${id}`),
  renameSpeaker: (id: string, key: string, name: string, remember: boolean) =>
    req<unknown>("PUT", `/meetings/${id}/speakers/${key}`, { name, remember }),
  addSpeaker: (id: string, name?: string) => req<{ key: string }>("POST", `/meetings/${id}/speakers`, { name: name || null }),
  mergeSpeaker: (id: string, key: string, into: string) => req<unknown>("POST", `/meetings/${id}/speakers/${key}/merge`, { into }),
  patchSegment: (id: string, seg: number, body: { speaker_key?: string; text?: string }) =>
    req<unknown>("PATCH", `/meetings/${id}/segments/${seg}`, body),
  rediarize: (id: string, num_speakers: number | null) =>
    req<{ speakers: Speaker[] }>("POST", `/meetings/${id}/rediarize`, { num_speakers }),
  retryMeeting: (id: string) => req<unknown>("POST", `/meetings/${id}/retry`),
  summarizeMeeting: (id: string, engine: "local" | "kimi") =>
    req<MeetingSummary | { queued: boolean }>("POST", `/meetings/${id}/summarize?engine=${engine}`),
  searchMeetings: (q: string) => req<{ hits: MeetingHit[] }>("GET", `/meetings/search?q=${encodeURIComponent(q)}`),
  askMeetings: (question: string, engine: "local" | "kimi") => req<MeetingAnswer>("POST", "/meetings/ask", { question, engine }),
  meetingGraph: (archived = false) => req<MeetingGraph>("GET", `/meetings/graph${archived ? "?archived=true" : ""}`),
  meetingActions: () => req<{ items: MeetingActionRow[] }>("GET", "/meetings/actions"),
  syncVault: () => req<{ written: number }>("POST", "/meetings/vault/sync"),
  cleanTranscripts: () => req<{ lines_changed: number; lines_removed: number }>("POST", "/meetings/clean-transcripts"),
  meetingSettings: () => req<MeetingSettings>("GET", "/settings/meetings"),
  setMeetingSettings: (body: { summary_mode?: string; local_ai_model?: string; obsidian_vault?: string; obsidian_folder?: string;
    summary_quality?: string; my_name?: string; speech_model?: string; transcript_cleanup?: boolean }) =>
    req<MeetingSettings>("PUT", "/settings/meetings", body),
  localModels: () => req<LocalModels>("GET", "/settings/local-ai/models"),
  pullLocalModel: (model: string, use: boolean) => req<LocalModels>("POST", "/settings/local-ai/pull", { model, use }),
  removeLocalModel: (name: string) => req<LocalModels>("DELETE", `/settings/local-ai/models?name=${encodeURIComponent(name)}`),
  parkMeetingActions: (id: string, indexes?: number[]) =>
    req<{ parked_ids: string[] }>("POST", `/meetings/${id}/park-actions`, indexes ? { indexes } : undefined),
  patchAction: (id: string, index: number, body: { task?: string; owner?: string; due_date?: string; due_time?: string;
    status?: "new" | "dismissed"; done?: boolean }) => req<unknown>("PATCH", `/meetings/${id}/actions/${index}`, body),
  convertActions: (id: string, items: { index: number; as: "task" | "reminder" | "park"; date?: string; time?: string }[]) =>
    req<{ made: { index: number; as: string; id: string }[] }>("POST", `/meetings/${id}/actions/convert`, { items }),
  archiveMeeting: (id: string, archived: boolean) => req<unknown>("POST", `/meetings/${id}/archive`, { archived }),
  meetingExportUrl: (id: string, format: "md" | "txt" | "srt" | "json") => `${BASE}/meetings/${id}/export?format=${format}`,
  meetingAudioUrl: (id: string, download = false) => `${BASE}/meetings/${id}/audio${download ? "?download=true" : ""}`,
  importMeeting: async (file: File, title: string): Promise<{ id: string }> => {
    const res = await fetch(`${BASE}/meetings/import?filename=${encodeURIComponent(file.name)}&title=${encodeURIComponent(title)}`,
      { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail; } catch { /* non-JSON */ }
      throw new ApiError(res.status, String(detail));
    }
    return (await res.json()) as { id: string };
  },
  voices: () => req<VoiceProfile[]>("GET", "/voices"),
  vocabulary: () => req<{ words: string[] }>("GET", "/settings/vocabulary"),
  setVocabulary: (words: string[]) => req<{ words: string[] }>("PUT", "/settings/vocabulary", { words }),
  forgetVoice: (id: string) => req<unknown>("DELETE", `/voices/${id}`),
  exportDiagnostics: () => req<Record<string, unknown>>("GET", "/diagnostics/export"),
};
