// Renders docs/index.html to docs/assets/preview.png (light) and preview-dark.png.
const { chromium } = require("playwright");
const path = require("path");
(async () => {
  const browser = await chromium.launch();
  for (const [scheme, name] of [["light", "preview.png"], ["dark", "preview-dark.png"]]) {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, colorScheme: scheme, reducedMotion: "reduce" });
    const page = await ctx.newPage();
    await page.goto("file://" + path.resolve(__dirname, "../index.html"));
    await page.waitForTimeout(1200);
    await page.screenshot({ path: path.resolve(__dirname, "../assets", name) });
    await ctx.close();
  }
  await browser.close();
})();
