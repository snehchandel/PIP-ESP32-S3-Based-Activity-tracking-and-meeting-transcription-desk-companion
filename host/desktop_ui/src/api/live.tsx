// Live store: canonical state from REST, refreshed by WebSocket events (reconnecting, no page reloads).
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api } from "./client";
import type { FullState, Health } from "./types";

export type Conn = "connecting" | "live" | "offline";

interface LiveValue {
  state: FullState | null;
  health: Health | null;
  conn: Conn;
  fbVersion: number;
  error: string | null;
  refresh: () => Promise<void>;
  run: <T>(fn: () => Promise<T>) => Promise<T | undefined>;
}

const LiveCtx = createContext<LiveValue | null>(null);

export function LiveProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<FullState | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [conn, setConn] = useState<Conn>("connecting");
  const [fbVersion, setFbVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const refreshTimer = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, h] = await Promise.all([api.state(), api.health()]);
      setState(s);
      setHealth(h);
      setError(null);
    } catch {
      setConn("offline");
    }
  }, []);

  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current !== null) return;
    refreshTimer.current = window.setTimeout(() => {
      refreshTimer.current = null;
      void refresh();
    }, 60);
  }, [refresh]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: number | undefined;
    let closed = false;
    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws/events`);
      ws.onopen = () => {
        setConn("live");
        void refresh();
      };
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data as string) as { event: string; data: Record<string, unknown> };
        if (msg.event === "timer_tick") {
          setState((s) => (s ? { ...s, timer: { ...s.timer, remaining_ms: Number(msg.data.remaining_ms),
            state: msg.data.state as FullState["timer"]["state"] } } : s));
          setFbVersion((v) => v + 1);
          return;
        }
        if (msg.event === "framebuffer_updated") return;
        scheduleRefresh();
        setFbVersion((v) => v + 1);
      };
      ws.onclose = () => {
        setConn("offline");
        if (!closed) retry = window.setTimeout(connect, 1500);
      };
      ws.onerror = () => ws?.close();
    };
    connect();
    const poll = window.setInterval(() => void api.health().then(setHealth).catch(() => setConn("offline")), 2000);
    return () => {
      closed = true;
      window.clearTimeout(retry);
      window.clearInterval(poll);
      ws?.close();
    };
  }, [refresh, scheduleRefresh]);

  const run = useCallback(async <T,>(fn: () => Promise<T>) => {
    try {
      const r = await fn();
      setError(null);
      scheduleRefresh();
      return r;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return undefined;
    }
  }, [scheduleRefresh]);

  const value = useMemo(() => ({ state, health, conn, fbVersion, error, refresh, run }),
    [state, health, conn, fbVersion, error, refresh, run]);
  return <LiveCtx.Provider value={value}>{children}</LiveCtx.Provider>;
}

export function useLive(): LiveValue {
  const v = useContext(LiveCtx);
  if (!v) throw new Error("useLive outside LiveProvider");
  return v;
}

export function fmtMs(ms: number): string {
  const s = Math.ceil(Math.max(0, ms) / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
