// pov_fuse_shot — screenshot a pov_fuse contact sheet (headless Chromium + SwiftShader WebGL).
// Usage: node pov_fuse_shot.js <html> <out.png> [--rows <dir>]
//   <out.png>     full-page screenshot of the whole sheet
//   --rows <dir>  also write one PNG per row (row_01.png ...) for full-resolution self-validation
const { chromium } = require('playwright');

(async () => {
  const args = process.argv.slice(2);
  const html = args[0], out = args[1];
  const ri = args.indexOf('--rows');
  const rowsDir = ri >= 0 ? args[ri + 1] : null;
  if (!html || !out) { console.log('usage: node pov_fuse_shot.js <html> <out.png> [--rows <dir>]'); process.exit(1); }

  const b = await chromium.launch({ headless: true,
    args: ['--no-sandbox', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--use-gl=angle', '--use-angle=swiftshader'] });
  // viewport wide enough for POV(580)+plot(580)+HUD(300) so the HUD column is never clipped
  const page = await b.newPage({ viewport: { width: 1500, height: 1000 } });
  page.on('pageerror', e => console.log('PAGEERR:', e.message.slice(0, 200)));
  await page.goto('file://' + html, { waitUntil: 'load', timeout: 45000 });
  await page.waitForFunction(() => document.title === 'READY', { timeout: 20000 }).catch(() => console.log('no READY title'));
  await page.waitForFunction(() => [...document.images].every(i => i.complete && i.naturalWidth > 0), { timeout: 20000 }).catch(() => console.log('imgs not all complete'));
  await page.waitForTimeout(600);

  await page.screenshot({ path: out, fullPage: true });
  console.log('SHOT_SAVED', out);

  if (rowsDir) {
    const rows = await page.$$('.row');
    for (let i = 0; i < rows.length; i++) {
      const f = `${rowsDir}/row_${String(i + 1).padStart(2, '0')}.png`;
      await rows[i].screenshot({ path: f });
      console.log('ROW', i + 1, f);
    }
  }
  await b.close();
})().catch(e => { console.log('FATAL:', e.message); process.exit(1); });
