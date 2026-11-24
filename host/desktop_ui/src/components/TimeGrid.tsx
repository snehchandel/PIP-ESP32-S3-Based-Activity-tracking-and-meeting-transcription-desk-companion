import { AlarmClock, Bell, ListTodo, Repeat } from "lucide-react";
import { useEffect, useRef } from "react";
import type { CalItem, DayItems } from "../api/types";
import { cn, todayIso } from "../lib/utils";

const HOUR_PX = 52;
const KIND_ICON = [ListTodo, Bell, AlarmClock];
const KIND_STYLE = [
  "border-l-ink bg-white text-ink",
  "border-l-sage bg-sage-soft text-ink",
  "border-l-amber bg-amber-soft text-amber-ink",
];

const toMin = (hhmm: string) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5));
const fmtHour = (h: number) => new Date(2000, 0, 1, h).toLocaleTimeString([], { hour: "numeric" });

/** Greedy lane assignment so overlapping items sit side by side instead of on top of each other. */
function layout(items: CalItem[]): { item: CalItem; lane: number; lanes: number }[] {
  const timed = items.filter((i) => i.hhmm).sort((a, b) => toMin(a.hhmm) - toMin(b.hhmm));
  const laneEnds: number[] = [];
  const placed = timed.map((item) => {
    const start = toMin(item.hhmm);
    let lane = laneEnds.findIndex((end) => end <= start);
    if (lane < 0) lane = laneEnds.length;
    laneEnds[lane] = start + Math.max(item.duration_min, 20);
    return { item, lane };
  });
  return placed.map((p) => ({ ...p, lanes: Math.max(1, laneEnds.length) }));
}

export function TimeGrid({ days, selectedId, onSelect, onSlot }: {
  days: DayItems[]; selectedId: string | null; onSelect: (item: CalItem, date: string) => void;
  onSlot: (date: string, hhmm: string) => void;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const timed = days.flatMap((d) => d.items.filter((i) => i.hhmm));
  const startH = Math.min(7, ...timed.map((i) => Math.floor(toMin(i.hhmm) / 60)));
  const endH = Math.max(22, ...timed.map((i) => Math.ceil((toMin(i.hhmm) + i.duration_min) / 60)));
  const hours = Array.from({ length: endH - startH }, (_, k) => startH + k);
  const now = new Date();
  const nowMin = now.getHours() * 60 + now.getMinutes();

  useEffect(() => {  // open at the current time (or 8 am) instead of midnight
    const target = Math.max(0, ((days.some((d) => d.date === todayIso()) ? nowMin / 60 - 1 : 8) - startH) * HOUR_PX);
    scroller.current?.scrollTo({ top: target });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days.length, startH]);

  const cols = `56px repeat(${days.length}, minmax(0, 1fr))`;
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-white/60">
      <div className="grid border-b border-line" style={{ gridTemplateColumns: cols }}>
        <div />
        {days.map((d) => {
          const dt = new Date(`${d.date}T12:00:00`);
          return (
            <div key={d.date} className={cn("px-2 py-2 text-center text-xs font-bold",
              d.date === todayIso() && "text-amber-ink")}>
              {dt.toLocaleDateString([], { weekday: "short" })}{" "}
              <span className={cn("ml-0.5", d.date === todayIso() && "rounded-full bg-amber px-1.5 text-white")}>
                {dt.getDate()}</span>
            </div>
          );
        })}
      </div>
      <div className="grid border-b border-line bg-paper-2/60" style={{ gridTemplateColumns: cols }}>
        <div className="px-1 py-1.5 text-right text-[10px] font-semibold uppercase text-muted">Anytime</div>
        {days.map((d) => (
          <div key={d.date} className="min-h-8 space-y-0.5 border-l border-line p-1">
            {d.items.filter((i) => !i.hhmm).map((i) => (
              <button key={i.id} onClick={() => onSelect(i, d.date)}
                className={cn("block w-full truncate rounded border-l-2 px-1.5 py-0.5 text-left text-[11px]",
                  KIND_STYLE[i.kind], i.done && "line-through opacity-50", selectedId === i.id && "ring-2 ring-ink")}>
                {i.title}</button>
            ))}
          </div>
        ))}
      </div>
      <div ref={scroller} className="relative max-h-[62vh] overflow-y-auto">
        <div className="grid" style={{ gridTemplateColumns: cols }}>
          <div>
            {hours.map((h) => (
              <div key={h} className="pr-1.5 text-right text-[10px] text-muted" style={{ height: HOUR_PX }}>
                <span className="relative -top-1.5">{fmtHour(h)}</span></div>
            ))}
          </div>
          {days.map((d) => (
            <div key={d.date} className="relative border-l border-line">
              {hours.map((h) => (
                <button key={h} aria-label={`Schedule on ${d.date} at ${String(h).padStart(2, "0")}:00`}
                  onClick={() => onSlot(d.date, `${String(h).padStart(2, "0")}:00`)}
                  className="block w-full border-t border-line/70 hover:bg-amber-soft/40" style={{ height: HOUR_PX }} />
              ))}
              {d.date === todayIso() && nowMin / 60 >= startH && nowMin / 60 <= endH && (
                <div aria-hidden className="pointer-events-none absolute inset-x-0 z-10 border-t-2 border-amber"
                  style={{ top: (nowMin / 60 - startH) * HOUR_PX }}>
                  <span className="absolute -left-1 -top-[5px] h-2 w-2 rounded-full bg-amber" /></div>
              )}
              {layout(d.items).map(({ item, lane, lanes }) => {
                const Icon = KIND_ICON[item.kind] ?? ListTodo;
                const top = (toMin(item.hhmm) / 60 - startH) * HOUR_PX;
                const height = Math.max(22, (item.duration_min / 60) * HOUR_PX - 2);
                return (
                  <button key={item.id} onClick={() => onSelect(item, d.date)}
                    aria-label={`${item.title} at ${item.hhmm}, ${item.duration_min} minutes`}
                    className={cn("absolute z-20 overflow-hidden rounded-md border border-line border-l-[3px] px-1.5 py-0.5",
                      "text-left text-[11px] leading-tight shadow-sm hover:z-30 hover:shadow-md", KIND_STYLE[item.kind],
                      item.done && "opacity-50", selectedId === item.id && "ring-2 ring-ink")}
                    style={{ top, height, left: `calc(${(lane / lanes) * 100}% + 2px)`, width: `calc(${100 / lanes}% - 4px)` }}>
                    <span className="flex items-center gap-1 font-semibold">
                      <Icon size={11} aria-hidden className="shrink-0" />
                      <span className="tabular">{item.hhmm}</span>
                      {item.recurring && <Repeat size={10} aria-hidden />}
                    </span>
                    <span className={cn("block truncate", item.done && "line-through")}>{item.title}</span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
