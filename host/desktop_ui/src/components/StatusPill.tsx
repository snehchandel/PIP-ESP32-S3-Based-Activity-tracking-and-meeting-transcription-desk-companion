import { Link2, Link2Off, WifiOff } from "lucide-react";
import { useLive } from "../api/live";
import { Badge } from "./ui/primitives";

/** Calm, non-blocking link indicator: never clears forms, never shouts. */
export function StatusPill() {
  const { health, conn } = useLive();
  if (conn === "offline" || !health) {
    return <Badge tone="neutral" role="status" aria-live="polite"><WifiOff size={13} aria-hidden /> Service offline</Badge>;
  }
  if (health.link_state === "TETHERED") {
    const label = health.device_transport === "SIMULATOR" ? "Linked · Simulator" : "Linked · PIP device";
    return <Badge tone="sage" role="status" aria-live="polite"><Link2 size={13} aria-hidden /> {label}</Badge>;
  }
  return <Badge tone="neutral" role="status" aria-live="polite"><Link2Off size={13} aria-hidden /> Standalone / Disconnected</Badge>;
}
