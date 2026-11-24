import { Sparkles } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useLive } from "../api/live";
import { Button } from "./ui/button";
import { Input } from "./ui/primitives";

/** Quick brain dump: plans + commits immediately unless a time needs confirming. Form text survives disconnects. */
export function BrainDumpBar() {
  const { run, health } = useLive();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const nav = useNavigate();
  const submit = async () => {
    if (!text.trim()) return;
    setBusy(true);
    const r = await run(() => api.plan(text.trim(), true));
    setBusy(false);
    if (r) {
      setNote(r.plan.summary || "Planned.");
      setText("");
    }
  };
  return (
    <form className="rounded-[var(--radius-card)] border border-line bg-white/80 p-3" aria-label="Quick brain dump"
      onSubmit={(e) => { e.preventDefault(); void submit(); }}>
      <div className="flex flex-col gap-2 sm:flex-row">
        <label htmlFor="brain-dump-input" className="sr-only">Brain dump</label>
        <Input id="brain-dump-input" value={text} onChange={(e) => setText(e.target.value)} aria-keyshortcuts="N"
          placeholder="Dump it here… e.g. “Finish Q3 report, also call the dentist, alarm at 3pm”" />
        <div className="flex gap-2">
          <Button type="submit" variant="amber" disabled={busy || !text.trim()}>
            <Sparkles size={16} aria-hidden /> {busy ? "Planning…" : "Plan it"}</Button>
          <Button onClick={() => nav("/voice", { state: { text } })} disabled={!text.trim()}>Review first</Button>
        </div>
      </div>
      <p className="mt-2 px-1 text-xs text-muted" aria-live="polite">
        {note ?? `Planner: ${health?.planner_mode === "KIMI" ? "Kimi (cloud)" : "Local Rule Engine (offline)"}`}</p>
    </form>
  );
}
