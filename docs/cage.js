/* BMFP cage renderer: a ball-and-stick model on canvas with manual perspective projection,
   depth-sorted drawing, drag/touch/keyboard rotation and theme-aware colours.
   No libraries. Exposes window.BMFPCage. */
(function (global) {
  "use strict";

  var reduceMQ = global.matchMedia ? global.matchMedia("(prefers-reduced-motion: reduce)") : null;

  function token(name, fallback) {
    try {
      var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      return v || fallback;
    } catch (e) {
      return fallback;
    }
  }
  function hexToRgb(h) {
    h = String(h || "").trim();
    var m = /^#?([0-9a-f]{6})$/i.exec(h);
    if (!m) {
      var s = /^#?([0-9a-f]{3})$/i.exec(h);
      if (!s) return [128, 128, 128];
      m = [0, s[1].split("").map(function (c) { return c + c; }).join("")];
    }
    var n = parseInt(m[1], 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function mix(a, b, t) {
    var x = hexToRgb(a), y = hexToRgb(b);
    var r = [0, 1, 2].map(function (i) { return Math.round(x[i] + (y[i] - x[i]) * t); });
    return "rgb(" + r.join(",") + ")";
  }
  function rgba(a, alpha) {
    var x = hexToRgb(a);
    return "rgba(" + x[0] + "," + x[1] + "," + x[2] + "," + alpha + ")";
  }

  // 3x3 rotation matrices, row-major arrays of 9
  function rotX(a) { var c = Math.cos(a), s = Math.sin(a); return [1, 0, 0, 0, c, -s, 0, s, c]; }
  function rotY(a) { var c = Math.cos(a), s = Math.sin(a); return [c, 0, s, 0, 1, 0, -s, 0, c]; }
  function mul(A, B) {
    var o = new Array(9);
    for (var r = 0; r < 3; r++)
      for (var c = 0; c < 3; c++)
        o[r * 3 + c] = A[r * 3] * B[c] + A[r * 3 + 1] * B[3 + c] + A[r * 3 + 2] * B[6 + c];
    return o;
  }
  // keep the matrix orthonormal after many small multiplications
  function orthonormalise(M) {
    var x = [M[0], M[3], M[6]], y = [M[1], M[4], M[7]];
    var nx = Math.hypot(x[0], x[1], x[2]) || 1;
    x = x.map(function (v) { return v / nx; });
    var d = x[0] * y[0] + x[1] * y[1] + x[2] * y[2];
    y = [y[0] - d * x[0], y[1] - d * x[1], y[2] - d * x[2]];
    var ny = Math.hypot(y[0], y[1], y[2]) || 1;
    y = y.map(function (v) { return v / ny; });
    var z = [x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]];
    return [x[0], y[0], z[0], x[1], y[1], z[1], x[2], y[2], z[2]];
  }

  var STATE_NAMES = { A: "ACTIVE", S: "STANDBY", G: "GHOST", D: "DEAD" };

  function Cage(canvas, opts) {
    opts = opts || {};
    this.canvas = canvas;
    this.ctx = canvas.getContext ? canvas.getContext("2d") : null;
    this.tip = opts.tip || null;
    this.onKeyOther = opts.onKeyOther || null;
    this.labelPrefix = opts.label || "Cage";
    this.M = mul(rotX(-0.38), rotY(0.55));
    this.cage = null;
    this.states = "";
    this.loads = "";
    this.stems = [];
    this.captains = [];
    this.autoRotate = opts.autoRotate !== false;
    this.userTouched = false;
    this.visible = true;
    this.raf = 0;
    this.last = 0;
    this.colors = {};
    this.proj = [];
    this.size = 0;
    this.readTheme();
    this._bind();
    this.resize();
  }

  Cage.prototype.readTheme = function () {
    this.colors = {
      plate: token("--plate", "#f9fbf8"),
      ink: token("--ink", "#17201c"),
      ink3: token("--ink-3", "#5f6a64"),
      stick: token("--stick", "#8d9890"),
      A: token("--st-active", "#2a78d6"),
      S: token("--st-standby", "#eda100"),
      G: token("--st-ghost", "#1baf7a"),
      D: token("--st-dead", "#d03b3b"),
      hi: token("--shade-hi", "#ffffff"),
      lo: token("--shade-lo", "#000000"),
    };
  };

  Cage.prototype.motionAllowed = function () {
    return !(reduceMQ && reduceMQ.matches);
  };

  Cage.prototype._bind = function () {
    var self = this, c = this.canvas;
    var dragging = false, lx = 0, ly = 0, pid = null;
    c.addEventListener("pointerdown", function (e) {
      dragging = true; pid = e.pointerId; lx = e.clientX; ly = e.clientY;
      self.userTouched = true;
      try { c.setPointerCapture(e.pointerId); } catch (err) { /* not capturable */ }
      self.hideTip();
    });
    c.addEventListener("pointermove", function (e) {
      if (dragging && e.pointerId === pid) {
        var dx = e.clientX - lx, dy = e.clientY - ly;
        lx = e.clientX; ly = e.clientY;
        self.rotate(dx * 0.011, dy * 0.011);
      } else if (e.pointerType !== "touch") {
        self.hover(e);
      }
    });
    function end(e) { if (e.pointerId === pid) { dragging = false; pid = null; } }
    c.addEventListener("pointerup", end);
    c.addEventListener("pointercancel", end);
    c.addEventListener("pointerleave", function () { if (!dragging) self.hideTip(); });
    c.addEventListener("keydown", function (e) {
      var step = e.shiftKey ? 0.35 : 0.14, handled = true;
      if (e.key === "ArrowLeft") self.rotate(-step, 0);
      else if (e.key === "ArrowRight") self.rotate(step, 0);
      else if (e.key === "ArrowUp") self.rotate(0, -step);
      else if (e.key === "ArrowDown") self.rotate(0, step);
      else handled = false;
      if (handled) { e.preventDefault(); e.stopPropagation(); self.userTouched = true; }
    });
    if (global.ResizeObserver) {
      new ResizeObserver(function () { self.resize(); }).observe(c);
    } else {
      global.addEventListener("resize", function () { self.resize(); });
    }
    if (global.IntersectionObserver) {
      new IntersectionObserver(function (entries) {
        self.visible = entries[0] ? entries[0].isIntersecting : true;
        self.loop();
      }).observe(c);
    }
    if (reduceMQ && reduceMQ.addEventListener) reduceMQ.addEventListener("change", function () { self.loop(); });
  };

  Cage.prototype.rotate = function (yaw, pitch) {
    this.M = orthonormalise(mul(rotX(pitch), mul(rotY(yaw), this.M)));
    this.draw();
  };

  Cage.prototype.resize = function () {
    var c = this.canvas;
    var w = c.clientWidth || c.width || 400;
    var dpr = Math.min(global.devicePixelRatio || 1, 2.5);
    var px = Math.max(100, Math.round(w * dpr));
    if (c.width !== px || c.height !== px) { c.width = px; c.height = px; }
    this.size = w;
    this.dpr = dpr;
    this.draw();
  };

  Cage.prototype.setCage = function (cage) {
    this.cage = cage && Array.isArray(cage.coords) && Array.isArray(cage.edges) ? cage : null;
    this.draw();
  };

  Cage.prototype.setFrame = function (states, loads, stems, captains) {
    this.states = typeof states === "string" ? states : "";
    this.loads = typeof loads === "string" ? loads : "";
    this.stems = Array.isArray(stems) ? stems : [];
    this.captains = Array.isArray(captains) ? captains : [];
    this.draw();
  };

  Cage.prototype.loop = function () {
    var self = this;
    var want = this.autoRotate && !this.userTouched && this.visible && this.motionAllowed() && !document.hidden;
    if (want && !this.raf) {
      this.last = 0;
      var step = function (ts) {
        if (!(self.autoRotate && !self.userTouched && self.visible && self.motionAllowed())) { self.raf = 0; return; }
        if (self.last) {
          var dt = Math.min(0.05, (ts - self.last) / 1000);
          self.M = orthonormalise(mul(rotY(dt * 0.16), self.M));
          self.draw();
        }
        self.last = ts;
        self.raf = requestAnimationFrame(step);
      };
      this.raf = requestAnimationFrame(step);
    }
  };

  Cage.prototype.project = function () {
    var cg = this.cage, M = this.M, out = [];
    if (!cg) return out;
    var size = this.size, D = 3.6;
    var n = cg.coords.length;
    var r0 = size * Math.min(0.055, 0.05 / Math.sqrt(Math.max(1, n) / 12));
    var maxP = D / (D - 1);
    var R = (size / 2 - r0 * 1.9) / maxP;
    for (var i = 0; i < n; i++) {
      var p = cg.coords[i] || [0, 0, 0];
      var x = M[0] * p[0] + M[1] * p[1] + M[2] * p[2];
      var y = M[3] * p[0] + M[4] * p[1] + M[5] * p[2];
      var z = M[6] * p[0] + M[7] * p[1] + M[8] * p[2];
      var s = D / (D - z);
      out.push({ i: i, x: size / 2 + x * R * s, y: size / 2 - y * R * s, z: z, s: s, r: r0 * s });
    }
    return out;
  };

  Cage.prototype.draw = function () {
    var ctx = this.ctx;
    if (!ctx || !this.size) return;
    var col = this.colors, dpr = this.dpr || 1, size = this.size;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size, size);
    var P = this.project();
    this.proj = P;
    if (!P.length) {
      ctx.fillStyle = col.ink3;
      ctx.font = "13px " + token("--font-body", "sans-serif");
      ctx.textAlign = "center";
      ctx.fillText("Cage geometry is missing from the data.", size / 2, size / 2);
      return;
    }
    var st = this.states, ld = this.loads;
    var stems = {}, caps = {};
    this.stems.forEach(function (s) { stems[s] = true; });
    this.captains.forEach(function (s) { caps[s] = true; });
    var items = [];
    var edges = this.cage.edges;
    for (var k = 0; k < edges.length; k++) {
      var e = edges[k];
      if (!e || P[e[0]] === undefined || P[e[1]] === undefined) continue;
      items.push({ t: 0, a: P[e[0]], b: P[e[1]], z: (P[e[0]].z + P[e[1]].z) / 2 - 0.02 });
    }
    for (var j = 0; j < P.length; j++) items.push({ t: 1, p: P[j], z: P[j].z });
    items.sort(function (u, v) { return u.z - v.z; });

    for (var q = 0; q < items.length; q++) {
      var it = items[q];
      var fog = (1 - it.z) / 2; // 0 near, 1 far
      if (it.t === 0) {
        var sa = st.charAt(it.a.i) || "S", sb = st.charAt(it.b.i) || "S";
        var broken = sa === "D" || sb === "D";
        var w = Math.max(1, (it.a.r + it.b.r) * 0.16);
        ctx.lineCap = "round";
        ctx.strokeStyle = broken ? rgba(col.stick, 0.28) : mix(col.stick, col.plate, fog * 0.55);
        ctx.lineWidth = broken ? Math.max(1, w * 0.45) : w;
        ctx.beginPath(); ctx.moveTo(it.a.x, it.a.y); ctx.lineTo(it.b.x, it.b.y); ctx.stroke();
        if (!broken && w > 1.6) {
          ctx.strokeStyle = rgba(col.plate, 0.35 * (1 - fog));
          ctx.lineWidth = w * 0.3;
          ctx.beginPath(); ctx.moveTo(it.a.x, it.a.y - w * 0.18); ctx.lineTo(it.b.x, it.b.y - w * 0.18); ctx.stroke();
        }
      } else {
        this.drawNode(ctx, it.p, st.charAt(it.p.i) || "", parseInt(ld.charAt(it.p.i), 10) || 0, !!stems[it.p.i], !!caps[it.p.i], fog);
      }
    }
  };

  Cage.prototype.drawNode = function (ctx, p, s, load, isStem, isCap, fog) {
    var col = this.colors, r = p.r, x = p.x, y = p.y;
    var base = col[s] || col.stick;
    var c = mix(base, col.plate, fog * 0.45);
    if (load > 0 && s !== "D") {
      ctx.fillStyle = rgba(base, 0.1 + 0.022 * load);
      ctx.beginPath(); ctx.arc(x, y, r * (1.25 + 0.11 * load), 0, Math.PI * 2); ctx.fill();
    }
    if (s === "A") {
      ctx.fillStyle = col.plate;
      ctx.beginPath(); ctx.arc(x, y, r + 1.5, 0, Math.PI * 2); ctx.fill();
      var g = ctx.createRadialGradient(x - r * 0.38, y - r * 0.42, r * 0.1, x, y, r);
      g.addColorStop(0, mix(base, col.hi, 0.5 - fog * 0.2));
      g.addColorStop(0.55, c);
      g.addColorStop(1, mix(base, col.lo, 0.28));
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
      if (isStem) {
        ctx.fillStyle = col.plate;
        ctx.beginPath(); ctx.arc(x, y, Math.max(1.6, r * 0.3), 0, Math.PI * 2); ctx.fill();
      }
    } else if (s === "S") {
      ctx.fillStyle = col.plate;
      ctx.beginPath(); ctx.arc(x, y, r * 0.9, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = c;
      ctx.lineWidth = Math.max(2, r * 0.42);
      ctx.beginPath(); ctx.arc(x, y, r * 0.72, 0, Math.PI * 2); ctx.stroke();
    } else if (s === "G") {
      ctx.fillStyle = rgba(col.plate, 0.9);
      ctx.beginPath(); ctx.arc(x, y, r * 0.62, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = rgba(base, 0.75 - fog * 0.3);
      ctx.lineWidth = Math.max(1.25, r * 0.16);
      ctx.beginPath(); ctx.arc(x, y, r * 0.55, 0, Math.PI * 2); ctx.stroke();
    } else if (s === "D") {
      var h = r * 0.62;
      ctx.strokeStyle = col.plate;
      ctx.lineCap = "round";
      ctx.lineWidth = Math.max(2, r * 0.36) + 3;
      ctx.beginPath(); ctx.moveTo(x - h, y - h); ctx.lineTo(x + h, y + h); ctx.moveTo(x + h, y - h); ctx.lineTo(x - h, y + h); ctx.stroke();
      ctx.strokeStyle = c;
      ctx.lineWidth = Math.max(2, r * 0.36);
      ctx.beginPath(); ctx.moveTo(x - h, y - h); ctx.lineTo(x + h, y + h); ctx.moveTo(x + h, y - h); ctx.lineTo(x - h, y + h); ctx.stroke();
    } else {
      ctx.fillStyle = mix(col.stick, col.plate, fog * 0.5);
      ctx.beginPath(); ctx.arc(x, y, r * 0.55, 0, Math.PI * 2); ctx.fill();
    }
    if (isStem && s !== "A" && s !== "D") {
      ctx.fillStyle = col.ink;
      ctx.beginPath(); ctx.arc(x, y, Math.max(1.4, r * 0.22), 0, Math.PI * 2); ctx.fill();
    }
    if (isCap && s !== "D") {
      // captain: a small pennant above the node
      var fx = x + r * 0.15, fy = y - r * 1.05, fh = Math.max(5, r * 0.95);
      ctx.strokeStyle = col.ink;
      ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.moveTo(fx, fy); ctx.lineTo(fx, fy - fh); ctx.stroke();
      ctx.fillStyle = col.ink;
      ctx.beginPath(); ctx.moveTo(fx, fy - fh); ctx.lineTo(fx + fh * 0.75, fy - fh * 0.72); ctx.lineTo(fx, fy - fh * 0.44); ctx.closePath(); ctx.fill();
    }
  };

  Cage.prototype.hover = function (e) {
    if (!this.tip || !this.proj.length) return;
    var rect = this.canvas.getBoundingClientRect();
    var mx = e.clientX - rect.left, my = e.clientY - rect.top;
    // the front-most node under the pointer wins; otherwise the nearest one within reach
    var best = null, near = null, nd = Infinity;
    for (var i = 0; i < this.proj.length; i++) {
      var p = this.proj[i];
      var d = Math.hypot(p.x - mx, p.y - my);
      if (d <= p.r && (!best || p.z > best.z)) best = p;
      if (d < p.r + 8 && d < nd) { near = p; nd = d; }
    }
    best = best || near;
    if (!best) { this.hideTip(); return; }
    var s = this.states.charAt(best.i);
    var parts = ["Node " + best.i, STATE_NAMES[s] || "state unknown"];
    if (this.stems.indexOf(best.i) >= 0) parts.push("stem");
    if (this.captains.indexOf(best.i) >= 0) parts.push("captain");
    var ld = this.loads.charAt(best.i);
    if (ld !== "" && s !== "D") parts.push("relay load " + ld + "/9");
    this.tip.textContent = parts.join(" · ");
    this.tip.hidden = false;
    var off = this.canvas.offsetLeft, offt = this.canvas.offsetTop;
    var tx = Math.min(Math.max(best.x, 70), rect.width - 70);
    this.tip.style.left = off + tx + "px";
    this.tip.style.top = offt + best.y - best.r + "px";
  };

  Cage.prototype.hideTip = function () { if (this.tip) this.tip.hidden = true; };

  Cage.prototype.refreshTheme = function () { this.readTheme(); this.draw(); };

  Cage.STATE_NAMES = STATE_NAMES;
  global.BMFPCage = Cage;
})(window);
