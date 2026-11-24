import type { HTMLAttributes, InputHTMLAttributes, LabelHTMLAttributes, ReactNode, SelectHTMLAttributes,
  TextareaHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

export function Card({ className, ...p }: HTMLAttributes<HTMLElement>) {
  return <section className={cn("rounded-[var(--radius-card)] border border-line bg-white/80 p-5 shadow-[0_1px_0_#0000000a]",
    className)} {...p} />;
}

export function CardTitle({ children, aside, id }: { children: ReactNode; aside?: ReactNode; id?: string }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 id={id} className="text-[15px] font-bold tracking-tight text-ink">{children}</h2>
      {aside}
    </div>
  );
}

type Tone = "neutral" | "amber" | "sage" | "ink";
const TONES: Record<Tone, string> = {
  neutral: "bg-paper-2 text-ink-2 border-line",
  amber: "bg-amber-soft text-amber-ink border-[#f2cfae]",
  sage: "bg-sage-soft text-sage border-[#c9dfcd]",
  ink: "bg-ink text-paper border-ink",
};

export function Badge({ tone = "neutral", className, ...p }: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return <span className={cn("inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold",
    TONES[tone], className)} {...p} />;
}

const field = "w-full rounded-xl border border-line bg-white px-3 py-2 text-sm text-ink placeholder:text-muted " +
  "focus:border-amber focus:outline-none";

export function Input({ className, ...p }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(field, "h-10", className)} {...p} />;
}

export function Textarea({ className, ...p }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(field, "min-h-24 resize-y leading-relaxed", className)} {...p} />;
}

export function Select({ className, ...p }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cn(field, "h-10", className)} {...p} />;
}

export function Label({ className, ...p }: LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("mb-1 block text-xs font-semibold uppercase tracking-wide text-muted", className)} {...p} />;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-xl border border-dashed border-line px-4 py-6 text-center text-sm text-muted">{children}</p>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}
