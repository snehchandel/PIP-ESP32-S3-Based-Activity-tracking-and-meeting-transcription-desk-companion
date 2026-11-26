import { ExternalLink, FileText, Loader2, Maximize2, Search, Sparkles, Tag, User, X, ZoomIn, ZoomOut } from "lucide-react";
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent, ReactNode } from "react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { useLive } from "../api/live";
import type { GraphNode, GraphNodeKind, MeetingDetail, MeetingGraph } from "../api/types";
import { ForceSim } from "../lib/forceLayout";
import { clock, shortDate, speakerColor, when } from "../lib/meetingFormat";
import { cn } from "../lib/utils";
import { Button } from "./ui/button";
import { Badge, Card, Empty, Input, Label } from "./ui/primitives";

/* Meetings -> Graph: the links the Obsidian notes make, drawn like Obsidian's graph view. Every meeting is a dot
   (its transcript), its summary a diamond beside it; people (rings) and topics (violet dots) join the meetings they
   share. Click a dot to read it in the panel on the right, follow links from there, double-click a meeting (or
   "Open meeting") to edit it in the list. Hover shows a node's neighbours; search finds and centres one. */

const KINDS: Record<GraphNodeKind, { name: string; plural: string; color: string }> = {
  meeting: { name: "Transcript", plural: "Meetings", color: "#18181b" },
  summary: { name: "Summary", plural: "Summaries", color: "#e87a1e" },
  person: { name: "Person", plural: "People", color: "#4d7c5a" },
  topic: { name: "Topic", plural: "Topics", color: "#6d5fa8" },
};
const TOGGLABLE: GraphNodeKind[] = ["summary", "person", "topic"];
const LINK_LEN = { summary: 30, attended: 70, topic: 56 } as const;
const LINK_STIFF = { summary: 4, attended: 1, topic: 1 } as const; // a summary stays beside its meeting
const PAPER = "#faf8f4";

type View = { x: number; y: number; k: number };
const clampK = (k: number) => Math.min(4, Math.max(0.2, k));
const reducedMotion = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

function radius(n: GraphNode): number {
  const shared = Math.max(0, (n.meetings?.length ?? 1) - 1);
  if (n.kind === "meeting") return 8 + Math.min(6, Math.sqrt((n.duration_s ?? 0) / 60));
  if (n.kind === "summary") return 6.5;
  if (n.kind === "person") return 5.5 + Math.min(6, shared * 1.5);
  return 4 + Math.min(5, shared * 1.2);
}

const trunc = (s: string, n = 26) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
export const meetingOf = (id: string | null) => id?.match(/^(?:meeting|summary):(.+)$/)?.[1] ?? null;

function describe(n: GraphNode): string {
  if (n.kind === "meeting") return `${n.started_at ? shortDate(n.started_at) : ""} · ${clock(n.duration_s ?? 0)}`
    + (n.status && n.status !== "READY" ? ` · ${n.status.toLowerCase()}` : "");
  if (n.kind === "summary") return n.gist || "Summary";
  const c = n.meetings?.length ?? 0;
  return `${c} meeting${c === 1 ? "" : "s"}`;
}

function ariaFor(n: GraphNode): string {
  const kind = n.kind === "meeting" ? "Meeting transcript" : KINDS[n.kind].name;
  return `${kind}: ${n.kind === "summary" ? n.label.replace(/^Summary · /, "") : n.label}, ${describe(n)}`;
}

/** The node's shape: circle (meeting), diamond (summary), ring (person), dot (topic) - never colour alone. */
function Shape({ n, r, k }: { n: GraphNode; r: number; k: number }) {
  const c = KINDS[n.kind].color;
  if (n.kind === "summary") {
    const s = r * 1.55;
    return <rect x={-s / 2} y={-s / 2} width={s} height={s} rx={1.5} transform="rotate(45)" fill={c} stroke={PAPER} strokeWidth={1.5 / k} />;
  }
  if (n.kind === "person") return <circle r={r} fill={PAPER} stroke={c} strokeWidth={3} />;
  if (n.kind === "meeting" && n.status !== "READY") {
    return <circle r={r} fill={PAPER} stroke={c} strokeWidth={2} strokeDasharray="3 2.5" />;
  }
  return <circle r={r} fill={c} stroke={PAPER} strokeWidth={1.5 / k} />;
}

function Swatch({ kind }: { kind: GraphNodeKind }) {
  const n = { id: "", kind, label: "", status: "READY" as const };
  return <svg width="14" height="14" viewBox="-7 -7 14 14" aria-hidden className="shrink-0">
    <Shape n={n} r={kind === "person" ? 4.5 : kind === "topic" ? 4 : 5} k={1} /></svg>;
}

// ---- canvas ----------------------------------------------------------------------------------------------------
function GraphCanvas({ nodes, edges, selected, matches, centerReq, onSelect, onOpen }: {
  nodes: GraphNode[]; edges: { source: string; target: string; kind: keyof typeof LINK_LEN }[];
  selected: string | null; matches: Set<string> | null; centerReq: { id: string; n: number } | null;
  onSelect: (id: string | null) => void; onOpen: (meetingId: string) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const sim = useRef<ForceSim | null>(null);
  const cache = useRef(new Map<string, { x: number; y: number }>());
  const raf = useRef(0);
  const anim = useRef(0);
  const touched = useRef(false); // the user panned/zoomed: stop auto-fitting
  const [size, setSize] = useState({ w: 800, h: 560 });
  const [view, setView] = useState<View>({ x: 0, y: 0, k: 1 });
  const viewRef = useRef(view);
  const sizeRef = useRef(size);
  useLayoutEffect(() => { viewRef.current = view; sizeRef.current = size; }, [view, size]);
  const selectedRef = useRef(selected);
  useLayoutEffect(() => { selectedRef.current = selected; }, [selected]);
  const [simState, setSimState] = useState<ForceSim | null>(null); // the same object as `sim`, for rendering
  const [, setFrame] = useState(0);
  const [hover, setHover] = useState<string | null>(null);
  const [panning, setPanning] = useState(false);
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ mode: "pan" | "node"; id?: string; sx: number; sy: number; ox: number; oy: number; moved: boolean } | null>(null);

  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const adj = useMemo(() => {
    const m = new Map<string, Set<string>>();
    for (const e of edges) {
      (m.get(e.source) ?? m.set(e.source, new Set()).get(e.source)!).add(e.target);
      (m.get(e.target) ?? m.set(e.target, new Set()).get(e.target)!).add(e.source);
    }
    return m;
  }, [edges]);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: Math.max(200, e.contentRect.width), h: Math.max(200, e.contentRect.height) }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const animateTo = useCallback((to: View) => {
    cancelAnimationFrame(anim.current);
    if (reducedMotion()) { setView(to); return; }
    const from = viewRef.current, t0 = performance.now();
    const step = (t: number) => {
      const p = Math.min(1, (t - t0) / 320), e = 1 - (1 - p) ** 3;
      setView({ x: from.x + (to.x - from.x) * e, y: from.y + (to.y - from.y) * e, k: from.k + (to.k - from.k) * e });
      if (p < 1) anim.current = requestAnimationFrame(step);
    };
    anim.current = requestAnimationFrame(step);
  }, []);

  const fitView = useCallback((): View | null => {
    const s = sim.current;
    if (!s || s.nodes.length === 0) return null;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of s.nodes) {
      x0 = Math.min(x0, n.x - n.r); y0 = Math.min(y0, n.y - n.r); x1 = Math.max(x1, n.x + n.r); y1 = Math.max(y1, n.y + n.r + 14);
    }
    const { w, h } = sizeRef.current;
    const k = clampK(Math.min(1.6, (w - 96) / Math.max(1, x1 - x0), (h - 96) / Math.max(1, y1 - y0)));
    return { k, x: -((x0 + x1) / 2) * k, y: -((y0 + y1) / 2) * k };
  }, []);

  const centerOn = useCallback((id: string) => {
    const n = sim.current?.get(id);
    if (!n) return;
    const k = Math.max(viewRef.current.k, 0.9);
    animateTo({ k, x: -n.x * k, y: -n.y * k });
  }, [animateTo]);

  const kick = useCallback(() => {
    if (raf.current) return;
    const step = () => {
      const s = sim.current;
      if (!s) { raf.current = 0; return; }
      s.tick();
      cache.current = s.positions();
      setFrame((f) => f + 1);
      if (!s.settled) { raf.current = requestAnimationFrame(step); return; }
      raf.current = 0;
      // settled and the user hasn't moved the view: a gentle final fit (or keep the selection centred)
      if (!touched.current) {
        const sel = selectedRef.current ? s.get(selectedRef.current) : undefined;
        const f = fitView();
        if (f) animateTo(sel ? { k: Math.max(f.k, 0.9), x: -sel.x * Math.max(f.k, 0.9), y: -sel.y * Math.max(f.k, 0.9) } : f);
      }
    };
    raf.current = requestAnimationFrame(step);
  }, [fitView, animateTo]);

  // (re)build the simulation when the visible graph changes; positions carry over
  const shape = useMemo(() => nodes.map((n) => n.id).join("|") + "#" + edges.map((e) => e.source + ">" + e.target).join("|"), [nodes, edges]);
  useEffect(() => {
    const first = cache.current.size === 0;
    const s = new ForceSim(nodes.map((n) => ({ id: n.id, r: radius(n) })),
      edges.map((e) => ({ source: e.source, target: e.target, len: LINK_LEN[e.kind], stiff: LINK_STIFF[e.kind] })), cache.current);
    // arrive mostly arranged (a calm entrance); with reduced motion, arrive finished
    const pre = reducedMotion() ? 500 : first ? 180 : 0;
    for (let i = 0; i < pre && !s.settled; i++) s.tick();
    sim.current = s;
    setSimState(s);
    cache.current = s.positions();
    if (first || !touched.current) {
      const f = fitView();
      const sel = selectedRef.current ? s.get(selectedRef.current) : undefined;
      if (f) setView(sel ? { k: Math.max(f.k, 0.9), x: -sel.x * Math.max(f.k, 0.9), y: -sel.y * Math.max(f.k, 0.9) } : f);
    }
    setFrame((x) => x + 1);
    kick();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `shape` stands for nodes + edges
  }, [shape, fitView, kick]);
  useEffect(() => () => { cancelAnimationFrame(raf.current); cancelAnimationFrame(anim.current); }, []);

  useEffect(() => { if (centerReq) centerOn(centerReq.id); }, [centerReq, centerOn]);
  useEffect(() => {
    if (touched.current || !sim.current) return;
    const f = fitView();
    const sel = selectedRef.current ? sim.current.get(selectedRef.current) : undefined;
    if (f) setView(sel ? { k: Math.max(f.k, 0.9), x: -sel.x * Math.max(f.k, 0.9), y: -sel.y * Math.max(f.k, 0.9) } : f);
  }, [size, fitView]);

  // wheel zoom around the pointer (needs a non-passive listener to keep the page from scrolling)
  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      touched.current = true;
      cancelAnimationFrame(anim.current);
      const r = el.getBoundingClientRect();
      const sx = e.clientX - r.left - r.width / 2, sy = e.clientY - r.top - r.height / 2;
      setView((v) => {
        const k = clampK(v.k * Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)));
        const wx = (sx - v.x) / v.k, wy = (sy - v.y) / v.k;
        return { k, x: sx - wx * k, y: sy - wy * k };
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const zoom = (f: number) => {
    touched.current = true;
    const v = viewRef.current, k = clampK(v.k * f);
    animateTo({ k, x: (v.x / v.k) * k, y: (v.y / v.k) * k });
  };
  const fit = () => { touched.current = false; const f = fitView(); if (f) animateTo(f); };

  const toWorld = (e: ReactPointerEvent) => {
    const r = svg.current!.getBoundingClientRect(), v = viewRef.current;
    return { x: (e.clientX - r.left - r.width / 2 - v.x) / v.k, y: (e.clientY - r.top - r.height / 2 - v.y) / v.k };
  };
  const nodeAt = (t: EventTarget) => (t as Element).closest?.("[data-node]")?.getAttribute("data-node") ?? null;

  const down = (e: ReactPointerEvent<SVGSVGElement>) => {
    if (e.button !== 0) return;
    const id = nodeAt(e.target);
    if (!id) box.current?.focus({ preventScroll: true }); // so +/-/0/Esc work after clicking the canvas
    svg.current?.setPointerCapture(e.pointerId);
    cancelAnimationFrame(anim.current);
    drag.current = id ? { mode: "node", id, sx: e.clientX, sy: e.clientY, ox: 0, oy: 0, moved: false }
      : { mode: "pan", sx: e.clientX, sy: e.clientY, ox: viewRef.current.x, oy: viewRef.current.y, moved: false };
  };
  const move = (e: ReactPointerEvent<SVGSVGElement>) => {
    const d = drag.current;
    if (!d) return;
    if (!d.moved && Math.hypot(e.clientX - d.sx, e.clientY - d.sy) < 4) return;
    if (!d.moved) { d.moved = true; if (d.mode === "pan") setPanning(true); else setDragging(true); }
    if (d.mode === "pan") {
      touched.current = true;
      setView((v) => ({ ...v, x: d.ox + e.clientX - d.sx, y: d.oy + e.clientY - d.sy }));
    } else if (d.id) {
      const n = sim.current?.get(d.id);
      if (!n) return;
      const p = toWorld(e);
      n.fx = p.x; n.fy = p.y;
      touched.current = true;
      sim.current!.reheat(0.25);
      kick();
    }
  };
  const up = () => {
    const d = drag.current;
    drag.current = null;
    setPanning(false);
    setDragging(false);
    if (!d) return;
    if (d.mode === "node" && d.id) {
      const n = sim.current?.get(d.id);
      if (n) { n.fx = null; n.fy = null; }
      if (!d.moved) onSelect(d.id);
    } else if (!d.moved) {
      onSelect(null);
    }
  };

  const onKey = (e: ReactKeyboardEvent) => {
    const id = nodeAt(e.target);
    if (id && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault(); e.stopPropagation();
      const n = byId.get(id);
      if (e.key === "Enter" && selected === id && n?.meeting_id) onOpen(n.meeting_id);
      else onSelect(id);
    } else if (e.key === "Escape") { e.stopPropagation(); onSelect(null); }
    else if (e.key === "+" || e.key === "=") { e.preventDefault(); zoom(1.3); }
    else if (e.key === "-" || e.key === "_") { e.preventDefault(); zoom(1 / 1.3); }
    else if (e.key === "0") { e.preventDefault(); fit(); }
  };

  const focusId = hover ?? selected;
  const lit = useMemo(() => {
    if (!focusId || !byId.has(focusId)) return null;
    return new Set([focusId, ...(adj.get(focusId) ?? [])]);
  }, [focusId, adj, byId]);
  const dim = (id: string) => (lit ? !lit.has(id) : matches ? !matches.has(id) : false);

  const s = simState;
  const { k } = view;
  const tip = hover ? byId.get(hover) : undefined;
  const tipPos = hover ? s?.get(hover) : undefined;

  return (
    <div ref={box} tabIndex={-1} className="relative h-full w-full overflow-hidden rounded-xl bg-[radial-gradient(#e4ded3_1px,transparent_1px)]
      [background-size:22px_22px] outline-none" onKeyDown={onKey}>
      <svg ref={svg} width={size.w} height={size.h} role="group" aria-label="Meetings graph: meetings, summaries, people and topics"
        className={cn("block touch-none select-none", panning ? "cursor-grabbing" : "cursor-grab")}
        onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}
        onDoubleClick={(e) => { const id = nodeAt(e.target); const mid = id && byId.get(id)?.meeting_id; if (mid) onOpen(mid); }}>
        <g transform={`translate(${size.w / 2 + view.x},${size.h / 2 + view.y}) scale(${k})`}>
          <g aria-hidden>
            {s && edges.map((e) => {
              const a = s.get(e.source), b = s.get(e.target);
              if (!a || !b) return null;
              const on = !!lit && lit.has(e.source) && lit.has(e.target) && (e.source === focusId || e.target === focusId);
              return <line key={e.source + ">" + e.target} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                stroke={on ? "#6b6760" : "#cdc5b6"} strokeWidth={(on ? 1.8 : 1) / k}
                opacity={lit ? (on ? 1 : 0.12) : matches ? 0.25 : 0.9} className="transition-opacity duration-150" />;
            })}
          </g>
          {s && nodes.map((n) => {
            const p = s.get(n.id);
            if (!p) return null;
            const r = radius(n);
            const isSel = n.id === selected, isMatch = !!matches?.has(n.id), faded = dim(n.id);
            const showLabel = isSel || isMatch || (lit?.has(n.id) ?? false)
              || (n.kind === "meeting" && k >= 0.55) || (n.kind === "person" && k >= 0.55) || (n.kind === "topic" && k >= 1.05);
            const label = n.kind === "summary" ? "Summary" : trunc(n.label);
            return (
              <g key={n.id} data-node={n.id} transform={`translate(${p.x},${p.y})`} tabIndex={0} role="button"
                aria-label={ariaFor(n)} aria-pressed={isSel}
                className="cursor-pointer outline-none transition-opacity duration-150 focus-visible:[&>.ring]:opacity-100"
                opacity={faded ? 0.16 : n.archived ? 0.55 : 1}
                onPointerEnter={() => { if (!drag.current) setHover(n.id); }} onPointerLeave={() => setHover((h) => (h === n.id ? null : h))}
                onFocus={() => setHover(n.id)} onBlur={() => setHover((h) => (h === n.id ? null : h))}>
                <circle r={r + 10} fill="transparent" />
                <circle className="ring opacity-0" r={r + 5} fill="none" stroke="#e87a1e" strokeWidth={2 / k} strokeDasharray={`${4 / k} ${3 / k}`} />
                {(isSel || isMatch) && <circle r={r + 4.5} fill="none" stroke="#e87a1e" strokeWidth={(isSel ? 2.5 : 1.6) / k}
                  strokeDasharray={isSel ? undefined : `${3 / k} ${2.5 / k}`} />}
                <Shape n={n} r={r} k={k} />
                {showLabel && <text y={r + 13 / k} textAnchor="middle" fontSize={11.5 / k} fontWeight={isSel || n.kind === "meeting" ? 650 : 500}
                  fill={n.kind === "summary" ? "#9a4a08" : "#18181b"} stroke={PAPER} strokeWidth={3.5 / k} paintOrder="stroke"
                  strokeLinejoin="round" className="pointer-events-none">{label}</text>}
              </g>
            );
          })}
        </g>
      </svg>

      {tip && tipPos && !dragging && !panning && (
        <div role="tooltip" className="pointer-events-none absolute z-10 max-w-64 rounded-lg border border-line bg-white px-2.5 py-1.5
          text-xs shadow-md" style={{ left: size.w / 2 + view.x + tipPos.x * k, top: size.h / 2 + view.y + (tipPos.y - radius(tip)) * k - 10,
          transform: "translate(-50%, -100%)" }}>
          <p className="font-semibold text-ink">{tip.kind === "summary" ? tip.label.replace(/^Summary · /, "Summary of ") : tip.label}</p>
          <p className="text-muted">{describe(tip)}</p>
          <p className="mt-0.5 text-[11px] text-muted">{tip.kind === "meeting" || tip.kind === "summary"
            ? "Click to read · double-click to open" : "Click to see its meetings"}</p>
        </div>
      )}

      <div className="absolute bottom-3 right-3 flex flex-col overflow-hidden rounded-xl border border-line bg-white/90 shadow-sm">
        <button type="button" className="grid h-9 w-9 place-items-center text-ink-2 hover:bg-paper-2" onClick={() => zoom(1.3)}
          aria-label="Zoom in" title="Zoom in (+)"><ZoomIn size={16} aria-hidden /></button>
        <button type="button" className="grid h-9 w-9 place-items-center border-y border-line text-ink-2 hover:bg-paper-2" onClick={() => zoom(1 / 1.3)}
          aria-label="Zoom out" title="Zoom out (−)"><ZoomOut size={16} aria-hidden /></button>
        <button type="button" className="grid h-9 w-9 place-items-center text-ink-2 hover:bg-paper-2" onClick={fit}
          aria-label="Fit the whole graph" title="Fit everything (0)"><Maximize2 size={15} aria-hidden /></button>
      </div>
      <p className="pointer-events-none absolute bottom-3 left-3 hidden rounded-lg bg-paper/85 px-2 py-1 text-[11px] text-muted md:block">
        Drag to move · scroll to zoom · click a dot to read it · double-click a meeting to open it</p>
    </div>
  );
}

// ---- preview panel ---------------------------------------------------------------------------------------------
function turnsOf(m: MeetingDetail) {
  const names = Object.fromEntries(m.speakers.map((s) => [s.key, s.name]));
  const out: { key: string; name: string; start: number; text: string }[] = [];
  for (const s of m.segments) {
    const last = out[out.length - 1];
    if (last && last.key === s.speaker_key) last.text += ` ${s.text}`;
    else out.push({ key: s.speaker_key, name: names[s.speaker_key] ?? s.speaker_key, start: s.start_s, text: s.text });
  }
  return out;
}

function useMeeting(mid: string | null) {
  const { meetingEvt } = useLive();
  const [data, setData] = useState<{ id: string; m: MeetingDetail | null; err?: string } | null>(null);
  const tick = meetingEvt.status === "TRANSCRIBING" && meetingEvt.progress !== undefined;
  const load = useCallback(() => {
    if (!mid) return;
    api.meeting(mid).then((m) => setData({ id: mid, m })).catch((e: Error) => setData({ id: mid, m: null, err: e.message }));
  }, [mid]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (mid && meetingEvt.id === mid && !tick) load(); }, [meetingEvt, mid, tick, load]);
  return data && data.id === mid ? data : null;
}

function KindChip({ kind }: { kind: GraphNodeKind }) {
  const Icon = { meeting: FileText, summary: Sparkles, person: User, topic: Tag }[kind];
  return <span className="inline-flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide" style={{ color: kind === "summary" ? "#9a4a08" : KINDS[kind].color }}>
    <Icon size={12} aria-hidden />{KINDS[kind].name}</span>;
}

function LinkChip({ node, onPick }: { node: GraphNode; onPick: (id: string) => void }) {
  return <button type="button" onClick={() => onPick(node.id)}
    className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-line bg-white/70 px-2 py-0.5 text-xs hover:border-ink hover:bg-white">
    <Swatch kind={node.kind} /><span className="truncate">{node.label}</span></button>;
}

function PanelHeader({ node, title, sub, onClose, actions }: {
  node: GraphNode; title: string; sub?: ReactNode; onClose: () => void; actions?: ReactNode;
}) {
  return (
    <div className="border-b border-line pb-3">
      <div className="flex items-start justify-between gap-2">
        <KindChip kind={node.kind} />
        <button type="button" onClick={onClose} aria-label="Close the preview" title="Close (Esc)"
          className="-mr-1 -mt-1 rounded-lg p-1 text-muted hover:bg-paper-2 hover:text-ink"><X size={15} aria-hidden /></button>
      </div>
      <h2 className="mt-1 text-lg font-extrabold leading-snug tracking-tight">{title}</h2>
      {sub && <p className="mt-0.5 text-xs text-muted">{sub}</p>}
      {actions && <div className="mt-3 flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

function TranscriptPreview({ node, graph, onPick, onOpen, onClose }: PreviewProps) {
  const mid = node.meeting_id!;
  const d = useMeeting(mid);
  const [q, setQ] = useState("");
  const summary = graph.byId.get(`summary:${mid}`);
  const people = (graph.adj.get(node.id) ?? []).map((id) => graph.byId.get(id)!).filter((n) => n?.kind === "person");
  const m = d?.m;
  const turns = useMemo(() => (m ? turnsOf(m) : []), [m]);
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    return s ? turns.filter((t) => t.text.toLowerCase().includes(s) || t.name.toLowerCase().includes(s)) : turns;
  }, [turns, q]);
  return (
    <>
      <PanelHeader node={node} title={node.label} onClose={onClose}
        sub={<>{m ? when(m) : node.started_at && shortDate(node.started_at)} · <span className="tabular">{clock(node.duration_s ?? 0)}</span>
          {node.archived && " · archived"}</>}
        actions={<>
          <Button size="sm" variant="primary" onClick={() => onOpen(mid)}><ExternalLink size={14} aria-hidden /> Open meeting</Button>
          {summary ? <Button size="sm" onClick={() => onPick(summary.id)}><Sparkles size={14} aria-hidden /> Summary</Button>
            : <Badge className="self-center">{node.summary_status === "QUEUED" || node.summary_status === "SUMMARIZING"
              ? "Summary on its way…" : "No summary yet"}</Badge>}
        </>} />
      {people.length > 0 && <div className="flex flex-wrap gap-1.5 border-b border-line py-3">
        {people.map((p) => <LinkChip key={p.id} node={p} onPick={onPick} />)}</div>}
      <div className="flex min-h-0 flex-1 flex-col pt-3">
        {!d ? <p className="flex items-center gap-2 text-sm text-muted"><Loader2 size={14} className="animate-spin" aria-hidden /> Loading transcript…</p>
          : !m ? <p className="text-sm text-[#8a3b2e]">Couldn't load this meeting{d.err ? `: ${d.err}` : ""}.</p>
            : m.status !== "READY" ? <Empty>{m.status === "FAILED" ? `Transcription failed: ${m.error ?? "unknown error"}. Open the meeting to try again.`
              : m.status === "RECORDING" ? "Still recording on PIP. The transcript appears here once it's transcribed."
                : `Transcribing${m.status === "TRANSCRIBING" ? ` (${Math.round(m.progress * 100)}%)` : ""}… the transcript appears here when it's ready.`}</Empty>
              : turns.length === 0 ? <Empty>No speech was found in this recording.</Empty> : (
                <>
                  <div className="relative mb-2">
                    <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" aria-hidden />
                    <Input aria-label="Find in this transcript" placeholder="Find in transcript…" value={q} onChange={(e) => setQ(e.target.value)}
                      className="h-8 pl-8 text-[13px]" />
                  </div>
                  <p className="mb-1 text-[11px] text-muted" aria-live="polite">{q.trim() ? `${shown.length} of ${turns.length} turns` : `${turns.length} turns`}</p>
                  <ol className="min-h-0 flex-1 space-y-2.5 overflow-y-auto pr-1" aria-label="Transcript">
                    {shown.map((t, i) => (
                      <li key={i} className="text-[13px] leading-relaxed">
                        <p className="flex items-baseline gap-2"><span className="font-bold" style={{ color: speakerColor(t.key) }}>{t.name}</span>
                          <span className="tabular text-[11px] text-muted">{clock(t.start)}</span></p>
                        <p className="text-ink-2">{t.text}</p>
                      </li>))}
                  </ol>
                </>)}
      </div>
    </>
  );
}

function SummaryPreview({ node, graph, onPick, onOpen, onClose }: PreviewProps) {
  const mid = node.meeting_id!;
  const d = useMeeting(mid);
  const s = d?.m?.summary;
  const topics = (graph.adj.get(node.id) ?? []).map((id) => graph.byId.get(id)!).filter((n) => n?.kind === "topic");
  const engine = node.engine?.startsWith("local/") ? `this PC (${node.engine.slice(6)})` : node.engine ?? "AI";
  const items = s?.action_items ?? [];
  return (
    <>
      <PanelHeader node={node} title={node.label.replace(/^Summary · /, "")} onClose={onClose}
        sub={<>Summary by {engine}{node.open_actions ? ` · ${node.open_actions} open action item${node.open_actions === 1 ? "" : "s"}` : ""}</>}
        actions={<>
          <Button size="sm" variant="primary" onClick={() => onOpen(mid)}><ExternalLink size={14} aria-hidden /> Open meeting</Button>
          <Button size="sm" onClick={() => onPick(`meeting:${mid}`)}><FileText size={14} aria-hidden /> Transcript</Button>
        </>} />
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pt-3 pr-1 text-[13px] leading-relaxed">
        {!d ? <p className="flex items-center gap-2 text-sm text-muted"><Loader2 size={14} className="animate-spin" aria-hidden /> Loading summary…</p>
          : !s ? <p className="text-sm text-muted">This summary isn't available any more.</p> : (<>
            {s.outcome && <p className="rounded-lg bg-amber-soft/60 px-3 py-2"><b>Outcome: </b>{s.outcome}</p>}
            <p>{s.summary}</p>
            {topics.length > 0 && <div className="flex flex-wrap gap-1.5">{topics.map((t) => <LinkChip key={t.id} node={t} onPick={onPick} />)}</div>}
            {(s.key_points?.length ?? 0) > 0 && <section><Label>Key points</Label>
              <ul className="list-disc space-y-1 pl-4">{s.key_points!.map((k, i) => <li key={i}>{k}</li>)}</ul></section>}
            {s.decisions.length > 0 && <section><Label>Decisions</Label>
              <ul className="list-disc space-y-1 pl-4">{s.decisions.map((x, i) => <li key={i}>{x}</li>)}</ul></section>}
            {items.length > 0 && <section><Label>Action items</Label>
              <ul className="space-y-1.5">{items.map((a, i) => {
                const closed = a.done || (a.status && a.status !== "new");
                return <li key={i} className={cn("rounded-lg border border-line bg-white/60 px-2.5 py-1.5", closed && "text-muted")}>
                  <p className={cn(a.done && "line-through")}>{a.task}</p>
                  <p className="text-[11px] text-muted">{[a.owner, a.due_date ?? a.due, a.status && a.status !== "new" ? a.status : a.done ? "done" : null]
                    .filter(Boolean).join(" · ") || "open"}</p></li>;
              })}</ul>
              <p className="mt-1.5 text-[11px] text-muted">Turn these into tasks or reminders from the meeting page.</p></section>}
          </>)}
      </div>
    </>
  );
}

function HubPreview({ node, graph, onPick, onClose }: PreviewProps) {
  const meetings = (node.meetings ?? []).map((mid) => graph.byId.get(`meeting:${mid}`)).filter((n): n is GraphNode => !!n)
    .sort((a, b) => (b.started_at ?? "").localeCompare(a.started_at ?? ""));
  // what else these meetings link to: topics for a person, people for a topic (most shared first)
  const otherKind: GraphNodeKind = node.kind === "person" ? "topic" : "person";
  const related = useMemo(() => {
    const count = new Map<string, number>();
    for (const m of meetings) {
      for (const hub of [m.id, `summary:${m.meeting_id}`]) {
        for (const id of graph.adj.get(hub) ?? []) {
          if (id !== node.id && graph.byId.get(id)?.kind === otherKind) count.set(id, (count.get(id) ?? 0) + 1);
        }
      }
    }
    return [...count.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10).map(([id]) => graph.byId.get(id)!);
  }, [meetings, graph, node.id, otherKind]);
  return (
    <>
      <PanelHeader node={node} title={node.label} onClose={onClose}
        sub={`In ${node.meetings?.length ?? 0} meeting${node.meetings?.length === 1 ? "" : "s"}${meetings.length < (node.meetings?.length ?? 0) ? " (some hidden)" : ""}`} />
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pt-3 pr-1">
        <section>
          <Label>Meetings</Label>
          <ul className="space-y-1.5">
            {meetings.map((m) => {
              const sum = graph.byId.get(`summary:${m.meeting_id}`);
              return (
                <li key={m.id} className="rounded-xl border border-line bg-white/60">
                  <button type="button" onClick={() => onPick(m.id)} className="w-full rounded-t-xl px-3 py-2 text-left hover:bg-white">
                    <span className="block truncate text-sm font-semibold">{m.label}</span>
                    <span className="text-xs text-muted">{describe(m)}</span>
                  </button>
                  {sum && <button type="button" onClick={() => onPick(sum.id)}
                    className="flex w-full items-start gap-1.5 rounded-b-xl border-t border-line px-3 py-1.5 text-left text-xs text-ink-2 hover:bg-white">
                    <Sparkles size={12} className="mt-0.5 shrink-0 text-amber" aria-hidden /><span className="line-clamp-2">{sum.gist || "Summary"}</span></button>}
                </li>);
            })}
          </ul>
        </section>
        {related.length > 0 && <section>
          <Label>{node.kind === "person" ? "Topics they come up in" : "People who talk about it"}</Label>
          <div className="flex flex-wrap gap-1.5">{related.map((r) => <LinkChip key={r.id} node={r} onPick={onPick} />)}</div>
        </section>}
      </div>
    </>
  );
}

function Guide({ counts }: { counts: MeetingGraph["counts"] }) {
  return (
    <div className="space-y-4 text-[13px] leading-relaxed text-ink-2">
      <div>
        <h2 className="text-lg font-extrabold tracking-tight text-ink">Explore your meetings</h2>
        <p className="mt-1">Pick any dot to read it here. Links show which meetings share people and topics — the same links your
          Obsidian notes make.</p>
      </div>
      <ul className="space-y-2">
        {(["meeting", "summary", "person", "topic"] as GraphNodeKind[]).map((k) => (
          <li key={k} className="flex items-start gap-2.5">
            <span className="mt-0.5"><Swatch kind={k} /></span>
            <span><b className="text-ink">{KINDS[k].plural}</b> <span className="tabular text-muted">({counts[k] ?? 0})</span><br />
              {{ meeting: "A meeting — click it to read the transcript. Dashed: not transcribed yet.",
                summary: "The meeting's summary, beside its meeting: outcome, decisions, action items.",
                person: "Named speakers. Bigger rings join more meetings.",
                topic: "From summaries and your vocabulary. Shared topics link meetings." }[k]}</span>
          </li>))}
      </ul>
      <p className="rounded-lg bg-paper-2 px-3 py-2 text-xs text-muted">Hover to see a dot's links · drag to pan or move a dot · scroll or
        +/− to zoom · 0 fits everything · Esc clears · double-click a meeting to open it for editing.</p>
    </div>
  );
}

type GraphIndex = { byId: Map<string, GraphNode>; adj: Map<string, string[]> };
type PreviewProps = { node: GraphNode; graph: GraphIndex; onPick: (id: string) => void; onOpen: (mid: string) => void; onClose: () => void };

// ---- the tab -----------------------------------------------------------------------------------------------------
export function MeetingGraphView({ selected, onSelect, onOpenMeeting }: {
  selected: string | null; onSelect: (id: string | null) => void; onOpenMeeting: (meetingId: string) => void;
}) {
  const { meetingEvt } = useLive();
  const [graph, setGraph] = useState<MeetingGraph | null>(null);
  const [err, setErr] = useState("");
  const [archived, setArchived] = useState(false);
  const [hidden, setHidden] = useState<Set<GraphNodeKind>>(new Set());
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const [centerReq, setCenterReq] = useState<{ id: string; n: number } | null>(null);

  const load = useCallback(() => {
    api.meetingGraph(archived).then((g) => { setGraph(g); setErr(""); }).catch((e: Error) => setErr(e.message));
  }, [archived]);
  useEffect(() => { load(); }, [load]);
  const tick = meetingEvt.status === "TRANSCRIBING" && meetingEvt.progress !== undefined;
  useEffect(() => { if (meetingEvt.n > 0 && !tick) load(); }, [meetingEvt, tick, load]);

  const index: GraphIndex = useMemo(() => {
    const byId = new Map((graph?.nodes ?? []).map((n) => [n.id, n]));
    const adj = new Map<string, string[]>();
    for (const e of graph?.edges ?? []) {
      (adj.get(e.source) ?? adj.set(e.source, []).get(e.source)!).push(e.target);
      (adj.get(e.target) ?? adj.set(e.target, []).get(e.target)!).push(e.source);
    }
    return { byId, adj };
  }, [graph]);

  // visible graph: hidden kinds drop out; with summaries hidden, their topics hang off the meeting instead
  const { nodes, edges } = useMemo(() => {
    const ns = (graph?.nodes ?? []).filter((n) => !hidden.has(n.kind));
    const keep = new Set(ns.map((n) => n.id));
    const seen = new Set<string>();
    const es: { source: string; target: string; kind: keyof typeof LINK_LEN }[] = [];
    for (const e of graph?.edges ?? []) {
      let { source } = e;
      if (hidden.has("summary") && source.startsWith("summary:")) source = `meeting:${source.slice(8)}`;
      if (source === e.target || !keep.has(source) || !keep.has(e.target) || seen.has(source + ">" + e.target)) continue;
      seen.add(source + ">" + e.target);
      es.push({ source, target: e.target, kind: e.kind });
    }
    return { nodes: ns, edges: es };
  }, [graph, hidden]);

  const found = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return [];
    return nodes.filter((n) => n.kind !== "summary" && n.label.toLowerCase().includes(s))
      .sort((a, b) => Number(!a.label.toLowerCase().startsWith(s)) - Number(!b.label.toLowerCase().startsWith(s)));
  }, [nodes, q]);
  const matches = useMemo(() => (q.trim() ? new Set(found.map((n) => n.id)) : null), [found, q]);

  const pick = useCallback((id: string) => { onSelect(id); setCenterReq((c) => ({ id, n: (c?.n ?? 0) + 1 })); }, [onSelect]);
  const choose = (n: GraphNode | undefined) => { if (!n) return; pick(n.id); setQ(""); setActive(0); };
  const toggle = (k: GraphNodeKind) => setHidden((h) => { const n = new Set(h); if (n.has(k)) n.delete(k); else n.add(k); return n; });

  const sel = selected ? index.byId.get(selected) : undefined;
  const props = sel && { node: sel, graph: index, onPick: pick, onOpen: onOpenMeeting, onClose: () => onSelect(null) };
  const empty = graph && graph.nodes.length === 0;

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
      <Card aria-label="Meetings graph" className="flex h-[max(480px,calc(100vh-250px))] flex-col p-3">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <div className="relative min-w-52 flex-1 sm:max-w-72">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" aria-hidden />
            <Input role="combobox" aria-expanded={found.length > 0} aria-controls="graph-found" aria-autocomplete="list"
              aria-activedescendant={found.length ? `graph-found-${Math.min(active, found.length - 1)}` : undefined}
              aria-label="Find a meeting, person or topic" placeholder="Find a meeting, person, topic…" value={q} className="h-9 pl-8"
              onChange={(e) => { setQ(e.target.value); setActive(0); }}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, found.length - 1)); }
                else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
                else if (e.key === "Enter") { e.preventDefault(); choose(found[Math.min(active, found.length - 1)]); }
                else if (e.key === "Escape") { setQ(""); }
              }} />
            {q.trim() && (
              <ul id="graph-found" role="listbox" aria-label="Matching nodes"
                className="absolute left-0 right-0 top-full z-20 mt-1 max-h-72 overflow-y-auto rounded-xl border border-line bg-white p-1 shadow-lg">
                {found.length === 0 ? <li className="px-2.5 py-2 text-sm text-muted">Nothing matches “{q.trim()}”.</li>
                  : found.slice(0, 12).map((n, i) => (
                    <li key={n.id} id={`graph-found-${i}`} role="option" aria-selected={i === active}
                      onMouseDown={(e) => { e.preventDefault(); choose(n); }} onMouseEnter={() => setActive(i)}
                      className={cn("flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm", i === active && "bg-paper-2")}>
                      <Swatch kind={n.kind} /><span className="min-w-0 flex-1 truncate">{n.label}</span>
                      <span className="shrink-0 text-[11px] text-muted">{n.kind === "meeting" ? (n.started_at ? shortDate(n.started_at) : "") : describe(n)}</span>
                    </li>))}
              </ul>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Show in the graph">
            <span className="inline-flex h-8 items-center gap-1.5 rounded-full border border-line bg-white/60 px-2.5 text-xs font-semibold text-ink-2">
              <Swatch kind="meeting" /> {KINDS.meeting.plural} <span className="tabular text-muted">{graph?.counts.meeting ?? 0}</span></span>
            {TOGGLABLE.map((k) => (
              <button key={k} type="button" aria-pressed={!hidden.has(k)} onClick={() => toggle(k)}
                title={hidden.has(k) ? `Show ${KINDS[k].plural.toLowerCase()}` : `Hide ${KINDS[k].plural.toLowerCase()}`}
                className={cn("inline-flex h-8 items-center gap-1.5 rounded-full border px-2.5 text-xs font-semibold transition-colors",
                  hidden.has(k) ? "border-dashed border-line bg-transparent text-muted line-through decoration-1"
                    : "border-line bg-white text-ink-2 hover:border-ink")}>
                <Swatch kind={k} /> {KINDS[k].plural} <span className="tabular text-muted no-underline">{graph?.counts[k] ?? 0}</span>
              </button>))}
          </div>
          <label className="ml-auto flex items-center gap-1.5 text-xs font-semibold text-ink-2">
            <input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Include archived</label>
        </div>
        <div className="min-h-0 flex-1">
          {err ? <div className="grid h-full place-items-center"><div className="text-center text-sm">
            <p className="text-[#8a3b2e]">Couldn't load the graph: {err}</p>
            <Button size="sm" className="mt-2" onClick={load}>Try again</Button></div></div>
            : !graph ? <p className="grid h-full place-items-center text-sm text-muted"><span className="flex items-center gap-2">
              <Loader2 size={14} className="animate-spin" aria-hidden /> Drawing your meetings…</span></p>
              : empty ? <div className="grid h-full place-items-center p-6"><Empty>{archived ? "No meetings yet."
                : "No meetings to show. Record one on PIP (hold KEY, choose Meeting) or import audio — archived meetings appear with “Include archived”."}</Empty></div>
                : <GraphCanvas nodes={nodes} edges={edges} selected={selected} matches={matches} centerReq={centerReq}
                  onSelect={onSelect} onOpen={onOpenMeeting} />}
        </div>
      </Card>
      <Card aria-label="Preview" className="flex h-[max(480px,calc(100vh-250px))] flex-col p-4">
        {props ? (sel.kind === "meeting" ? <TranscriptPreview key={sel.id} {...props} />
          : sel.kind === "summary" ? <SummaryPreview key={sel.id} {...props} /> : <HubPreview key={sel.id} {...props} />)
          : <Guide counts={graph?.counts ?? {}} />}
      </Card>
    </div>
  );
}
