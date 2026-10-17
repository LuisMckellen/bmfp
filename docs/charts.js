/* BMFP charts: small SVG chart kit (line / dot-and-whisker), built in JS.
   Every chart sits in a <figure class="chart"> with a hover + keyboard tooltip and a
   table-view twin. Colours are CSS custom properties, so marks follow the theme.
   Exposes window.BMFPCharts. */
(function (global) {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  var uid = 0;
  var registry = [];

  function isNum(v) { return typeof v === "number" && isFinite(v); }
  function el(tag, attrs, parent, text) {
    var e = document.createElement(tag);
    if (attrs) for (var k in attrs) if (attrs[k] !== undefined && attrs[k] !== null) e.setAttribute(k, attrs[k]);
    if (text !== undefined && text !== null) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }
  function svg(tag, attrs, parent, text) {
    var e = document.createElementNS(NS, tag);
    if (attrs) for (var k in attrs) if (attrs[k] !== undefined && attrs[k] !== null) e.setAttribute(k, attrs[k]);
    if (text !== undefined && text !== null) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }

  // ---- number formatting --------------------------------------------------
  function fmt(v, digits) {
    if (!isNum(v)) return "—";
    var d = digits === undefined ? 3 : digits;
    var a = Math.abs(v);
    if (a >= 10000) return Math.round(v).toLocaleString("en-US");
    return Number(v.toFixed(d)).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: 0 });
  }
  function fixed(v, digits) { return isNum(v) ? v.toFixed(digits) : "—"; }
  function pct(v, digits) {
    if (!isNum(v)) return "—";
    return (v * 100).toFixed(digits === undefined ? 1 : digits) + "%";
  }
  function niceStep(span, count) {
    var raw = span / Math.max(1, count);
    var p = Math.pow(10, Math.floor(Math.log10(raw)));
    var m = raw / p;
    var s = m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10;
    return s * p;
  }
  function ticks(min, max, count) {
    if (!isNum(min) || !isNum(max)) return [];
    if (min === max) return [min];
    var step = niceStep(max - min, count || 4);
    var out = [], start = Math.ceil(min / step - 1e-9) * step;
    for (var v = start; v <= max + step * 1e-6; v += step) out.push(Number(v.toFixed(10)));
    return out;
  }
  function niceMax(max, count) {
    if (!isNum(max) || max <= 0) return 1;
    var step = niceStep(max, count || 4);
    return Math.ceil(max / step - 1e-9) * step;
  }
  function niceDomain(lo, hi, count) {
    if (!isNum(lo) || !isNum(hi)) return { min: 0, max: 1, ticks: [0, 1] };
    if (lo === hi) { lo -= 1; hi += 1; }
    var step = niceStep(hi - lo, count || 4);
    var mn = Math.floor(lo / step + 1e-9) * step, mx = Math.ceil(hi / step - 1e-9) * step;
    var t = [];
    for (var v = mn; v <= mx + step * 1e-6; v += step) t.push(Number(v.toFixed(10)));
    return { min: mn, max: mx, ticks: t };
  }
  function textWidth(s, px) { return String(s).length * (px || 11) * 0.62; }

  // ---- tiny glyphs used by legends and tooltips --------------------------
  // kind: "dot" (marker on a line), "band" (shaded strip), "ref" (thin reference line), or a
  // plain line; dash: an SVG dasharray, so dashed series read as dashed in the key too
  function lineKey(color, parent, kind, dash) {
    var s = svg("svg", { viewBox: "0 0 18 12", "aria-hidden": "true" }, parent);
    if (kind === "dot") {
      svg("line", { x1: 1, y1: 6, x2: 17, y2: 6, style: "stroke:" + color + ";stroke-width:1.5;opacity:.7" }, s);
      svg("circle", { cx: 9, cy: 6, r: 4, style: "fill:" + color }, s);
    } else if (kind === "band") {
      svg("rect", { x: 1, y: 1, width: 16, height: 10, class: "band", style: "fill:" + color }, s);
    } else if (kind === "ref") {
      svg("line", { x1: 1, y1: 6, x2: 17, y2: 6, style: "stroke:var(--edge);stroke-width:1.2" }, s);
    } else {
      svg("line", { x1: 1, y1: 6, x2: 17, y2: 6, style: "stroke:" + color + ";stroke-width:2.5;stroke-linecap:" + (dash ? "butt" : "round") + (dash ? ";stroke-dasharray:" + dash : "") }, s);
    }
    return s;
  }

  // ---- tables -------------------------------------------------------------
  // head: array of labels; rows: arrays of strings; opts.num: indexes of numeric columns
  function fillTable(wrap, head, rows, opts) {
    opts = opts || {};
    wrap.textContent = "";
    // the visible caption sits outside the table so it wraps to the container, not the table width
    if (opts.caption) el("p", { class: "tcap", "aria-hidden": "true" }, wrap, opts.caption);
    var t = el("table", { class: opts.cls || null }, wrap);
    if (opts.caption) el("caption", { class: "vh" }, t, opts.caption);
    var thead = el("thead", null, t), tr = el("tr", null, thead);
    var num = {};
    (opts.num || []).forEach(function (i) { num[i] = true; });
    head.forEach(function (h, i) { el("th", { scope: "col", class: num[i] ? "num" : null }, tr, h); });
    var tb = el("tbody", null, t);
    if (!rows.length) {
      var r0 = el("tr", null, tb);
      el("td", { colspan: head.length }, r0, "No rows in the data.");
    }
    rows.forEach(function (row) {
      var r = el("tr", null, tb);
      row.forEach(function (c, i) {
        if (i === 0 && opts.rowHeader !== false) el("th", { scope: "row" }, r, c);
        else el("td", { class: num[i] ? "num" : null }, r, c);
      });
    });
    return t;
  }

  // ---- figure frame with table-view toggle --------------------------------
  // o.id should be passed: a fixed id keeps the table-toggle ids stable across re-renders
  function figure(parent, o) {
    o = o || {};
    var id = o.id || "chart-" + ++uid;
    var fig = el("figure", { class: "chart" + (o.cls ? " " + o.cls : ""), id: id, "data-chart": "" }, parent);
    var head = el("div", { class: "chart-head" }, fig);
    var hd = el("div", null, head);
    el(o.level || "h4", { class: "chart-title" }, hd, o.title || "");
    var sub = el("p", { class: "chart-sub" }, hd, o.sub || "");
    if (!o.sub) sub.hidden = true;
    var btn = el("button", { class: "btn table-toggle", type: "button", "aria-expanded": "false", "aria-controls": id + "-table", id: id + "-toggle" }, head, "Table view");
    var legend = el("ul", { class: "legend", "aria-label": "Legend" }, fig);
    legend.hidden = true;
    var area = el("div", { class: "plot-area" }, fig);
    var tableWrap = el("div", { class: "table-wrap" + (o.tallTable ? " tall" : ""), id: id + "-table" }, fig);
    tableWrap.hidden = true;
    var note = el("p", { class: "chart-note" }, fig, o.note || "");
    if (!o.note) note.hidden = true;
    var tip = el("div", { class: "tip", role: "status", "aria-live": "polite" }, fig);
    tip.hidden = true;
    btn.addEventListener("click", function () {
      var showTable = tableWrap.hidden;
      tableWrap.hidden = !showTable;
      area.hidden = showTable;
      legend.hidden = showTable || legend.childNodes.length < 2;
      btn.setAttribute("aria-expanded", showTable ? "true" : "false");
      btn.textContent = showTable ? "Chart view" : "Table view";
      tip.hidden = true;
    });
    var api = {
      fig: fig, area: area, tableWrap: tableWrap, tip: tip, legendEl: legend, noteEl: note, subEl: sub,
      legend: function (items) {
        legend.textContent = "";
        (items || []).forEach(function (it) {
          var li = el("li", null, legend);
          lineKey(it.color, li, it.kind, it.dash);
          el("span", null, li, it.name);
        });
        legend.hidden = !(items && items.length >= 2) || area.hidden;
      },
      table: function (head, rows, opts) { return fillTable(tableWrap, head, rows, opts); },
      plot: function (cls) { return el("div", { class: "plot" + (cls ? " " + cls : "") }, area); },
    };
    return api;
  }

  // ---- tooltip helpers ----------------------------------------------------
  function showTip(tip, fig, svgEl, px, py, title, rows) {
    tip.textContent = "";
    if (title) el("div", { class: "tip-h" }, tip, title);
    rows.forEach(function (r) {
      var row = el("div", { class: "row" }, tip);
      if (r.color) lineKey(r.color, row, r.kind, r.dash); else el("span", null, row);
      el("b", null, row, r.value);
      el("span", null, row, r.name || "");
    });
    tip.hidden = false;
    var fr = fig.getBoundingClientRect(), sr = svgEl.getBoundingClientRect();
    var tw = tip.offsetWidth, th = tip.offsetHeight;
    var left = sr.left - fr.left + px + 14;
    if (left + tw > fr.width - 6) left = sr.left - fr.left + px - tw - 14;
    left = Math.max(6, left);
    var top = sr.top - fr.top + Math.max(0, py - th / 2);
    top = Math.min(top, fr.height - th - 6);
    tip.style.left = left + "px";
    tip.style.top = Math.max(4, top) + "px";
  }

  // ---- line chart ---------------------------------------------------------
  function LineChart(host, o) {
    this.host = host;
    this.o = o;
    this.play = null;
    this.focusIdx = -1;
    var self = this;
    this.svg = svg("svg", { tabindex: "0", role: "img", "aria-label": o.ariaLabel || o.title || "Line chart", focusable: "true" }, host);
    this._keys();
    if (global.ResizeObserver) {
      var pending = false;
      this.ro = new ResizeObserver(function () {
        if (pending) return;
        pending = true;
        requestAnimationFrame(function () { pending = false; if (self.host.clientWidth && self.host.clientWidth !== self.lastW) self.render(); });
      });
      this.ro.observe(host);
    }
    register(this);
    this.render();
  }

  // Charts whose host has left the document (a scenario switch rebuilds the live charts)
  // are dropped from the registry and their resize observers disconnected, so nothing
  // keeps detached charts and their data arrays alive.
  function prune() {
    registry = registry.filter(function (c) {
      if (c.host && c.host.isConnected) return true;
      if (c.ro) { try { c.ro.disconnect(); } catch (e) { /* already gone */ } }
      c.ro = null;
      return false;
    });
  }
  function register(chart) {
    prune();
    registry.push(chart);
  }

  LineChart.prototype.xs = function () {
    // sorted union of every x that has a value (inside the x window, when one is set)
    var seen = {}, out = [], xo = this.o.x || {};
    var lo = isNum(xo.min) ? xo.min : -Infinity, hi = isNum(xo.max) ? xo.max : Infinity;
    (this.o.series || []).forEach(function (s) {
      (s.x || []).forEach(function (x, i) {
        if (isNum(x) && x >= lo && x <= hi && isNum((s.y || [])[i]) && !seen[x]) { seen[x] = true; out.push(x); }
      });
    });
    out.sort(function (a, b) { return a - b; });
    return out;
  };

  LineChart.prototype.render = function () {
    var o = this.o, s = this.svg;
    while (s.firstChild) s.removeChild(s.firstChild);
    var W = Math.max(220, this.host.clientWidth || 300);
    this.lastW = this.host.clientWidth;
    var H = o.height || 200;
    var series = (o.series || []).filter(function (x) { return x && Array.isArray(x.x) && Array.isArray(x.y); });
    var allX = this.xs();
    this.allX = allX;
    var xo = o.x || {}, yo = o.y || {};
    // domains
    var xmin = isNum(xo.min) ? xo.min : allX.length ? allX[0] : 0;
    var xmax = isNum(xo.max) ? xo.max : allX.length ? allX[allX.length - 1] : 1;
    if (xmin === xmax) { xmax = xmin + 1; }
    var ymin = isNum(yo.min) ? yo.min : 0, ymax = yo.max;
    if (!isNum(ymax)) {
      var m = -Infinity;
      series.forEach(function (sr) {
        sr.y.forEach(function (v, i) { if (isNum(v)) m = Math.max(m, v); var h = sr.hi && sr.hi[i]; if (isNum(h)) m = Math.max(m, h); });
      });
      (o.refs || []).forEach(function (r) { if (r.axis === "y" && isNum(r.value)) m = Math.max(m, r.value); });
      ymax = niceMax(isFinite(m) ? m * 1.04 : 1, 4);
      if (ymax <= ymin) ymax = ymin + 1;
    }
    var yt = yo.ticks || ticks(ymin, ymax, yo.count || 4);
    var yfmt = yo.format || function (v) { return fmt(v, 2); };
    var xfmt = xo.format || function (v) { return fmt(v, 2); };
    var ml = 8 + Math.max.apply(null, yt.map(function (t) { return textWidth(yfmt(t)); }).concat([16]));
    // the right margin holds end-of-line labels and y-reference labels; x-reference labels
    // sit above the plot, so no reference label is ever drawn over the data
    var endLabelW = 0;
    series.forEach(function (sr) { if (sr.label) endLabelW = Math.max(endLabelW, textWidth(sr.label) + 10); });
    var refs = o.refs || [];
    refs.forEach(function (r) { if (r.axis === "y" && (r.short || r.label)) endLabelW = Math.max(endLabelW, textWidth(r.short || r.label) + 10); });
    var xRefLabel = refs.some(function (r) { return r.axis === "x" && r.label; });
    var mt = yo.title ? 22 : 10, mr = 10 + endLabelW, mb = xo.title ? 38 : 24;
    if (xRefLabel) mt = Math.max(mt, 22);
    var pw = Math.max(40, W - ml - mr), ph = Math.max(40, H - mt - mb);
    var log = xo.type === "log2";
    var lx = function (v) { return log ? Math.log2(v) : v; };
    var X = function (v) { return ml + ((lx(v) - lx(xmin)) / (lx(xmax) - lx(xmin) || 1)) * pw; };
    var Y = function (v) { return mt + ph - ((v - ymin) / (ymax - ymin || 1)) * ph; };
    this.X = X; this.Y = Y; this.ml = ml; this.mt = mt; this.pw = pw; this.ph = ph; this.xmin = xmin; this.xmax = xmax; this.log = log;
    s.setAttribute("viewBox", "0 0 " + W + " " + H);
    s.setAttribute("height", H);
    s.setAttribute("width", W);
    s.style.height = H + "px";

    if (yo.title) svg("text", { x: 0, y: 11, class: "axis-title" }, s, yo.title);
    var g = svg("g", { class: "grid" }, s);
    yt.forEach(function (t) {
      var y = Math.round(Y(t)) + 0.5;
      if (t !== ymin) svg("line", { x1: ml, x2: ml + pw, y1: y, y2: y }, g);
      svg("text", { x: ml - 6, y: y + 3.5, "text-anchor": "end" }, s, yfmt(t));
    });
    var ax = svg("g", { class: "axis" }, s);
    svg("line", { x1: ml, x2: ml + pw, y1: Math.round(Y(ymin)) + 0.5, y2: Math.round(Y(ymin)) + 0.5 }, ax);
    var xt = xo.ticks || (log ? allX : ticks(xmin, xmax, Math.max(2, Math.min(6, Math.floor(pw / 70)))));
    var lastRight = -Infinity;
    xt.forEach(function (t, i) {
      var x = X(t), label = xfmt(t), w = textWidth(label);
      var anchor = "middle";
      if (x - w / 2 < ml - 4) anchor = "start";
      if (x + w / 2 > ml + pw + mr) anchor = "end";
      var left = anchor === "middle" ? x - w / 2 : anchor === "start" ? x : x - w;
      if (left < lastRight + 6 && i > 0) return;
      lastRight = left + w;
      svg("line", { x1: Math.round(x) + 0.5, x2: Math.round(x) + 0.5, y1: Y(ymin), y2: Y(ymin) + 4 }, ax);
      svg("text", { x: x, y: mt + ph + 16, "text-anchor": anchor }, s, label);
    });
    if (xo.title) svg("text", { x: ml + pw / 2, y: H - 4, "text-anchor": "middle", class: "axis-title" }, s, xo.title);

    // shaded x-intervals (e.g. seconds with nothing to plot), behind everything else
    (o.bands || []).forEach(function (b) {
      if (!isNum(b.x0) || !isNum(b.x1)) return;
      var x0 = Math.max(xmin, Math.min(b.x0, b.x1)), x1 = Math.min(xmax, Math.max(b.x0, b.x1));
      if (x1 <= x0) return;
      var bx = X(x0), bw = Math.max(2, X(x1) - bx);
      svg("rect", { x: bx.toFixed(1), y: mt, width: bw.toFixed(1), height: ph, class: "band", style: "fill:" + (b.color || "var(--ink-3)") }, s);
      if (b.edge !== false) {
        [bx, bx + bw].forEach(function (ex) { svg("line", { x1: ex.toFixed(1), x2: ex.toFixed(1), y1: mt, y2: mt + ph, class: "band-edge", style: "stroke:" + (b.color || "var(--ink-3)") }, s); });
      }
    });

    // reference marks; their labels live in the margins (see above), never on the data
    var refLabels = [];
    refs.forEach(function (r) {
      if (r.diag) {
        var a = Math.max(xmin, ymin), b = Math.min(xmax, ymax);
        svg("line", { x1: X(a), y1: Y(a), x2: X(b), y2: Y(b), class: "ref" }, s);
        if (r.label) {
          // below the diagonal, moved down-left until the whole label fits inside the plot
          var lw = textWidth(r.label), mid = a + (b - a) * 0.62;
          var span = X(b) - X(a) || 1;
          var room = (ml + pw - 4 - lw - 6 - X(a)) / span;
          mid = Math.max(a, Math.min(mid, a + (b - a) * room));
          refLabels.push([{ x: Math.max(ml + 2, X(mid) + 6), y: Math.min(mt + ph - 4, Y(mid) + 14), "text-anchor": "start", class: "dl" }, r.label]);
        }
      } else if (r.axis === "x" && isNum(r.value) && r.value >= xmin && r.value <= xmax) {
        var x = Math.round(X(r.value)) + 0.5;
        svg("line", { x1: x, x2: x, y1: mt - (r.label ? 4 : 0), y2: mt + ph, class: "ref" }, s);
        if (r.label) {
          var w = textWidth(r.label);
          var right = x + 4 + w <= ml + pw + mr - 2;
          var lx = right ? x + 4 : x - 4;
          if (!right && lx - w < 0) lx = w;
          refLabels.push([{ x: lx, y: mt - 7, "text-anchor": right ? "start" : "end", class: "dl" }, r.label]);
        }
      } else if (r.axis === "y" && isNum(r.value) && r.value >= ymin && r.value <= ymax) {
        var y = Math.round(Y(r.value)) + 0.5;
        svg("line", { x1: ml, x2: ml + pw + 4, y1: y, y2: y, class: "ref" }, s);
        if (r.short || r.label) refLabels.push([{ x: ml + pw + 7, y: y + 3.5, "text-anchor": "start", class: "dl" }, r.short || r.label]);
      }
    });

    var hasData = series.some(function (sr) { return sr.y.some(isNum); });
    if (!hasData) {
      svg("text", { x: ml + pw / 2, y: mt + ph / 2, "text-anchor": "middle", class: "empty" }, s, o.emptyText || "No data for this chart in the export.");
    }
    var sg = svg("g", { class: "series" }, s);
    series.forEach(function (sr) {
      var d = "", pen = false, gapEnds = [];
      var yAt = function (yv) { return Math.max(mt - 4, Math.min(mt + ph, Y(Math.min(yv, ymax * 1.5)))); };
      for (var i = 0; i < sr.x.length; i++) {
        var xv = sr.x[i], yv = sr.y[i];
        var inX = isNum(xv) && xv >= xmin && xv <= xmax;
        if (!inX || !isNum(yv)) {
          // a missing value inside the window breaks the line; remember both ends of the break
          if (sr.gapMarks && inX && pen && i > 0) gapEnds.push(i - 1);
          pen = false;
          continue;
        }
        if (sr.gapMarks && !pen && i > 0 && isNum(sr.x[i - 1]) && sr.x[i - 1] >= xmin && !isNum(sr.y[i - 1])) gapEnds.push(i);
        d += (pen ? "L" : "M") + X(xv).toFixed(1) + " " + yAt(yv).toFixed(1);
        pen = true;
      }
      if (sr.lo && sr.hi) {
        for (var k = 0; k < sr.x.length; k++) {
          if (isNum(sr.lo[k]) && isNum(sr.hi[k]) && isNum(sr.x[k]) && sr.hi[k] > sr.lo[k]) {
            svg("line", { x1: X(sr.x[k]), x2: X(sr.x[k]), y1: Y(sr.lo[k]), y2: Y(sr.hi[k]), style: "stroke:" + sr.color + ";stroke-width:1.5;opacity:.75;stroke-linecap:round" }, sg);
          }
        }
      }
      if (sr.line !== false && d) svg("path", { d: d, style: "stroke:" + sr.color + (sr.width ? ";stroke-width:" + sr.width : "") + (sr.dash ? ";stroke-dasharray:" + sr.dash + ";stroke-linecap:butt" : "") }, sg);
      // hollow end caps where the line breaks, so a gap shows even where other lines run alongside
      gapEnds.forEach(function (gi) {
        svg("circle", { cx: X(sr.x[gi]).toFixed(1), cy: yAt(sr.y[gi]).toFixed(1), r: 3.6, class: "gap-end", style: "stroke:" + sr.color }, sg);
      });
      if (sr.dots) {
        for (var j = 0; j < sr.x.length; j++) {
          if (!isNum(sr.x[j]) || !isNum(sr.y[j])) continue;
          var rr = typeof sr.r === "function" ? sr.r(j) : sr.r || 4;
          svg("circle", { cx: X(sr.x[j]), cy: Y(sr.y[j]), r: rr, style: "fill:" + sr.color + ";stroke:var(--plate);stroke-width:2" }, sg);
        }
      }
      if (sr.label) {
        for (var e = sr.x.length - 1; e >= 0; e--) {
          if (isNum(sr.x[e]) && isNum(sr.y[e]) && sr.x[e] >= xmin && sr.x[e] <= xmax) {
            // labelNudge (in y units) lets the caller move end labels apart when lines end close together
            var ly = Math.max(mt + 4, Math.min(mt + ph + 4, Y(sr.y[e] + (sr.labelNudge || 0)) + 4));
            svg("text", { x: X(sr.x[e]) + 6, y: ly, class: "dl" }, s, sr.label);
            break;
          }
        }
      }
    });
    refLabels.forEach(function (l) { svg("text", l[0], s, l[1]); });
    (o.points || []).forEach(function (p) {
      if (!isNum(p.x) || !isNum(p.y)) return;
      svg("circle", { cx: X(p.x), cy: Y(p.y), r: 5.5, style: "fill:" + (p.color || "var(--ink)") + ";stroke:var(--plate);stroke-width:2" }, s);
      if (p.label) {
        var px = X(p.x), right = px + 10 + textWidth(p.label) < ml + pw;
        svg("text", { x: right ? px + 9 : px - 9, y: Y(p.y) - 9, "text-anchor": right ? "start" : "end", class: "dl" }, s, p.label);
      }
    });
    // crosshair layer
    this.cross = svg("line", { class: "cross", y1: mt, y2: mt + ph, x1: -10, x2: -10, visibility: "hidden" }, s);
    this.crossDots = svg("g", null, s);
    if (o.playhead) {
      this.playLine = svg("line", { class: "playhead", y1: mt - 2, y2: mt + ph, x1: -10, x2: -10 }, s);
      this.setPlayhead(this.play);
    }
    var hit = svg("rect", { x: ml, y: mt, width: pw, height: ph, class: "hit" }, s);
    this._hover(hit);
  };

  LineChart.prototype.setPlayhead = function (x) {
    this.play = x;
    if (!this.playLine) return;
    if (!isNum(x) || x < this.xmin || x > this.xmax) { this.playLine.setAttribute("visibility", "hidden"); return; }
    var px = this.X(x).toFixed(1);
    this.playLine.setAttribute("x1", px);
    this.playLine.setAttribute("x2", px);
    this.playLine.setAttribute("visibility", "visible");
  };

  LineChart.prototype.nearestX = function (px) {
    var xs = this.allX;
    if (!xs || !xs.length) return null;
    var lo = 0, hi = xs.length - 1, X = this.X;
    while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (X(xs[mid]) < px) lo = mid; else hi = mid; }
    return Math.abs(X(xs[lo]) - px) <= Math.abs(X(xs[hi]) - px) ? lo : hi;
  };

  function nearestIndex(arr, x) {
    var best = -1, bd = Infinity;
    for (var i = 0; i < arr.length; i++) {
      if (!isNum(arr[i])) continue;
      var d = Math.abs(arr[i] - x);
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  }

  LineChart.prototype.showAt = function (k) {
    var o = this.o, xs = this.allX;
    if (!xs || k < 0 || k >= xs.length) return;
    var xv = xs[k], X = this.X, Y = this.Y;
    var px = X(xv);
    this.cross.setAttribute("x1", px);
    this.cross.setAttribute("x2", px);
    this.cross.setAttribute("visibility", "visible");
    while (this.crossDots.firstChild) this.crossDots.removeChild(this.crossDots.firstChild);
    var rows = [], ys = [];
    var self = this;
    (o.series || []).forEach(function (sr) {
      if (!sr || !Array.isArray(sr.x)) return;
      var i = sr.exact === false ? nearestIndex(sr.x, xv) : sr.x.indexOf(xv);
      if (i < 0 && sr.exact !== true) i = nearestIndex(sr.x, xv);
      var yv = i >= 0 ? sr.y[i] : null;
      if (isNum(yv) && isNum(sr.x[i])) {
        svg("circle", { cx: X(sr.x[i]), cy: Y(yv), r: 4, style: "fill:" + sr.color + ";stroke:var(--plate);stroke-width:2", "pointer-events": "none" }, self.crossDots);
        ys.push(Y(yv));
      }
      rows.push({ color: sr.color, dash: sr.dash, name: sr.name, value: o.tipValue ? o.tipValue(sr, i) : (o.y && o.y.format ? o.y.format(yv) : fmt(yv, 3)) });
    });
    var title = o.tipTitle ? o.tipTitle(xv) : (o.x && o.x.format ? o.x.format(xv) : fmt(xv, 2));
    var py = ys.length ? Math.min.apply(null, ys) : this.mt + this.ph / 2;
    showTip(o.tip, o.fig, this.svg, px, py, title, rows);
  };

  LineChart.prototype.hideTip = function () {
    if (this.cross) this.cross.setAttribute("visibility", "hidden");
    if (this.crossDots) while (this.crossDots.firstChild) this.crossDots.removeChild(this.crossDots.firstChild);
    if (this.o.tip) this.o.tip.hidden = true;
  };

  LineChart.prototype._hover = function (hit) {
    var self = this;
    function local(e) {
      var r = self.svg.getBoundingClientRect();
      var scale = r.width ? (self.svg.viewBox.baseVal.width || r.width) / r.width : 1;
      return (e.clientX - r.left) * scale;
    }
    hit.addEventListener("pointermove", function (e) {
      var k = self.nearestX(local(e));
      if (k !== null) { self.focusIdx = k; self.showAt(k); }
    });
    hit.addEventListener("pointerleave", function () { self.hideTip(); });
    hit.addEventListener("click", function (e) {
      if (!self.o.onSeek) return;
      var k = self.nearestX(local(e));
      if (k !== null) self.o.onSeek(self.allX[k]);
    });
  };

  LineChart.prototype._keys = function () {
    var self = this;
    this.svg.addEventListener("focus", function () {
      if (!self.allX || !self.allX.length) return;
      // a chart with a playhead starts its keyboard cursor at the playhead every time it gets
      // focus, so Enter never jumps back to wherever the cursor was left earlier
      if (self.o.playhead && isNum(self.play)) {
        var kp = self.nearestX(self.X(self.play));
        self.focusIdx = kp === null ? 0 : kp;
      } else if (self.focusIdx < 0 || self.focusIdx >= self.allX.length) {
        var k = isNum(self.play) ? self.nearestX(self.X(self.play)) : self.allX.length - 1;
        self.focusIdx = k === null ? 0 : k;
      }
      self.showAt(self.focusIdx);
    });
    this.svg.addEventListener("blur", function () { self.hideTip(); });
    this.svg.addEventListener("keydown", function (e) {
      if (!self.allX || !self.allX.length) return;
      var n = self.allX.length, k = self.focusIdx < 0 ? n - 1 : self.focusIdx;
      var big = Math.max(1, Math.round(n / 20));
      if (e.key === "ArrowRight") k = Math.min(n - 1, k + (e.shiftKey ? big : 1));
      else if (e.key === "ArrowLeft") k = Math.max(0, k - (e.shiftKey ? big : 1));
      else if (e.key === "Home") k = 0;
      else if (e.key === "End") k = n - 1;
      else if (e.key === "Enter" && self.o.onSeek) { self.o.onSeek(self.allX[k]); e.preventDefault(); e.stopPropagation(); return; }
      else if (e.key === "Escape") { self.hideTip(); return; }
      else return;
      e.preventDefault();
      e.stopPropagation();
      self.focusIdx = k;
      self.showAt(k);
    });
  };

  // ---- dot-and-whisker (one value per category, min-max range) -----------
  function DotWhisker(host, o) {
    this.host = host;
    this.o = o;
    this.idx = -1;
    var self = this;
    this.svg = svg("svg", { tabindex: "0", role: "img", "aria-label": o.ariaLabel || o.title || "Dot and whisker chart" }, host);
    this.svg.addEventListener("focus", function () { self.show(self.idx < 0 ? 0 : self.idx); });
    this.svg.addEventListener("blur", function () { self.hide(); });
    this.svg.addEventListener("keydown", function (e) {
      var n = (self.o.rows || []).length;
      if (!n) return;
      var k = self.idx < 0 ? 0 : self.idx;
      if (e.key === "ArrowDown" || e.key === "ArrowRight") k = Math.min(n - 1, k + 1);
      else if (e.key === "ArrowUp" || e.key === "ArrowLeft") k = Math.max(0, k - 1);
      else if (e.key === "Escape") { self.hide(); return; }
      else return;
      e.preventDefault();
      self.show(k);
    });
    if (global.ResizeObserver) {
      this.ro = new ResizeObserver(function () { if (self.host.clientWidth !== self.lastW) self.render(); });
      this.ro.observe(host);
    }
    register(this);
    this.render();
  }
  DotWhisker.prototype.render = function () {
    var o = this.o, s = this.svg, self = this;
    while (s.firstChild) s.removeChild(s.firstChild);
    var rows = o.rows || [];
    var W = Math.max(220, this.host.clientWidth || 300);
    this.lastW = this.host.clientWidth;
    var rowH = 34, mt = o.xTitle ? 20 : 8, mb = 24;
    var H = mt + mb + Math.max(1, rows.length) * rowH;
    var xf = o.format || function (v) { return fmt(v, 2); };
    var ml = 10 + Math.max.apply(null, rows.map(function (r) { return textWidth(r.label); }).concat([30]));
    var mr = 12 + Math.max.apply(null, rows.map(function (r) { return textWidth(xf(r.mean)); }).concat([20]));
    var pw = Math.max(40, W - ml - mr);
    var max = o.max;
    if (!isNum(max)) {
      var m = 0;
      rows.forEach(function (r) { [r.max, r.mean].forEach(function (v) { if (isNum(v)) m = Math.max(m, v); }); });
      (o.refs || []).forEach(function (r) { if (isNum(r.value)) m = Math.max(m, r.value); });
      max = niceMax(m * 1.05 || 1, 4);
    }
    var min = isNum(o.min) ? o.min : 0;
    var X = function (v) { return ml + ((v - min) / (max - min || 1)) * pw; };
    s.setAttribute("viewBox", "0 0 " + W + " " + H);
    s.setAttribute("width", W);
    s.setAttribute("height", H);
    s.style.height = H + "px";
    if (o.xTitle) svg("text", { x: ml, y: 11, class: "axis-title" }, s, o.xTitle);
    var g = svg("g", { class: "grid" }, s);
    var tk = ticks(min, max, Math.max(2, Math.min(5, Math.floor(pw / 70))));
    tk.forEach(function (t) {
      var x = Math.round(X(t)) + 0.5;
      svg("line", { x1: x, x2: x, y1: mt, y2: H - mb }, g);
      svg("text", { x: x, y: H - mb + 15, "text-anchor": "middle" }, s, xf(t));
    });
    (o.refs || []).forEach(function (r) {
      if (!isNum(r.value)) return;
      var x = Math.round(X(r.value)) + 0.5;
      svg("line", { x1: x, x2: x, y1: mt, y2: H - mb, class: "ref" }, s);
    });
    this.hits = [];
    this.geo = [];
    rows.forEach(function (r, i) {
      var cy = mt + i * rowH + rowH / 2;
      svg("text", { x: ml - 8, y: cy + 4, "text-anchor": "end", class: "axis-title" }, s, r.label);
      var color = o.color || "var(--pencil)";
      if (isNum(r.min) && isNum(r.max)) {
        svg("line", { x1: X(r.min), x2: X(r.max), y1: cy, y2: cy, style: "stroke:" + color + ";stroke-width:2;stroke-linecap:round" }, s);
        [r.min, r.max].forEach(function (v) { svg("line", { x1: X(v), x2: X(v), y1: cy - 5, y2: cy + 5, style: "stroke:" + color + ";stroke-width:2;stroke-linecap:round" }, s); });
      }
      if (isNum(r.mean)) {
        svg("circle", { cx: X(r.mean), cy: cy, r: 5, style: "fill:" + color + ";stroke:var(--plate);stroke-width:2" }, s);
        var right = Math.max(X(r.mean), isNum(r.max) ? X(r.max) : 0);
        svg("text", { x: right + 8, y: cy + 4, class: "dl" }, s, xf(r.mean));
      } else {
        svg("text", { x: ml + 4, y: cy + 4, class: "empty" }, s, "—");
      }
      var hit = svg("rect", { x: 0, y: cy - rowH / 2, width: W, height: rowH, class: "hit" }, s);
      hit.addEventListener("pointermove", function () { self.show(i); });
      hit.addEventListener("pointerleave", function () { self.hide(); });
      self.geo.push({ cy: cy, x: isNum(r.max) ? X(r.max) : isNum(r.mean) ? X(r.mean) : ml });
    });
    this.hl = svg("rect", { x: 0, y: 0, width: W, height: rowH, visibility: "hidden", style: "fill:var(--plate-2);opacity:.6", "pointer-events": "none" }, s, null);
    s.insertBefore(this.hl, s.firstChild);
  };
  DotWhisker.prototype.show = function (i) {
    var r = (this.o.rows || [])[i];
    if (!r) return;
    this.idx = i;
    var gm = this.geo[i];
    this.hl.setAttribute("y", gm.cy - 17);
    this.hl.setAttribute("visibility", "visible");
    var f = this.o.format || function (v) { return fmt(v, 2); };
    showTip(this.o.tip, this.o.fig, this.svg, gm.x, gm.cy, r.label, [
      { value: f(r.mean), name: "mean" },
      { value: f(r.min) + " – " + f(r.max), name: "lowest to highest seed" },
    ]);
  };
  DotWhisker.prototype.hide = function () {
    if (this.hl) this.hl.setAttribute("visibility", "hidden");
    if (this.o.tip) this.o.tip.hidden = true;
  };

  function rerenderAll() {
    prune();
    registry.forEach(function (c) {
      try { c.render(); } catch (e) { /* keep others drawing */ }
    });
  }

  global.BMFPCharts = {
    figure: figure,
    line: function (host, o) { return new LineChart(host, o); },
    dotWhisker: function (host, o) { return new DotWhisker(host, o); },
    fillTable: fillTable,
    lineKey: lineKey,
    rerenderAll: rerenderAll,
    // how many charts are registered (after dropping detached ones); used by the smoke test
    liveCount: function () { prune(); return registry.length; },
    fmt: fmt,
    fixed: fixed,
    pct: pct,
    ticks: ticks,
    niceDomain: niceDomain,
    isNum: isNum,
    el: el,
    svg: svg,
  };
})(window);
