import { Check, ClipboardCopy, Download, FileUp, Loader2 } from "lucide-react";
import { useRef, useState } from "react";
import { api } from "../api/client";
import { Button } from "./ui/button";
import { Dialog } from "./ui/dialog";
import { Input, Label, Textarea } from "./ui/primitives";

/** Summarise with another AI agent (ADR-036): download the transcript with the prompt, give it to any agent,
    then paste or upload its Markdown reply - it becomes the meeting's summary. */
export function SummaryHandoff({ meetingId, open, onOpenChange, onSaved }: {
  meetingId: string; open: boolean; onOpenChange: (o: boolean) => void; onSaved: () => void;
}) {
  const [text, setText] = useState("");
  const [source, setSource] = useState("");
  const [copied, setCopied] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);

  const copyPrompt = async () => {
    setError(null);
    try {
      const { prompt } = await api.summaryPrompt();
      await navigator.clipboard.writeText(prompt);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2500);
    } catch (e) {
      setError(`Couldn't copy the prompt: ${e instanceof Error ? e.message : String(e)}`);
    }
  };
  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.uploadSummary(meetingId, text, source.trim());
      setText("");
      onOpenChange(false);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Summarise with another AI"
      description="Use any AI assistant you like. Its summary replaces the one shown here; action items you already decided on keep their choice.">
      <ol className="space-y-4 text-sm">
        <li>
          <p className="mb-1.5"><b>1.</b> Download the transcript. The instructions for the AI are at the top of the file.</p>
          <Button size="sm" asChild><a href={api.meetingExportUrl(meetingId, "ai")} download>
            <Download size={14} aria-hidden /> Transcript for AI (.md)</a></Button>
        </li>
        <li>
          <p className="mb-1.5"><b>2.</b> Give the file to the AI. If it ignores the instructions in the file, paste the prompt
            too (it also works with the ordinary Markdown export).</p>
          <Button size="sm" onClick={() => void copyPrompt()}>
            {copied ? <><Check size={14} aria-hidden /> Copied</> : <><ClipboardCopy size={14} aria-hidden /> Copy prompt</>}</Button>
        </li>
        <li>
          <p className="mb-1.5"><b>3.</b> Paste the AI's reply here, or choose the .md file it gave you.</p>
          <Textarea aria-label="The AI's summary" value={text} className="min-h-36 font-mono text-xs"
            placeholder={"# Meeting title\n\n## Summary\n...\n\n## Action items\n- [ ] [mm:ss] Task | Owner: ... | Due: ..."}
            onChange={(e) => setText(e.target.value)} />
          <div className="mt-2 flex flex-wrap items-end gap-2">
            <input ref={file} type="file" accept=".md,.markdown,.txt,.json,text/markdown,text/plain" className="hidden"
              aria-label="Summary file" onChange={async (e) => {
                const f = e.target.files?.[0];
                if (f) setText(await f.text());
                e.target.value = "";
              }} />
            <Button size="sm" onClick={() => file.current?.click()}><FileUp size={14} aria-hidden /> Choose file…</Button>
            <div className="min-w-40 flex-1">
              <Label htmlFor="handoff-source">Which AI (optional)</Label>
              <Input id="handoff-source" value={source} maxLength={40} placeholder="e.g. Claude, ChatGPT"
                onChange={(e) => setSource(e.target.value)} className="h-8" />
            </div>
          </div>
        </li>
      </ol>
      {error && <p role="alert" className="mt-3 text-sm text-[#8a3b2e]">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <Button onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button variant="primary" disabled={!text.trim() || saving} onClick={() => void save()}>
          {saving && <Loader2 size={14} className="animate-spin" aria-hidden />} Use this summary</Button>
      </div>
    </Dialog>
  );
}
