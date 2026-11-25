// Typed mirror of the host service JSON contracts (host/service/api/*).

export type UiState =
  | "IDLE_READY" | "LISTENING" | "TRANSCRIBING" | "THINKING" | "RUNNING" | "PAUSED" | "BREAK"
  | "STEP_DONE" | "ALARM_RINGING" | "NEEDS_CONFIRMATION" | "SLEEP" | "ERROR_RECOVERABLE";

export interface Step {
  id: string; task_id: string; position: number; title: string; duration_min: number;
  is_starter: number; remaining_sec: number; status: "PENDING" | "ACTIVE" | "COMPLETED"; completed_at: string | null;
}

export interface Task {
  id: string; title: string; status: "ACTIVE" | "SCHEDULED" | "COMPLETED" | "ARCHIVED"; target_date: string;
  timezone: string; if_then_cue: string | null; priority: number; revision: number; steps: Step[];
  start_hhmm: string | null;
}

export interface Parked {
  id: string; title: string; source_text: string | null; status: string; created_at: string;
  task_id?: string | null; // a parked task that kept its steps (resumes where it stopped)
}

export type MeetingStatus = "RECORDING" | "QUEUED" | "TRANSCRIBING" | "READY" | "FAILED";
export interface Speaker { key: string; name: string; profile_id: string | null; auto: boolean; segments: number; talk_s: number }
export interface Segment { id: number; idx: number; start_s: number; end_s: number; text: string; speaker_key: string }
export interface MeetingSummary {
  title: string; summary: string; decisions: string[];
  action_items: { task: string; owner: string | null; due: string | null }[];
}
export interface Meeting {
  id: string; title: string; started_at: string; ended_at: string | null; duration_s: number; timezone: string;
  status: MeetingStatus; source: "DEVICE" | "IMPORT"; progress: number; error: string | null; notes: string | null;
  gaps_s: number;
}
export interface MeetingListItem extends Meeting { has_summary: boolean; speaker_names: string[]; segment_count: number }
export interface MeetingList {
  meetings: MeetingListItem[];
  status: { stt: string; busy: string; queued: number; recording: { id: string; recorded_s: number }[] };
}
export interface MeetingDetail extends Meeting { speakers: Speaker[]; segments: Segment[]; summary: MeetingSummary | null }
export interface VoiceProfile { id: string; name: string; samples: number; updated_at: string }
export interface Reminder { id: string; title: string; due_utc: string; timezone: string; done: number }

export interface Alarm {
  id: string; task_id: string | null; title: string; schedule_kind: "ONCE" | "RECURRING"; fire_utc: string | null;
  rrule_days: string | null; local_hhmm: string; timezone: string; audio_mode: "WAV" | "TTS" | "CHIME";
  audio_path: string | null; tts_script: string | null; snooze_min: number; enabled: number;
  ack_state: string; last_fired_utc: string | null; voice: string | null;
}

export interface TimerInfo { state: "STOPPED" | "RUNNING" | "PAUSED"; remaining_ms: number; total_ms: number; started: boolean }

export interface FullState {
  revision: number; ui_state: UiState; page: "FOCUS" | "AGENDA"; active_task: Task | null;
  active_step_id: string | null; timer: TimerInfo; break_remaining_ms: number; tasks: Task[]; parked: Parked[];
  reminders: Reminder[]; alarms: Alarm[]; ringing: { id: string; title: string; hhmm: string; test?: boolean; expires_at_ms?: number | null } | null;
  pending_confirmation: { question: string; items: ScheduledItem[] } | null; done_title: string; timezone: string;
  device: { transport: string; linked: boolean; telemetry: Record<string, unknown>; heartbeat: Record<string, unknown> };
  voice: { status: string; transcript?: string; error?: string; planner_mode?: string };
  error: { title: string; text: string; at: string } | null;
  ack: { id: number; text: string } | null;
  weather: { out_temp_c10?: number; out_hum?: number; out_code?: number; place?: string; updated?: string };
}

export interface Health {
  status: string; device_transport: "SIMULATOR" | "USB_HARDWARE" | "DISCONNECTED";
  link_state: "TETHERED" | "STANDALONE"; planner_mode: "KIMI" | "AI_NOT_CONFIGURED"; stt_mode: string; tts_mode: string;
  revision: number;
}

export interface PlanStep { title: string; duration_min: number; is_starter: boolean }
export interface ScheduledItem {
  kind: "REMINDER" | "ALARM" | "TASK"; title: string; when_text: string; due_local: string | null; needs_confirmation: boolean;
}
export interface Plan {
  version: 1; intent: string;
  active_task: { title: string; steps: PlanStep[]; if_then_cue: string | null } | null;
  scheduled: ScheduledItem[]; parked: { title: string; source_text: string }[];
  control: { action: string } | null; clarification_question: string | null; needs_confirmation: boolean; summary: string;
}

export interface PlanResult {
  voice_session_id: string; transcript: string; planner_mode: string; plan: Plan; committed: unknown;
}

export interface CalItem {
  id: string; title: string; hhmm: string; kind: number; done: boolean; active: boolean;
  duration_min: number; recurring?: boolean;
}
export interface DayItems { date: string; items: CalItem[] }

export interface VoiceSession {
  id: string; status: string; transcript: string; planner_mode: string; raw_json: string;
  needs_confirmation: number; created_at: string;
}

export interface Settings {
  planner_mode: string; kimi_model: string | null; stt: string; tts: string; timezone: string;
  transport_setting: string; host_port: number; privacy: string; missed_alarms: string[];
  api_key: { configured: boolean; source: "env" | "keyring" | "none"; hint: string; editable: boolean };
  stt_ready: boolean; stt_loading: boolean; tts_enabled: boolean; piper_voice: string | null; voices: string[];
  alarm_voice_female: string | null; alarm_voice_male: string | null;
}

export interface AiUsageDay {
  date: string; calls: number; prompt_tokens: number; cached_tokens: number; completion_tokens: number; cost_usd: number;
}
export interface AiUsage {
  days: AiUsageDay[]; today: AiUsageDay; active_model: string | null;
  month: { calls: number; prompt_tokens: number; completion_tokens: number; cost_usd: number; by_model: { model: string; calls: number; cost: number }[] };
  cap_usd: number | null; cap_used: number | null; cap_state: "OK" | "WARN" | "REACHED";
  prices: Record<string, { input: number; cached: number; output: number }>;
}

export interface NetworkInfo {
  linked: boolean; via: string; paired_on_pc: boolean; known_hosts: string[];
  wifi: { configured?: boolean; paired?: boolean; state?: string; ssid?: string; ip?: string; host?: string; rssi?: number; client?: boolean };
}
export interface FirmwareImage { version?: string; project?: string; date?: string; time?: string; size?: number; error?: string }
export interface FirmwareInfo {
  device: { version: string | null; ota: { slot?: string; built?: string; last?: string; progress?: number } };
  linked: boolean; via: string; available: { build?: FirmwareImage; upload?: FirmwareImage };
  status: { state: "IDLE" | "SENDING" | "REBOOTING" | "DONE" | "FAILED"; progress: number; message: string };
}
export interface WakeInfo {
  enabled: boolean; word: string; words: Record<string, string>;
  device: { enabled?: boolean; ready?: boolean; word?: string; hits?: number; words?: string[] };
}

export type Activity = "BRAIN_DUMP" | "CALENDAR" | "FOCUS" | "ALARMS";
export interface Place { name: string; admin1: string; country: string; latitude: number; longitude: number }
export interface WeatherInfo {
  out_temp_c10?: number; out_hum?: number; out_code?: number; place?: string; updated?: string;
  location: Partial<Place>; error: string;
}
