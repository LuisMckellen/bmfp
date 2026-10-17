/* BMFP Design Journal: page logic. Every number shown comes from window.BMFP_DATA
   (written by `bmfp export-web`) or window.MESHGUARD_DATA (`meshguard export-web`).
   Missing keys render as an em dash; nothing here should throw on a partial export. */
(function () {
  "use strict";
  var C = window.BMFPCharts;
  var el = C.el, fmt = C.fmt, pct = C.pct, isNum = C.isNum;
  var reduceMQ = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : { matches: false };
  var D = null, MG = null;
  var FIXTURE = { bmfp: false };
  var cages = [];
  var DASH = "—";
  // CSS uses this to swap the header's scrolling nav for a compact menu on narrow screens
  document.documentElement.classList.add("js");

  // ---- helpers --------------------------------------------------------------
  function get(o, path, dflt) {
    var parts = Array.isArray(path) ? path : String(path).split(".");
    var cur = o;
    for (var i = 0; i < parts.length; i++) {
      if (cur === null || cur === undefined || typeof cur !== "object") return dflt;
      cur = cur[parts[i]];
    }
    return cur === undefined || cur === null ? dflt : cur;
  }
  function arr(v) { return Array.isArray(v) ? v : []; }
  function $(id) { return document.getElementById(id); }
  function safe(name, fn, host) {
    try { fn(); } catch (e) {
      console.error("[BMFP] " + name + " could not be drawn:", e);
      if (host) el("p", { class: "err" }, host, "This part could not be drawn from the data (" + name + ").");
    }
  }
  function store(key, val) {
    try {
      if (val === undefined) return window.localStorage.getItem(key);
      window.localStorage.setItem(key, val);
    } catch (e) { /* storage blocked: conveniences only */ }
    return null;
  }
  function slug(s) { return String(s || "").toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, ""); }
  function humanKey(k) {
    var map = {
      rto_service_s: "Service RTO (s)", rto_journal_formula_s: "Journal formula RTO (s)", rpo_s: "RPO (s)",
      death_event: "Death event", path: "Recovery path", ratio_dip: "Ratio dip", min_ratio_after_kill: "Lowest ratio after kill",
      baseline_ratio: "Ratio before the kill", first_delivery_after_kill_s: "First delivery after kill (s)", detect_time_s: "Detection delay (s), a journal input",
      kill_at: "Kill at (s)", killed: "Nodes killed", state_changes_per_min: "ACTIVE changes / min, all sources", flaps: "Flaps",
      active_fraction_start: "ACTIVE share, start", active_fraction_end: "ACTIVE share, end", active_fraction_mean: "ACTIVE share, mean",
      mean_max_avg_load_ratio: "Max / avg load", deliverable_ratio: "Deliverable ratio", ghost_time_share: "GHOST time share",
      demotions: "Demotions", promotions: "Promotions", tx_per_delivered: "Transmissions / delivered",
      duplicates_per_delivered: "Duplicates / delivered", out_of_order_per_delivered: "Out of order / delivered",
      congestion_drops: "Congestion drops", stale_view_drops: "Stale-view drops", share_to_asleep: "Sent to a sleeping device",
      initial_active_fraction: "ACTIVE share after start-up", delivery_ratio: "Delivery ratio, all messages", no_route_drops: "No-route drops",
      leaves: "Nodes that left", standby_fraction: "STANDBY share (setting)", active_fraction: "ACTIVE share (setting)", churn_rate: "Leaves per second",
      drops_stale_view: "Stale-view drops", drops_no_route: "No-route drops", captain_reelections: "Captain re-elections",
      skipped_cycles: "Cycles skipped, no captain", cds_impossible: "Backbone repairs that failed", kill_fraction: "Share killed",
      mean_paths: "Disjoint paths per message", mean_hops: "Hops per delivered message", p95_latency_ms: "Latency, 95th percentile (ms)",
      mean_latency_ms: "Mean latency (ms)", state_changes_per_min_vsepr: "ACTIVE changes / min from VSEPR", state_changes_per_min_resonance: "ACTIVE changes / min from resonance",
      state_changes_per_min_vsepr_repair: "ACTIVE changes / min from VSEPR's backbone repair",
      all_state_changes_per_min: "Any state change / min, incl. STANDBY ↔ GHOST", fairness_moves_per_min: "Fairness moves / min", vsepr_flaps: "VSEPR flaps",
      single_path_share: "Sends with one path only", refill_after_kill_s: "Empty slots refilled after (s)",
    };
    if (map[k]) return map[k];
    var s = String(k).replace(/_/g, " ");
    return s.charAt(0).toUpperCase() + s.slice(1);
  }
  function isMMM(v) { return v && typeof v === "object" && ("mean" in v || "min" in v || "max" in v); }
  function digitsFor(key) {
    if (/ratio|share|fraction|dip/.test(key)) return 3;
    if (/_s$/.test(key)) return 2;
    return 2;
  }
  // nSeeds: how many seeds the aggregate covers; when a metric has fewer values (n), say so
  function fmtVal(v, key, nSeeds) {
    if (v === null || v === undefined) return key === "rto_service_s" ? "never" : DASH;
    if (typeof v === "boolean") return v ? "yes" : "no";
    var asPct = isPctKey(key);
    if (isMMM(v)) {
      var d = digitsFor(key || "");
      if (!isNum(v.mean)) return key === "rto_service_s" ? "never" : DASH;
      var f1 = asPct ? function (x) { return (x * 100).toFixed(1); } : function (x) { return fmt(x, d); };
      var m = f1(v.mean) + (asPct ? "%" : "");
      if (isNum(v.min) && isNum(v.max) && f1(v.min) !== f1(v.max)) m += " (" + f1(v.min) + "–" + f1(v.max) + (asPct ? "%" : "") + ")";
      if (isNum(v.n) && isNum(nSeeds) && v.n < nSeeds) m += key === "rto_service_s" ? "; never in " + (nSeeds - v.n) + " of " + nSeeds : "; " + v.n + " of " + nSeeds + " seeds";
      return m;
    }
    if (typeof v === "number") return asPct ? pct(v, 1) : fmt(v, digitsFor(key || ""));
    if (Array.isArray(v)) return v.length <= 6 ? v.join(", ") : v.length + " values";
    if (typeof v === "object") return JSON.stringify(v).slice(0, 80);
    return String(v);
  }
  function isPctKey(k) { return /(^|_)(ratio|share|fraction|dip)(_|$)/.test(String(k || "")) && !/load|frac$/.test(String(k)); }
  function durText(d) { return isNum(d) ? fmt(d, 0) + " s runs" : null; }
  function genericRows(rows, firstKey, firstFmt, nSeeds) {
    rows = arr(rows).filter(function (r) { return r && typeof r === "object"; });
    var keys = [];
    rows.forEach(function (r) { Object.keys(r).forEach(function (k) { if (k !== firstKey && keys.indexOf(k) < 0) keys.push(k); }); });
    return {
      head: [humanKey(firstKey)].concat(keys.map(humanKey)),
      rows: rows.map(function (r) { return [firstFmt(r[firstKey])].concat(keys.map(function (k) { return fmtVal(r[k], k, nSeeds); })); }),
      num: [0].concat(keys.map(function (_, i) { return i + 1; })),
    };
  }
  function seedsText(s) {
    s = arr(s).filter(isNum);
    if (!s.length) return "seeds " + DASH;
    var contiguous = s.every(function (v, i) { return i === 0 || v === s[i - 1] + 1; });
    return (s.length === 1 ? "seed " : "seeds ") + (contiguous && s.length > 2 ? s[0] + "–" + s[s.length - 1] : s.join(", "));
  }
  function mmm(o) { return isMMM(o) ? o : { mean: isNum(o) ? o : null, min: null, max: null }; }

  // ---- data loading with a dev fixture fallback -----------------------------
  function ensureData(done) {
    var pending = 0;
    function finish() {
      D = window.BMFP_DATA || null;
      MG = window.MESHGUARD_DATA || null;
      done();
    }
    if (!window.BMFP_DATA) {
      pending++;
      FIXTURE.bmfp = true;
      var s = document.createElement("script");
      s.src = "dev/fixture-bmfp-data.js";
      s.onload = s.onerror = function () { if (--pending === 0) finish(); };
      document.body.appendChild(s);
    }
    if (pending === 0) finish();
  }

  function renderNotice() {
    var n = $("fixture-notice");
    var msgs = [];
    if (FIXTURE.bmfp && window.BMFP_DATA) msgs.push("Fixture data in use. data/bmfp-data.js was not found, so the simulator sections show made-up placeholder values from docs/dev/. They are not results. Run `bmfp export-web --out docs/data` to replace them.");
    if (!window.BMFP_DATA) msgs.push("No simulator data was found. Run `bmfp export-web --out docs/data`.");
    if (!window.MESHGUARD_DATA) msgs.push("No MeshGuard data was found. Run `meshguard export-web --out docs/data`.");
    if (msgs.length) { n.textContent = msgs.join(" "); n.hidden = false; }
  }

  // ---- state glyphs (shape + colour, same encoding as the canvas) ----------
  var STATES = [
    { k: "A", name: "ACTIVE", color: "var(--st-active)", flag: "STATE_FLAG 1", gloss: "carrying traffic" },
    { k: "S", name: "STANDBY", color: "var(--st-standby)", flag: "STATE_FLAG 2", gloss: "awake, holding ready" },
    { k: "G", name: "GHOST", color: "var(--st-ghost)", flag: "STATE_FLAG 0", gloss: "asleep, carries nothing" },
    { k: "D", name: "DEAD", color: "var(--st-dead)", flag: "not a flag", gloss: "node gone or slot vacant" },
  ];
  function glyph(kind, parent) {
    var s = C.svg("svg", { viewBox: "0 0 14 14", "aria-hidden": "true" }, parent);
    var g = function (t, a) { return C.svg(t, a, s); };
    if (kind === "A") g("circle", { cx: 7, cy: 7, r: 5.6, style: "fill:var(--st-active)" });
    else if (kind === "S") g("circle", { cx: 7, cy: 7, r: 4.4, style: "fill:var(--plate);stroke:var(--st-standby);stroke-width:2.6" });
    else if (kind === "G") g("circle", { cx: 7, cy: 7, r: 3.8, style: "fill:none;stroke:var(--st-ghost);stroke-width:1.3;opacity:.85" });
    else if (kind === "D") g("path", { d: "M3 3L11 11M11 3L3 11", style: "stroke:var(--st-dead);stroke-width:2.3;stroke-linecap:round;fill:none" });
    else if (kind === "stem") { g("circle", { cx: 7, cy: 7, r: 5.6, style: "fill:var(--st-active)" }); g("circle", { cx: 7, cy: 7, r: 1.8, style: "fill:var(--plate)" }); }
    else if (kind === "cap") { g("path", { d: "M4 13V2", style: "stroke:var(--ink);stroke-width:1.3;fill:none" }); g("path", { d: "M4 2L11 4.6L4 7.2Z", style: "fill:var(--ink)" }); }
    else if (kind === "halo") { g("circle", { cx: 7, cy: 7, r: 6.5, style: "fill:var(--st-active);opacity:.25" }); g("circle", { cx: 7, cy: 7, r: 3.6, style: "fill:var(--st-active)" }); }
    else if (kind === "confirmed") g("circle", { cx: 7, cy: 7, r: 5, style: "fill:var(--ink)" });
    else if (kind === "refuted") g("path", { d: "M3 3L11 11M11 3L3 11", style: "stroke:var(--ink);stroke-width:2;stroke-linecap:round;fill:none" });
    else if (kind === "partly") { g("circle", { cx: 7, cy: 7, r: 4.6, style: "fill:none;stroke:var(--ink);stroke-width:1.5" }); g("path", { d: "M7 2.4A4.6 4.6 0 0 1 7 11.6Z", style: "fill:var(--ink)" }); }
    else if (kind === "not simulated") g("circle", { cx: 7, cy: 7, r: 4.6, style: "fill:none;stroke:var(--ink);stroke-width:1.4;stroke-dasharray:2.2 1.8" });
    else if (kind === "negative") g("path", { d: "M2.5 7H11.5", style: "stroke:var(--ink);stroke-width:2.2;stroke-linecap:round" });
    else if (kind === "note") { g("circle", { cx: 7, cy: 7, r: 4.8, style: "fill:none;stroke:var(--ink);stroke-width:1.3" }); g("path", { d: "M7 6.2V10M7 4.1V4.2", style: "stroke:var(--ink);stroke-width:1.5;stroke-linecap:round" }); }
    else g("rect", { x: 2.5, y: 2.5, width: 9, height: 9, style: "fill:none;stroke:var(--ink);stroke-width:1.3" });
    return s;
  }
  function renderLegends() {
    var names = get(D, "states", {});
    STATES.forEach(function (s) { if (typeof names[s.k] === "string" && names[s.k]) s.name = names[s.k]; });
    document.querySelectorAll("[data-legend]").forEach(function (ul) {
      ul.textContent = "";
      STATES.forEach(function (s) {
        var li = el("li", null, ul);
        glyph(s.k, li);
        el("span", null, li, s.name + " · " + (s.k === "A" ? "filled" : s.k === "S" ? "ring" : s.k === "G" ? "hollow, faint" : "cross"));
      });
      if (ul.getAttribute("data-legend") === "states-full") {
        [["stem", "Stem node"], ["cap", "Captain"], ["halo", "Halo · relay load that second"]].forEach(function (p) {
          var li = el("li", null, ul);
          glyph(p[0], li);
          el("span", null, li, p[1]);
        });
      }
    });
  }
  function countStates(str) {
    var c = { A: 0, S: 0, G: 0, D: 0 };
    for (var i = 0; i < (str || "").length; i++) { var ch = str.charAt(i); if (c[ch] !== undefined) c[ch]++; }
    return c;
  }
  function frameAt(sc, i) {
    var f = get(sc, "frames", {});
    return {
      states: arr(f.states)[i] || "",
      loads: arr(f.loads)[i] || "",
      stems: arr(arr(f.stems)[i]),
      captains: arr(arr(f.captains)[i]),
    };
  }

  // ---- 1 · hero ---------------------------------------------------------------
  function renderHero() {
    var c60 = get(D, "cages.C60", null);
    var counts = $("hero-counts");
    var n = get(c60, "n"), links = get(c60, "links"), edges = arr(get(c60, "edges"));
    var degree = null;
    if (isNum(n) && edges.length) {
      var deg = new Array(n).fill(0);
      edges.forEach(function (e) { if (Array.isArray(e)) { deg[e[0]]++; deg[e[1]]++; } });
      var mn = Math.min.apply(null, deg), mx = Math.max.apply(null, deg);
      degree = mn === mx ? mn : mn + "–" + mx;
    }
    var vals = { n: n, links: links, degree: degree, diameter: get(c60, "diameter") };
    counts.querySelectorAll("[data-k]").forEach(function (s) {
      var v = vals[s.getAttribute("data-k")];
      s.textContent = v === null || v === undefined ? DASH : String(v);
    });
    var scs = arr(get(D, "scenarios"));
    var base = scs.filter(function (s) { return s && s.id === "baseline"; })[0] || scs.filter(function (s) { return s && s.cage === "C60"; })[0] || null;
    var cg = new window.BMFPCage($("hero-cage"), { tip: $("hero-tip"), autoRotate: true });
    cages.push(cg);
    cg.setCage(c60);
    var fr = frameAt(base, 0);
    cg.setFrame(fr.states, fr.loads, fr.stems, fr.captains);
    cg.loop();
    var t0 = get(base, "series.t", [])[0];
    var cnt = countStates(fr.states);
    $("hero-tag").textContent = "";
    var b = el("b", null, $("hero-tag"), "C60");
    $("hero-tag").appendChild(document.createTextNode(base ? " · " + (base.id || "") + " · t = " + (isNum(t0) ? t0 : 0) + " s" : ""));
    void b;
    if (base && fr.states) {
      $("hero-cap").textContent = "The C60 cell at the start of the baseline run (seed " + fmtVal(base.seed) + "): " +
        cnt.A + " ACTIVE, " + cnt.S + " STANDBY, " + cnt.G + " GHOST. Drag, or use the arrow keys, to turn it.";
    } else {
      $("hero-cap").textContent = "The C60 cage. No baseline frame was found in the data, so nodes are drawn without state. Drag to turn it.";
    }
    $("hero-cage").setAttribute("aria-label", "Ball-and-stick model of the C60 cell, " + fmtVal(n) + " nodes and " + fmtVal(links) + " links. " +
      (fr.states ? cnt.A + " ACTIVE, " + cnt.S + " STANDBY, " + cnt.G + " GHOST at the start of the baseline run. " : "") + "Drag, or use the arrow keys, to turn it.");
  }

  // ---- 2 · the cell, live ------------------------------------------------------
  var JOURNAL_KEYS = {
    k_paths: ["Disjoint paths per send", "v1.0 / v1.2, “3 exits”"],
    adaptive_threshold: ["Hell-mode switch, relay utilisation", "v1.7a, 90%"],
    path_rotation: ["Path rotation", "v1.4"],
    hop_latency: ["Latency per hop", "v1.7a, edge cluster"],
    stem_count: ["Stem nodes", "v1.7e"],
    vsepr_period: ["VSEPR period", "v1.7d"],
    vsepr_factor: ["VSEPR threshold, × average", "v1.7d"],
    vsepr_promote: ["Promoted per demotion", "v1.7d"],
    fairness_max_ghost_cycles: ["Max GHOST cycles in a row", "v1.7c"],
    captain_count: ["Captains", "v1.7c"],
    captain_term: ["Captain term", "v1.7c"],
    detect_delay: ["Death detection", "v1.7e"],
    checkpoint_period: ["Checkpoint period", "v1.7e"],
    death_threshold: ["Death threshold, share unreachable", "v1.7e, “more than half”"],
    mitosis_time: ["Mitosis time", "v1.7e"],
    meiosis_time: ["Meiosis time", "v1.7e"],
  };
  // the journal's Part IX asks to "kill half the nodes": only that value is a journal figure;
  // any other kill share (0.6, 1.0) is a choice made for the scenario
  var JOURNAL_KILL = { label: "Share of nodes killed", src: "Part IX, “kill half”", value: 0.5 };
  var ASSUME_KEYS = {
    send_rate: "Send rate, whole cell", hotspot_fraction: "Share sent to one popular node", relay_capacity: "Relay capacity",
    relay_burst: "Relay token burst", link_loss: "Per-hop loss", max_retries: "Retries (resend is v1.3)", retry_timeout: "Retry timeout",
    active_fraction: "Initial ACTIVE share", standby_fraction: "Initial STANDBY share", resonance_period: "Resonance period",
    resonance_swaps: "Swaps per resonance", churn_rate: "Churn, leaves per second", rejoin_delay: "Rejoin delay",
    vsepr_cooldown_cycles: "Damped: cooldown cycles", vsepr_max_demotions_frac: "Damped: max demotions per cycle",
    hotspot_node: "Popular node", resonance_phase: "First resonance round", checkpoint_phase: "First checkpoint",
  };
  var CHOICE_KEYS = {
    cage: "Cage", duration: "Duration", seed: "Seed", routing: "Routing", vsepr: "VSEPR variant", resonance: "Resonance",
    kill_at: "Kill time", kill_fraction: "Share of nodes killed",
  };
  var UNITS = {
    hop_latency: " s", vsepr_period: " s", captain_term: " s", detect_delay: " s", checkpoint_period: " s", mitosis_time: " s",
    meiosis_time: " s", retry_timeout: " s", resonance_period: " s", rejoin_delay: " s", kill_at: " s", duration: " s",
    resonance_phase: " s", checkpoint_phase: " s",
    send_rate: " msg/s", relay_capacity: " msg/s", churn_rate: " /s",
  };
  function hasKill(cfg) { return isNum(get(cfg, "kill_at", null)); }
  // which drawer group a config key belongs to: "journal", "assume" or "choice"
  function settingGroup(k, cfg) {
    if (k === "kill_fraction") return hasKill(cfg) && cfg[k] === JOURNAL_KILL.value ? "journal" : "choice";
    if (JOURNAL_KEYS[k]) return "journal";
    if (ASSUME_KEYS[k]) return "assume";
    if (CHOICE_KEYS[k]) return "choice";
    return null;
  }
  // a null in the config means "use the default"; say which default the run actually used
  function cfgVal(k, v, cfg, summary) {
    cfg = cfg || {};
    if (v === null || v === undefined) {
      if (k === "hotspot_node") {
        var hn = get(summary, "hotspot_node", null);
        return isNum(hn) ? "node " + hn + ", drawn from the seed" : "drawn from the seed";
      }
      if (k === "resonance_phase") {
        var rp = get(cfg, "resonance_period", null);
        return "default: half the period" + (isNum(rp) ? ", " + fmt(rp / 2, 2) + " s" : "");
      }
      if (k === "checkpoint_phase") return "drawn from the seed, between 0 and the period";
      if (k === "kill_at") return "no kill in this run";
      return "not set";
    }
    if (k === "kill_fraction" && cfg && !hasKill(cfg)) return fmt(v, 4) + ", unused: no kill in this run";
    if (typeof v === "boolean") return v ? "on" : "off";
    if (typeof v === "number") return fmt(v, 4) + (UNITS[k] || "");
    return String(v);
  }

  // Event text from the simulator lists node ids bare ("Resonance swapped 33 ACTIVE->STANDBY,
  // 22 STANDBY->ACTIVE"), which reads like a count. Name the ids as nodes, and name the bare
  // counts as counts. Text already in another form passes through unchanged.
  function idList(s) {
    var n = String(s).split(/,\s*/).length;
    return (n === 1 ? "node " : "nodes ") + s;
  }
  function eventText(e) {
    var kind = String(e.kind || "").toUpperCase(), s = String(e.text || "");
    if (kind === "RESONANCE") {
      var first = true;
      s = s.replace(/(\d+) ACTIVE->STANDBY, (\d+) STANDBY->ACTIVE/g, function (_, h, r) {
        var out = first ? "node " + h + " (ACTIVE→STANDBY) with node " + r + " (STANDBY→ACTIVE)" : "node " + h + " with node " + r;
        first = false;
        return out;
      });
    }
    if (kind === "MITOSIS_DONE" || kind === "MEIOSIS_DONE") {
      // here the number after "promoted" is how many nodes the repair promoted
      s = s.replace(/CDS repair promoted (\d+)$/, function (_, c) { return "CDS repair promoted " + c + (c === "1" ? " node" : " nodes"); });
    } else {
      s = s.replace(/\bpromoted (\d+(?:, \d+)*)/g, function (_, ids) { return "promoted " + idList(ids); });
    }
    s = s.replace(/^Fairness woke (\d+(?:, \d+)*) to STANDBY; (\d+(?:, \d+)*) went GHOST/, function (_, a, b) {
      return "Fairness woke " + idList(a) + " to STANDBY; " + idList(b) + " went GHOST";
    });
    return s.replace(/(\d)x avg/g, "$1× avg").replace(/->/g, "→");
  }

  var Live = {
    sc: null, idx: 0, F: 0, playing: false, speed: 4, userPaused: false, acc: 0, raf: 0, last: 0,
    charts: [], cage: null, ratio5: [], events: [], ticksW: 0,

    init: function () {
      var self = this;
      var scs = arr(get(D, "scenarios")).filter(function (s) { return s && typeof s === "object"; });
      this.scs = scs;
      var tabs = $("scen-tabs");
      tabs.textContent = "";
      scs.forEach(function (s, i) {
        var li = el("li", null, tabs);
        var b = el("button", { class: "btn", type: "button", id: "scen-" + slug(s.id || i), "aria-pressed": "false", "data-i": i }, li);
        el("span", null, b, s.title || s.id || "Scenario " + (i + 1));
        el("small", null, b, [s.id, s.cage, isNum(s.duration) ? s.duration + "\u00a0s" : null].filter(Boolean).join(" · "));
        b.addEventListener("click", function () { self.setScenario(i); store("bmfp-scenario", s.id || ""); });
      });
      if (!scs.length) el("li", { class: "small" }, tabs, "No scenarios in the data.");
      this.cage = new window.BMFPCage($("live-cage"), { tip: $("live-tip"), autoRotate: true });
      cages.push(this.cage);
      this.cage.loop();
      // flags
      var fl = $("flags");
      fl.textContent = "";
      this.flagEls = {};
      STATES.forEach(function (s) {
        var li = el("li", { "data-state": s.k }, fl);
        var h = el("span", { class: "fl-h" }, li);
        glyph(s.k, h);
        el("span", null, h, s.name);
        var n = el("span", { class: "fl-n", id: "count-" + s.k }, li, DASH);
        self.flagEls[s.k] = n;
        el("span", { class: "fl-s" }, li, s.flag + " · " + s.gloss);
      });
      // transport
      $("play").addEventListener("click", function () { self.toggle(true); });
      document.querySelectorAll("#speeds [data-speed]").forEach(function (b) {
        b.addEventListener("click", function () {
          self.speed = Number(b.getAttribute("data-speed")) || 4;
          document.querySelectorAll("#speeds [data-speed]").forEach(function (o) { o.setAttribute("aria-pressed", o === b ? "true" : "false"); });
        });
      });
      $("scrub").addEventListener("input", function () { self.seek(Number($("scrub").value) || 0); });
      // keyboard: space plays, arrows scrub (the model's own arrow keys rotate it)
      // Space also works with focus on a live chart (the chart keeps its own arrow keys)
      $("cell").addEventListener("keydown", function (e) {
        if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
        var t = e.target, tag = t.tagName;
        if (t.closest && t.closest("details")) return;
        var inChart = !!(t.closest && t.closest(".chart"));
        if (tag === "SELECT" || tag === "TEXTAREA" || (tag === "INPUT" && t.type !== "range")) return;
        if (e.key === " " || e.code === "Space") {
          if (tag === "BUTTON" || tag === "A" || tag === "SUMMARY") return;
          e.preventDefault();
          self.toggle(true);
        } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
          if (inChart) return;
          if (tag === "INPUT" && !e.shiftKey) return; // native slider step
          e.preventDefault();
          self.seek(self.idx + (e.key === "ArrowRight" ? 1 : -1) * (e.shiftKey ? 10 : 1), true);
        }
      });
      // a reader who turns on reduced motion mid-run stops the playback the page started
      var onReduce = function () { if (reduceMQ.matches && self.playing && self.autoStarted) self.pause(false); };
      if (reduceMQ.addEventListener) reduceMQ.addEventListener("change", onReduce);
      else if (reduceMQ.addListener) reduceMQ.addListener(onReduce);
      // event log: one delegated handler; the list's nodes are reused, never rebuilt
      $("log").addEventListener("click", function (e) {
        var b = e.target.closest ? e.target.closest("button[data-i]") : null;
        if (b) self.goToEvent(Number(b.getAttribute("data-i")));
      });
      $("log").addEventListener("focusout", function (e) {
        // the list holds still while it has focus; catch up once focus leaves it
        if (!$("log").contains(e.relatedTarget) && self.logStale) self.renderLog(self.timeAt(self.idx));
      });
      // autoplay while in view, unless the reader prefers reduced motion or paused it
      if (window.IntersectionObserver) {
        new IntersectionObserver(function (entries) {
          var vis = entries[0] && entries[0].isIntersecting;
          if (vis && !self.userPaused && !reduceMQ.matches && !self.playing && self.idx < self.F - 1) self.play(true);
          // only playback this observer started is paused when the player leaves the screen
          if (!vis && self.playing && self.autoStarted) self.pause(false);
        }, { threshold: 0.35 }).observe($("instrument"));
      }
      var startId = store("bmfp-scenario");
      var start = 0;
      scs.forEach(function (s, i) { if (startId && s.id === startId) start = i; });
      if (scs.length) this.setScenario(start);
      if (window.ResizeObserver) new ResizeObserver(function () { if ($("ticks").clientWidth !== self.ticksW) self.renderTicks(); }).observe($("ticks"));
    },

    setScenario: function (i) {
      var sc = this.scs[i];
      if (!sc) return;
      this.sc = sc;
      document.querySelectorAll("#scen-tabs .btn").forEach(function (b) { b.setAttribute("aria-pressed", Number(b.getAttribute("data-i")) === i ? "true" : "false"); });
      $("scen-blurb").textContent = sc.blurb || "";
      var cage = get(D, ["cages", sc.cage], null);
      this.n = get(cage, "n", null);
      this.cage.setCage(cage);
      var states = arr(get(sc, "frames.states")), t = arr(get(sc, "series.t"));
      this.F = Math.max(states.length, t.length);
      this.dt = get(sc, "frames.dt", 1);
      var scrub = $("scrub");
      scrub.max = String(Math.max(0, this.F - 1));
      // the run's length: the scenario's duration, else the last bin's start plus one bin
      var last = this.timeAt(this.F - 1);
      var end = isNum(sc.duration) ? sc.duration : isNum(last) ? last + (this.dt || 1) : null;
      $("time-end").textContent = isNum(end) ? fmt(end, 2) + " s" : DASH;
      $("scrub-end").textContent = isNum(end) ? fmt(end, 2) + " s" : DASH;
      this.endT = end;
      $("live-tag").textContent = [sc.cage, sc.id, isNum(sc.seed) ? "seed " + sc.seed : null].filter(Boolean).join(" · ");
      // rolling 5 s deliverable ratio
      var ds = arr(get(sc, "series.deliverable_sent")), dd = arr(get(sc, "series.deliverable_delivered"));
      var un = arr(get(sc, "series.unserved"));
      var r5 = [];
      for (var k = 0; k < this.F; k++) {
        var a = 0, b = 0;
        for (var j = Math.max(0, k - 4); j <= k; j++) {
          if (isNum(ds[j])) a += ds[j];
          if (isNum(un[j])) a += un[j];
          if (isNum(dd[j])) b += dd[j];
        }
        r5.push(a > 0 ? b / a : null);
      }
      this.ratio5 = r5;
      this.events = arr(sc.events).filter(function (e) { return e && isNum(e.t); }).slice().sort(function (x, y) { return x.t - y.t; });
      var tot = get(sc, "events_total", null);
      $("log-note").textContent = isNum(tot) && tot > this.events.length ? "The export keeps the first " + this.events.length + " of " + tot + " events for this run." : "";
      this.renderTicks();
      this.renderCharts();
      this.renderSettings();
      this.renderSummary();
      this.acc = 0;
      // the reused log rows describe the previous scenario's events: mark them for rewrite
      if (this.logItems) this.logItems.rows.forEach(function (r) { r.b.removeAttribute("data-i"); });
      this.seek(0, true);
      if (this.playing === false && !this.userPaused && !reduceMQ.matches && this.inView()) this.play(true);
    },

    inView: function () {
      var r = $("instrument").getBoundingClientRect();
      return r.top < window.innerHeight * 0.65 && r.bottom > window.innerHeight * 0.35;
    },
    timeAt: function (i) {
      var t = get(this.sc, "series.t", []);
      if (isNum(t[i])) return t[i];
      return isNum(i) && i >= 0 ? Math.round(i * (this.dt || 1) * 100) / 100 : null;
    },

    // force: the reader asked for this position (an event pick), so the log updates even
    // while it has focus
    seek: function (i, force) {
      if (!this.sc) return;
      i = Math.max(0, Math.min(this.F - 1, Math.round(i)));
      if (!isNum(i)) i = 0;
      this.idx = i;
      var fr = frameAt(this.sc, i);
      this.cage.setFrame(fr.states, fr.loads, fr.stems, fr.captains);
      var cnt;
      if (fr.states) cnt = countStates(fr.states);
      else {
        var s = get(this.sc, "series", {});
        cnt = { A: arr(s.active)[i], S: arr(s.standby)[i], G: arr(s.ghost)[i], D: arr(s.dead)[i] };
      }
      var self = this;
      STATES.forEach(function (s) {
        var e = self.flagEls[s.k];
        e.textContent = isNum(cnt[s.k]) ? String(cnt[s.k]) : DASH;
        if (isNum(self.n)) { var sm = el("small", null, null, " of " + self.n); e.appendChild(sm); }
      });
      var t = this.timeAt(i);
      $("time-now").textContent = isNum(t) ? t + " s" : DASH;
      var scrub = $("scrub");
      if (Number(scrub.value) !== i) scrub.value = String(i);
      scrub.setAttribute("aria-valuetext", (isNum(t) ? t + " seconds" : "") + (isNum(this.endT) ? " of " + fmt(this.endT, 2) : ""));
      $("ratio-now").textContent = pct(this.ratio5[i], 1);
      this.renderLog(t, force);
      this.charts.forEach(function (c) { c.setPlayhead(t); });
      $("live-cage").setAttribute("aria-label", "Ball-and-stick model of the cell at t = " + (isNum(t) ? t : DASH) + " s: " +
        [cnt.A + " ACTIVE", cnt.S + " STANDBY", cnt.G + " GHOST", cnt.D + " DEAD"].join(", ") + ". Arrow keys turn it.");
    },

    play: function (auto) {
      var self = this;
      if (!this.sc || this.F < 2) return;
      this.autoStarted = !!auto;
      if (this.idx >= this.F - 1) this.seek(0);
      this.playing = true;
      this.setPlayUI();
      this.last = 0;
      var step = function (ts) {
        if (!self.playing) return;
        if (self.last) {
          self.acc += Math.min(0.25, (ts - self.last) / 1000) * self.speed / (self.dt || 1);
          if (self.acc >= 1) {
            var n = Math.floor(self.acc);
            self.acc -= n;
            if (self.idx + n >= self.F - 1) { self.seek(self.F - 1); self.pause(false); return; }
            self.seek(self.idx + n);
          }
        }
        self.last = ts;
        self.raf = requestAnimationFrame(step);
      };
      this.raf = requestAnimationFrame(step);
    },
    pause: function (byUser) {
      this.playing = false;
      if (byUser) this.userPaused = true;
      if (this.raf) cancelAnimationFrame(this.raf);
      this.raf = 0;
      this.setPlayUI();
    },
    toggle: function (byUser) {
      if (this.playing) this.pause(byUser);
      else { if (byUser) this.userPaused = false; this.play(!byUser); }
    },
    setPlayUI: function () {
      $("play").setAttribute("aria-pressed", this.playing ? "true" : "false");
      $("play-label").textContent = this.playing ? "Pause" : "Play";
      $("play-icon").setAttribute("d", this.playing ? "M4 2.5h3v11H4zM9 2.5h3v11H9z" : "M4 2.5v11l9-5.5z");
    },

    renderTicks: function () {
      var s = $("ticks");
      while (s.firstChild) s.removeChild(s.firstChild);
      var W = s.clientWidth || 300;
      this.ticksW = W;
      s.setAttribute("viewBox", "0 0 " + W + " 18");
      var end = this.timeAt(this.F - 1) || 1, inset = 8;
      // failures and recoveries differ in shape, not only colour: a failure tick ends in a
      // downward triangle, a recovery tick in a round dot
      var FAIL = { KILL: 1, LEAVE: 1, DEATH_EVENT: 1, CELL_DEATH_EVENT: 1 };
      var RECOVER = { DETECT: 1, MITOSIS_DONE: 1, MEIOSIS_DONE: 1, JOIN: 1 };
      C.svg("line", { x1: inset, x2: W - inset, y1: 17.5, y2: 17.5, style: "stroke:var(--rule-2);stroke-width:1" }, s);
      var marks = [];
      this.events.forEach(function (e) {
        var x = inset + (Math.min(e.t, end) / end) * (W - 2 * inset);
        var kind = String(e.kind || "").toUpperCase();
        var type = FAIL[kind] ? "fail" : RECOVER[kind] ? "recover" : "other";
        if (type === "other") C.svg("line", { x1: x.toFixed(1), x2: x.toFixed(1), y1: 10, y2: 17, style: "stroke:var(--edge);stroke-width:1" }, s);
        else marks.push([x, type]);
      });
      // tall marks go on top of the short ones
      marks.forEach(function (m) {
        var x = m[0], col = m[1] === "fail" ? "var(--st-dead)" : "var(--ink)";
        C.svg("line", { x1: x.toFixed(1), x2: x.toFixed(1), y1: 5, y2: 17, "data-tick": m[1], style: "stroke:" + col + ";stroke-width:2" }, s);
        if (m[1] === "fail") C.svg("path", { d: "M" + (x - 4).toFixed(1) + " 0.5H" + (x + 4).toFixed(1) + "L" + x.toFixed(1) + " 6.5Z", style: "fill:" + col }, s);
        else C.svg("circle", { cx: x.toFixed(1), cy: 3.6, r: 3, style: "fill:var(--plate);stroke:" + col + ";stroke-width:1.6" }, s);
      });
    },

    goToEvent: function (i) {
      var e = this.events[i];
      if (!e) return;
      var ts = get(this.sc, "series.t", []), best = Math.round(e.t / (this.dt || 1));
      for (var q = 0; q < ts.length; q++) if (ts[q] <= e.t) best = q; else break;
      this.seek(best, true);
      // keep focus on the event the reader chose, wherever it now sits in the list
      var ol = $("log");
      if (ol.contains(document.activeElement)) {
        var b = ol.querySelector('button[data-i="' + i + '"]');
        if (b && b !== document.activeElement) b.focus();
      }
    },

    // The log is updated in place: its <li>/<button> nodes are reused, so a focused button is
    // never destroyed. While focus is inside the log, playback ticks leave it alone (the reader
    // is choosing an event); it catches up when focus leaves or the reader picks an event.
    renderLog: function (t, force) {
      var ol = $("log");
      if (!force && ol.contains(document.activeElement)) { this.logStale = true; return; }
      this.logStale = false;
      if (!this.logItems || this.logItems.ol !== ol) this.logItems = { ol: ol, rows: [], empty: null };
      var L = this.logItems;
      var ev = this.events;
      if (!ev.length) {
        L.rows.forEach(function (r) { r.li.remove(); });
        L.rows = [];
        if (!L.empty) L.empty = el("li", { class: "log-empty" }, ol, "No events recorded in this run.");
        return;
      }
      if (L.empty) { L.empty.remove(); L.empty = null; }
      var lo = 0, hi = ev.length;
      while (lo < hi) { var mid = (lo + hi) >> 1; if (ev[mid].t <= t + 1e-9) lo = mid + 1; else hi = mid; }
      var k = lo - 1; // last event at or before t
      var from = Math.max(0, k - 2), to = Math.min(ev.length - 1, Math.max(k, 0) + 2);
      if (k < 0) { from = 0; to = Math.min(ev.length - 1, 4); }
      var need = to - from + 1;
      while (L.rows.length < need) {
        var li = el("li", null, ol);
        var b = el("button", { type: "button" }, li);
        L.rows.push({ li: li, b: b, t: el("span", { class: "t" }, b), kd: el("span", { class: "kd" }, b), tx: el("span", { class: "tx" }, b) });
      }
      while (L.rows.length > need) {
        var gone = L.rows.pop();
        gone.li.remove();
      }
      for (var p = 0; p < need; p++) {
        var i = from + p, e = ev[i], r = L.rows[p];
        var cls = i === k ? "now" : i > k ? "future" : "";
        if (r.li.className !== cls) r.li.className = cls;
        if (r.b.getAttribute("data-i") === String(i)) continue;
        var text = eventText(e);
        r.b.setAttribute("data-i", String(i));
        r.b.setAttribute("aria-label", "Go to " + fmt(e.t, 1) + " s: " + (text || e.kind || ""));
        r.t.textContent = fmt(e.t, 1) + " s";
        r.kd.textContent = String(e.kind || "");
        r.tx.textContent = text;
      }
    },

    renderCharts: function () {
      var host = $("charts-live"), sc = this.sc, self = this;
      this.charts.forEach(function (c) { if (c.ro) c.ro.disconnect(); });
      this.charts = [];
      host.textContent = "";
      var t = arr(get(sc, "series.t"));
      var seekT = function (x) {
        var best = 0;
        for (var q = 0; q < t.length; q++) if (t[q] <= x) best = q; else break;
        self.seek(best);
      };
      var killAt = get(sc, "config.kill_at", null);
      var killRef = isNum(killAt) ? [{ axis: "x", value: killAt, label: "kill at " + fmt(killAt, 0) + " s" }] : [];
      var xo = { title: "time (s)", format: function (v) { return fmt(v, 0); } };
      // ratio
      safe("delivery ratio chart", function () {
        var f = C.figure(host, { id: "live-ratio", cls: "wide", level: "h3", title: "Deliverable delivery ratio", sub: "Share of deliverable messages delivered, over a 5 s rolling window. Sends offered while no node was alive count as undelivered. Click the chart to move the playhead.", tallTable: true });
        var ch = C.line(f.plot(), {
          fig: f.fig, tip: f.tip, height: 190, playhead: true, onSeek: seekT, refs: killRef,
          series: [{ name: "5 s rolling ratio", color: "var(--pencil)", x: t, y: self.ratio5 }],
          x: xo, y: { min: 0, max: Math.max(1, Math.max.apply(null, self.ratio5.filter(isNum).concat([0]))), format: function (v) { return pct(v, 0); } },
          tipTitle: function (x) { return "t = " + fmt(x, 0) + " s"; }, tipValue: function (sr, i) { return pct(sr.y[i], 1); },
          ariaLabel: "Line chart of the 5 second rolling deliverable delivery ratio over the run. Use the arrow keys to read values; Enter moves the playhead.",
        });
        self.charts.push(ch);
        var ds = arr(get(sc, "series.deliverable_sent")), dd = arr(get(sc, "series.deliverable_delivered"));
        var sn = arr(get(sc, "series.sent")), dl = arr(get(sc, "series.delivered"));
        f.table(["t (s)", "Sent", "Delivered", "Deliverable sent", "Deliverable delivered", "5 s rolling ratio"], t.map(function (tv, i) {
          return [fmt(tv, 0), fmt(sn[i], 0), fmt(dl[i], 0), fmt(ds[i], 0), fmt(dd[i], 0), pct(self.ratio5[i], 1)];
        }), { num: [0, 1, 2, 3, 4, 5], caption: "Per second. Sent counts every message; deliverable leaves out messages to a sleeping or dead device. The ratio also counts sends offered while no node was alive as undelivered." });
      }, host);
      // states
      safe("state count chart", function () {
        var f = C.figure(host, { id: "live-states", level: "h3", title: "Nodes in each state", sub: "Count per second. The four lines always add up to the cell size. Each line is labelled at its end; DEAD is dashed.", tallTable: true });
        var keys = [["active", "A"], ["standby", "S"], ["ghost", "G"], ["dead", "D"]];
        // direct labels at the line ends and a dashed DEAD line, so no state is told by colour alone
        var series = keys.map(function (k) {
          var st = STATES.filter(function (s) { return s.k === k[1]; })[0];
          return { name: st.name, color: st.color, x: t, y: arr(get(sc, ["series", k[0]])), label: st.name, dash: k[1] === "D" ? "5 4" : null };
        });
        // end labels that would land on top of each other are nudged apart (and dropped when
        // the line has no value); the legend below still names every line
        var ends = series.map(function (s, i) {
          for (var q = s.y.length - 1; q >= 0; q--) if (isNum(s.y[q])) return { i: i, v: s.y[q] };
          return { i: i, v: null };
        }).filter(function (e) { return e.v !== null; }).sort(function (a, b) { return a.v - b.v; });
        var cap = isNum(self.n) ? self.n : 1, minGap = cap * 0.092, prev = -Infinity;
        ends.forEach(function (e) { if (e.v - prev < minGap) series[e.i].labelNudge = (prev + minGap) - e.v; prev = e.v + (series[e.i].labelNudge || 0); });
        f.legend(series.map(function (s) { return { name: s.name, color: s.color, dash: s.dash }; }));
        var ch = C.line(f.plot(), {
          fig: f.fig, tip: f.tip, height: 190, playhead: true, onSeek: seekT, refs: killRef, series: series, x: xo,
          y: { min: 0, max: isNum(self.n) ? self.n : undefined, format: function (v) { return fmt(v, 0); } },
          tipTitle: function (x) { return "t = " + fmt(x, 0) + " s"; }, tipValue: function (sr, i) { return fmt(sr.y[i], 0); },
          ariaLabel: "Line chart of how many nodes are ACTIVE, STANDBY, GHOST and DEAD each second.",
        });
        self.charts.push(ch);
        f.table(["t (s)", "ACTIVE", "STANDBY", "GHOST", "DEAD"], t.map(function (tv, i) {
          return [fmt(tv, 0)].concat(series.map(function (s) { return fmt(s.y[i], 0); }));
        }), { num: [0, 1, 2, 3, 4] });
      }, host);
      // load
      safe("load chart", function () {
        var vf = get(sc, "config.vsepr_factor", null);
        var f = C.figure(host, { id: "live-load", level: "h3", title: "Hottest relay against the average", sub: "Load on the busiest relay divided by the mean relay load, per second." + (isNum(vf) ? " The line marks the VSEPR demotion threshold, an input from the journal." : ""), tallTable: true });
        var y = arr(get(sc, "series.max_load_ratio"));
        var ch = C.line(f.plot(), {
          fig: f.fig, tip: f.tip, height: 190, playhead: true, onSeek: seekT,
          refs: (isNum(vf) ? [{ axis: "y", value: vf, label: "VSEPR threshold " + fmt(vf, 2) + "×", short: "VSEPR " + fmt(vf, 2) + "×" }] : []).concat(killRef),
          series: [{ name: "max / avg load", color: "var(--pencil)", x: t, y: y }], x: xo,
          y: { min: 0, format: function (v) { return fmt(v, 1) + "×"; } },
          tipTitle: function (x) { return "t = " + fmt(x, 0) + " s"; }, tipValue: function (sr, i) { return fmt(sr.y[i], 2) + "×"; },
          ariaLabel: "Line chart of the busiest relay's load relative to the average, per second.",
        });
        self.charts.push(ch);
        f.table(["t (s)", "Max / avg load", "Transmissions", "Mean hops"], t.map(function (tv, i) {
          return [fmt(tv, 0), fmt(y[i], 2), fmt(arr(get(sc, "series.transmissions"))[i], 1), fmt(arr(get(sc, "series.mean_hops"))[i], 2)];
        }), { num: [0, 1, 2, 3] });
      }, host);
    },

    renderSettings: function () {
      var host = $("settings"), cfg = get(this.sc, "config", {}), summ = get(this.sc, "summary", {});
      host.textContent = "";
      var groups = [
        ["journal", "From the journal (inputs, not results)"],
        ["assume", "Simulator assumptions (not in the journal)"],
        ["choice", "Scenario choices"],
      ];
      var used = { record_frames: true };
      groups.forEach(function (g) {
        var box = el("div", { "data-group": g[0] }, host);
        el("h4", null, box, g[1]);
        var dl = el("dl", { class: "kv" }, box);
        Object.keys(cfg).forEach(function (k) {
          if (settingGroup(k, cfg) !== g[0]) return;
          used[k] = true;
          var label, src;
          if (k === "kill_fraction" && g[0] === "journal") { label = JOURNAL_KILL.label; src = JOURNAL_KILL.src; }
          else if (g[0] === "journal") { label = JOURNAL_KEYS[k][0]; src = JOURNAL_KEYS[k][1]; }
          else { label = g[0] === "assume" ? ASSUME_KEYS[k] : CHOICE_KEYS[k]; src = k; }
          var dt = el("dt", { "data-key": k }, dl, label + " ");
          el("small", null, dt, src);
          el("dd", null, dl, cfgVal(k, cfg[k], cfg, summ));
        });
        if (!dl.childNodes.length) el("p", { class: "small" }, box, DASH);
      });
      var rest = Object.keys(cfg).filter(function (k) { return !used[k]; });
      if (rest.length) {
        var box = el("div", null, host);
        el("h4", null, box, "Other settings");
        var dl = el("dl", { class: "kv" }, box);
        rest.forEach(function (k) { el("dt", { "data-key": k }, dl, k); el("dd", null, dl, cfgVal(k, cfg[k], cfg, summ)); });
      }
    },

    renderSummary: function () {
      var host = $("summary"), s = get(this.sc, "summary", {});
      var rows = [];
      Object.keys(s).forEach(function (k) {
        var v = s[k];
        if (v && typeof v === "object" && !Array.isArray(v) && !isMMM(v)) {
          Object.keys(v).forEach(function (k2) { rows.push([k + "." + k2, fmtVal(v[k2], k2)]); });
        } else rows.push([k, fmtVal(v, k)]);
      });
      C.fillTable(host, ["Key", "Value"], rows, { num: [1] });
    },
  };

  // ---- 3 · ladder --------------------------------------------------------------
  function findingFor(re) {
    var fs = arr(get(D, "findings"));
    for (var i = 0; i < fs.length; i++) {
      var f = fs[i] || {};
      var hay = [f.id, f.problem, f.journal_ref].join(" ");
      if (re.test(hay)) return f;
    }
    return null;
  }
  function verdictChip(v, parent, href) {
    var tag = href ? "a" : "span";
    var c = el(tag, { class: "chip", href: href || null }, parent);
    var key = String(v || "").toLowerCase();
    glyph(["confirmed", "refuted", "partly", "not simulated"].indexOf(key) >= 0 ? key : "other", c);
    el("span", null, c, v || "no verdict");
    return c;
  }
  function renderLadder() {
    var fs = arr(get(D, "findings")).filter(function (f) { return f && typeof f === "object"; });
    document.querySelectorAll(".tile[data-v]").forEach(function (tile) {
      var v = tile.getAttribute("data-v");
      // a finding tests a rung when its journal reference names that exact version,
      // or when its id/problem matches the rung's keywords
      var vre = new RegExp(v.replace(/\./g, "\\.") + "(?![a-z0-9])", "i");
      var kre = null;
      try { if (tile.getAttribute("data-match")) kre = new RegExp(tile.getAttribute("data-match"), "i"); } catch (e) { kre = null; }
      var hits = fs.filter(function (f) {
        return vre.test(String(f.journal_ref || "")) || (kre && kre.test([f.id, f.problem, f.journal_ref].join(" ")));
      });
      if (!hits.length) return;
      // a finding the simulator could not run ("not simulated") did not test anything: it is
      // listed as an open question, never under "Tested by"
      var isOpen = function (f) { return String(f.verdict || "").toLowerCase() === "not simulated"; };
      [["Tested by", hits.filter(function (f) { return !isOpen(f); }), "tested"],
       ["Open, not simulated", hits.filter(isOpen), "open"]].forEach(function (grp) {
        if (!grp[1].length) return;
        var row = el("div", { class: "tested", "data-kind": grp[2] }, tile);
        el("span", { class: "tested-l" }, row, grp[0]);
        grp[1].forEach(function (f) {
          var verdict = String(f.verdict || "no verdict");
          var c = el("a", { class: "chip", href: "#finding-" + slug(f.id || f.problem), title: (f.problem || "") + " (" + verdict + ")", "data-verdict": verdict.toLowerCase() }, row);
          var key = verdict.toLowerCase();
          glyph(["confirmed", "refuted", "partly", "not simulated"].indexOf(key) >= 0 ? key : "other", c);
          // the verdict word sits on the chip itself, so the glyph never has to be decoded
          var name = String(f.id || f.problem || "finding").replace(/[-_]+/g, " ");
          el("span", null, c, (grp[2] === "open" ? "" : verdict + " · ") + name);
          c.setAttribute("aria-label", "Finding: " + (f.problem || f.id) + ". Verdict: " + verdict + ".");
        });
      });
    });
  }

  // ---- 4 · findings + experiments ---------------------------------------------
  function renderFindings() {
    var key = $("verdict-key");
    key.textContent = "";
    [["confirmed", "the simulator agrees with the journal"], ["partly", "agrees in part"], ["refuted", "the simulator disagrees"], ["not simulated", "outside what the simulator models"]].forEach(function (p) {
      var li = el("li", null, key);
      verdictChip(p[0], li);
      el("span", null, li, p[1]);
    });
    var ol = $("findings-list");
    ol.textContent = "";
    var fs = arr(get(D, "findings"));
    if (!fs.length) el("li", { class: "finding" }, ol, "No findings in the data.");
    fs.forEach(function (f) {
      if (!f || typeof f !== "object") return;
      var li = el("li", { class: "finding", id: "finding-" + slug(f.id || f.problem) }, ol);
      var meta = el("div", { class: "fmeta" }, li);
      verdictChip(f.verdict, meta);
      el("span", { class: "fref" }, meta, f.journal_ref || "");
      var body = el("div", { class: "fbody" }, li);
      el("h3", null, body, f.problem || f.id || DASH);
      el("p", { class: "measured" }, body, f.measured || DASH);
      if (f.next_step) {
        var p = el("p", { class: "next" }, body);
        el("b", null, p, "Next step. ");
        p.appendChild(document.createTextNode(f.next_step));
      }
    });
  }

  var VARIANT_LABEL = { naive: "Naive, as written", damped: "Damped, the fix", off: "VSEPR off" };
  function pick(obj, names) {
    for (var i = 0; i < names.length; i++) if (obj && obj[names[i]] !== undefined) return obj[names[i]];
    return null;
  }

  function renderExperiments() {
    var host = $("exp-charts");
    host.textContent = "";
    var ex = get(D, "experiments", {});

    // E2 · VSEPR
    safe("E2 VSEPR", function () {
      var v = get(ex, "vsepr.variants", {});
      var names = Object.keys(v);
      var nS = arr(get(ex, "vsepr.seeds")).length;
      var f = C.figure(host, { id: "e2-vsepr", level: "h4", title: "E2 · VSEPR as written, damped, and off", sub: ["C60 cell, default workload", durText(get(ex, "vsepr.duration")), seedsText(get(ex, "vsepr.seeds"))].filter(Boolean).join(", ") + ". Dot: mean across seeds. Whisker: lowest to highest seed." });
      var wrap = el("div", { class: "chart-grid two" }, f.area);
      var rowsOf = function (keys) {
        return names.map(function (n) { var m = mmm(pick(v[n], keys)); return { label: VARIANT_LABEL[n] || n, mean: m.mean, min: m.min, max: m.max }; });
      };
      // VSEPR's own changes: the all-source count is dominated by resonance swaps, which run
      // the same way in every variant and would hide VSEPR's effect (it stays in the table view)
      var p1 = el("div", { "data-metric": "state_changes_per_min_vsepr" }, wrap);
      el("p", { class: "chart-sub" }, p1, "ACTIVE ↔ not-ACTIVE changes per minute caused by VSEPR");
      C.dotWhisker(el("div", { class: "plot" }, p1), { fig: f.fig, tip: f.tip, rows: rowsOf(["state_changes_per_min_vsepr"]), format: function (x) { return fmt(x, 1); }, ariaLabel: "ACTIVE changes per minute caused by VSEPR, for each VSEPR variant" });
      var resMeans = names.map(function (n) { return mmm(get(v, [n, "state_changes_per_min_resonance"])).mean; }).filter(isNum);
      if (resMeans.length) {
        var rlo = Math.min.apply(null, resMeans), rhi = Math.max.apply(null, resMeans);
        el("p", { class: "chart-note" }, p1, "Resonance swaps add " + (fmt(rlo, 1) === fmt(rhi, 1) ? fmt(rlo, 1) : fmt(rlo, 1) + " to " + fmt(rhi, 1)) + " ACTIVE changes per minute on top of these, in every variant. The table view lists every source.");
      }
      var p2 = el("div", null, wrap);
      var start = mmm(pick(get(v, "naive", {}), ["active_fraction_start"]));
      el("p", { class: "chart-sub" }, p2, "Share of nodes ACTIVE at the end of the run" + (isNum(start.mean) ? ". The line is the share at the start, " + pct(start.mean, 0) + "." : ""));
      C.dotWhisker(el("div", { class: "plot" }, p2), { fig: f.fig, tip: f.tip, rows: rowsOf(["active_fraction_end", "active_end"]), min: 0, max: 1, refs: isNum(start.mean) ? [{ value: start.mean }] : [], format: function (x) { return pct(x, 0); }, ariaLabel: "ACTIVE share at the end of the run for each VSEPR variant" });
      var metricKeys = [];
      names.forEach(function (n) { Object.keys(v[n] || {}).forEach(function (k) { if (metricKeys.indexOf(k) < 0) metricKeys.push(k); }); });
      f.table(["Metric"].concat(names.map(function (n) { return VARIANT_LABEL[n] || n; })), metricKeys.map(function (k) {
        return [humanKey(k)].concat(names.map(function (n) { return fmtVal(v[n][k], k, nS); }));
      }), { num: names.map(function (_, i) { return i + 1; }), caption: "Every VSEPR metric in the export. Mean across seeds, with the lowest and highest seed in brackets." });
    }, host);

    // E3 · recovery
    safe("E3 recovery", function () {
      var cases = get(ex, "recovery.cases", {});
      var nS = arr(get(ex, "recovery.seeds")).length;
      var order = ["kill50", "kill60", "kill100"].filter(function (k) { return cases[k]; }).concat(Object.keys(cases).filter(function (k) { return ["kill50", "kill60", "kill100"].indexOf(k) < 0; }));
      var label = { kill50: "Half killed (kill50)", kill60: "Most killed (kill60)", kill100: "All killed (kill100)" };
      var colors = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"];
      var killAt = get(ex, "recovery.kill_at", null);
      order.forEach(function (k) { if (!isNum(killAt) && isNum(get(cases, [k, "kill_at"]))) killAt = cases[k].kill_at; });
      var repSeed = null;
      order.forEach(function (k) { if (repSeed === null && isNum(get(cases, [k, "series", "seed"]))) repSeed = cases[k].series.seed; });
      var win = isNum(killAt) ? " The chart shows the stretch around the kill; the table view lists every second." : "";
      var f = C.figure(host, { id: "e3-recovery", level: "h4", title: "E3 · Recovery after a scripted kill", sub: "Deliverable delivery ratio per second" + (repSeed !== null ? " for seed " + repSeed : ", one representative run per case") + (durText(get(ex, "recovery.duration")) ? ", " + durText(get(ex, "recovery.duration")) : "") + "." + win + " The table below aggregates " + seedsText(get(ex, "recovery.seeds")) + ".", tallTable: true });
      var x0 = isNum(killAt) ? killAt - 20 : null, x1 = isNum(killAt) ? killAt + 70 : null;
      var series = order.map(function (k, i) { return { name: label[k] || k, color: colors[i % 4], x: arr(get(cases, [k, "series", "t"])), y: arr(get(cases, [k, "series", "ratio"])), gapMarks: true }; });
      // Seconds after the kill with no ratio at all (nothing deliverable was sent) are shaded in
      // the case's colour. With every node dead the line simply stops; drawn at 100% among the
      // other lines that break is easy to miss, so it gets a band, end caps and a legend entry.
      var bands = [], bandNotes = [];
      series.forEach(function (sr) {
        if (!isNum(killAt)) return;
        var dt = sr.x.length > 1 && isNum(sr.x[1] - sr.x[0]) && sr.x[1] > sr.x[0] ? sr.x[1] - sr.x[0] : 1, runStart = null;
        for (var q = 0; q <= sr.x.length; q++) {
          var xv = sr.x[q], missing = q < sr.x.length && isNum(xv) && xv >= killAt && xv <= x1 && !isNum(sr.y[q]);
          if (missing && runStart === null) runStart = xv;
          if (!missing && runStart !== null) {
            var endX = isNum(sr.x[q - 1]) ? sr.x[q - 1] + dt : runStart + dt;
            bands.push({ x0: runStart, x1: endX, color: sr.color });
            bandNotes.push({ name: sr.name, color: sr.color, from: runStart, to: endX });
            runStart = null;
          }
        }
      });
      f.legend(series.map(function (s) { return { name: s.name, color: s.color }; }).concat(bandNotes.map(function (b) {
        return { name: b.name + ": nothing deliverable sent, " + fmt(b.from, 0) + "–" + fmt(b.to, 0) + " s", color: b.color, kind: "band" };
      })));
      C.line(f.plot(), {
        fig: f.fig, tip: f.tip, height: 230, series: series, bands: bands, refs: isNum(killAt) ? [{ axis: "x", value: killAt, label: "kill at " + fmt(killAt, 0) + " s" }] : [],
        x: { min: isNum(x0) ? x0 : undefined, max: isNum(x1) ? x1 : undefined, title: "time (s)", format: function (x) { return fmt(x, 0); } }, y: { min: 0, max: 1, format: function (x) { return pct(x, 0); } },
        tipTitle: function (x) { return "t = " + fmt(x, 1) + " s"; }, tipValue: function (sr, i) { return isNum(sr.y[i]) ? pct(sr.y[i], 1) : "nothing sent"; },
        ariaLabel: "Line chart of deliverable delivery ratio around the kill for each kill case." + bandNotes.map(function (b) { return " " + b.name + ": no deliverable message sent from " + fmt(b.from, 0) + " to " + fmt(b.to, 0) + " s."; }).join(""),
      });
      if (bandNotes.length) {
        f.noteEl.hidden = false;
        f.noteEl.textContent = "Shaded: seconds with no ratio to plot, because nothing deliverable was sent (" + bandNotes.map(function (b) { return b.name + ", " + fmt(b.from, 0) + "–" + fmt(b.to, 0) + " s"; }).join("; ") + "). Hollow dots mark where a line stops and restarts.";
      }
      var xs = [];
      series.forEach(function (s) { s.x.forEach(function (x) { if (isNum(x) && xs.indexOf(x) < 0) xs.push(x); }); });
      xs.sort(function (a, b) { return a - b; });
      f.table(["t (s)"].concat(series.map(function (s) { return s.name; })), xs.map(function (x) {
        return [fmt(x, 1)].concat(series.map(function (s) { var i = s.x.indexOf(x); return i >= 0 ? pct(s.y[i], 1) : DASH; }));
      }), { num: series.map(function (_, i) { return i; }).concat([series.length]) });
      // metrics table, always visible
      var pref = ["rto_service_s", "rto_journal_formula_s", "first_delivery_after_kill_s", "detect_time_s", "rpo_s", "death_event", "path", "ratio_dip", "killed"];
      var keys = [];
      pref.forEach(function (k) { if (order.some(function (c) { return cases[c] && cases[c][k] !== undefined; })) keys.push(k); });
      order.forEach(function (c) { Object.keys(cases[c] || {}).forEach(function (k) { if (k !== "series" && k !== "kill_at" && keys.indexOf(k) < 0) keys.push(k); }); });
      var box = el("div", { class: "table-wrap" }, f.fig);
      f.fig.insertBefore(box, f.noteEl);
      C.fillTable(box, ["Measure"].concat(order.map(function (c) { return label[c] || c; })), keys.map(function (k) {
        return [humanKey(k)].concat(order.map(function (c) { return fmtVal(get(cases, [c, k]), k, nS); }));
      }), { cls: "measures", num: order.map(function (_, i) { return i + 1; }), caption: "These measures use 5 s windows of messages sent after the kill, and they count messages offered while no node was alive (no device could send them) as undelivered. The per-second line above counts the same unserved sends, but it is a single second at a time, so a 5 s window smooths short dips and the two can differ slightly. Service RTO runs from the kill until that window ratio is back to 95% of its pre-kill level and stays there for 10 s; these thresholds are the metric's definition in bmfp/bmfp/metrics.py, not results. The journal formula RTO is detection plus mitosis or meiosis time, both inputs from the journal, so it is not a measurement either." });
    }, host);

    // E4 · hell mode
    safe("E4 hell mode", function () {
      var nS = arr(get(ex, "hell.seeds")).length;
      var sets = [{ key: "rows", name: "Living cell", rows: arr(get(ex, "hell.rows")) }];
      var sc = get(ex, "hell.static_cell", null);
      if (arr(get(ex, "hell.static_rows")).length) {
        var desc = sc ? Object.keys(sc).map(function (k) { return k.replace(/_/g, " ") + " " + cfgVal(k, sc[k]); }).join(", ") : "";
        sets.push({ key: "static_rows", name: "Static fullerene, the v1.2 network", desc: desc, rows: arr(get(ex, "hell.static_rows")) });
      }
      var all = [];
      sets.forEach(function (st) { all = all.concat(st.rows); });
      var losses = [], rates = [], routings = [];
      all.forEach(function (r) {
        if (isNum(r.link_loss) && losses.indexOf(r.link_loss) < 0) losses.push(r.link_loss);
        if (isNum(r.send_rate) && rates.indexOf(r.send_rate) < 0) rates.push(r.send_rate);
        if (r.routing && routings.indexOf(r.routing) < 0) routings.push(r.routing);
      });
      losses.sort(function (a, b) { return a - b; });
      rates.sort(function (a, b) { return a - b; });
      var palette = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"];
      var colors = { chill: "var(--s1)", duplicate: "var(--s2)", stripe: "var(--s3)" };
      var names = { chill: "Chill, one path", duplicate: "Hell: duplicate", stripe: "Hell: stripe" };
      var colorOf = function (rt, i) { return colors[rt] || palette[i % 4]; };
      var f = C.figure(host, { id: "e4-hell", level: "h4", title: "E4 · Hell mode: what each routing costs", sub: "Transmissions per delivered message as the send rate grows. Columns: per-hop link loss. " + (sets.length > 1 ? "Rows: the living cell, where only ACTIVE nodes relay, and the static v1.2 fullerene" + (sets[1].desc ? " (" + sets[1].desc + ")" : "") + ". " : "") + [durText(get(ex, "hell.duration")), seedsText(get(ex, "hell.seeds"))].filter(Boolean).join(", ") + "; whiskers span the seeds. Send rate and loss are assumptions.", tallTable: true });
      f.legend(routings.map(function (r, i) { return { name: names[r] || r, color: colorOf(r, i), kind: "dot" }; }));
      var ymax = 0;
      all.forEach(function (r) { var m = mmm(r.tx_per_delivered); [m.mean, m.max].forEach(function (v) { if (isNum(v)) ymax = Math.max(ymax, v); }); });
      var dom = C.niceDomain(0, ymax || 1, 4);
      sets.forEach(function (st) {
        if (sets.length > 1) el("p", { class: "mtitle", style: "margin-top:0.4rem" }, f.area, st.name);
        var grid = el("div", { class: "multiples" }, f.area);
        losses.forEach(function (loss) {
          var cell = el("div", null, grid);
          el("p", { class: "msub" }, cell, "link loss " + pct(loss, 0) + " per hop");
          var series = routings.map(function (rt, i) {
            var pts = st.rows.filter(function (r) { return r.routing === rt && r.link_loss === loss; }).sort(function (a, b) { return a.send_rate - b.send_rate; });
            return {
              name: names[rt] || rt, color: colorOf(rt, i), dots: true,
              x: pts.map(function (p) { return p.send_rate; }),
              y: pts.map(function (p) { return mmm(p.tx_per_delivered).mean; }),
              lo: pts.map(function (p) { return mmm(p.tx_per_delivered).min; }),
              hi: pts.map(function (p) { return mmm(p.tx_per_delivered).max; }),
            };
          });
          C.line(el("div", { class: "plot" }, cell), {
            fig: f.fig, tip: f.tip, height: 200, series: series,
            x: { type: rates.every(function (r) { return r > 0; }) ? "log2" : "linear", ticks: rates, title: "send rate (msg/s)", format: function (x) { return fmt(x, 0); } },
            y: { min: 0, max: dom.max, ticks: dom.ticks, title: "transmissions per delivered", format: function (x) { return fmt(x, 0); } },
            tipTitle: function (x) { return st.name + ": " + fmt(x, 0) + " msg/s, loss " + pct(loss, 0); }, tipValue: function (sr, i) { return fmt(sr.y[i], 2); },
            ariaLabel: st.name + ": transmissions per delivered message against send rate, link loss " + pct(loss, 0),
          });
        });
      });
      var mk = [];
      all.forEach(function (r) { Object.keys(r).forEach(function (k) { if (["routing", "send_rate", "link_loss"].indexOf(k) < 0 && mk.indexOf(k) < 0) mk.push(k); }); });
      var trows = [];
      sets.forEach(function (st) {
        st.rows.forEach(function (r) {
          trows.push([st.name, names[r.routing] || String(r.routing), fmt(r.send_rate, 0), pct(r.link_loss, 0)].concat(mk.map(function (k) { return fmtVal(r[k], k, nS); })));
        });
      });
      f.table(["Cell", "Routing", "Send rate", "Link loss"].concat(mk.map(humanKey)), trows, { num: [2, 3].concat(mk.map(function (_, i) { return i + 4; })) });
    }, host);

    // E1 · topology
    safe("E1 topology", function () {
      var rows = arr(get(ex, "topology"));
      var ks = [];
      rows.forEach(function (r) { Object.keys(get(r, "partition_probability", {})).forEach(function (k) { var n = Number(k); if (isNum(n) && ks.indexOf(n) < 0) ks.push(n); }); });
      ks.sort(function (a, b) { return a - b; });
      var colors = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"];
      var f = C.figure(host, { id: "e1-topology", level: "h4", title: "E1 · Topology: when does the ball split?", sub: "Share of ways to remove k nodes that leave the survivors disconnected, for each cage. Counted exactly where the number of combinations is small, sampled otherwise." });
      var series = rows.map(function (r, i) {
        var pp = get(r, "partition_probability", {});
        return { name: (r.cage || "cage " + (i + 1)) + (r.solid ? " · " + r.solid : ""), color: colors[i % 4], dots: true, x: ks, y: ks.map(function (k) { var v = pp[String(k)]; return isNum(v) ? v : null; }) };
      });
      f.legend(series.map(function (s) { return { name: s.name, color: s.color, kind: "dot" }; }));
      C.line(f.plot(), {
        fig: f.fig, tip: f.tip, height: 230, series: series,
        x: { ticks: ks, title: "nodes removed (k)", format: function (x) { return fmt(x, 0); } },
        y: { min: 0, format: function (x) { return pct(x, 0); } },
        tipTitle: function (x) { return "k = " + fmt(x, 0) + " removed"; }, tipValue: function (sr, i) { return pct(sr.y[i], 2); },
        ariaLabel: "Line chart of partition probability against the number of removed nodes, one line per cage.",
      });
      var extra = [["cds_lower_bound", "Smallest backbone, lower bound"], ["cds_exact", "Smallest backbone, exact"], ["cds_greedy", "Backbone the builder finds"]].filter(function (p) { return rows.some(function (r) { return r[p[0]] !== undefined; }); });
      f.table(["Cage", "Solid", "Nodes", "Links", "Degree", "Diameter", "Min vertex cut", "Faces"].concat(extra.map(function (p) { return p[1]; })).concat(ks.map(function (k) { return "P(split), k=" + k; })), rows.map(function (r) {
        var pp = get(r, "partition_probability", {}), ex2 = arr(r.partition_exact);
        return [String(r.cage || DASH), String(r.solid || DASH), fmtVal(r.n), fmtVal(r.links), fmtVal(r.degree), fmtVal(r.diameter), fmtVal(r.min_vertex_cut), fmtVal(r.faces)]
          .concat(extra.map(function (p) { return fmtVal(r[p[0]]); }))
          .concat(ks.map(function (k, i) { return pct(pp[String(k)], 2) + (ex2[i] === false ? " *" : ""); }));
      }), { num: [2, 3, 4, 5, 6, 7].concat(extra.map(function (_, i) { return 8 + i; })).concat(ks.map(function (_, i) { return 8 + extra.length + i; })), caption: "* sampled at random rather than counted exactly. Backbone: the smallest connected dominating set, the simulator's reading of a valid ACTIVE set." });
    }, host);

    // E5 + E6 · small tables
    safe("E5 E6 tables", function () {
      var wrap = el("div", { class: "chart-grid" }, host);
      var smallFig = function (id, title, sub) {
        var b = el("figure", { class: "chart", "data-chart": "", id: id }, wrap);
        var h = el("div", { class: "chart-head" }, b);
        var d = el("div", null, h);
        el("h4", { class: "chart-title" }, d, title);
        el("p", { class: "chart-sub" }, d, sub);
        return b;
      };
      var nS5 = arr(get(ex, "offline.seeds")).length;
      var b5 = smallFig("e5", "E5 · Offline: messages sent to sleeping devices", "Share of messages addressed to a GHOST device. Nothing in the protocol holds them for later, so each one is dropped. " + [durText(get(ex, "offline.duration")), seedsText(get(ex, "offline.seeds"))].filter(Boolean).join(", ") + ".");
      var g1 = genericRows(get(ex, "offline.rows"), "active_fraction", function (v) { return pct(v, 0); }, nS5);
      C.fillTable(el("div", { class: "table-wrap" }, b5), g1.head, g1.rows, { num: g1.num, caption: "Varying the initial ACTIVE share (an assumption)." });
      if (arr(get(ex, "offline.ghost_pool_rows")).length) {
        var g2 = genericRows(get(ex, "offline.ghost_pool_rows"), "standby_fraction", function (v) { return pct(v, 0); }, nS5);
        C.fillTable(el("div", { class: "table-wrap", style: "margin-top:0.75rem" }, b5), g2.head, g2.rows, { num: g2.num, caption: "Varying the STANDBY share instead, which shrinks or grows the GHOST pool." });
      }
      var b6 = smallFig("e6", "E6 · Churn: nodes leaving and rejoining", "Churn rate is an assumption: the journal asks for a fixed rate but gives none. " + [durText(get(ex, "churn.duration")), seedsText(get(ex, "churn.seeds"))].filter(Boolean).join(", ") + ".");
      var g6 = genericRows(get(ex, "churn.rows"), "churn_rate", function (v) { return fmt(v, 3) + " /s"; }, arr(get(ex, "churn.seeds")).length);
      C.fillTable(el("div", { class: "table-wrap" }, b6), g6.head, g6.rows, { num: g6.num });
    }, host);
  }

  // ---- 5 · MeshGuard -------------------------------------------------------------
  var SMALL = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve"];
  function renderMeshGuard() {
    // the rule count in the intro is the number of labeling functions in the export
    var nr = arr(get(MG, "detail.lf")).length, nrEl = $("mg-nrules");
    if (nrEl) nrEl.textContent = nr ? (SMALL[nr] || String(nr)) : "Several";
    var pl = $("mg-pipeline");
    pl.textContent = "";
    var stages = arr(get(MG, "pipeline"));
    if (!stages.length) el("li", null, pl, "No pipeline in the data.");
    stages.forEach(function (s) {
      var li = el("li", null, pl);
      el("span", null, li, s.label || s.id || DASH);
      if (s.id) el("small", null, li, s.id);
    });
    var sweep = arr(get(MG, "sweep"));
    var res = $("mg-results");
    res.textContent = "";
    safe("MeshGuard results", function () {
      el("h3", { style: "margin-bottom:0.5rem" }, res, "Results across seeds");
      var tw = el("div", { class: "table-wrap" }, res);
      var st = function (r, stage, k) { return fixedOr(get(r, ["stages", stage, k]), 3); };
      C.fillTable(tw, ["Seed", "MV AUPRC", "DS AUPRC", "DS+iso AUPRC", "MV F1", "DS F1", "DS+iso F1", "ECE raw", "ECE temp", "ECE iso", "Rogue quarantined"], sweep.map(function (r) {
        var q = get(r, "rogue.quarantined", null);
        return [String(get(r, "seed", DASH)), st(r, "majority_vote", "auprc"), st(r, "dawid_skene", "auprc"), st(r, "dawid_skene_isolation", "auprc"),
          st(r, "majority_vote", "f1"), st(r, "dawid_skene", "f1"), st(r, "dawid_skene_isolation", "f1"),
          fixedOr(get(r, "calibration.ece_before"), 4), fixedOr(get(r, "calibration.ece_temperature"), 4), fixedOr(get(r, "calibration.ece_isotonic"), 4),
          q === null ? DASH : q ? "yes" : "no"];
      }), { num: [1, 2, 3, 4, 5, 6, 7, 8, 9], caption: "Held-out evaluation blocks, " + seedsText(get(MG, "seeds")) + ". MV: majority vote. DS: Dawid–Skene. iso: failure-domain isolation. ECE: expected calibration error, raw, after temperature scaling, and after isotonic regression." });
      // every scalar per seed, so nothing in the export is hidden
      var flat = function (o, prefix, out) {
        Object.keys(o || {}).forEach(function (k) {
          var v = o[k], key = prefix ? prefix + "." + k : k;
          if (v && typeof v === "object" && !Array.isArray(v)) flat(v, key, out);
          else if (!Array.isArray(v) && k !== "seed") out[key] = v;
        });
        return out;
      };
      var flats = sweep.map(function (r) { return flat(r, "", {}); });
      var keys = [];
      flats.forEach(function (f) { Object.keys(f).forEach(function (k) { if (keys.indexOf(k) < 0) keys.push(k); }); });
      var dr = el("details", { class: "drawer", style: "margin-top:0.75rem", id: "mg-all" }, res);
      el("summary", null, dr, "Every metric per seed");
      var inner = el("div", null, dr);
      C.fillTable(el("div", { class: "table-wrap" }, inner), ["Metric"].concat(sweep.map(function (r) { return "seed " + get(r, "seed", DASH); })), keys.map(function (k) {
        return [k.replace(/_/g, " ")].concat(flats.map(function (f) { var v = f[k]; return typeof v === "number" ? fmt(v, 4) : v === undefined || v === null ? DASH : typeof v === "boolean" ? (v ? "yes" : "no") : String(v); }));
      }), { num: sweep.map(function (_, i) { return i + 1; }) });
    }, res);

    var det = get(MG, "detail", {});
    var host = $("mg-charts");
    host.textContent = "";
    safe("reliability diagram", function () {
      var b = get(det, "reliability.before", {}), a = get(det, "reliability.after", {});
      var f = C.figure(host, { id: "mg-reliability", level: "h4", title: "Reliability, before and after calibration", sub: "Seed " + fmtVal(det.seed) + ". Each dot is a confidence bin, sized by how many readings fall in it. On the diagonal, confidence equals accuracy." });
      var maxCount = 1;
      [b, a].forEach(function (o) { arr(o.count).forEach(function (c) { if (isNum(c)) maxCount = Math.max(maxCount, c); }); });
      var mk = function (o, name, color) {
        var x = [], y = [], cnt = [];
        arr(o.conf).forEach(function (cv, i) { if (isNum(cv) && isNum(arr(o.acc)[i])) { x.push(cv); y.push(o.acc[i]); cnt.push(arr(o.count)[i]); } });
        return { name: name + " · ECE " + fixedOr(o.ece, 4), color: color, x: x, y: y, cnt: cnt, dots: true, line: false, exact: false, r: function (i) { return 2.5 + 5.5 * Math.sqrt((cnt[i] || 0) / maxCount); } };
      };
      var series = [mk(b, "Before", "var(--s1)"), mk(a, "After temperature scaling", "var(--s2)")];
      f.legend(series.map(function (s) { return { name: s.name, color: s.color, kind: "dot" }; }));
      C.line(f.plot(), {
        fig: f.fig, tip: f.tip, height: 260, series: series, refs: [{ diag: true, label: "perfect calibration" }],
        x: { min: -0.03, max: 1.03, ticks: [0, 0.2, 0.4, 0.6, 0.8, 1], title: "mean confidence in bin", format: function (v) { return fmt(v, 1); } },
        y: { min: 0, max: 1.06, ticks: [0, 0.25, 0.5, 0.75, 1], title: "accuracy in bin", format: function (v) { return fmt(v, 2); } },
        tipTitle: function (x) { return "confidence near " + fmt(x, 2); },
        tipValue: function (sr, i) { return i >= 0 ? fmt(sr.y[i], 2) + " acc · " + fmt(sr.cnt[i], 0) + " readings" : DASH; },
        ariaLabel: "Reliability diagram: accuracy against confidence per bin, before and after calibration.",
      });
      var n = Math.max(arr(b.conf).length, arr(a.conf).length);
      var rows = [];
      for (var i = 0; i < n; i++) rows.push([String(i + 1), fixedOr(arr(b.conf)[i], 3), fixedOr(arr(b.acc)[i], 3), fmt(arr(b.count)[i], 0), fixedOr(arr(a.conf)[i], 3), fixedOr(arr(a.acc)[i], 3), fmt(arr(a.count)[i], 0)]);
      f.table(["Bin", "Before conf", "Before acc", "Before n", "After conf", "After acc", "After n"], rows, { num: [1, 2, 3, 4, 5, 6] });
    }, host);
    safe("coverage-risk curve", function () {
      var cr = get(det, "coverage_risk", {});
      var sel = get(cr, "selection", {});
      var f = C.figure(host, { id: "mg-coverage", level: "h4", title: "Coverage against risk", sub: "Seed " + fmtVal(det.seed) + ". Accept the most confident readings first; risk is the error rate among those accepted. The dot is the operating point chosen for the risk limit." , tallTable: true });
      var series = [
        { name: "Uncalibrated", color: "var(--s1)", x: arr(get(cr, "uncalibrated.coverage")), y: arr(get(cr, "uncalibrated.risk")), exact: false, dash: "6 4" },
        { name: "Calibrated", color: "var(--s2)", x: arr(get(cr, "calibrated.coverage")), y: arr(get(cr, "calibrated.risk")), exact: false },
      ];
      f.legend(series.map(function (s) { return { name: s.name, color: s.color, dash: s.dash }; }));
      // where the curves share a coverage value, compare their risk: if they coincide, the
      // calibrated line would hide the other, so the uncalibrated one is drawn dashed on top
      var shared = 0, maxGap = 0;
      series[0].x.forEach(function (cv, i) {
        if (!isNum(cv) || !isNum(series[0].y[i])) return;
        for (var j = 0; j < series[1].x.length; j++) {
          if (isNum(series[1].x[j]) && Math.abs(series[1].x[j] - cv) < 1e-9 && isNum(series[1].y[j])) { shared++; maxGap = Math.max(maxGap, Math.abs(series[1].y[j] - series[0].y[i])); break; }
        }
      });
      var extra = series[0].x.filter(isNum).length - shared;
      if (shared) {
        f.noteEl.hidden = false;
        f.noteEl.textContent = (maxGap < 5e-4
          ? "The two curves have " + (maxGap === 0 ? "the same risk" : "the same risk to within 0.05 percentage points") + " at all " + shared + " coverage values they share, so they overlap; the uncalibrated curve is drawn dashed on top."
          : "At the " + shared + " coverage values the curves share, their risk differs by at most " + fmt(maxGap * 100, 2) + " percentage points; the uncalibrated curve is drawn dashed on top.") +
          (extra > 0 ? " The uncalibrated curve also has " + extra + " point" + (extra === 1 ? "" : "s") + " the calibrated one lacks." : "");
      }
      C.line(f.plot(), {
        fig: f.fig, tip: f.tip, height: 260, series: [series[1], series[0]],
        refs: isNum(sel.max_risk) ? [{ axis: "y", value: sel.max_risk, label: "risk limit " + pct(sel.max_risk, 0), short: "limit " + pct(sel.max_risk, 0) }] : [],
        points: isNum(sel.coverage) && isNum(sel.risk) ? [{ x: sel.coverage, y: sel.risk, label: "chosen: " + pct(sel.coverage, 1) + " coverage, " + pct(sel.risk, 1) + " risk" }] : [],
        x: { min: 0, max: 1, title: "coverage", format: function (v) { return pct(v, 0); } }, y: { min: 0, title: "risk", format: function (v) { return pct(v, 1); } },
        tipTitle: function (x) { return "coverage " + pct(x, 1); }, tipValue: function (sr, i) { return i >= 0 ? pct(sr.y[i], 2) + " at " + pct(sr.x[i], 1) : DASH; },
        ariaLabel: "Coverage-risk curves for the uncalibrated and calibrated model, with the chosen operating point.",
      });
      var n = Math.max(series[0].x.length, series[1].x.length), rows = [];
      for (var i = 0; i < n; i++) rows.push([String(i + 1), pct(series[0].x[i], 2), pct(series[0].y[i], 2), pct(series[1].x[i], 2), pct(series[1].y[i], 2)]);
      f.table(["Point", "Uncalibrated coverage", "Uncalibrated risk", "Calibrated coverage", "Calibrated risk"], rows, { num: [0, 1, 2, 3, 4] });
    }, host);

    var sh = $("mg-stream");
    sh.textContent = "";
    safe("stream sample", function () {
      var ss = get(det, "stream_sample", {});
      var steps = arr(ss.steps), ser = arr(ss.series);
      var f = C.figure(sh, { id: "mg-stream-fig", level: "h4", title: "The faulty sensors, and two healthy ones", sub: "Seed " + fmtVal(det.seed) + ", raw readings. The marked line is where the injected fault begins. Gaps are missing readings.", tallTable: true });
      var lo = Infinity, hi = -Infinity;
      ser.forEach(function (s) { arr(s.values).forEach(function (v) { if (isNum(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }); });
      if (!isFinite(lo)) { lo = 0; hi = 1; }
      var dom = C.niceDomain(lo, hi, 3);
      var x0 = steps.length ? steps[0] : 0, x1 = steps.length ? steps[steps.length - 1] : 1;
      var grid = el("div", { class: "multiples" }, f.area);
      ser.forEach(function (s) {
        var cell = el("div", null, grid);
        el("p", { class: "mtitle" }, cell, "Sensor " + fmtVal(s.node) + " · " + (s.regime || DASH));
        el("p", { class: "msub" }, cell, isNum(s.onset) ? "fault from step " + s.onset : "no fault injected");
        C.line(el("div", { class: "plot" }, cell), {
          fig: f.fig, tip: f.tip, height: 130, series: [{ name: "reading", color: "var(--pencil)", x: steps, y: arr(s.values), width: 1.5 }],
          refs: isNum(s.onset) ? [{ axis: "x", value: s.onset }] : [],
          x: { min: x0, max: x1, format: function (v) { return fmt(v, 0); } }, y: { min: dom.min, max: dom.max, ticks: dom.ticks, format: function (v) { return fmt(v, 0); } },
          tipTitle: function (x) { return "sensor " + s.node + ", step " + fmt(x, 0); }, tipValue: function (sr, i) { return fmt(sr.y[i], 2); },
          ariaLabel: "Readings of sensor " + s.node + " (" + s.regime + ") over time.",
        });
      });
      f.table(["Step"].concat(ser.map(function (s) { return "Sensor " + s.node + " (" + s.regime + ")"; })), steps.map(function (st, i) {
        return [fmt(st, 0)].concat(ser.map(function (s) { return fmt(arr(s.values)[i], 3); }));
      }), { num: ser.map(function (_, i) { return i; }).concat([ser.length]) });
    }, sh);

    var lf = $("mg-lf");
    lf.textContent = "";
    safe("labeling functions", function () {
      el("h3", { style: "margin-bottom:0.5rem" }, lf, "How far each rule can be trusted");
      el("p", { class: "small", style: "margin-bottom:0.5rem" }, lf, "Seed " + fmtVal(det.seed) + ". The label model estimates each rule's accuracy without labels; the true accuracy is measured on the evaluation blocks only, as a check.");
      var tw = el("div", { class: "table-wrap" }, lf);
      C.fillTable(tw, ["Rule", "Estimated accuracy", "True accuracy (eval)", "Abstains"], arr(det.lf).map(function (r) {
        return [String(r.name || DASH), fixedOr(r.estimated_accuracy, 3), fixedOr(r.true_accuracy_eval_only, 3), pct(r.abstain_rate, 1)];
      }), { num: [1, 2, 3] });
    }, lf);

    var sel = $("mg-seed");
    sel.textContent = "";
    sweep.forEach(function (r, i) { el("option", { value: String(i) }, sel, "seed " + get(r, "seed", i)); });
    var di = 0;
    sweep.forEach(function (r, i) { if (r.seed === det.seed) di = i; });
    sel.value = String(di);
    var draw = function () {
      var ul = $("mg-flags");
      ul.textContent = "";
      var flags = arr(get(sweep[Number(sel.value)], "flags"));
      if (!flags.length) el("li", null, ul, "No flags for this seed.");
      flags.forEach(function (fl) {
        var m = /^([A-Z][A-Z ]+):\s*(.*)$/.exec(String(fl));
        var kind = m ? m[1].trim() : "NOTE", text = m ? m[2] : String(fl);
        var li = el("li", null, ul);
        var chip = el("span", { class: "chip" }, li);
        glyph(/NEGATIVE/.test(kind) ? "negative" : "note", chip);
        el("span", null, chip, /NEGATIVE/.test(kind) ? "negative" : kind.toLowerCase());
        el("span", null, li, text);
      });
    };
    sel.addEventListener("change", draw);
    draw();
  }
  function fixedOr(v, d) { return isNum(v) ? v.toFixed(d) : DASH; }

  // ---- 8 · reproduce + footer ----------------------------------------------------
  function renderReproduce() {
    document.querySelectorAll("#steps .copy").forEach(function (b) {
      var code = b.parentNode.querySelector("code");
      b.setAttribute("aria-label", "Copy command: " + code.textContent);
      b.addEventListener("click", function () {
        var text = code.textContent;
        var out = $("copied");
        var fallback = function () {
          try {
            var r = document.createRange();
            r.selectNodeContents(code);
            var s = window.getSelection();
            s.removeAllRanges();
            s.addRange(r);
            out.textContent = "Selected. Press Ctrl+C or Cmd+C to copy.";
          } catch (e) { out.textContent = "Select the command and copy it."; }
        };
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(function () { out.textContent = "Copied: " + text; }, fallback);
          } else fallback();
        } catch (e) { fallback(); }
      });
    });
    var g = $("generators");
    g.textContent = "Data files: " + (D ? get(D, "generator", DASH) + " (schema " + get(D, "schema", DASH) + ")" : "simulator data missing") +
      " · " + (MG ? get(MG, "generator", DASH) + " (schema " + get(MG, "schema", DASH) + ")" : "MeshGuard data missing") + ".";
  }

  // ---- theme ------------------------------------------------------------------------
  function watchTheme() {
    var refresh = function () {
      requestAnimationFrame(function () {
        cages.forEach(function (c) { c.refreshTheme(); });
        C.rerenderAll();
        Live.charts.forEach(function (c) { c.setPlayhead(Live.timeAt(Live.idx)); });
        if (Live.sc) Live.renderTicks();
      });
    };
    if (window.matchMedia) {
      var mq = window.matchMedia("(prefers-color-scheme: dark)");
      if (mq.addEventListener) mq.addEventListener("change", refresh);
      else if (mq.addListener) mq.addListener(refresh);
    }
    if (window.MutationObserver) new MutationObserver(refresh).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  }

  // ---- header nav: on narrow screens the links sit behind a "Sections" button -------
  function setupNav() {
    var nav = document.querySelector(".nav"), btn = $("nav-toggle"), list = $("nav-list");
    if (!nav || !btn || !list) return;
    var isOpen = function () { return nav.classList.contains("open"); };
    var set = function (open, focusBtn) {
      nav.classList.toggle("open", open);
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      if (!open && focusBtn) btn.focus();
    };
    btn.addEventListener("click", function () { set(!isOpen()); });
    list.addEventListener("click", function (e) { if (e.target.closest && e.target.closest("a")) set(false); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && isOpen()) set(false, true); });
    document.addEventListener("click", function (e) { if (isOpen() && !nav.contains(e.target)) set(false); });
    nav.addEventListener("focusout", function (e) { if (isOpen() && e.relatedTarget && !nav.contains(e.relatedTarget)) set(false); });
  }

  function boot() {
    safe("navigation", setupNav);
    ensureData(function () {
      renderNotice();
      safe("legends", renderLegends);
      safe("hero", renderHero, $("hero-counts").parentNode);
      safe("live cell", function () { Live.init(); }, $("instrument"));
      safe("ladder", renderLadder);
      safe("findings", renderFindings, $("findings-list"));
      safe("experiments", renderExperiments, $("exp-charts"));
      safe("MeshGuard", renderMeshGuard, $("mg-results"));
      safe("reproduce", renderReproduce);
      watchTheme();
      window.__BMFP = { Live: Live, fixture: FIXTURE, eventText: eventText };
      window.__BMFP_READY = true;
      document.documentElement.setAttribute("data-ready", "1");
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
