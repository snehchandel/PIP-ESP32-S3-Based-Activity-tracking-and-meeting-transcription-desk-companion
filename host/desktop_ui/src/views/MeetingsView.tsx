import { CircleCheck, CircleParking, Cpu, Download, Loader2, Pencil, RefreshCw, Search, Sparkles, Trash2, Upload, UserPlus, Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { useLive } from "../api/live";
import type { MeetingAnswer, MeetingDetail, MeetingHit, MeetingList, MeetingListItem, Segment, Speaker } from "../api/types";
import { Button } from "../components/ui/button";
import { Dialog } from "../components/ui/dialog";
import { Badge, Card, CardTitle, Empty, Input, Label, PageHeader, Select, Textarea } from "../components/ui/primitives";
import { cn } from "../lib/utils";

/* Meetings recorded on PIP ("Meeting" in the voice menu) or imported: transcribed on this PC with speakers told
   apart. Speakers PIP doesn't know yet are "Speaker 01, 02..." - name them once and PIP remembers the voice. */

const SPEAKER_COLORS = ["#2563eb", "#d97706", "#059669", "#9333ea", "#dc2626", "#0891b2", "#65a30d", "#db2777"];
const color = (key: string) => SPEAKER_COLORS[(Number(key.slice(1)) - 1 + SPEAKER_COLORS.length) % SPEAKER_COLORS.length];

function clock(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  const mmss = `${String(Math.floor(s / 60) % 60).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  return s >= 3600 ? `${Math.floor(s / 3600)}:${mmss}` : mmss;
}

function when(m: { started_at: string; ended_at: string | null }): string {
  const a = new Date(m.started_at);
  const day = a.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric", year: "numeric" });
  const t = (d: Date) => d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return `${day} · ${t(a)}${m.ended_at ? `–${t(new Date(m.ended_at))}` : ""}`;
}

function StatusBadge({ m }: { m: { status: string; progress: number } }) {
  if (m.status === "RECORDING") return <Badge tone="amber"><span className="h-2 w-2 animate-pulse rounded-full bg-[#c0392b]" />Recording</Badge>;
  if (m.status === "TRANSCRIBING") return <Badge tone="amber"><Loader2 size={11} className="animate-spin" aria-hidden />Transcribing {Math.round(m.progress * 100)}%</Badge>;
  if (m.status === "QUEUED") return <Badge>Waiting to transcribe</Badge>;
  if (m.status === "FAILED") return <Badge className="border-[#e7c2b8] bg-[#fbeee9] text-[#8a3b2e]">Failed</Badge>;
  return <Badge tone="sage">Ready</Badge>;
}

function ImportButton({ onDone }: { onDone: (id: string) => void }) {
  const { run } = useLive();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  return (
    <>
      <input ref={input} type="file" accept="audio/*,video/*,.m4a,.mp3,.wav,.ogg,.flac,.webm" className="hidden"
        aria-label="Audio file to transcribe" onChange={async (e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (!f) return;
          setBusy(true);
          const r = await run(() => api.importMeeting(f, f.name.replace(/\.[^.]+$/, "")));
          setBusy(false);
          if (r) onDone(r.id);
        }} />
      <Button size="sm" disabled={busy} onClick={() => input.current?.click()}>
        {busy ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <Upload size={14} aria-hidden />} Import audio</Button>
    </>
  );
}

function SpeakerRow({ m, sp, others, reload }: { m: MeetingDetail; sp: Speaker; others: Speaker[]; reload: () => void }) {
  const { run } = useLive();
  const [name, setName] = useState(sp.name);
  const [remember, setRemember] = useState(true);
  const dirty = name.trim() && name.trim() !== sp.name;
  const save = async () => {
    if (!dirty) return;
    await run(() => api.renameSpeaker(m.id, sp.key, name.trim(), remember));
    reload();
  };
  return (
    <li className="rounded-xl border border-line bg-white/60 p-2.5">
      <div className="flex items-center gap-2">
        <span className="h-3 w-3 shrink-0 rounded-full" style={{ background: color(sp.key) }} aria-hidden />
        <Input aria-label={`Name for ${sp.name}`} value={name} className="h-8" onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void save(); }} />
        <Button size="sm" variant={dirty ? "primary" : "outline"} disabled={!dirty} onClick={() => void save()}>Save</Button>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 pl-5 text-xs text-muted">
        <span className="tabular">{sp.segments} lines · {clock(sp.talk_s)}</span>
        {sp.auto && <Badge tone="sage" title="Named from a voice PIP remembers">recognised</Badge>}
        {dirty && <label className="flex items-center gap-1"><input type="checkbox" checked={remember}
          onChange={(e) => setRemember(e.target.checked)} /> Remember this voice</label>}
        {others.length > 0 && (
          <Select aria-label={`Merge ${sp.name} into another speaker`} className="ml-auto h-7 w-auto py-0 text-xs" value=""
            onChange={async (e) => {
              if (!e.target.value) return;
              await run(() => api.mergeSpeaker(m.id, sp.key, e.target.value));
              reload();
            }}>
            <option value="">Same person as…</option>
            {others.map((o) => <option key={o.key} value={o.key}>{o.name}</option>)}
          </Select>
        )}
      </div>
    </li>
  );
}

function SegmentRow({ m, seg, speakers, playing, onSeek, reload }: {
  m: MeetingDetail; seg: Segment; speakers: Speaker[]; playing: boolean; onSeek: (t: number) => void; reload: () => void;
}) {
  const { run } = useLive();
  const [edit, setEdit] = useState(false);
  const [text, setText] = useState(seg.text);
  const save = async () => {
    setEdit(false);
    if (text.trim() && text.trim() !== seg.text) {
      await run(() => api.patchSegment(m.id, seg.id, { text: text.trim() }));
      reload();
    }
  };
  return (
    <li className={cn("group grid grid-cols-[52px_150px_minmax(0,1fr)] items-start gap-2 rounded-lg px-2 py-1.5",
      playing ? "bg-amber-soft/60" : "hover:bg-paper-2/60")} data-testid="segment">
      <button className="tabular pt-1 text-left text-xs font-semibold text-muted hover:text-ink" onClick={() => onSeek(seg.start_s)}
        aria-label={`Play from ${clock(seg.start_s)}`}>{clock(seg.start_s)}</button>
      <select aria-label="Speaker of this line" value={seg.speaker_key}
        className="h-7 rounded-lg border border-transparent bg-transparent px-1 text-sm font-bold hover:border-line focus:border-amber"
        style={{ color: color(seg.speaker_key) }} onChange={async (e) => {
          await run(() => api.patchSegment(m.id, seg.id, { speaker_key: e.target.value }));
          reload();
        }}>
        {speakers.map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}
      </select>
      {edit ? (
        <Textarea autoFocus value={text} className="min-h-16" onChange={(e) => setText(e.target.value)} onBlur={() => void save()}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void save(); } }} />
      ) : (
        <p className="flex gap-1 pt-0.5 text-sm leading-relaxed">
          <span className="flex-1">{seg.text}</span>
          <button className="h-6 shrink-0 rounded p-1 text-muted opacity-0 hover:text-ink group-hover:opacity-100 focus:opacity-100"
            aria-label="Edit this line" onClick={() => setEdit(true)}><Pencil size={13} /></button>
        </p>
      )}
    </li>
  );
}

function MeetingPanel({ id, onDeleted }: { id: string; onDeleted: () => void }) {
  const { run, meetingEvt } = useLive();
  const [data, setM] = useState<MeetingDetail | null>(null);
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [query, setQuery] = useState("");
  const [now, setNow] = useState(0);
  const [count, setCount] = useState("auto");
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const audio = useRef<HTMLAudioElement>(null);

  const reload = useCallback(() => {
    void api.meeting(id).then((d) => { setM(d); setTitle(d.title); setNotes(d.notes ?? ""); }).catch(() => setM(null));
  }, [id]);
  useEffect(() => { reload(); }, [reload]);
  const liveProgress = meetingEvt.id === id && meetingEvt.status === "TRANSCRIBING" && meetingEvt.progress !== undefined;
  useEffect(() => { // refetch when this meeting changes state (progress ticks are shown from the event itself)
    if (meetingEvt.id === id && !liveProgress) reload();
  }, [meetingEvt, id, liveProgress, reload]);

  const segments = useMemo(() => {
    const q = query.trim().toLowerCase();
    const names = Object.fromEntries((data?.speakers ?? []).map((s) => [s.key, s.name.toLowerCase()]));
    return (data?.segments ?? []).filter((s) => !q || s.text.toLowerCase().includes(q) || names[s.speaker_key]?.includes(q));
  }, [data, query]);

  if (!data) return <Card><Empty>Loading…</Empty></Card>;
  const m: MeetingDetail = liveProgress ? { ...data, status: "TRANSCRIBING", progress: meetingEvt.progress ?? data.progress } : data;
  const seek = (t: number) => {
    if (!audio.current) return;
    audio.current.currentTime = t;
    void audio.current.play();
  };
  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    await run(fn);
    setBusy(null);
    reload();
  };
  const ready = m.status === "READY";
  const summarizing = m.summary_status === "QUEUED" || m.summary_status === "SUMMARIZING";
  const part = meetingEvt.id === id && meetingEvt.summary_parts
    ? { part: meetingEvt.summary_part ?? 0, parts: meetingEvt.summary_parts } : null;
  return (
    <div className="min-w-0 space-y-5">
      <Card aria-label="Meeting">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <Input aria-label="Meeting title" value={title} className="h-auto border-transparent bg-transparent px-1 py-0.5 text-xl font-extrabold
              tracking-tight hover:border-line" onChange={(e) => setTitle(e.target.value)}
              onBlur={() => { if (title.trim() && title !== m.title) void act("title", () => api.patchMeeting(m.id, { title: title.trim() })); }} />
            <p className="mt-1 px-1 text-sm text-muted">{when(m)} · <span className="tabular">{clock(m.duration_s)}</span>
              {m.source === "IMPORT" ? " · imported" : " · recorded on PIP"}
              {m.gaps_s > 0 && ` · ${Math.round(m.gaps_s)} s lost to link drops`}</p>
          </div>
          <StatusBadge m={m} />
        </div>
        {m.status === "TRANSCRIBING" && (
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-paper-2" role="progressbar" aria-label="Transcription progress"
            aria-valuenow={Math.round(m.progress * 100)} aria-valuemin={0} aria-valuemax={100}>
            <div className="h-full rounded-full bg-amber transition-[width] duration-700" style={{ width: `${m.progress * 100}%` }} />
          </div>
        )}
        {m.status === "FAILED" && (
          <p className="mt-3 flex items-center gap-3 text-sm text-[#8a3b2e]">{m.error}
            <Button size="sm" onClick={() => void act("retry", () => api.retryMeeting(m.id))}>Try again</Button></p>
        )}
        {m.status !== "RECORDING" && (
          <audio ref={audio} controls preload="metadata" className="mt-4 w-full" src={api.meetingAudioUrl(m.id)}
            onTimeUpdate={(e) => setNow(e.currentTarget.currentTime)} aria-label="Meeting recording" />
        )}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted">Export</span>
          {(["md", "txt", "srt", "json"] as const).map((f) => (
            <Button key={f} size="sm" asChild={ready} disabled={!ready}>
              {ready ? <a href={api.meetingExportUrl(m.id, f)} download>{f === "md" ? "Markdown" : f.toUpperCase()}</a>
                : <span>{f.toUpperCase()}</span>}
            </Button>
          ))}
          {m.status !== "RECORDING" && <Button size="sm" asChild><a href={api.meetingAudioUrl(m.id, true)} download>
            <Download size={14} aria-hidden /> Audio</a></Button>}
          <Button size="sm" variant="danger" className="ml-auto" disabled={m.status === "RECORDING"}
            onClick={() => setConfirmDelete(true)}><Trash2 size={14} aria-hidden /> Delete</Button>
        </div>
      </Card>

      {ready && (
        <div className="grid gap-5 xl:grid-cols-2">
          <Card aria-label="Speakers">
            <CardTitle aside={<Button size="sm" variant="ghost" onClick={() => void act("add", () => api.addSpeaker(m.id))}>
              <UserPlus size={14} aria-hidden /> Add</Button>}>Speakers</CardTitle>
            <p className="mb-3 text-xs text-muted">Name a speaker once and PIP recognises that voice in later meetings.
              Wrong line? Change its speaker in the transcript.</p>
            <ul className="space-y-2">
              {m.speakers.map((sp) => <SpeakerRow key={`${sp.key}:${sp.name}`} m={m} sp={sp} reload={reload}
                others={m.speakers.filter((o) => o.key !== sp.key)} />)}
            </ul>
            <div className="mt-3 flex items-center gap-2 border-t border-line pt-3">
              <Label htmlFor="spk-count" className="mb-0 normal-case">People in the meeting</Label>
              <Select id="spk-count" value={count} onChange={(e) => setCount(e.target.value)} className="h-8 w-24 py-0">
                <option value="auto">Auto</option>
                {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
              <Button size="sm" disabled={busy !== null} title="Re-run speaker detection (keeps the words)"
                onClick={() => void act("redo", () => api.rediarize(m.id, count === "auto" ? null : Number(count)))}>
                {busy === "redo" ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <RefreshCw size={14} aria-hidden />}
                Detect again</Button>
            </div>
          </Card>
          <Card aria-label="Summary">
            <CardTitle aside={<div className="flex gap-1.5">
              <Button size="sm" disabled={busy !== null || summarizing} title="Summarise on this PC (free, private)"
                onClick={() => void act("sum", () => api.summarizeMeeting(m.id, "local"))}>
                <Cpu size={14} aria-hidden /> {m.summary ? "Redo on this PC" : "Summarise on this PC"}</Button>
              <Button size="sm" variant="ghost" disabled={busy !== null || summarizing} title="Uses your AI budget"
                onClick={() => void act("kimi", () => api.summarizeMeeting(m.id, "kimi"))}>
                {busy === "kimi" ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <Sparkles size={14} aria-hidden />}
                Kimi</Button></div>}>Summary</CardTitle>
            {summarizing && (
              <p role="status" className="mb-3 flex items-center gap-2 text-sm text-muted">
                <Loader2 size={14} className="animate-spin" aria-hidden />
                {m.summary_status === "QUEUED" ? "Waiting its turn (transcriptions and voice commands go first)…"
                  : part ? `Summarising on this PC — part ${Math.min(part.part + 1, part.parts)} of ${part.parts}…`
                    : "Summarising…"}</p>
            )}
            {m.summary_status === "FAILED" && m.summary_error && (
              <p className="mb-3 text-sm text-[#8a3b2e]">Summary failed: {m.summary_error}</p>
            )}
            {m.summary ? (
              <div className="space-y-3 text-sm">
                <p className="leading-relaxed">{m.summary.summary}</p>
                {(m.summary.topics?.length ?? 0) > 0 && <div className="flex flex-wrap gap-1.5">
                  {m.summary.topics?.map((t) => <Badge key={t}>{t}</Badge>)}</div>}
                {m.summary.decisions.length > 0 && (<div><Label>Decisions</Label>
                  <ul className="list-disc space-y-0.5 pl-5">{m.summary.decisions.map((d, i) => <li key={i}>{d}</li>)}</ul></div>)}
                {m.summary.action_items.length > 0 && (<div><Label>Action items</Label>
                  <ul className="space-y-1">{m.summary.action_items.map((a, i) => (
                    <li key={i} className={cn("rounded-lg border border-line bg-white/60 px-2.5 py-1.5", a.done && "text-muted line-through")}>
                      {a.done && <CircleCheck size={13} className="mr-1 inline text-sage" aria-label="done" />}{a.task}
                      {(a.owner || a.due) && <span className="text-xs text-muted"> — {[a.owner, a.due && `due ${a.due}`].filter(Boolean).join(", ")}</span>}
                      {a.parked && <Badge className="ml-2">parked</Badge>}
                    </li>))}</ul>
                  <Button size="sm" className="mt-2" disabled={m.summary.action_items.every((a) => a.parked || a.done)}
                    onClick={() => void act("park", () => api.parkMeetingActions(m.id))}>
                    <CircleParking size={14} aria-hidden /> Park action items</Button></div>)}
                <p className="text-xs text-muted">Summary by {m.summary_engine?.startsWith("local/")
                  ? `this PC (${m.summary_engine.slice(6)})` : m.summary_engine ?? "AI"}
                  {m.vault_note && <> · in Obsidian: <span className="break-all">{m.vault_note}</span></>}</p>
              </div>
            ) : !summarizing && <Empty>Summaries are made on this PC after each transcription (Settings → Meetings).
              Kimi is there if you want a second opinion (uses your AI budget).</Empty>}
            <div className="mt-4">
              <Label htmlFor="mt-notes">Your notes</Label>
              <Textarea id="mt-notes" value={notes} placeholder="Anything to remember about this meeting…"
                onChange={(e) => setNotes(e.target.value)}
                onBlur={() => { if (notes !== (m.notes ?? "")) void act("notes", () => api.patchMeeting(m.id, { notes })); }} />
            </div>
          </Card>
        </div>
      )}

      {ready && (
        <Card aria-label="Transcript">
          <CardTitle aside={<Input aria-label="Search the transcript" placeholder="Search words or a speaker…" value={query}
            onChange={(e) => setQuery(e.target.value)} className="h-8 w-56" />}>Transcript</CardTitle>
          {m.segments.length === 0 ? <Empty>No speech was found in this recording.</Empty> : (
            <ol className="max-h-[70vh] space-y-0.5 overflow-y-auto pr-1">
              {segments.map((s) => <SegmentRow key={`${s.id}:${s.text}`} m={m} seg={s} speakers={m.speakers} reload={reload} onSeek={seek}
                playing={now > 0 && now >= s.start_s && now < s.end_s} />)}
            </ol>
          )}
        </Card>
      )}
      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete} title="Delete this meeting?"
        description="The recording and its transcript are removed from this PC. This can't be undone.">
        <div className="flex justify-end gap-2">
          <Button onClick={() => setConfirmDelete(false)}>Keep it</Button>
          <Button variant="danger" onClick={async () => {
            setConfirmDelete(false);
            await run(() => api.deleteMeeting(m.id));
            onDeleted();
          }}><Trash2 size={14} aria-hidden /> Delete</Button>
        </div>
      </Dialog>
    </div>
  );
}

/** Questions across every meeting: PIP finds the passages that match (no AI), then one short AI call answers
    from just those - local by default. Sources open the meeting. */
function AskCard({ onOpen }: { onOpen: (id: string) => void }) {
  const { run } = useLive();
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState<"" | "search" | "local" | "kimi">("");
  const [hits, setHits] = useState<MeetingHit[] | null>(null);
  const [answer, setAnswer] = useState<MeetingAnswer | null>(null);
  const ok = q.trim().length >= 3;
  const go = async (kind: "search" | "local" | "kimi") => {
    if (!ok) return;
    setBusy(kind);
    if (kind === "search") {
      const r = await run(() => api.searchMeetings(q.trim()));
      if (r) { setHits(r.hits); setAnswer(null); }
    } else {
      const r = await run(() => api.askMeetings(q.trim(), kind));
      if (r) { setAnswer(r); setHits(null); }
    }
    setBusy("");
  };
  return (
    <Card aria-label="Ask your meetings" className="mb-5">
      <CardTitle>Ask your meetings</CardTitle>
      <div className="flex flex-wrap gap-2">
        <Input aria-label="Question or words to find" className="min-w-64 flex-1" value={q}
          placeholder="Who is sending the Q3 budget? · What did we decide about hiring?"
          onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void go("local"); }} />
        <Button variant="primary" disabled={busy !== "" || !ok} onClick={() => void go("local")}>
          {busy === "local" ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <Cpu size={14} aria-hidden />} Ask</Button>
        <Button disabled={busy !== "" || !ok} onClick={() => void go("search")}>
          <Search size={14} aria-hidden /> Find</Button>
        <Button variant="ghost" disabled={busy !== "" || !ok} title="Ask Kimi instead (uses your AI budget)"
          onClick={() => void go("kimi")}>
          {busy === "kimi" ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <Sparkles size={14} aria-hidden />} Kimi</Button>
      </div>
      {answer && (
        <div className="mt-3 space-y-2 text-sm" role="status">
          <p className="whitespace-pre-line leading-relaxed">{answer.answer}</p>
          {answer.sources.length > 0 && <div className="flex flex-wrap gap-1.5">
            {answer.sources.map((s, i) => (
              <button key={i} className="rounded-full border border-line bg-white/60 px-2 py-0.5 text-xs hover:bg-white"
                onClick={() => onOpen(s.meeting_id)}>{s.title}{s.at && ` @ ${s.at}`}</button>))}</div>}
          <p className="text-xs text-muted">Answered by {answer.engine.startsWith("local/") ? "this PC" : answer.engine} from
            {" "}{answer.context_chars.toLocaleString()} characters of matching passages.</p>
        </div>
      )}
      {hits && (hits.length === 0 ? <p className="mt-3 text-sm text-muted">Nothing found.</p> : (
        <ul className="mt-3 max-h-72 space-y-1 overflow-y-auto">
          {hits.map((h, i) => (
            <li key={i}><button className="w-full rounded-lg px-2 py-1.5 text-left text-sm hover:bg-paper-2/60" onClick={() => onOpen(h.meeting_id)}>
              <span className="font-semibold">{h.title}</span> <span className="text-xs text-muted">{h.date}{h.at && ` @ ${h.at}`}
                {h.speaker && ` · ${h.speaker}`}{h.kind !== "turn" && ` · ${h.kind}`}</span>
              <span className="block text-muted">{highlight(h.snippet)}</span></button></li>))}
        </ul>
      ))}
    </Card>
  );
}

/** FTS snippets mark matches as **word**: show those parts bold (as React text, never as HTML). */
function highlight(snippet: string) {
  return snippet.split("**").map((part, i) => (i % 2 ? <b key={i}>{part}</b> : <span key={i}>{part}</span>));
}

export default function MeetingsView() {
  const { meetingEvt, run } = useLive();
  const [list, setList] = useState<MeetingList | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [voices, setVoices] = useState<{ id: string; name: string }[]>([]);
  const load = useCallback(() => {
    void api.meetings().then((l) => {
      setList(l);
      setSel((s) => (s && l.meetings.some((m) => m.id === s) ? s : l.meetings[0]?.id ?? null));
    }).catch(() => undefined);
    void api.voices().then(setVoices).catch(() => undefined);
  }, []);
  useEffect(() => { load(); }, [load]);
  const tick = meetingEvt.status === "TRANSCRIBING" && meetingEvt.progress !== undefined;
  useEffect(() => { // progress ticks update the badge in place (below); anything else refetches the list
    if (meetingEvt.n > 0 && !tick) load();
  }, [meetingEvt, tick, load]);

  const items: MeetingListItem[] = (list?.meetings ?? []).map((m) => (tick && m.id === meetingEvt.id
    ? { ...m, status: "TRANSCRIBING", progress: meetingEvt.progress ?? m.progress } : m));
  return (
    <>
      <PageHeader title="Meetings"
        subtitle="Hold KEY on PIP, pick Meeting, hold KEY again to record. Transcribed on this PC — nothing leaves it."
        actions={<ImportButton onDone={(id) => { setSel(id); load(); }} />} />
      <AskCard onOpen={setSel} />
      <div className="grid gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
        <div className="space-y-5">
          <Card aria-label="All meetings" className="p-3">
            {items.length === 0 ? <Empty>No meetings yet. On PIP: hold KEY, choose Meeting, then hold KEY to start.</Empty> : (
              <ul className="space-y-1.5">
                {items.map((m) => (
                  <li key={m.id}>
                    <button onClick={() => setSel(m.id)} aria-pressed={sel === m.id}
                      className={cn("w-full rounded-xl border px-3 py-2 text-left", sel === m.id ? "border-ink bg-white"
                        : "border-line bg-white/50 hover:bg-white")}>
                      <p className="truncate text-sm font-semibold">{m.title}</p>
                      <p className="text-xs text-muted">{when(m)} · <span className="tabular">{clock(m.duration_s)}</span></p>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5">
                        <StatusBadge m={m} />
                        {(m.summary_status === "QUEUED" || m.summary_status === "SUMMARIZING") &&
                          <Badge><Loader2 size={11} className="animate-spin" aria-hidden />Summarising</Badge>}
                        {m.speaker_names.length > 0 && <span className="flex items-center gap-1 truncate text-xs text-muted">
                          <Users size={11} aria-hidden /> {m.speaker_names.join(", ")}</span>}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {list && list.status.queued > 0 && <p className="mt-2 text-xs text-muted">{list.status.queued} waiting to be transcribed.</p>}
            {list && list.status.summaries_queued > 0 && <p className="mt-1 text-xs text-muted">
              {list.status.summaries_queued} summary(ies) on this PC in progress or waiting.</p>}
          </Card>
          <Card aria-label="Remembered voices" className="p-4">
            <CardTitle>Remembered voices</CardTitle>
            {voices.length === 0 ? <p className="text-xs text-muted">Name a speaker in a transcript and PIP learns their voice.</p> : (
              <ul className="space-y-1">
                {voices.map((v) => (
                  <li key={v.id} className="flex items-center justify-between gap-2 text-sm">
                    <span className="truncate">{v.name}</span>
                    <Button size="sm" variant="ghost" aria-label={`Forget ${v.name}'s voice`}
                      onClick={async () => { await run(() => api.forgetVoice(v.id)); load(); }}><Trash2 size={13} aria-hidden /> Forget</Button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        {sel ? <MeetingPanel key={sel} id={sel} onDeleted={() => { setSel(null); load(); }} />
          : <Card><Empty>Pick a meeting to review its transcript.</Empty></Card>}
      </div>
    </>
  );
}
