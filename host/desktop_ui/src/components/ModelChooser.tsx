import { Check, Download, Loader2, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { useLive } from "../api/live";
import type { LocalModelFit, LocalModels } from "../api/types";
import { cn } from "../lib/utils";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { Badge, Input, Label } from "./ui/primitives";

/* The local AI models to choose from: what each is good for, its download size, whether it fits this PC's GPU,
   and Download / Use / Remove. The user decides; PIP only marks a recommendation. */

const FIT: Record<LocalModelFit, { label: string; tone: "sage" | "amber" | "neutral"; title: string }> = {
  gpu: { label: "Fits your GPU", tone: "sage", title: "Runs fully on the graphics card: fast" },
  mixed: { label: "GPU + RAM, slower", tone: "amber", title: "Split between graphics card and memory: works, a few times slower" },
  cpu: { label: "CPU only, slow", tone: "amber", title: "No usable graphics card memory: runs from RAM, slowly" },
  too_big: { label: "Too big for this PC", tone: "neutral", title: "Not enough graphics or system memory" },
};

const stars = (n: number) => "●".repeat(n) + "○".repeat(5 - n);

export function ModelChooser({ running, onChanged }: { running: boolean; onChanged: () => void }) {
  const { run } = useLive();
  const [d, setD] = useState<LocalModels | null>(null);
  const [other, setOther] = useState("");
  const [showBig, setShowBig] = useState(false);
  const [remove, setRemove] = useState<string | null>(null);
  const load = useCallback(() => { void api.localModels().then(setD).catch(() => undefined); }, []);
  useEffect(() => { load(); }, [load, running]);
  const pulling = d?.pull.active ?? false;
  useEffect(() => {  // follow a download, then refresh the rest of the card
    if (!pulling) return;
    const t = window.setInterval(() => void api.localModels().then((r) => {
      setD(r);
      if (!r.pull.active) onChanged();
    }).catch(() => undefined), 1200);
    return () => window.clearInterval(t);
  }, [pulling, onChanged]);
  if (!d) return null;

  const use = async (name: string) => {
    const r = await run(() => api.setMeetingSettings({ local_ai_model: name }));
    if (r) { load(); onChanged(); }
  };
  const download = async (name: string) => {
    const r = await run(() => api.pullLocalModel(name, true));
    if (r) setD(r);
  };
  const hw = d.hardware;
  const rows = d.catalog.filter((c) => showBig || c.fit !== "too_big" || c.installed);
  const hidden = d.catalog.length - rows.length;
  const busyWith = d.pull.active ? d.pull.model : "";
  const rec = d.catalog.find((c) => c.recommended);
  return (
    <div className="mt-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Label className="mb-0">Model</Label>
        <span className="text-xs text-muted">This PC: {hw.gpu ? `${hw.gpu} (${hw.vram_gb} GB)` : "no NVIDIA GPU found"} · {hw.ram_gb} GB RAM</span>
      </div>
      {rec && !rec.installed && (
        <div className="mt-1.5 flex flex-wrap items-center gap-2 rounded-xl border border-sage/40 bg-white/70 p-2.5">
          <span className="text-sm">Recommended for this PC: <b>{rec.name}</b>
            <span className="text-xs text-muted"> · {rec.size_gb} GB · {FIT[rec.fit].label}</span></span>
          {busyWith === rec.name
            ? <span className="ml-auto flex items-center gap-1.5 text-xs text-muted"><Loader2 size={13} className="animate-spin" aria-hidden />
                {d.pull.percent ?? 0}%</span>
            : <Button size="sm" variant="primary" className="ml-auto" disabled={!running || pulling}
                title={!running ? "Install Ollama first" : undefined} onClick={() => void download(rec.name)}>
                <Download size={13} aria-hidden /> Download &amp; use</Button>}
        </div>
      )}
      <ul className="mt-1.5 max-h-96 space-y-1.5 overflow-y-auto pr-1" aria-label="Local AI models">
        {rows.map((c) => {
          const fit = FIT[c.fit];
          const downloading = busyWith === c.name;
          return (
            <li key={c.name} className={cn("rounded-xl border bg-white/70 p-2.5", c.in_use ? "border-ink" : "border-line",
              c.fit === "too_big" && !c.installed && "opacity-60")}>
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="font-semibold">{c.name}</span>
                <span className="text-xs text-muted">{c.family} {c.params} · {c.size_gb} GB</span>
                <span className="text-xs tracking-tight text-amber" title={`Summary quality ${c.quality} of 5`} aria-label={`quality ${c.quality} of 5`}>
                  {stars(c.quality)}</span>
                {c.recommended && <Badge tone="sage">Recommended</Badge>}
                {c.in_use && <Badge tone="sage"><Check size={11} aria-hidden /> In use</Badge>}
              </div>
              <p className="mt-0.5 text-xs text-muted">{c.note}</p>
              <div className="mt-1.5 flex flex-wrap items-center gap-2">
                <Badge tone={fit.tone} title={fit.title}>{fit.label}</Badge>
                {c.installed && <span className="text-xs text-muted">downloaded</span>}
                <span className="ml-auto flex gap-1.5">
                  {c.installed && !c.in_use && <>
                    <Button size="sm" onClick={() => void use(c.name)}>Use</Button>
                    <Button size="sm" variant="ghost" aria-label={`Remove ${c.name}`} onClick={() => setRemove(c.name)}>
                      <Trash2 size={13} aria-hidden /></Button></>}
                  {!c.installed && (downloading
                    ? <span className="flex items-center gap-1.5 text-xs text-muted" role="status">
                        <Loader2 size={13} className="animate-spin" aria-hidden />{d.pull.percent ?? 0}%</span>
                    : <Button size="sm" disabled={!running || pulling || c.fit === "too_big"}
                        title={!running ? "Install Ollama first" : c.fit === "too_big" ? "Not enough memory on this PC" : undefined}
                        onClick={() => void download(c.name)}><Download size={13} aria-hidden /> Download &amp; use</Button>)}
                </span>
              </div>
              {downloading && <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-paper-2" role="progressbar"
                aria-label={`Downloading ${c.name}`} aria-valuenow={d.pull.percent ?? 0} aria-valuemin={0} aria-valuemax={100}>
                <div className="h-full rounded-full bg-amber transition-[width]" style={{ width: `${d.pull.percent ?? 0}%` }} /></div>}
            </li>
          );
        })}
        {d.other_installed.map((o) => (
          <li key={o.name} className={cn("flex flex-wrap items-center gap-2 rounded-xl border bg-white/70 p-2.5",
            o.in_use ? "border-ink" : "border-line")}>
            <span className="font-semibold">{o.name}</span>
            <span className="text-xs text-muted">{o.size_gb} GB · downloaded (not in PIP's list)</span>
            {o.in_use && <Badge tone="sage"><Check size={11} aria-hidden /> In use</Badge>}
            <span className="ml-auto flex gap-1.5">
              {!o.in_use && <Button size="sm" onClick={() => void use(o.name)}>Use</Button>}
              {!o.in_use && <Button size="sm" variant="ghost" aria-label={`Remove ${o.name}`} onClick={() => setRemove(o.name)}>
                <Trash2 size={13} aria-hidden /></Button>}
            </span>
          </li>
        ))}
      </ul>
      {hidden > 0 && <button className="mt-1 text-xs font-semibold text-muted underline" onClick={() => setShowBig(true)}>
        Show {hidden} model(s) too big for this PC</button>}
      {d.pull.error && <p className="mt-1 text-xs text-[#8a3b2e]" role="status">Download of {d.pull.model} failed: {d.pull.error}</p>}
      <div className="mt-2 flex gap-2">
        <Input aria-label="Any other Ollama model name" placeholder="Any other model from ollama.com/library, e.g. llama3.2:1b"
          value={other} onChange={(e) => setOther(e.target.value)} className="h-8" />
        <Button size="sm" disabled={!running || pulling || !/^[\w][\w.:/-]{1,79}$/.test(other.trim())}
          onClick={() => { void download(other.trim()); setOther(""); }}><Download size={13} aria-hidden /> Download &amp; use</Button>
      </div>
      <p className="mt-2 text-xs text-muted">● = how good its meeting summaries are. Bigger is better but slower; "Fits your GPU" ones
        summarise an hour of meeting in about a minute. Downloads keep using the current model until they finish.</p>
      <Dialog open={remove !== null} onOpenChange={(o) => { if (!o) setRemove(null); }} title={`Remove ${remove ?? ""}?`}
        description="The model is deleted from this PC to free disk space. You can download it again any time.">
        <div className="flex justify-end gap-2">
          <Button onClick={() => setRemove(null)}>Keep it</Button>
          <Button variant="danger" onClick={async () => {
            const name = remove ?? "";
            setRemove(null);
            const r = await run(() => api.removeLocalModel(name));
            if (r) { setD(r); onChanged(); }
          }}><Trash2 size={14} aria-hidden /> Remove</Button>
        </div>
      </Dialog>
    </div>
  );
}
