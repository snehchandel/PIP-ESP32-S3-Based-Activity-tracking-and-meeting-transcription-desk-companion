/* A small force-directed layout (the Obsidian graph feel) with no dependencies: nodes push each other apart
   (grid-bucketed, so it stays fast with hundreds of nodes), links pull like springs, a weak pull keeps loose
   clusters near the middle and nodes never overlap. Positions survive rebuilds (filters, live updates), so the
   graph never jumps: only new nodes find their place. */

export interface SimNode {
  id: string; x: number; y: number; vx: number; vy: number; r: number;
  fx: number | null; fy: number | null; // pinned while dragged
}
export interface SimLink { s: number; t: number; len: number; k: number; bias: number }

const REPEL = 320;        // charge strength
const CUTOFF = 260;       // repulsion range (px); beyond it only the centre pull acts
const CENTER = 0.035;
const DECAY = 0.58;       // velocity kept per tick
const ALPHA_DECAY = 0.0228;
export const ALPHA_MIN = 0.003;

export class ForceSim {
  alpha = 1;
  nodes: SimNode[];
  links: SimLink[];
  private index = new Map<string, number>();

  /** links: `stiff` multiplies the spring (1 = normal); springs are weaker at busy nodes, as in d3-force, so hubs
      don't drag their neighbours around and a node stays beside the one it belongs to. */
  constructor(nodes: { id: string; r: number }[], links: { source: string; target: string; len: number; stiff?: number }[],
    previous?: Map<string, { x: number; y: number }>) {
    this.nodes = nodes.map((n, i) => {
      const p = previous?.get(n.id);
      // new nodes start on a sunflower spiral (even, deterministic spread)
      const rad = 18 * Math.sqrt(i + 0.5), a = i * Math.PI * (3 - Math.sqrt(5));
      return { id: n.id, r: n.r, x: p?.x ?? rad * Math.cos(a), y: p?.y ?? rad * Math.sin(a), vx: 0, vy: 0, fx: null, fy: null };
    });
    this.nodes.forEach((n, i) => this.index.set(n.id, i));
    const pairs = links.flatMap((l) => {
      const s = this.index.get(l.source), t = this.index.get(l.target);
      return s === undefined || t === undefined ? [] : [{ s, t, len: l.len, stiff: l.stiff ?? 1 }];
    });
    const deg = new Array<number>(this.nodes.length).fill(0);
    for (const l of pairs) { deg[l.s]++; deg[l.t]++; }
    this.links = pairs.map((l) => ({ s: l.s, t: l.t, len: l.len, k: Math.min(1, l.stiff / Math.min(deg[l.s], deg[l.t])),
      bias: deg[l.s] / (deg[l.s] + deg[l.t]) }));
    // a new node with a placed neighbour starts beside it instead of on the spiral
    if (previous?.size) {
      for (const l of this.links) {
        const a = this.nodes[l.s], b = this.nodes[l.t];
        const aNew = !previous.has(a.id), bNew = !previous.has(b.id);
        if (aNew && !bNew) { a.x = b.x + jitter(a.id) * l.len; a.y = b.y + jitter(b.id) * l.len; }
        if (bNew && !aNew) { b.x = a.x + jitter(b.id) * l.len; b.y = a.y + jitter(a.id) * l.len; }
      }
      const fresh = this.nodes.filter((n) => !previous.has(n.id)).length;
      this.alpha = fresh ? Math.min(1, 0.3 + fresh / Math.max(8, this.nodes.length)) : 0.08;
    }
  }

  get(id: string): SimNode | undefined {
    const i = this.index.get(id);
    return i === undefined ? undefined : this.nodes[i];
  }

  reheat(to = 0.3): void { this.alpha = Math.max(this.alpha, to); }
  get settled(): boolean { return this.alpha < ALPHA_MIN; }

  tick(): void {
    const { nodes, links, alpha } = this;
    // springs
    for (const l of links) {
      const a = nodes[l.s], b = nodes[l.t];
      let dx = b.x + b.vx - a.x - a.vx, dy = b.y + b.vy - a.y - a.vy;
      const d = Math.hypot(dx, dy) || 0.01;
      const f = ((d - l.len) / d) * alpha * l.k;
      dx *= f; dy *= f;
      b.vx -= dx * l.bias; b.vy -= dy * l.bias; a.vx += dx * (1 - l.bias); a.vy += dy * (1 - l.bias);
    }
    // repulsion + collision, only between nodes in neighbouring grid cells
    const grid = new Map<string, number[]>();
    nodes.forEach((n, i) => {
      const k = `${Math.floor(n.x / CUTOFF)},${Math.floor(n.y / CUTOFF)}`;
      const cell = grid.get(k);
      if (cell) cell.push(i); else grid.set(k, [i]);
    });
    for (let i = 0; i < nodes.length; i++) {
      const a = nodes[i];
      const cx = Math.floor(a.x / CUTOFF), cy = Math.floor(a.y / CUTOFF);
      for (let gx = cx - 1; gx <= cx + 1; gx++) for (let gy = cy - 1; gy <= cy + 1; gy++) {
        for (const j of grid.get(`${gx},${gy}`) ?? []) {
          if (j <= i) continue;
          const b = nodes[j];
          let dx = b.x - a.x, dy = b.y - a.y;
          let d2 = dx * dx + dy * dy;
          if (d2 > CUTOFF * CUTOFF) continue;
          if (d2 < 1) { dx = jitter(a.id + b.id); dy = jitter(b.id + a.id); d2 = dx * dx + dy * dy + 0.01; }
          const d = Math.sqrt(d2);
          let f = (REPEL * alpha) / d2;
          const min = a.r + b.r + 6;
          if (d < min) f += ((min - d) / d) * 0.5; // no overlaps, whatever alpha is
          a.vx -= dx * f; a.vy -= dy * f; b.vx += dx * f; b.vy += dy * f;
        }
      }
    }
    for (const n of nodes) {
      n.vx -= n.x * CENTER * alpha; n.vy -= n.y * CENTER * alpha;
      if (n.fx !== null && n.fy !== null) { n.x = n.fx; n.y = n.fy; n.vx = 0; n.vy = 0; continue; }
      n.vx *= DECAY; n.vy *= DECAY;
      n.x += n.vx; n.y += n.vy;
    }
    this.alpha += (0 - this.alpha) * ALPHA_DECAY;
  }

  positions(): Map<string, { x: number; y: number }> {
    return new Map(this.nodes.map((n) => [n.id, { x: n.x, y: n.y }]));
  }
}

/** A stable pseudo-random number in [-0.5, 0.5) from a string (layouts look the same every time). */
function jitter(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return ((h >>> 0) % 1000) / 1000 - 0.5;
}
