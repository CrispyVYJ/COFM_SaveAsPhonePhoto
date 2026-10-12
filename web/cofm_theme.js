/**
 * Comfy OFM — node theme.
 *
 * Themes any node whose CATEGORY starts with "ComfyOFM/". Nothing else on the
 * canvas is touched: no globals are reassigned, no prototypes are patched, and
 * every hook is installed per-instance on COFM nodes only. Nodes from other
 * packs render exactly as they always did.
 *
 * Verified against comfyui_frontend_package 1.45.20 (ComfyUI 0.27.0):
 *   - LGraphCanvas.drawNode() only calls ctx.clip() when node.clip_area is set,
 *     which is undefined by default. onDrawForeground therefore runs UNCLIPPED,
 *     which is what lets the circuit traces radiate outside the node bounds.
 *     onDrawBackground would not work: it runs before the title bar and slots
 *     and would be painted over.
 *   - node.onDrawTitleBar early-returns out of drawTitleBarBackground, so we
 *     own the header outright.
 *   - node.strokeStyles is a per-instance record, left alone here so LiteGraph
 *     keeps drawing its own selection/error outlines underneath ours.
 *
 * Heads-up: if Comfy.VueNodes.Enabled is ever turned on, LiteGraph skips all
 * canvas node rendering and NO canvas theme draws — this one or anyone else's.
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

/* ==========================================================================
 * THE ONE CONFIG OBJECT. Every tunable lives here.
 * ========================================================================== */

const COFM = {
  // Master switch. false = COFM nodes render as stock ComfyUI nodes.
  enabled: true,

  // Only nodes whose CATEGORY starts with this get themed. Must match
  // COFM_THEME["namespace"] in cofm_theme.py.
  namespace: "ComfyOFM/",

  palette: {
    cyan: "#4FD6F0",
    mint: "#6FE8B0",
    lime: "#A6F065",
    violet: "#8B7BF0",
    magenta: "#E070C8",
    bg: "#0C121F", // node body fill
    bg2: "#131B2E", // panel fill behind widgets
    trace: "#1E2C45", // inner border + traces at rest
    error: "#FF4557", // error state
  },

  // Neon ring, in order. Wraps magenta -> cyan so the drift is seamless.
  gradient: ["#4FD6F0", "#6FE8B0", "#A6F065", "#8B7BF0", "#E070C8"],

  // 1. Header bar
  header: {
    driftSpeed: 0.045, // gradient travel, cycles/second
    sampleStops: 14, // smoothness of the drifting ramp
    dim: 0.55, // brightness at rest (1.0 = full neon)
    dimActive: 1.0, // brightness when hovered/selected/running
    underline: 0.22, // dark separator under the header, 0 = off
  },

  // 2 + 3. Body, panel, inner border, corners
  body: {
    radius: 8, // rounded corners
    borderWidth: 1, // inner border stroke
    panel: true, // fill a panel behind the widget stack
    panelInset: 5, // horizontal inset of that panel
    panelRadius: 5,
  },

  // 4. Selection glow
  selection: {
    enabled: true,
    blur: 20,
    width: 1.6,
    spread: 2.5, // how far outside the body the glow ring sits
    alpha: 0.85,
  },

  // 5. Circuit-trace routing — the signature effect.
  //
  // Each trace is one continuous run that enters one edge of the node, routes
  // across the body behind the widgets, and exits the far edge, terminating in
  // a pad at each end. The in-body stretch is drawn before LiteGraph paints the
  // widgets, so a trace passing under a control is occluded by it and reappears
  // on the far side — the routing reads as if it goes through the node.
  traces: {
    enabled: true,
    min: 3, // per node
    max: 6,
    width: 1.3,
    dotRadius: [1.7, 2.6],
    overshoot: [16, 38], // how far past each edge the trace runs before its pad
    run: [11, 28], // orthogonal run, px
    elbow: [5, 12], // 45-degree jog, px
    elbowChance: 0.55, // chance of a jog between runs, while inside the body
    margin: 12, // keep in-body routing this far off the parallel edges
    horizontalBias: 0.62, // share of traces that cross left-to-right
    bodyAlpha: 0.5, // in-body stretch is dimmer than the outside runs
    restAlpha: 0.85, // dim state (#1E2C45)
    litAlpha: 0.5, // gradient wash along a lit trace
    pulseSpeed: 0.3, // travel, cycles/second
    pulseLength: 0.16, // fraction of the trace lit by the pulse head
    pulseGlow: 6, // shadow blur on the pulse
    dotGlow: 7, // shadow blur on a pad as the pulse reaches it
  },

  // 6. Execution state
  exec: {
    speed: 3.0, // pulse speed multiplier while running
    brightness: 1.35, // trace brightness multiplier while running
  },

  // 7. Error state
  error: {
    borderWidth: 1.8,
    traceAlpha: 1.0,
  },

  // 8. Collapsed nodes keep the header, border, glow and traces.
  collapsed: { traces: true },

  // Animation cost control. The canvas is only marked dirty when at least one
  // COFM node is actually animating (hovered, selected, running, or errored);
  // an idle graph of COFM nodes costs zero redraws no matter how many there are.
  animation: {
    enabled: true,
    fps: 30, // redraw cap
  },
};

/* ==========================================================================
 * Colour helpers
 * ========================================================================== */

const hexToRgb = (hex) => {
  const h = hex.replace("#", "");
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
};

const GRAD_RGB = COFM.gradient.map(hexToRgb);
const ERROR_RGB = hexToRgb(COFM.palette.error);

const rgba = (rgb, a = 1, mul = 1) =>
  `rgba(${Math.min(255, Math.round(rgb[0] * mul))},${Math.min(255, Math.round(rgb[1] * mul))},${Math.min(255, Math.round(rgb[2] * mul))},${a})`;

/**
 * Sample the neon ring cyclically. u wraps, so magenta blends back into cyan
 * and a drifting gradient has no visible seam.
 */
function ringAt(u) {
  const n = GRAD_RGB.length;
  const x = (((u % 1) + 1) % 1) * n;
  const i = Math.floor(x);
  const f = x - i;
  const a = GRAD_RGB[i % n];
  const b = GRAD_RGB[(i + 1) % n];
  return [
    a[0] + (b[0] - a[0]) * f,
    a[1] + (b[1] - a[1]) * f,
    a[2] + (b[2] - a[2]) * f,
  ];
}

/* ==========================================================================
 * Deterministic per-node randomness
 *
 * Trace geometry is generated once from a hash of the node id, so a node's
 * traces are stable across frames, pans, reloads and workflow saves. Random
 * geometry regenerated per frame would strobe.
 * ========================================================================== */

function hashId(id) {
  const s = String(id);
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const rnd = (r, lo, hi) => lo + r() * (hi - lo);

/* ==========================================================================
 * Geometry
 * ========================================================================== */

/** Node bounds in node-local space, collapsed-aware. */
function nodeBounds(node) {
  const th = LiteGraph.NODE_TITLE_HEIGHT;
  if (node.flags?.collapsed) {
    const w = node._collapsed_width || LiteGraph.NODE_COLLAPSED_WIDTH || 80;
    return { x: 0, y: -th, w, h: th, collapsed: true };
  }
  const size = node.renderingSize || node.size;
  return { x: 0, y: 0, w: size[0], h: size[1], collapsed: false };
}

/**
 * Build the PCB traces for one node.
 *
 * A trace is one continuous run that starts at a pad outside the node, crosses
 * the body, and ends at a pad outside the opposite edge. Routing is orthogonal
 * with 45-degree jogs, and jogs only happen while the run is inside the body —
 * outside the node the trace runs dead straight into its pad, which is what
 * makes the board read as entering and leaving rather than wandering.
 *
 * Built in travel-axis space (u along the crossing, v across it) and mapped
 * back to x/y at the end, so one routine covers both orientations.
 *
 * Cached; only rebuilt when the node's footprint changes.
 */
function buildTraces(node, b) {
  const cfg = COFM.traces;
  const r = mulberry32(hashId(node.id));
  const count = Math.round(rnd(r, cfg.min, cfg.max));
  const traces = [];

  for (let i = 0; i < count; i++) {
    const horizontal = r() < cfg.horizontalBias;

    // u = the axis the trace travels along, v = across it.
    const uMin = horizontal ? b.x : b.y;
    const uLen = horizontal ? b.w : b.h;
    const vMin = horizontal ? b.y : b.x;
    const vLen = horizontal ? b.h : b.w;

    // Keep routing off the parallel edges, but never more than a third of the
    // span — collapsed nodes are only a title bar tall.
    const m = Math.min(cfg.margin, vLen * 0.32);
    const vLo = vMin + m;
    const vHi = vMin + vLen - m;

    const outA = rnd(r, cfg.overshoot[0], cfg.overshoot[1]);
    const outB = rnd(r, cfg.overshoot[0], cfg.overshoot[1]);
    const uEnd = uMin + uLen + outB;

    let u = uMin - outA;
    let v = vLo + r() * Math.max(0, vHi - vLo);

    const pts = [];
    const push = () => pts.push(horizontal ? [u, v] : [v, u]);
    push();

    let guard = 0;
    while (u < uEnd && guard++ < 48) {
      // Orthogonal run.
      u = Math.min(u + rnd(r, cfg.run[0], cfg.run[1]), uEnd);
      push();
      if (u >= uEnd) break;

      // 45-degree jog, only while inside the body and only if there is room
      // across. Outside the node the trace stays straight into its pad.
      const inside = u > uMin && u < uMin + uLen;
      if (!inside || r() >= cfg.elbowChance || vHi - vLo < 2) continue;

      const d = Math.min(rnd(r, cfg.elbow[0], cfg.elbow[1]), (vHi - vLo) / 2);
      let dir = r() < 0.5 ? 1 : -1;
      if (v + dir * d < vLo || v + dir * d > vHi) dir = -dir; // bounce off the edge
      const nv = v + dir * d;
      if (nv < vLo || nv > vHi) continue;

      u = Math.min(u + d, uEnd);
      v = nv;
      push();
    }

    // Drop zero-length segments so the arc-length table stays strictly
    // increasing — subPath() divides by segment length.
    const clean = [pts[0]];
    for (let k = 1; k < pts.length; k++) {
      const p = pts[k], q = clean[clean.length - 1];
      if (Math.hypot(p[0] - q[0], p[1] - q[1]) > 1e-6) clean.push(p);
    }
    if (clean.length < 2) continue;

    // Arc-length table so the pulse travels at constant speed regardless of
    // how many segments a given trace happens to have.
    const cum = [0];
    for (let k = 1; k < clean.length; k++) {
      cum.push(cum[k - 1] + Math.hypot(clean[k][0] - clean[k - 1][0], clean[k][1] - clean[k - 1][1]));
    }

    traces.push({
      pts: clean,
      cum,
      total: cum[cum.length - 1],
      dot: rnd(r, cfg.dotRadius[0], cfg.dotRadius[1]),
      phase: r(), // desynchronise the pulses
      hue: r(), // where on the ring this trace sits
    });
  }
  return traces;
}

/** Extract the sub-polyline between two arc-length positions. */
function subPath(tr, from, to) {
  const { pts, cum, total } = tr;
  const a = Math.max(0, from) * total;
  const b = Math.min(1, to) * total;
  if (b <= a) return null;

  const at = (dist) => {
    for (let k = 1; k < cum.length; k++) {
      if (dist <= cum[k]) {
        const seg = cum[k] - cum[k - 1] || 1;
        const f = (dist - cum[k - 1]) / seg;
        return [
          pts[k - 1][0] + (pts[k][0] - pts[k - 1][0]) * f,
          pts[k - 1][1] + (pts[k][1] - pts[k - 1][1]) * f,
          k,
        ];
      }
    }
    const last = pts[pts.length - 1];
    return [last[0], last[1], cum.length - 1];
  };

  const s = at(a);
  const e = at(b);
  const out = [[s[0], s[1]]];
  for (let k = s[2]; k < e[2]; k++) out.push(pts[k]);
  out.push([e[0], e[1]]);
  return out;
}

const strokePts = (ctx, pts) => {
  ctx.beginPath();
  ctx.moveTo(pts[0][0], pts[0][1]);
  for (let k = 1; k < pts.length; k++) ctx.lineTo(pts[k][0], pts[k][1]);
  ctx.stroke();
};

/* ==========================================================================
 * Node state
 * ========================================================================== */

const themed = new Set(); // live COFM nodes, for the animation scan

const isError = (node) => !!(node.__cofm?.error || node.has_errors);
const isExec = (node) => !!node.__cofm?.exec;

/** rest | hover | select | exec | error — drives brightness and pulse speed. */
function activity(node) {
  if (isError(node)) return "error";
  if (isExec(node)) return "exec";
  if (node.selected) return "select";
  if (node.mouseOver) return "hover";
  return "rest";
}

const isAnimating = (node) => activity(node) !== "rest";

/* ==========================================================================
 * Drawing
 * ========================================================================== */

function drawHeader(node, ctx, titleHeight, size) {
  const R = COFM.body.radius;
  const collapsed = !!node.flags?.collapsed;
  const w = collapsed
    ? node._collapsed_width || LiteGraph.NODE_COLLAPSED_WIDTH || 80
    : size[0];
  const t = performance.now() / 1000;
  const act = activity(node);
  const bright = act === "rest" ? COFM.header.dim : COFM.header.dimActive;

  ctx.save();
  ctx.beginPath();
  // Collapsed nodes are a self-contained pill; expanded ones round only the
  // top corners so the header meets the body flush.
  ctx.roundRect(0, -titleHeight, w, titleHeight, collapsed ? [R] : [R, R, 0, 0]);

  if (act === "error") {
    ctx.fillStyle = rgba(ERROR_RGB, 0.9);
  } else {
    const phase = COFM.animation.enabled ? t * COFM.header.driftSpeed : 0;
    const g = ctx.createLinearGradient(0, 0, w, 0);
    const n = COFM.header.sampleStops;
    for (let i = 0; i <= n; i++) {
      const u = i / n;
      g.addColorStop(u, rgba(ringAt(u + phase), 1, bright));
    }
    ctx.fillStyle = g;
  }
  ctx.fill();

  // Separator so the title text keeps its footing against the bright ramp.
  if (COFM.header.underline > 0 && !collapsed) {
    ctx.fillStyle = `rgba(0,0,0,${COFM.header.underline})`;
    ctx.fillRect(0, -2, w, 2);
  }
  ctx.restore();
}

/**
 * Panel behind the widget stack. Drawn in the foreground hook, which runs
 * before LiteGraph lays out and draws widgets — so this lands underneath them
 * rather than covering them.
 */
function drawPanel(node, ctx, b) {
  if (!COFM.body.panel || b.collapsed || !node.widgets?.length) return;
  const slots = Math.max(node.inputs?.length || 0, node.outputs?.length || 0);
  const fallback = slots * LiteGraph.NODE_SLOT_HEIGHT + 6;
  const top = node.widgets_start_y > 0 ? node.widgets_start_y - 3 : fallback;
  const inset = COFM.body.panelInset;
  const h = b.h - top - inset;
  if (h <= 6) return;

  ctx.save();
  ctx.beginPath();
  ctx.roundRect(b.x + inset, b.y + top, b.w - inset * 2, h, COFM.body.panelRadius);
  ctx.fillStyle = COFM.palette.bg2;
  ctx.fill();
  ctx.restore();
}

/** 1px inner border, hugging the inside of the body edge. */
function drawBorder(node, ctx, b) {
  const act = activity(node);
  const lw = act === "error" ? COFM.error.borderWidth : COFM.body.borderWidth;
  const o = lw / 2;
  ctx.save();
  ctx.lineWidth = lw;
  ctx.strokeStyle = act === "error" ? rgba(ERROR_RGB, 0.95) : COFM.palette.trace;
  ctx.beginPath();
  ctx.roundRect(b.x + o, b.y + o, b.w - lw, b.h - lw, Math.max(0, COFM.body.radius - o));
  ctx.stroke();
  ctx.restore();
}

/**
 * Run `fn` clipped to either the inside of the body or everything outside it,
 * so one polyline can be drawn at two different strengths without splitting
 * the geometry. The outside case uses an even-odd fill rule: a very large rect
 * with the body punched out of it as a hole.
 */
function clipped(ctx, b, inside, fn) {
  const R = COFM.body.radius;
  ctx.save();
  ctx.beginPath();
  if (inside) {
    ctx.roundRect(b.x, b.y, b.w, b.h, R);
    ctx.clip();
  } else {
    const pad = 4000;
    ctx.rect(b.x - pad, b.y - pad, b.w + pad * 2, b.h + pad * 2);
    ctx.roundRect(b.x, b.y, b.w, b.h, R);
    ctx.clip("evenodd");
  }
  fn();
  ctx.restore();
}

function drawSelectionGlow(node, ctx, b) {
  if (!COFM.selection.enabled || !node.selected) return;
  const cfg = COFM.selection;
  const t = performance.now() / 1000;
  // Canvas shadows take a single colour, so the glow is tinted by sampling the
  // ring at the current drift position — the hue travels with the header.
  const tint = isError(node)
    ? ERROR_RGB
    : ringAt(COFM.animation.enabled ? t * COFM.header.driftSpeed : 0.12);

  ctx.save();
  ctx.shadowColor = rgba(tint, cfg.alpha);
  ctx.shadowBlur = cfg.blur;
  ctx.strokeStyle = rgba(tint, cfg.alpha);
  ctx.lineWidth = cfg.width;
  const s = cfg.spread;
  ctx.beginPath();
  ctx.roundRect(
    b.x - s,
    b.y - s - (b.collapsed ? 0 : LiteGraph.NODE_TITLE_HEIGHT),
    b.w + s * 2,
    b.h + s * 2 + (b.collapsed ? 0 : LiteGraph.NODE_TITLE_HEIGHT),
    COFM.body.radius + s
  );
  // Two passes: the second rides the first's shadow to deepen the bloom.
  ctx.stroke();
  ctx.stroke();
  ctx.restore();
}

function drawTraces(node, ctx, b) {
  const cfg = COFM.traces;
  if (!cfg.enabled) return;
  if (b.collapsed && !COFM.collapsed.traces) return;

  const state = node.__cofm;
  const key = `${Math.round(b.w)}x${Math.round(b.h)}x${b.collapsed ? 1 : 0}`;
  if (!state.traces || state.key !== key) {
    state.traces = buildTraces(node, b);
    state.key = key;
  }

  const act = activity(node);
  const lit = act !== "rest";
  const err = act === "error";
  const t = performance.now() / 1000;
  const speed = cfg.pulseSpeed * (act === "exec" ? COFM.exec.speed : 1);
  const bright = act === "exec" ? COFM.exec.brightness : 1;
  const animate = COFM.animation.enabled;

  ctx.save();
  ctx.lineCap = "round";
  ctx.lineJoin = "round";

  for (const tr of state.traces) {
    const tint = err ? ERROR_RGB : ringAt(tr.hue + (animate ? t * COFM.header.driftSpeed : 0));
    const head = (t * speed + tr.phase) % 1;
    const pulse = animate && lit ? subPath(tr, head - cfg.pulseLength, head) : null;

    // The same polyline is drawn twice, once clipped to the body and once to
    // everything outside it, so the stretch crossing the node sits back as
    // background routing while the runs into the pads stay full strength.
    // Widgets are painted after this hook, so they occlude the in-body stretch
    // and the trace reappears past them.
    for (const inside of [true, false]) {
      const fade = inside ? cfg.bodyAlpha : 1;
      clipped(ctx, b, inside, () => {
        ctx.lineWidth = cfg.width;
        ctx.strokeStyle = err
          ? rgba(ERROR_RGB, cfg.restAlpha * fade)
          : `rgba(30,44,69,${cfg.restAlpha * fade})`;
        strokePts(ctx, tr.pts);

        if (!lit) return;
        ctx.strokeStyle = rgba(tint, (err ? COFM.error.traceAlpha : cfg.litAlpha) * 0.75 * fade, bright);
        strokePts(ctx, tr.pts);

        if (pulse) {
          ctx.save();
          ctx.shadowColor = rgba(tint, 0.9 * fade);
          ctx.shadowBlur = cfg.pulseGlow;
          ctx.strokeStyle = rgba(tint, fade, bright);
          ctx.lineWidth = cfg.width * 1.5;
          strokePts(ctx, pulse);
          ctx.restore();
        }
      });
    }

    // A pad at each end, outside the node. Each lights as the pulse reaches it:
    // the tail pad as the pulse leaves, the head pad as it arrives.
    for (const [pt, at] of [[tr.pts[0], 0], [tr.pts[tr.pts.length - 1], 1]]) {
      let alpha = 1;
      let glow = 0;
      if (lit && animate) {
        const near = at === 0
          ? Math.max(0, 1 - head / cfg.pulseLength)
          : Math.max(0, 1 - (1 - head) / cfg.pulseLength);
        glow = cfg.dotGlow * near;
        alpha = 0.55 + 0.45 * near;
      }
      ctx.save();
      if (glow > 0) {
        ctx.shadowColor = rgba(tint, 0.9);
        ctx.shadowBlur = glow;
      }
      ctx.fillStyle = lit ? rgba(tint, alpha, bright) : `rgba(30,44,69,${cfg.restAlpha})`;
      ctx.beginPath();
      ctx.arc(pt[0], pt[1], tr.dot, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }
  }
  ctx.restore();
}

/* ==========================================================================
 * Applying the theme to one node
 * ========================================================================== */

function themeNode(node) {
  if (!COFM.enabled || node.__cofm) return;
  node.__cofm = { traces: null, key: "", exec: false, error: false };

  // Body + fallback colours. LiteGraph reads these through renderingColor /
  // renderingBgColor, so they also cover anything we do not draw ourselves.
  node.color = COFM.palette.bg2;
  node.bgcolor = COFM.palette.bg;
  node.boxcolor = COFM.gradient[0];
  node.shape = "round"; // 3. rounded corners

  // 1. Header — early-returns out of LiteGraph's own title bar fill.
  node.onDrawTitleBar = function (ctx, titleHeight, size) {
    drawHeader(this, ctx, titleHeight, size);
  };

  // 2/4/5/6/7/8 — everything else. Foreground is unclipped, which is what
  // lets the traces leave the node's footprint.
  const prevForeground = node.onDrawForeground;
  node.onDrawForeground = function (ctx, canvas, canvasEl) {
    prevForeground?.call(this, ctx, canvas, canvasEl);
    if (!COFM.enabled) return;
    const b = nodeBounds(this);
    // Order matters: the panel backs the traces, the traces run over it, and
    // the border closes the edge on top so the trace passes under the rim.
    drawPanel(this, ctx, b);
    drawTraces(this, ctx, b);
    drawBorder(this, ctx, b);
    drawSelectionGlow(this, ctx, b);
  };

  const prevRemoved = node.onRemoved;
  node.onRemoved = function () {
    themed.delete(this);
    prevRemoved?.apply(this, arguments);
  };

  themed.add(node);
  startTicker();
}

/* ==========================================================================
 * Animation ticker
 *
 * One rAF loop for the whole canvas, capped at COFM.animation.fps. It marks
 * the canvas dirty only while at least one COFM node is animating, so an idle
 * graph costs nothing however many COFM nodes it holds. Redraw cost does not
 * scale with node count; the per-frame scan is a walk over a small Set.
 * ========================================================================== */

let rafId = null;
let lastFrame = 0;

function tick(now) {
  rafId = null;
  if (!COFM.enabled || !COFM.animation.enabled) return;

  let active = 0;
  for (const node of themed) {
    if (!node.graph) { themed.delete(node); continue; } // dropped from the graph
    if (isAnimating(node)) active++;
  }
  if (themed.size === 0) return; // nothing left to drive; loop stops

  const interval = 1000 / COFM.animation.fps;
  if (active > 0 && now - lastFrame >= interval) {
    lastFrame = now;
    app.canvas?.setDirty(true, true);
  }
  rafId = requestAnimationFrame(tick);
}

function startTicker() {
  if (rafId == null && COFM.enabled && COFM.animation.enabled) {
    rafId = requestAnimationFrame(tick);
  }
}

/* ==========================================================================
 * Execution + error state, from the backend event stream
 * ========================================================================== */

const nodeById = (id) => {
  try {
    return app.graph?.getNodeById?.(id) ?? null;
  } catch {
    return null;
  }
};

function setFlag(id, key, value) {
  const node = nodeById(id);
  if (node?.__cofm) {
    node.__cofm[key] = value;
    startTicker();
  }
}

function clearAll(keys) {
  for (const node of themed) {
    for (const k of keys) node.__cofm[k] = false;
  }
}

api.addEventListener("execution_start", () => {
  clearAll(["exec", "error"]);
  startTicker();
});

api.addEventListener("executing", ({ detail }) => {
  // 1.45.20 sends a bare node id (or null at end of run); older shapes send
  // an object. Accept both rather than pinning to one.
  const id = detail && typeof detail === "object" ? detail.node ?? detail.node_id : detail;
  clearAll(["exec"]);
  if (id != null) setFlag(id, "exec", true);
  startTicker();
});

api.addEventListener("progress_state", ({ detail }) => {
  const nodes = detail?.nodes;
  if (!nodes) return;
  clearAll(["exec"]);
  for (const [id, s] of Object.entries(nodes)) {
    if (s?.state === "running") setFlag(id, "exec", true);
    else if (s?.state === "error") setFlag(id, "error", true);
  }
  startTicker();
});

api.addEventListener("execution_error", ({ detail }) => {
  clearAll(["exec"]);
  if (detail?.node_id != null) setFlag(detail.node_id, "error", true);
  startTicker();
});

for (const evt of ["execution_success", "execution_interrupted"]) {
  api.addEventListener(evt, () => {
    clearAll(["exec"]);
    startTicker();
  });
}

/* ==========================================================================
 * Registration
 *
 * CATEGORY is the only selector. A new node needs zero styling code: land it
 * under ComfyOFM/ and it is themed. Nothing here can reach a node from any
 * other pack.
 * ========================================================================== */

// Several COFM packs ship this same file. The first one to load registers the
// theme; later copies stand down instead of throwing "already registered".
if (globalThis.cofmTheme) {
  console.info("[COFM] theme already registered by another COFM pack");
} else {
  app.registerExtension({
    name: "cofm.theme",

    async beforeRegisterNodeDef(nodeType, nodeData) {
      if (nodeData?.category?.startsWith(COFM.namespace)) {
        nodeType.__cofmThemed = true;
      }
    },

    nodeCreated(node) {
      if (!COFM.enabled) return;
      const flagged = node.constructor?.__cofmThemed;
      const category = node.constructor?.category ?? node.category;
      if (flagged || category?.startsWith?.(COFM.namespace)) themeNode(node);
    },
  });

  // Exposed for live tweaking from the browser console, e.g.
  //   cofmTheme.config.traces.enabled = false; cofmTheme.refresh();
  globalThis.cofmTheme = {
    config: COFM,
    nodes: themed,
    refresh() {
      for (const node of themed) {
        node.__cofm.traces = null;
        node.__cofm.key = "";
      }
      startTicker();
      app.canvas?.setDirty(true, true);
    },
  };
}
