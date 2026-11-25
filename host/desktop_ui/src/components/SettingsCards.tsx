import { CheckCircle2, KeyRound, Loader2, Mic, Volume2, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { useLive } from "../api/live";
import type { Settings } from "../api/types";
import { Button } from "./ui/button";
import { Badge, Card, CardTitle, Input, Label, Select, Textarea } from "./ui/primitives";

function ModelPicker() {
  const { run } = useLive();
  const [m, setM] = useState<{ models: string[]; active: string | null; pinned: string | null } | null>(null);
  useEffect(() => { void api.kimiModels().then(setM).catch(() => undefined); }, []);
  if (!m) return null;
  return (
    <div className="mb-3">
      <Label htmlFor="kimi-model">Kimi model</Label>
      <Select id="kimi-model" value={m.pinned ?? ""} onChange={async (e) => {
        const r = await run(() => api.setKimiModel(e.target.value)); if (r) setM(r); }}>
        <option value="">Automatic (newest available{m.active && !m.pinned ? `: ${m.active}` : ""})</option>
        {m.models.map((x) => <option key={x} value={x}>{x}</option>)}
      </Select>
    </div>
  );
}

/** Kimi key: write-only. The page never receives the stored key, only whether it exists + last 4 chars. */
export function ApiKeyCard({ s, onChange }: { s: Settings; onChange: (s: Settings) => void }) {
  const { run } = useLive();
  const [key, setKey] = useState("");
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const k = s.api_key;
  const test = async (candidate?: string) => {
    setBusy(true);
    setResult((await run(() => api.testApiKey(candidate))) ?? null);
    setBusy(false);
  };
  const save = async () => {
    setBusy(true);
    const r = await run(() => api.saveApiKey(key.trim()));
    if (r) { onChange(r); setKey(""); setResult({ ok: true, detail: "Saved to Windows Credential Manager." }); }
    setBusy(false);
  };
  return (
    <Card aria-label="Kimi API key">
      <CardTitle aside={k.configured ? <Badge tone="sage">Kimi active · {k.hint}</Badge> : <Badge tone="amber">AI not set up</Badge>}>
        <span className="inline-flex items-center gap-2"><KeyRound size={16} aria-hidden /> Kimi (Moonshot) API key</span></CardTitle>
      <p className="mb-3 text-sm text-muted">
        PIP uses Kimi to break your brain dumps into steps. Without a working key PIP shows
        “AI has left the device” and keeps your words as a parked note. The key is stored in Windows Credential
        Manager — never in files or logs, and this page can't read it back.</p>
      {k.configured && <ModelPicker />}
      {k.source === "env" ? (
        <p className="rounded-xl bg-paper-2 p-3 text-sm">The key is set in the <code>.env</code> file, which takes priority.
          Remove <code>MOONSHOT_API_KEY</code> there to manage it here.</p>
      ) : (
        <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          <Label htmlFor="api-key">{k.configured ? "Replace key" : "Paste your key"}</Label>
          <Input id="api-key" type="password" autoComplete="off" spellCheck={false} placeholder="sk-…"
            value={key} onChange={(e) => setKey(e.target.value)} />
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary" disabled={busy || key.trim().length < 10}>Save key</Button>
            <Button disabled={busy || key.trim().length < 10} onClick={() => void test(key)}>Test this key</Button>
            {k.configured && <Button disabled={busy} onClick={() => void test()}>Test saved key</Button>}
            {k.configured && <Button variant="danger" disabled={busy} onClick={async () => {
              const r = await run(() => api.deleteApiKey());
              if (r) { onChange(r); setResult(null); }
            }}>Remove key</Button>}
          </div>
        </form>
      )}
      {busy && <p className="mt-2 flex items-center gap-2 text-sm text-muted"><Loader2 size={14} className="animate-spin" aria-hidden /> Working…</p>}
      {result && !busy && (
        <p role="status" className={`mt-2 flex items-center gap-2 text-sm ${result.ok ? "text-sage" : "text-[#8a3b2e]"}`}>
          {result.ok ? <CheckCircle2 size={15} aria-hidden /> : <XCircle size={15} aria-hidden />} {result.detail}</p>
      )}
    </Card>
  );
}

/** Names and acronyms the user says: Whisper gets them as hints, Kimi fixes near-misses ("castle" -> "CASL"). */
export function VocabularyCard() {
  const { run } = useLive();
  const [text, setText] = useState("");
  const [saved, setSaved] = useState("");
  useEffect(() => {
    void api.vocabulary().then((v) => { const t = v.words.join(", "); setText(t); setSaved(t); }).catch(() => undefined);
  }, []);
  const save = async () => {
    const r = await run(() => api.setVocabulary(text.split(/[,\n]/).map((w) => w.trim()).filter(Boolean)));
    if (r) { const t = r.words.join(", "); setText(t); setSaved(t); }
  };
  return (
    <Card aria-label="Words PIP should know">
      <CardTitle>Words PIP should know</CardTitle>
      <p className="mb-2 text-sm text-muted">Names, acronyms and jargon you say — e.g. <i>CASL, CST, Priya, Salesforce
        Marketing Cloud</i>. Speech-to-text hears them better and Kimi corrects near-misses.</p>
      <Textarea aria-label="Your words, separated by commas" value={text} placeholder="CASL, CST, Priya"
        onChange={(e) => setText(e.target.value)} className="min-h-20" />
      <div className="mt-2 flex justify-end">
        <Button size="sm" variant={text !== saved ? "primary" : "outline"} disabled={text === saved}
          onClick={() => void save()}>Save words</Button>
      </div>
    </Card>
  );
}

export function SpeechCard({ s, onChange }: { s: Settings; onChange: (s: Settings) => void }) {
  const { run, health } = useLive();
  const [text, setText] = useState("Hi, I'm PIP. Let's do one small thing.");
  const [note, setNote] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement>(null);
  useEffect(() => {  // poll while the speech model loads
    if (!s.stt_loading) return;
    const t = window.setInterval(() => void api.settings().then(onChange).catch(() => undefined), 1500);
    return () => window.clearInterval(t);
  }, [s.stt_loading, onChange]);
  const linked = health?.link_state === "TETHERED";
  return (
    <Card aria-label="Speech">
      <CardTitle><span className="inline-flex items-center gap-2"><Mic size={16} aria-hidden /> Voice</span></CardTitle>
      <dl className="mb-4 grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2 text-sm">
        <dt className="text-muted">Speech-to-text</dt>
        <dd className="flex flex-wrap items-center gap-2">
          <Badge tone={s.stt_ready ? "sage" : "neutral"}>{s.stt_ready ? "Ready" : s.stt_loading ? "Loading…" : "Not loaded"}</Badge>
          <span className="text-xs text-muted">{s.stt}</span>
          {!s.stt_ready && !s.stt_loading && <Button size="sm" onClick={async () => {
            const r = await run(() => api.preloadStt()); if (r) onChange(r); }}>Load now</Button>}
        </dd>
        <dt className="text-muted">Text-to-speech</dt>
        <dd><Badge tone={s.tts_enabled ? "sage" : "neutral"}>{s.tts_enabled ? "Piper" : "Chimes only"}</Badge>
          <span className="ml-2 text-xs text-muted">{s.tts}</span></dd>
      </dl>
      {s.voices.length > 0 && (
        <div className="mb-3"><Label htmlFor="voice-sel">Piper voice</Label>
          <Select id="voice-sel" value={s.piper_voice ?? ""} onChange={async (e) => {
            const r = await run(() => api.setVoice(e.target.value)); if (r) onChange(r); }}>
            {s.voices.map((v) => <option key={v} value={v}>{v}</option>)}</Select></div>
      )}
      {s.voices.length > 0 && (
        <div className="mb-3 grid grid-cols-2 gap-3">
          <div><Label htmlFor="alarm-voice-f">Wake-up voice (female)</Label>
            <Select id="alarm-voice-f" value={s.alarm_voice_female ?? ""} onChange={async (e) => {
              const r = await run(() => api.setAlarmVoice("female", e.target.value)); if (r) onChange(r); }}>
              {s.voices.map((v) => <option key={v} value={v}>{v}</option>)}</Select></div>
          <div><Label htmlFor="alarm-voice-m">Wake-up voice (male)</Label>
            <Select id="alarm-voice-m" value={s.alarm_voice_male ?? ""} onChange={async (e) => {
              const r = await run(() => api.setAlarmVoice("male", e.target.value)); if (r) onChange(r); }}>
              {s.voices.map((v) => <option key={v} value={v}>{v}</option>)}</Select></div>
        </div>
      )}
      <Label htmlFor="say-text">Try the voice</Label>
      <Input id="say-text" value={text} onChange={(e) => setText(e.target.value)} />
      <div className="mt-2 flex flex-wrap gap-2">
        <Button disabled={!s.tts_enabled || !text.trim()} onClick={() => {
          if (audio.current) { audio.current.src = api.sayWavUrl(text); void audio.current.play(); } }}>
          <Volume2 size={15} aria-hidden /> Play on this PC</Button>
        <Button variant="primary" disabled={!s.tts_enabled || !linked || !text.trim()} onClick={async () => {
          const r = await run(() => api.sayOnDevice(text));
          setNote(r?.played_on_device ? "Playing on PIP." : "PIP is not connected."); }}>
          <Volume2 size={15} aria-hidden /> Play on PIP</Button>
      </div>
      {note && <p role="status" className="mt-2 text-sm text-muted">{note}</p>}
      <audio ref={audio} className="hidden" />
      <p className="mt-3 text-xs text-muted">Alarms set to "Piper voice" speak their message on PIP after the chime.</p>
    </Card>
  );
}
