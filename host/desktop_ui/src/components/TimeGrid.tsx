import { AlarmClock, Bell, ListTodo, Repeat } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { CalItem, DayItems } from "../api/types";
import { cn, todayIso } from "../lib/utils";

/* Outlook-style week/day grid: roomy hours, events as solid blocks with a coloured edge,
   the title first (wrapping as far as the block allows) and the time range underneath. */
const HOUR_PX = 64;
const KIND_ICON = [ListTodo, Bell, AlarmClock];
const KIND_NAME = ["Task", "Reminder", "Alarm"];
const KIND_STYLE = [
  "border-l-ink bg-[#eef0f3] text-ink",
  "border-l-sage bg-sage-soft text-ink",
  "border-l-amber bg-amber-soft text-amber-ink",
];
const ALLDAY_SHOWN = 3;

const toMin = (hhmm: string) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5));
const fmtHour = (h: number) => new Date(2000, 0, 1, h).toLocaleTimeString([], { hour: "numeric" });
const fmtTime = (min: number) =>
  new Date(2000, 0, 1, Math.floor(min / 60) % 24, min % 60).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

/** Greedy lane assignment so overlapping items sit side by side instead of on top of each other. */
function layout(items: CalItem[]): { item: CalItem; lane: number; lanes: number }[] {
  const timed = items.filter((i) => i.hhmm).sort((a, b) => toMin(a.hhmm) - toMin(b.hhmm));
  const laneEnds: number[] = [];
  const placed = timed.map((item) => {
    const start = toMin(item.hhmm);
    let lane = laneEnds.findIndex((end) => end <= start);
    if (lane < 0) lane = laneEnds.length;
    laneEnds[lane] = start + Math.max(item.duration_min, 30);
    return { item, lane };
  });
  return placed.map((p) => ({ ...p, lanes: Math.max(1, laneEnds.length) }));
}

function AllDay({ day, selectedId, onSelect }: {
  day: DayItems; selectedId: string | null; onSelect: (item: CalItem, date: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const items = day.items.filter((i) => !i.hhmm);
  const shown = open ? items : items.slice(0, ALLDAY_SHOWN);
  return (
    <div className="min-h-9 space-y-1 border-l border-line p-1">
      {shown.map((i) => (
        <button key={i.id} title={i.title} onClick={() => onSelect(i, day.date)}
          className={cn("block w-full rounded-[4px] border-l-[3px] px-1.5 py-1 text-left text-xs font-medium leading-snug",
            "line-clamp-2 break-words hover:brightness-95", KIND_STYLE[i.kind],
            i.done && "line-through opacity-50", selectedId === i.id && "ring-2 ring-ink")}>
          {i.title}</button>
      ))}
      {items.length > ALLDAY_SHOWN && (
        <button onClick={() => setOpen(!open)} className="w-full px-1.5 text-left text-xs font-semibold text-muted hover:text-ink">
          {open ? "Show less" : `+${items.length - ALLDAY_SHOWN} more`}</button>
      )}
    </div>
  );
}

export function TimeGrid({ days, selectedId, onSelect, onSlot }: {
  days: DayItems[]; selectedId: string | null; onSelect: (item: CalItem, date: string) => void;
  onSlot: (date: string, hhmm: string) => void;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const timed = days.flatMap((d) => d.items.filter((i) => i.hhmm));
  const startH = Math.min(6, ...timed.map((i) => Math.floor(toMin(i.hhmm) / 60)));
  const endH = Math.min(24, Math.max(23, ...timed.map((i) => Math.ceil((toMin(i.hhmm) + i.duration_min) / 60))));
  const hours = Array.from({ length: endH - startH }, (_, k) => startH + k);
  const [nowMin, setNowMin] = useState(() => new Date().getHours() * 60 + new Date().getMinutes());
  useEffect(() => {
    const t = window.setInterval(() => setNowMin(new Date().getHours() * 60 + new Date().getMinutes()), 60_000);
    return () => window.clearInterval(t);
  }, []);

  useEffect(() => { // open at the current time (or 8 am) instead of midnight
    const target = Math.max(0, ((days.some((d) => d.date === todayIso()) ? nowMin / 60 - 1.5 : 8) - startH) * HOUR_PX);
    scroller.current?.scrollTo({ top: target });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days.length, startH]);

  const cols = `64px repeat(${days.length}, minmax(${days.length > 1 ? 104 : 0}px, 1fr))`;
  return (
    <div className="overflow-x-auto rounded-xl border border-line bg-white">
      <div className="min-w-fit">
        <div className="grid border-b border-line" style={{ gridTemplateColumns: cols }}>
          <div />
          {days.map((d) => {
            const dt = new Date(`${d.date}T12:00:00`);
            const today = d.date === todayIso();
            return (
              <div key={d.date} className={cn("border-l border-line px-2 py-1.5", today && "bg-amber-soft/50")}>
                <p className={cn("text-[11px] font-semibold uppercase tracking-wide text-muted", today && "text-amber-ink")}>
                  {dt.toLocaleDateString([], { weekday: "short" })}</p>
                <p className={cn("text-xl font-bold leading-tight", today && "text-amber-ink")}>{dt.getDate()}</p>
              </div>
            );
          })}
        </div>
        <div className="grid border-b border-line bg-paper-2/50" style={{ gridTemplateColumns: cols }}>
          <div className="px-1.5 py-2 text-right text-[10px] font-semibold uppercase leading-tight text-muted">All day /<br />anytime</div>
          {days.map((d) => <AllDay key={d.date} day={d} selectedId={selectedId} onSelect={onSelect} />)}
        </div>
        <div ref={scroller} className="relative max-h-[68vh] overflow-y-auto">
          <div className="grid" style={{ gridTemplateColumns: cols }}>
            <div>
              {hours.map((h) => (
                <div key={h} className="pr-2 text-right text-[11px] text-muted" style={{ height: HOUR_PX }}>
                  <span className="relative -top-2">{h === startH ? "" : fmtHour(h)}</span></div>
              ))}
            </div>
            {days.map((d) => (
              <div key={d.date} className="relative border-l border-line">
                {hours.map((h) => (
                  <div key={h} className={cn("border-t border-line", (h < 8 || h >= 18) && "bg-paper-2/40")}
                    style={{ height: HOUR_PX }}>
                    {[0, 30].map((mm) => (
                      <button key={mm} aria-label={`Schedule on ${d.date} at ${String(h).padStart(2, "0")}:${mm ? "30" : "00"}`}
                        onClick={() => onSlot(d.date, `${String(h).padStart(2, "0")}:${mm ? "30" : "00"}`)}
                        className={cn("block w-full hover:bg-amber-soft/50", mm && "border-t border-dotted border-line/80")}
                        style={{ height: HOUR_PX / 2 }} />
                    ))}
                  </div>
                ))}
                {d.date === todayIso() && nowMin / 60 >= startH && nowMin / 60 <= endH && (
                  <div aria-hidden className="pointer-events-none absolute inset-x-0 z-10 border-t-2 border-amber"
                    style={{ top: (nowMin / 60 - startH) * HOUR_PX }}>
                    <span className="absolute -left-1 -top-[5px] h-2 w-2 rounded-full bg-amber" /></div>
                )}
                {layout(d.items).map(({ item, lane, lanes }) => {
                  const Icon = KIND_ICON[item.kind] ?? ListTodo;
                  const start = toMin(item.hhmm);
                  const dur = Math.max(item.duration_min, item.kind === 2 ? 15 : 30);
                  const top = (start / 60 - startH) * HOUR_PX + 1;
                  const height = Math.max(42, (dur / 60) * HOUR_PX - 3); // always room for title + time
                  const range = item.kind === 2 ? fmtTime(start) : `${fmtTime(start)} – ${fmtTime(start + item.duration_min)}`;
                  return (
                    <button key={item.id} onClick={() => onSelect(item, d.date)}
                      title={`${item.title}\n${range} · ${KIND_NAME[item.kind]}`}
                      aria-label={`${item.title}, ${range}, ${KIND_NAME[item.kind]}`}
                      className={cn("absolute z-20 overflow-hidden rounded-[4px] border-l-[4px] px-1.5 py-1 text-left text-xs",
                        "leading-snug shadow-[0_1px_2px_rgba(0,0,0,0.12)] hover:z-30 hover:brightness-95", KIND_STYLE[item.kind],
                        item.done && "opacity-50", selectedId === item.id && "ring-2 ring-ink")}
                      style={{ top, height, left: `calc(${(lane / lanes) * 100}% + 2px)`, width: `calc(${100 / lanes}% - 5px)` }}>
                        <>
                          <span className={cn("block break-words font-semibold", item.done && "line-through")}
                            style={{ display: "-webkit-box", WebkitBoxOrient: "vertical",
                              WebkitLineClamp: Math.max(1, Math.floor((height - 22) / 16)), overflow: "hidden" }}>
                            {item.title}</span>
                          <span className="mt-0.5 flex items-center gap-1 text-[11px] opacity-80">
                            <Icon size={11} aria-hidden className="shrink-0" />
                            <span className="tabular truncate">{range}</span>
                            {item.recurring && <Repeat size={10} aria-hidden className="shrink-0" />}
                          </span>
                        </>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
