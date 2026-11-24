import { useEffect, useRef, useState } from "react";
import { useLive } from "../api/live";

/** Live 400x300 reflective-LCD mirror: the actual DUMP_FB pixels from the board or sim_rlcd. */
export function RlcdMirror({ scale = 2 }: { scale?: number }) {
  const { fbVersion, health } = useLive();
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const inflight = useRef(false);
  const linked = health?.link_state === "TETHERED";

  useEffect(() => {
    if (!linked || inflight.current) return;
    inflight.current = true;
    const ctl = new AbortController();
    fetch(`/api/v1/device/framebuffer.png?v=${fbVersion}`, { signal: ctl.signal, cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error(String(r.status));
        const url = URL.createObjectURL(await r.blob());
        setSrc((old) => { if (old) URL.revokeObjectURL(old); return url; });
        setFailed(false);
      })
      .catch(() => setFailed(true))
      .finally(() => { inflight.current = false; });
    return () => ctl.abort();
  }, [fbVersion, linked]);

  return (
    <div className="inline-block rounded-[28px] bg-[#e98a2c] p-3 shadow-[inset_0_-6px_0_#c86a16]">
      <div className="rounded-[18px] bg-ink p-3">
        <div className="relative overflow-hidden rounded-md bg-[#d9d6cc]" style={{ width: 400 * scale, maxWidth: "100%", aspectRatio: "4 / 3" }}>
          {src && linked ? (
            <img src={src} alt="Live PIP screen" className="rlcd-canvas h-full w-full mix-blend-multiply" width={400} height={300} />
          ) : (
            <p className="absolute inset-0 grid place-items-center px-6 text-center text-sm text-ink-2">
              {linked ? (failed ? "Waiting for the screen…" : "Loading screen…") : "PIP is not connected. Plug it in over USB or start the simulator."}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
