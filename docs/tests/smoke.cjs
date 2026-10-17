/* Smoke test for the BMFP site (docs/index.html over file://).
   Run:   NODE_PATH=/opt/node22/lib/node_modules node docs/tests/smoke.cjs
   Env:   SHOT_DIR (default /tmp/claude-0/shots), PLAYWRIGHT_BROWSERS_PATH (browser location).
   Checks, at 1280x900 and 400x860 in light and dark: no console or page errors, every
   section heading present, no horizontal page overflow, scenario switching changes the
   state counts, scrubbing changes the time label, every chart has a working table view,
   and the fixture notice appears only when the dev fixture is in use. reviewChecks() guards
   the design-review fixes (event-log focus during playback, Space and Enter on live charts,
   stable chart ids and released charts, ladder verdicts, E2 metric, E3 bands, event text,
   settings drawer, tick shapes, reduced motion at runtime, tabular digits, hero legend, chart
   text inside its chart, header nav at every width). Saves screenshots. */
"use strict";
const path = require("path");
const fs = require("fs");
const { execFileSync } = require("child_process");
const { chromium } = require("playwright");

const SHOT_DIR = process.env.SHOT_DIR || "/tmp/claude-0/shots";
const INDEX = path.resolve(__dirname, "..", "index.html");
const URL = "file://" + INDEX;
const SECTIONS = [
  "The cell, live",
  "The ladder, v1.0 to v1.7e",
  "What the simulator found",
  "MeshGuard",
  "Learning log",
  "How this was built",
  "Reproduce every number",
];
const SECTION_IDS = ["top", "cell", "ladder", "findings", "meshguard", "learned", "built", "reproduce"];
const VARIANTS = [
  { label: "desktop", width: 1280, height: 900 },
  { label: "mobile", width: 400, height: 860 },
];
const SCHEMES = ["light", "dark"];

// In a sandbox whose outbound HTTPS goes through a proxy, Chromium cannot reach Google Fonts on
// its own; fetch those two hosts with curl (which verifies TLS against the configured CA bundle).
async function routeFonts(ctx, notes) {
  if (!process.env.HTTPS_PROXY && !process.env.https_proxy) return;
  await ctx.route(/^https:\/\/fonts\.(googleapis|gstatic)\.com\//, async (route) => {
    const req = route.request();
    try {
      const ua = req.headers()["user-agent"] || "Mozilla/5.0";
      const body = execFileSync("curl", ["-sS", "--fail", "--max-time", "20", "-A", ua, req.url()], { maxBuffer: 30e6 });
      const css = req.url().includes("googleapis");
      await route.fulfill({
        status: 200,
        body,
        headers: { "content-type": css ? "text/css; charset=utf-8" : "font/woff2", "access-control-allow-origin": "*" },
      });
    } catch (e) {
      notes.add("font fetch failed: " + req.url().slice(0, 80));
      await route.abort();
    }
  });
}

// wait until smooth scrolling (scrollIntoView, focus) has come to rest
async function settleScroll(page) {
  let last = -1;
  for (let i = 0; i < 30; i++) {
    const y = await page.evaluate(() => window.scrollY);
    if (y === last) return;
    last = y;
    await page.waitForTimeout(80);
  }
}

// Checks for defects found in the adversarial design review, each of which could come back
// without any visible error. `once` marks the run (desktop, light) that also sweeps widths.
async function reviewChecks(page, fail, once) {
  const Lpause = () => page.evaluate(() => window.__BMFP.Live.pause(true));

  // 1. focus survives playback in the event log, and Enter there keeps focus on that event
  await page.evaluate(() => { const L = window.__BMFP.Live; L.setScenario(0); L.pause(true); L.seek(0, true); });
  const logBtn = page.locator("#log button").nth(1);
  if (await logBtn.count()) {
    await logBtn.scrollIntoViewIfNeeded();
    const idx0 = await page.evaluate(() => { const L = window.__BMFP.Live; L.speed = 16; L.userPaused = false; L.play(false); return L.idx; });
    await logBtn.focus();
    await page.waitForTimeout(1200);
    const st = await page.evaluate(() => ({
      inLog: document.getElementById("log").contains(document.activeElement),
      what: document.activeElement.tagName + " " + (document.activeElement.getAttribute("aria-label") || "").slice(0, 40),
      idx: window.__BMFP.Live.idx, playing: window.__BMFP.Live.playing,
    }));
    if (st.idx <= idx0) fail(`playback did not advance while the event log had focus (idx ${idx0} -> ${st.idx})`);
    if (!st.inLog) fail(`focus left the event log during playback (now on ${st.what})`);
    if (st.inLog) {
      // pause first so the playhead holds still for the position check below
      const want = await page.evaluate(() => { window.__BMFP.Live.pause(false); return Number(document.activeElement.getAttribute("data-i")); });
      await page.keyboard.press("Enter");
      const got = await page.evaluate(() => {
        const L = window.__BMFP.Live, a = document.activeElement, i = Number(a.getAttribute("data-i"));
        return { inLog: document.getElementById("log").contains(a), i, t: L.timeAt(L.idx), et: (L.events[i] || {}).t };
      });
      if (!got.inLog || got.i !== want) fail(`Enter on an event lost focus or moved it to another event (${want} -> ${got.i})`);
      else if (!(got.t <= got.et + 1e-9 && got.et - got.t < 1 + 1e-9)) fail(`Enter on event ${want} (t=${got.et}) moved the playhead to ${got.t} s`);
    }
  }
  await Lpause();

  // 2. Space on a focused live chart plays/pauses and does not scroll; the chart's keyboard
  //    cursor starts at the playhead each time it gets focus
  const chartSvg = page.locator("#charts-live svg[tabindex='0']").first();
  await chartSvg.scrollIntoViewIfNeeded();
  await page.evaluate(() => { const L = window.__BMFP.Live; L.pause(true); L.seek(100, true); });
  await chartSvg.focus();
  await settleScroll(page);
  const y0 = await page.evaluate(() => window.scrollY);
  await page.keyboard.press(" ");
  await page.waitForTimeout(150);
  const sp = await page.evaluate(() => ({ y: window.scrollY, playing: window.__BMFP.Live.playing }));
  if (Math.abs(sp.y - y0) > 40) fail(`Space on a live chart scrolled the page by ${sp.y - y0}px`);
  if (!sp.playing) fail("Space on a live chart did not start playback");
  await Lpause();
  const prevented = await page.evaluate(() => {
    const s = document.querySelector("#charts-live svg[tabindex='0']");
    const e = new KeyboardEvent("keydown", { key: " ", code: "Space", bubbles: true, cancelable: true });
    s.dispatchEvent(e);
    window.__BMFP.Live.pause(true);
    return e.defaultPrevented;
  });
  if (!prevented) fail("Space on a live chart is not handled (the browser would scroll the page)");
  for (const target of [100, 200]) {
    await page.evaluate((t) => { const L = window.__BMFP.Live; L.pause(true); L.seek(t, true); document.activeElement.blur(); }, target);
    await chartSvg.focus();
    await page.keyboard.press("Enter");
    const at = await page.evaluate(() => window.__BMFP.Live.idx);
    if (at !== target) fail(`Enter on a live chart focused at frame ${target} moved the playhead to frame ${at}`);
  }
  await page.evaluate(() => document.activeElement.blur());

  // 3. stable chart ids, and replaced charts are released
  const liveIds = () => page.evaluate(() => Array.from(document.querySelectorAll("#charts-live .table-toggle")).map((b) => b.id));
  const reg = () => page.evaluate(() => (window.BMFPCharts.liveCount ? window.BMFPCharts.liveCount() : -1));
  const ids1 = await liveIds(), n1 = await reg();
  for (const i of [2, 3, 0]) await page.evaluate((k) => { const L = window.__BMFP.Live; L.setScenario(Math.min(k, L.scs.length - 1)); L.pause(true); }, i);
  const ids2 = await liveIds(), n2 = await reg();
  if (ids1.join() !== ids2.join()) fail(`live chart ids changed across scenario switches: ${ids1.join()} -> ${ids2.join()}`);
  if (n1 < 0) fail("charts.js does not report its registry (BMFPCharts.liveCount)");
  else if (n2 !== n1) fail(`chart registry changed from ${n1} to ${n2} after scenario switches (detached charts kept)`);
  const allIds = await page.evaluate(() => Array.from(document.querySelectorAll("figure[data-chart]")).map((f) => f.id));
  if (allIds.some((id) => /^chart-\d+$/.test(id))) fail(`charts with counter ids: ${allIds.filter((id) => /^chart-\d+$/.test(id)).join(", ")}`);
  if (new Set(allIds).size !== allIds.length) fail("duplicate chart ids");

  // 4. the ladder never claims a test for a "not simulated" finding, and names each verdict.
  //    Judged from the export: each chip's link names a finding, whose verdict is in the data.
  const ladder = await page.evaluate(() => {
    const bad = [], slug = (x) => String(x || "").toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
    const byAnchor = {};
    ((window.BMFP_DATA || {}).findings || []).forEach((f) => { byAnchor["finding-" + slug(f.id || f.problem)] = f; });
    document.querySelectorAll(".tile .chip[href]").forEach((c) => {
      const id = c.getAttribute("href").slice(1), f = byAnchor[id];
      if (!document.getElementById(id) || !f) { bad.push("ladder chip links nowhere: #" + id); return; }
      const v = String(f.verdict || "").toLowerCase();
      const label = ((c.closest(".tested") || {}).querySelector ? c.closest(".tested").querySelector(".tested-l") : null);
      const rowText = label ? label.textContent.trim() : "";
      if (v === "not simulated" && /^tested/i.test(rowText)) bad.push(`ladder says "${rowText}" for a not-simulated finding: ${f.id}`);
      if (v !== "not simulated" && !c.textContent.toLowerCase().includes(v)) bad.push(`ladder chip without its verdict word (${v}): ${c.textContent}`);
    });
    return bad;
  });
  ladder.forEach(fail);

  // 5. E2 plots the VSEPR-only change rate (the all-source rate hides VSEPR's effect)
  const e2 = await page.evaluate(() => {
    const v = (((window.BMFP_DATA || {}).experiments || {}).vsepr || {}).variants;
    if (!v) return null;
    const box = document.querySelector('#e2-vsepr [data-metric="state_changes_per_min_vsepr"]');
    if (!box) return "E2: the VSEPR-only panel is missing";
    const got = Array.from(box.querySelectorAll("svg text.dl")).map((t) => t.textContent);
    const want = Object.keys(v).map((n) => (v[n].state_changes_per_min_vsepr || {}).mean).filter((x) => typeof x === "number").map((x) => window.BMFPCharts.fmt(x, 1));
    return want.length && want.join("/") === got.join("/") ? null : `E2 shows ${got.join("/")}, VSEPR-only data is ${want.join("/")}`;
  });
  if (e2) fail(e2);

  // 6. E3 shades the seconds after the kill with nothing to plot (total death)
  const e3 = await page.evaluate(() => {
    const r = (((window.BMFP_DATA || {}).experiments || {}).recovery) || {};
    const k = r.kill_at;
    let gaps = 0;
    Object.values(r.cases || {}).forEach((c) => { const s = c.series || {}; (s.t || []).forEach((t, i) => { if (t >= k && t <= k + 70 && (s.ratio || [])[i] === null) gaps++; }); });
    const fig = document.getElementById("e3-recovery");
    return { gaps, bands: fig ? fig.querySelectorAll(".plot rect.band").length : 0, legend: fig ? /nothing deliverable sent/.test(fig.querySelector(".legend").textContent) : false };
  });
  if (e3.gaps && (!e3.bands || !e3.legend)) fail(`E3: ${e3.gaps} empty seconds after the kill but ${e3.bands} shaded bands (legend entry: ${e3.legend})`);

  // 7. event text names node ids as nodes (no "33 ACTIVE→STANDBY" read as a count)
  const evBad = await page.evaluate(() => {
    const bad = [];
    if (!window.__BMFP.eventText) return ["app.js does not expose eventText"];
    (window.BMFP_DATA.scenarios || []).forEach((sc) => (sc.events || []).forEach((e) => {
      const s = window.__BMFP.eventText(e);
      if (/\b\d+ (ACTIVE|STANDBY|GHOST)\s*(→|->)/.test(s)) bad.push(`${sc.id} t=${e.t}: ${s}`);
      if (String(e.kind).toUpperCase() === "RESONANCE" && /swapped \d/.test(s)) bad.push(`${sc.id} t=${e.t}: ${s}`);
    }));
    return bad.slice(0, 3);
  });
  evBad.forEach((b) => fail("event text reads ids as counts: " + b));

  // 8. settings drawer: only the journal's own kill share is a journal input; no bare "none"
  const drawer = await page.evaluate(() => {
    const L = window.__BMFP.Live, bad = [];
    L.scs.forEach((sc, i) => {
      L.setScenario(i); L.pause(true);
      const cfg = sc.config || {};
      // read the drawer as a reader does: the group headed "From the journal", its row labels
      const journalBox = Array.from(document.querySelectorAll("#settings h4")).find((h) => /^From the journal/.test(h.textContent));
      const killRow = journalBox && Array.from(journalBox.parentNode.querySelectorAll("dt")).some((dt) => /^Share of nodes killed/.test(dt.textContent));
      if (killRow && !(cfg.kill_fraction === 0.5 && typeof cfg.kill_at === "number"))
        bad.push(`${sc.id}: kill share ${cfg.kill_fraction} filed under the journal`);
      document.querySelectorAll("#settings dd").forEach((dd) => { if (/^\s*none\s*$/i.test(dd.textContent)) bad.push(`${sc.id}: bare "none" for ${dd.previousElementSibling.getAttribute("data-key")}`); });
      // labels must stay readable however long a value is (a squeezed label wraps per letter)
      const drawerEl = document.getElementById("settings-drawer"), wasOpen = drawerEl.open;
      drawerEl.open = true;
      document.querySelectorAll("#settings dt").forEach((dt) => {
        const r = dt.getBoundingClientRect();
        if (r.width < 70 || r.height > 90) bad.push(`${sc.id}: settings label squeezed to ${Math.round(r.width)}x${Math.round(r.height)}px: ${dt.textContent.slice(0, 30)}`);
      });
      drawerEl.open = wasOpen;
      const end = document.getElementById("time-end").textContent;
      if (typeof sc.duration === "number" && end !== window.BMFPCharts.fmt(sc.duration, 2) + " s") bad.push(`${sc.id}: clock says "of ${end}", duration is ${sc.duration} s`);
    });
    L.setScenario(0); L.pause(true);
    return bad;
  });
  drawer.forEach(fail);

  // 9. failure and recovery ticks differ in shape, not only colour
  const ticks = await page.evaluate(() => {
    const L = window.__BMFP.Live;
    const i = L.scs.findIndex((s) => (s.events || []).some((e) => e.kind === "KILL"));
    if (i < 0) return null;
    L.setScenario(i); L.pause(true);
    const r = { fail: document.querySelectorAll('#ticks [data-tick="fail"]').length, tri: document.querySelectorAll("#ticks path").length, rec: document.querySelectorAll('#ticks [data-tick="recover"]').length, dots: document.querySelectorAll("#ticks circle").length };
    L.setScenario(0); L.pause(true);
    return r;
  });
  if (ticks && (!ticks.fail || ticks.tri !== ticks.fail || ticks.dots !== ticks.rec)) fail(`scrubber ticks: ${JSON.stringify(ticks)} (each failure needs a triangle, each recovery a dot)`);

  // 10. runtime switch to reduced motion stops playback the page started
  await page.evaluate(() => { const L = window.__BMFP.Live; L.pause(false); L.userPaused = false; L.play(true); });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.waitForTimeout(120);
  if (await page.evaluate(() => window.__BMFP.Live.playing)) fail("auto-started playback kept running after reduced motion was turned on");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await Lpause();

  // 11. small things: tabular digits on live readouts, hero legend explains every mark
  const misc = await page.evaluate(() => ({
    tn: ["count-A", "ratio-now"].map((id) => getComputedStyle(document.getElementById(id)).fontVariantNumeric),
    heroLegend: document.querySelectorAll("#top [data-legend] li").length,
  }));
  misc.tn.forEach((v, i) => { if (!/tabular-nums/.test(v)) fail(`live readout ${i} lacks tabular-nums (${v})`); });
  if (misc.heroLegend < 7) fail(`hero legend explains ${misc.heroLegend} marks; the hero draws states, stems, captains and halos`);

  // 12. chart text stays inside its chart
  const spill = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll(".plot svg").forEach((s) => {
      if (!s.getClientRects().length) return;
      const W = s.viewBox.baseVal.width, H = s.viewBox.baseVal.height;
      s.querySelectorAll("text").forEach((t) => {
        const b = t.getBBox();
        if (b.width && (b.x < -1 || b.x + b.width > W + 1 || b.y < -2 || b.y + b.height > H + 2))
          out.push(`"${t.textContent}" in ${(s.closest("figure") || {}).id} (x ${Math.round(b.x)}..${Math.round(b.x + b.width)} of ${W})`);
      });
    });
    return out.slice(0, 5);
  });
  spill.forEach((m) => fail("chart text outside its chart: " + m));

  // 13. every header link can be reached: visible in the bar, or through the Sections menu
  const widths = once ? [360, 400, 520, 780, 860, 961, 1280] : [null];
  const vp = page.viewportSize();
  for (const w of widths) {
    if (w) { await page.setViewportSize({ width: w, height: vp.height }); await page.waitForTimeout(80); }
    await page.evaluate(() => window.scrollTo(0, 0));
    const tag = w ? ` at ${w}px` : "";
    const vis = () => page.evaluate(() => Array.from(document.querySelectorAll(".nav ul a")).map((a) => {
      const r = a.getBoundingClientRect(), n = document.querySelector(".nav").getBoundingClientRect();
      const inside = r.width > 0 && r.left >= Math.max(0, n.left) - 1 && r.right <= Math.min(window.innerWidth, n.right) + 1;
      return { t: a.textContent, ok: inside || (document.querySelector(".nav").classList.contains("open") && r.width > 0 && r.left >= 0 && r.right <= window.innerWidth) };
    }));
    const compact = await page.evaluate(() => { const b = document.getElementById("nav-toggle"); return !!b && getComputedStyle(b).display !== "none"; });
    const vw = await page.evaluate(() => window.innerWidth);
    if (vw > 960 && compact) fail(`the Sections menu button shows${tag || " at " + vw + "px"}, where every link fits in the bar`);
    const headH = await page.evaluate(() => document.querySelector(".masthead").getBoundingClientRect().height);
    if (headH > 64) fail(`the header is ${Math.round(headH)}px tall${tag || " at " + vw + "px"} (links wrapped onto a second row?)`);
    if (!compact) {
      const off = (await vis()).filter((x) => !x.ok).map((x) => x.t);
      if (off.length) fail(`header links cut off${tag}: ${off.join(", ")}`);
    } else {
      await page.click("#nav-toggle");
      const st = await page.evaluate(() => document.getElementById("nav-toggle").getAttribute("aria-expanded"));
      const off = (await vis()).filter((x) => !x.ok).map((x) => x.t);
      if (st !== "true") fail(`Sections menu did not open${tag}`);
      if (off.length) fail(`links outside the open Sections menu${tag}: ${off.join(", ")}`);
      await page.keyboard.press("Escape");
      const closed = await page.evaluate(() => ({ exp: document.getElementById("nav-toggle").getAttribute("aria-expanded"), focus: document.activeElement.id }));
      if (closed.exp !== "false" || closed.focus !== "nav-toggle") fail(`Escape did not close the Sections menu and return focus${tag}`);
    }
  }
  if (once) await page.setViewportSize(vp);
  await page.evaluate(() => window.scrollTo(0, 0));
}

async function run() {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  const browser = await chromium.launch();
  const failures = [];
  const notes = new Set();
  const shots = [];
  let fixtureSeen = false;

  for (const v of VARIANTS) {
    for (const scheme of SCHEMES) {
      const tag = `${v.label}-${scheme}`;
      const fail = (m) => failures.push(`[${tag}] ${m}`);
      const ctx = await browser.newContext({ viewport: { width: v.width, height: v.height }, colorScheme: scheme, deviceScaleFactor: 1 });
      await routeFonts(ctx, notes);
      const page = await ctx.newPage();
      const errors = [];
      page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
      page.on("console", (msg) => {
        if (msg.type() !== "error") return;
        const loc = (msg.location() && msg.location().url) || "";
        if (/fonts\.(googleapis|gstatic)\.com/.test(loc) || /fonts\.(googleapis|gstatic)\.com/.test(msg.text())) {
          notes.add("font request error (network): " + msg.text().slice(0, 100));
          return;
        }
        if (/\/data\/bmfp-data\.js$/.test(loc)) {
          notes.add("data/bmfp-data.js missing: page fell back to the dev fixture");
          return;
        }
        errors.push("console: " + msg.text() + (loc ? " @ " + loc : ""));
      });
      await page.goto(URL, { waitUntil: "load" });
      await page.waitForFunction(() => window.__BMFP_READY === true, null, { timeout: 15000 });
      await page.evaluate(() => (document.fonts ? document.fonts.ready : null));
      await page.waitForTimeout(300);

      // headings
      const h = await page.evaluate(() => ({
        h1: Array.from(document.querySelectorAll("h1")).map((e) => e.textContent.trim()),
        h2: Array.from(document.querySelectorAll("h2")).map((e) => e.textContent.trim()),
      }));
      if (!h.h1.length) fail("no h1");
      for (const s of SECTIONS) if (!h.h2.includes(s)) fail(`missing section heading "${s}"`);

      // fixture notice only with fixture data
      const fx = await page.evaluate(() => ({
        fixture: !!(window.__BMFP && window.__BMFP.fixture && window.__BMFP.fixture.bmfp),
        noticeVisible: !document.getElementById("fixture-notice").hidden,
        noticeText: document.getElementById("fixture-notice").textContent,
        fixtureScript: !!document.querySelector('script[src*="fixture"]'),
        generator: window.BMFP_DATA && window.BMFP_DATA.generator,
      }));
      if (fx.fixture) {
        fixtureSeen = true;
        if (!fx.noticeVisible || !/fixture/i.test(fx.noticeText)) fail("fixture data in use but no visible notice");
      } else {
        if (fx.fixtureScript) fail("fixture script loaded although real data is present");
        if (fx.noticeVisible && /fixture/i.test(fx.noticeText)) fail("fixture notice shown with real data");
      }

      // live cell: stop playback so readings are stable
      await page.evaluate(() => { if (window.__BMFP) window.__BMFP.Live.pause(true); });
      const counts = () => page.evaluate(() => document.getElementById("flags").textContent);
      const before = await counts();
      const nScen = await page.locator("#scen-tabs button").count();
      if (nScen < 2) fail(`expected several scenarios, found ${nScen}`);
      let changed = false;
      for (let i = nScen - 1; i >= 1 && !changed; i--) {
        await page.locator("#scen-tabs button").nth(i).click();
        await page.evaluate(() => window.__BMFP.Live.pause(true));
        await page.waitForTimeout(60);
        if ((await counts()) !== before) changed = true;
      }
      if (!changed) fail("switching scenarios did not change the state counts");
      await page.locator("#scen-tabs button").first().click();
      await page.evaluate(() => window.__BMFP.Live.pause(true));

      // scrubbing
      const t0 = await page.textContent("#time-now");
      await page.focus("#scrub");
      for (let i = 0; i < 5; i++) await page.keyboard.press("ArrowRight");
      await page.keyboard.press("Shift+ArrowRight");
      const t1 = await page.textContent("#time-now");
      if (t0 === t1) fail(`scrubbing did not change the time label (${t0})`);
      // space toggles play from the slider, then pause again
      await page.keyboard.press(" ");
      const playing = await page.evaluate(() => window.__BMFP.Live.playing);
      if (!playing) fail("space on the slider did not start playback");
      await page.evaluate(() => window.__BMFP.Live.pause(true));

      // ---- regression checks for the design-review fixes ----------------------------
      await reviewChecks(page, fail, v.label === "desktop" && scheme === "light");

      // park on a mid-run frame for the screenshots
      await page.evaluate(() => { const L = window.__BMFP.Live; L.setScenario(0); L.pause(true); L.seek(Math.floor(L.F * 0.42)); });

      // every chart has a table view that opens
      const charts = await page.evaluate(() => Array.from(document.querySelectorAll("figure[data-chart]")).map((f) => ({
        id: f.id,
        title: (f.querySelector(".chart-title") || {}).textContent || "",
        toggle: !!f.querySelector(".table-toggle"),
        table: !!f.querySelector("table"),
      })));
      if (charts.length < 10) fail(`expected at least 10 charts, found ${charts.length}`);
      for (const c of charts) if (!c.table) fail(`chart "${c.title}" has no table`);
      const toggles = page.locator("figure[data-chart] .table-toggle");
      const nt = await toggles.count();
      for (let i = 0; i < nt; i++) {
        const tg = toggles.nth(i);
        await tg.scrollIntoViewIfNeeded();
        await tg.click();
        const ok = await tg.evaluate((b) => {
          const w = document.getElementById(b.getAttribute("aria-controls"));
          return !!w && !w.hidden && w.querySelector("table") !== null && w.getBoundingClientRect().height > 0;
        });
        if (!ok) fail(`table view toggle ${i} did not show a table`);
        await tg.click();
      }

      // tooltip on hover for the first live chart
      const plot = page.locator("#charts-live .plot svg").first();
      await plot.scrollIntoViewIfNeeded();
      const box = await plot.boundingBox();
      if (box) {
        await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.5);
        const tipShown = await page.evaluate(() => Array.from(document.querySelectorAll("#charts-live .tip")).some((t) => !t.hidden && t.textContent.length > 0));
        if (!tipShown) fail("hovering a live chart did not show a tooltip");
        await page.mouse.move(2, 2);
      }

      // no horizontal overflow (also with every drawer open)
      await page.evaluate(() => document.querySelectorAll("details").forEach((d) => (d.open = true)));
      await page.waitForTimeout(100);
      const ov = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }));
      if (ov.sw > ov.iw) {
        const culprits = await page.evaluate(() => {
          const iw = window.innerWidth, out = [];
          document.querySelectorAll("body *").forEach((e) => {
            const r = e.getBoundingClientRect();
            if (r.right > iw + 1 && out.length < 6) out.push(e.tagName.toLowerCase() + (e.id ? "#" + e.id : "") + "." + String(e.className).split(" ")[0] + " right=" + Math.round(r.right));
          });
          return out;
        });
        fail(`horizontal overflow: scrollWidth ${ov.sw} > innerWidth ${ov.iw} (${culprits.join(", ")})`);
      }
      await page.evaluate(() => document.querySelectorAll("details").forEach((d) => (d.open = false)));

      // screenshots: the first screen as a reader sees it, then each section on its own
      // (the sticky header is unstuck for section shots so it does not land mid-image)
      await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
      await page.waitForTimeout(200);
      const first = path.join(SHOT_DIR, `${tag}-viewport.png`);
      await page.screenshot({ path: first });
      shots.push(first);
      await page.addStyleTag({ content: ".masthead{position:static!important} html{scroll-behavior:auto!important}" });
      for (const id of SECTION_IDS) {
        const loc = page.locator("#" + id);
        if (!(await loc.count())) { fail(`missing section #${id}`); continue; }
        await loc.scrollIntoViewIfNeeded();
        await page.waitForTimeout(120);
        const p = path.join(SHOT_DIR, `${tag}-${id}.png`);
        await loc.screenshot({ path: p });
        shots.push(p);
      }

      for (const e of errors) fail(e);
      await ctx.close();
      console.log(`${tag}: ${failures.filter((f) => f.startsWith(`[${tag}]`)).length ? "FAIL" : "ok"} (${charts.length} charts, ${nScen} scenarios, time ${t0} -> ${t1})`);
    }
  }
  await browser.close();

  for (const n of notes) console.log("note: " + n);
  if (fixtureSeen) console.log("note: the dev fixture was in use; numbers on the page are placeholders");
  console.log(`screenshots (${shots.length}) in ${SHOT_DIR}`);
  if (failures.length) {
    console.log(`\n${failures.length} failure(s):`);
    for (const f of failures) console.log("  " + f);
    process.exit(1);
  }
  console.log("smoke: all checks passed");
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
