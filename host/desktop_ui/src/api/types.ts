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

export interface Parked { id: string; title: string; source_text: string | null; status: string; created_at: string }
export interface Reminder { id: string; title: string; due_utc: string; timezone: string; done: number }

export interface Alarm {
  id: string; task_id: string | null; title: string; schedule_kind: "ONCE" | "RECURRING"; fire_utc: string | null;
  rrule_days: string | null; local_hhmm: string; timezone: string; audio_mode: "WAV" | "TTS" | "CHIME";
  audio_path: string | null; tts_script: string | null; snooze_min: number; enabled: number;
  ack_state: string; last_fired_utc: string | null;
}

export interface TimerInfo { state: "STOPPED" | "RUNNING" | "PAUSED"; remaining_ms: number; total_ms: number; started: boolean }

export interface FullState {
  revision: number; ui_state: UiState; page: "FOCUS" | "AGENDA"; active_task: Task | null;
  active_step_id: string | null; timer: TimerInfo; break_remaining_ms: number; tasks: Task[]; parked: Parked[];
  reminders: Reminder[]; alarms: Alarm[]; ringing: { id: string; title: string; hhmm: string; test?: boolean; expires_at_ms?: number | null } | null;
  pending_confirmation: { question: string; items: ScheduledItem[] } | null; done_title: string; timezone: string;
  device: { transport: string; linked: boolean; telemetry: Record<string, unknown>; heartbeat: Record<string, unknown> };
  voice: { status: string; transcript?: string; error?: string; planner_mode?: string };
}

export interface Health {
  status: string; device_transport: "SIMULATOR" | "USB_HARDWARE" | "DISCONNECTED";
  link_state: "TETHERED" | "STANDALONE"; planner_mode: "KIMI" | "LOCAL_RULE"; stt_mode: string; tts_mode: string;
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
}
