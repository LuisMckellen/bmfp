// Generates schema-faithful FAKE fixtures for docs/dev/. Values are placeholders, not results.
// usage: node docs/dev/make-fixture.cjs docs
"use strict";
const fs = require("fs");
const path = require("path");
const out = process.argv[2];
if (!out) throw new Error("usage: node docs/dev/make-fixture.cjs docs");

function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const R = rng(7);
const r3 = (x) => Math.round(x * 1000) / 1000;
const r4 = (x) => Math.round(x * 10000) / 10000;

// ---- geometry ---------------------------------------------------------------
const PHI = (1 + Math.sqrt(5)) / 2;
function signs(v) {
  let out = [[]];
  for (const c of v) {
    const next = [];
    for (const o of out) {
      if (c === 0) next.push([...o, 0]);
      else { next.push([...o, c]); next.push([...o, -c]); }
    }
    out = next;
  }
  return out;
}
const cyc = (v) => [v, [v[1], v[2], v[0]], [v[2], v[0], v[1]]];
const allPerm = (v) => [
  [v[0], v[1], v[2]], [v[0], v[2], v[1]], [v[1], v[0], v[2]],
  [v[1], v[2], v[0]], [v[2], v[0], v[1]], [v[2], v[1], v[0]],
];
function uniq(pts) {
  const m = new Map();
  for (const p of pts) m.set(p.map((x) => x.toFixed(6)).join(","), p);
  return [...m.values()];
}
function cageFrom(pts) {
  pts = uniq(pts);
  const rr = Math.max(...pts.map((p) => Math.hypot(...p)));
  pts = pts.map((p) => p.map((x) => x / rr));
  pts.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]);
  let dmin = Infinity;
  for (let i = 0; i < pts.length; i++)
    for (let j = i + 1; j < pts.length; j++)
      dmin = Math.min(dmin, Math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1], pts[i][2] - pts[j][2]));
  const edges = [];
  for (let i = 0; i < pts.length; i++)
    for (let j = i + 1; j < pts.length; j++) {
      const d = Math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1], pts[i][2] - pts[j][2]);
      if (d < dmin * (1 + 1e-6)) edges.push([i, j]);
    }
  const n = pts.length;
  const adj = Array.from({ length: n }, () => []);
  for (const [a, b] of edges) { adj[a].push(b); adj[b].push(a); }
  let diam = 0;
  for (let s = 0; s < n; s++) {
    const dist = new Array(n).fill(-1); dist[s] = 0; const q = [s];
    while (q.length) { const u = q.shift(); for (const v of adj[u]) if (dist[v] < 0) { dist[v] = dist[u] + 1; q.push(v); } }
    diam = Math.max(diam, ...dist);
  }
  return { n, links: edges.length, diameter: diam, edges, coords: pts.map((p) => p.map(r4)), adj };
}
const C12pts = []; for (const p of allPerm([3, 1, 1])) for (const s of signs(p)) if (s.filter((x) => x < 0).length % 2 === 0) C12pts.push(s);
const C20pts = [...signs([1, 1, 1])];
for (const v of cyc([0, 1 / PHI, PHI])) C20pts.push(...signs(v));
const C24pts = []; for (const p of allPerm([0, 1, 2])) C24pts.push(...signs(p));
const C60pts = [];
for (const base of [[0, 1, 3 * PHI], [1, 2 + PHI, 2 * PHI], [PHI, 2, 2 * PHI + 1]])
  for (const v of cyc(base)) C60pts.push(...signs(v));
const cages = { C12: cageFrom(C12pts), C20: cageFrom(C20pts), C24: cageFrom(C24pts), C60: cageFrom(C60pts) };
for (const k of Object.keys(cages)) console.error(k, cages[k].n, cages[k].links, cages[k].diameter);

// ---- scenarios (fake dynamics) ---------------------------------------------
function scenario(id, title, blurb, cageName, duration, opts) {
  const c = cages[cageName];
  const n = c.n;
  const rnd = rng(id.length * 97 + duration);
  const st = new Array(n).fill("G");
  const stems = [0, Math.floor(n / 3), Math.floor((2 * n) / 3)];
  for (let i = 0; i < n; i++) { const u = rnd(); st[i] = u < 0.35 ? "A" : u < 0.55 ? "S" : "G"; }
  for (const s of stems) st[s] = "A";
  const frames = { dt: 1, states: [], loads: [], stems: [], captains: [] };
  const series = { t: [], sent: [], delivered: [], deliverable_sent: [], deliverable_delivered: [], active: [], standby: [], ghost: [], dead: [], transmissions: [], mean_hops: [], max_load_ratio: [] };
  const events = [];
  let captains = [1, 2, 3];
  for (let t = 0; t < duration; t++) {
    if (t > 0 && t % 30 === 0 && opts.vsepr) {
      const hot = []; for (let i = 0; i < n; i++) if (st[i] === "A" && !stems.includes(i) && rnd() < 0.12) hot.push(i);
      const promoted = [];
      for (const h of hot) { st[h] = "G"; for (let k = 0; k < (opts.damped ? 1 : 2); k++) { const g = st.findIndex((x, j) => x === "G" && !hot.includes(j) && !promoted.includes(j) && rnd() < 0.3); if (g >= 0) { st[g] = "A"; promoted.push(g); } } }
      events.push({ t: t + 0.0, kind: "VSEPR", text: `FIXTURE: VSEPR demoted ${hot.length ? "node " + hot.join(", ") : "nobody"}; promoted ${promoted.join(", ") || "none"}` });
    }
    if (t > 0 && t % 10 === 0 && t % 30 !== 0) {
      const a = st.findIndex((x, j) => x === "A" && !stems.includes(j) && rnd() < 0.2);
      const s = st.findIndex((x) => x === "S");
      if (a >= 0 && s >= 0) { st[a] = "S"; st[s] = "A"; events.push({ t: t + 0.0, kind: "RESONANCE", text: `FIXTURE: resonance swapped ${a} out, ${s} in` }); }
    }
    if (opts.killAt !== undefined && t === opts.killAt) {
      const k = Math.round(n * opts.killFrac);
      const order = [...Array(n).keys()].sort(() => rnd() - 0.5).slice(0, k);
      for (const i of order) st[i] = "D";
      events.push({ t: t + 0.0, kind: "KILL", text: `FIXTURE: scripted kill of ${k} nodes` });
    }
    if (opts.killAt !== undefined && t === opts.killAt + 3) events.push({ t: t + 0.0, kind: "DETECT", text: "FIXTURE: failures detected" });
    if (opts.recover && t === opts.killAt + 5) {
      for (let i = 0; i < n; i++) if (st[i] === "D") st[i] = opts.recover === "meiosis" && rnd() < 0.35 ? "A" : "S";
      for (const s of stems) st[s] = "A";
      events.push({ t: opts.killAt + 3.0, kind: "DEATH_EVENT", text: "FIXTURE: cell death event raised" });
      events.push({ t: t - 0.5, kind: opts.recover === "meiosis" ? "MEIOSIS_DONE" : "MITOSIS_DONE", text: `FIXTURE: ${opts.recover} complete` });
    }
    if (opts.killAt !== undefined && !opts.recover && t === opts.killAt + 23) {
      for (let i = 0; i < n; i++) if (st[i] === "D") st[i] = "S";
      events.push({ t: t + 0.0, kind: "JOIN", text: "FIXTURE: vacant slots refilled" });
    }
    if (t > 0 && t % 300 === 0) { captains = captains.map((c) => (c + 3) % n); events.push({ t: t + 0.0, kind: "CAPTAIN_TERM", text: `FIXTURE: captains now ${captains.join(", ")}` }); }
    const loads = st.map((x) => (x === "A" ? String(Math.min(9, Math.floor(rnd() * (opts.hot ? 10 : 6)))) : "0"));
    frames.states.push(st.join(""));
    frames.loads.push(loads.join(""));
    frames.stems.push(stems.filter((s) => st[s] !== "D"));
    frames.captains.push(captains.filter((c) => st[c] !== "D"));
    const cnt = (ch) => st.filter((x) => x === ch).length;
    const sent = 15 + Math.floor(rnd() * 10);
    const dead = cnt("D");
    const dsent = Math.max(0, Math.round(sent * (0.55 - dead / n * 0.4)));
    const ratio = dead > 0 && dead === n ? 0 : Math.max(0, Math.min(1, 0.93 - (dead / n) * 0.5 + (rnd() - 0.5) * 0.06));
    series.t.push(t);
    series.sent.push(sent);
    series.delivered.push(Math.round(sent * ratio * 0.6));
    series.deliverable_sent.push(dsent);
    series.deliverable_delivered.push(Math.round(dsent * ratio));
    series.active.push(cnt("A")); series.standby.push(cnt("S")); series.ghost.push(cnt("G")); series.dead.push(dead);
    series.transmissions.push(Math.round(sent * (opts.hot ? 9 : 4) * (0.8 + rnd() * 0.4)));
    series.mean_hops.push(r3(3 + rnd() * 2));
    series.max_load_ratio.push(r3(1.5 + rnd() * (opts.hot ? 3 : 1.5)));
  }
  events.sort((a, b) => a.t - b.t);
  const summary = {
    fixture: true, cage: cageName, n, deliverable_ratio: 0.111, delivery_ratio: 0.222, sent: 12345, mean_hops: 3.33,
    state_changes_per_min: 1.11, drops_dst_asleep: 111, drops_no_route: 2, drops_congestion: 3, drops_stale_view: 4,
    drops_link_loss: 5, drops_dst_dead: 6, kill_at: opts.killAt === undefined ? null : opts.killAt, rto_service_s: null, path: "none",
  };
  const config = {
    cage: cageName, duration, seed: 1, send_rate: opts.hot ? 40 : 20, hotspot_fraction: 0.3,
    routing: opts.routing || "chill", k_paths: 3, adaptive_threshold: 0.9, path_rotation: true,
    relay_capacity: 40, relay_burst: 10, hop_latency: 0.005, link_loss: opts.hot ? 0.05 : 0,
    max_retries: 2, retry_timeout: 0.2, active_fraction: 0.35, standby_fraction: 0.3, stem_count: 3,
    resonance: "on", resonance_period: 10, resonance_swaps: 2, vsepr: opts.damped ? "damped" : "naive",
    vsepr_period: 30, vsepr_factor: 2, vsepr_promote: 2, vsepr_cooldown_cycles: 2,
    vsepr_max_demotions_frac: 0.1, fairness_max_ghost_cycles: 2, captain_count: 3, captain_term: 300,
    detect_delay: 3, checkpoint_period: 10, death_threshold: 0.5, mitosis_time: 1.5, meiosis_time: 1.5,
    churn_rate: 0, rejoin_delay: 20, kill_at: opts.killAt === undefined ? null : opts.killAt,
    kill_fraction: opts.killFrac || 0.5, record_frames: true,
  };
  return { id, title, blurb, cage: cageName, duration, seed: 1, config, frames, series, events, events_total: events.length, summary };
}
const scenarios = [
  scenario("baseline", "FIXTURE · Naive VSEPR, as written", "FIXTURE: placeholder blurb. Fake states, fake numbers.", "C60", 600, { vsepr: true }),
  scenario("damped", "FIXTURE · Damped VSEPR", "FIXTURE: placeholder blurb for the damped variant.", "C60", 600, { vsepr: true, damped: true }),
  scenario("kill-half", "FIXTURE · Kill half at 120 s", "FIXTURE: placeholder blurb.", "C60", 300, { vsepr: true, killAt: 120, killFrac: 0.5 }),
  scenario("kill-60", "FIXTURE · Kill 60%, mitosis", "FIXTURE: placeholder blurb.", "C60", 300, { vsepr: true, killAt: 120, killFrac: 0.6, recover: "mitosis" }),
  scenario("kill-all", "FIXTURE · Kill everyone, meiosis", "FIXTURE: placeholder blurb.", "C60", 300, { vsepr: true, killAt: 120, killFrac: 1, recover: "meiosis" }),
  scenario("hell-duplicate", "FIXTURE · Hell mode, duplicate", "FIXTURE: placeholder blurb.", "C60", 300, { vsepr: true, hot: true, routing: "duplicate" }),
  scenario("c20", "FIXTURE · The C20 cell", "FIXTURE: placeholder blurb.", "C20", 300, { vsepr: true }),
];

const mmm = (m, spread, n) => ({ mean: r3(m), min: r3(m - spread), max: r3(m + spread), n: n === undefined ? 5 : n });
const seeds = [1, 2, 3, 4, 5];
const topology = Object.entries(cages).map(([name, c]) => {
  const pp = {};
  for (let k = 1; k <= 6; k++) pp[String(k)] = k < 3 ? 0 : r4(Math.min(1, (k - 2) * (k - 2) * (6 / c.n) * 0.05));
  const solid = { C12: 'truncated tetrahedron', C20: 'dodecahedron', C24: 'truncated octahedron', C60: 'truncated icosahedron' }[name];
  return { cage: name, solid, n: c.n, links: c.links, degree: 3, diameter: c.diameter, min_vertex_cut: 3, faces: c.links - c.n + 2, partition_probability: pp, partition_exact: [1, 2, 3, 4, 5, 6].map((k) => k < 4), cds_lower_bound: (c.n - 2) / 2, cds_greedy: c.n / 2 + 1, cds_exact: null };
});
const variant = (a, b) => ({
  state_changes_per_min: mmm(a, 0.4), flaps: mmm(a * 3, 1), active_fraction_start: mmm(0.35, 0),
  active_fraction_end: mmm(b, 0.04), active_fraction_mean: mmm((0.35 + b) / 2, 0.02),
  mean_max_avg_load_ratio: mmm(2.2, 0.2), deliverable_ratio: mmm(0.9, 0.02), ghost_time_share: mmm(0.4, 0.03),
  demotions: mmm(a * 10, 3), promotions: mmm(a * 18, 4),
});
const recSeries = (killFrac, rec) => {
  const t = [], ratio = [];
  for (let i = 60; i < 300; i++) { t.push(i); ratio.push(i < 120 ? 0.92 : i < 125 ? (killFrac === 1 ? null : r3(0.92 * (1 - killFrac))) : rec ? 0.9 : r3(0.92 * (1 - killFrac * 0.6))); }
  return { seed: 1, t, ratio };
};
const recovery = {
  seeds, duration: 300, kill_at: 120,
  cases: {
    kill50: { rto_service_s: mmm(30, 5, 3), rto_journal_formula_s: 3, rpo_s: mmm(5, 3), death_event: false, path: "none", ratio_dip: mmm(0.4, 0.1), series: recSeries(0.5, false) },
    kill60: { rto_service_s: mmm(8, 2), rto_journal_formula_s: 4.5, rpo_s: mmm(5, 3), death_event: true, path: "mitosis", ratio_dip: mmm(0.6, 0.1), series: recSeries(0.6, true) },
    kill100: { rto_service_s: mmm(9, 2), rto_journal_formula_s: 4.5, rpo_s: mmm(5, 3), death_event: true, path: "meiosis", ratio_dip: mmm(1, 0), series: recSeries(1, true) },
  },
};
const hell = { seeds: [1, 2, 3], duration: 300, rows: [], static_cell: { active_fraction: 1, vsepr: 'off', resonance: 'off' }, static_rows: [] };
for (const routing of ["chill", "duplicate", "stripe"])
  for (const send_rate of [10, 20, 40, 80])
    for (const link_loss of [0, 0.05]) {
      const base = routing === "chill" ? 3.5 : routing === "duplicate" ? 9.5 : 4.2;
      hell.rows.push({
        routing, send_rate, link_loss,
        deliverable_ratio: mmm(0.95 - send_rate / 400 - link_loss, 0.01),
        tx_per_delivered: mmm(base + send_rate / 40 + link_loss * 20, 0.2),
        duplicates_per_delivered: mmm(routing === "duplicate" ? 1.8 : 0, routing === "duplicate" ? 0.1 : 0),
        out_of_order_per_delivered: mmm(routing === "chill" ? 0.001 : 0.02, 0.001),
        congestion_drops: mmm(send_rate * 2, 3),
      });
      hell.static_rows.push({
        routing, send_rate, link_loss,
        deliverable_ratio: mmm(0.97 - link_loss, 0.01),
        tx_per_delivered: mmm(base * 1.6 + link_loss * 30, 0.3),
        duplicates_per_delivered: mmm(routing === "duplicate" ? 2.1 : 0, 0),
        out_of_order_per_delivered: mmm(0.01, 0.001),
        congestion_drops: mmm(0, 0),
      });
    }
const offline = { seeds, duration: 600, rows: [0.2, 0.35, 0.5].map((a) => ({ active_fraction: a, share_to_asleep: mmm(0.5 - a * 0.4, 0.02) })), ghost_pool_rows: [0, 0.15, 0.3].map((s) => ({ standby_fraction: s, share_to_asleep: mmm(0.45 - s, 0.02), delivery_ratio: mmm(0.55 + s, 0.02) })) };
const churn = { seeds, duration: 300, rows: [0, 0.02, 0.05, 0.1].map((c) => ({ churn_rate: c, deliverable_ratio: mmm(0.92 - c, 0.01), stale_view_drops: mmm(c * 400, 3), state_changes_per_min: mmm(2 + c * 10, 0.3) })) };
const F = (id, problem, verdict) => ({ id, problem, journal_ref: "Part VII · Open problems", verdict, measured: `FIXTURE: placeholder sentence for “${problem}”. Not a result.`, next_step: "FIXTURE: placeholder next step." });
const findings = [
  { ...F("topology-cut", "No single failed checkpoint can cut the ball in half", "confirmed"), journal_ref: "Figure 0 · Why a soccer ball" },
  F("offline-delivery", "Offline delivery", "partly"),
  F("gateway-server", "The gateway is a server", "not simulated"),
  F("push-wake", "Waking a phone needs push", "not simulated"),
  { ...F("hell-ambiguity", "Hell mode is ambiguous", "confirmed"), journal_ref: "Part VII · Open problems (v1.2)" },
  F("vsepr-oscillation", "VSEPR will oscillate", "confirmed"),
  F("captain-election", "Captains are not elected yet", "partly"),
  F("rto-arithmetic", "RTO arithmetic", "refuted"),
  F("group-rekeying", "Group token rekeying", "not simulated"),
  { ...F("c20-count", "What the number in C20 counts", "partly"), journal_ref: "Part VII · Open problems (v1.7, Figure 3)" },
  { ...F("valid-active-sets", "Three valid ACTIVE sets of 4 in a 12-node cell", "refuted"), journal_ref: "v1.7b · Figure 6" },
];
const bmfp = {
  schema: 1,
  generator: "FIXTURE (docs/dev) — not produced by bmfp export-web",
  cages: Object.fromEntries(Object.entries(cages).map(([k, c]) => [k, { n: c.n, links: c.links, diameter: c.diameter, edges: c.edges, coords: c.coords }])),
  states: { A: "ACTIVE", S: "STANDBY", G: "GHOST", D: "DEAD" },
  scenarios,
  experiments: { topology, vsepr: { seeds, duration: 600, variants: { naive: variant(4, 0.55), damped: variant(1.2, 0.36), off: variant(0.4, 0.35) } }, recovery, hell, offline, churn },
  findings,
};
fs.writeFileSync(path.join(out, "dev", "fixture-bmfp-data.js"), "window.BMFP_DATA = " + JSON.stringify(bmfp) + ";\n");

console.error("wrote fixture");
