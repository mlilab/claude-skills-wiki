// Screen-only driver: replay mouse/keyboard actions from a fresh load, then save what the screen shows.
// Local check of the core on assets/test.html after you change it (the live site is checked in the real browser).
// usage: GAI_PAGE=assets/test.html node scripts/gui.mjs '<query string or "">' '<json actions>' <out.png>
// actions: ["click",x,y] ["type","text"] ["key","Enter"] ["scroll",dy] ["wait",ms]
const { chromium } = await import(process.env.PLAYWRIGHT || 'playwright');   // PLAYWRIGHT=/path/to/playwright/index.mjs if it is not resolvable
import path from 'node:path';
const [qs = '', acts = '[]', out = '/tmp/gui.png'] = process.argv.slice(2);
const file = 'file://' + path.resolve(process.env.GAI_PAGE || 'assets/test.html');
const b = await chromium.launch({ executablePath: process.env.CHROME || undefined, args: ['--no-sandbox'] })   // CHROME=/usr/bin/google-chrome to use an installed browser;
const c = await b.newContext({ viewport: { width: 1280, height: 800 }, locale: 'ko-KR', timezoneId: 'Asia/Seoul' });
const p = await c.newPage();
const left = [];
await p.route(u => !u.href.startsWith('file:'), r => { if (r.request().isNavigationRequest()) left.push(r.request().url()); r.abort(); });
await p.goto(file + qs);
for (const [k, a, b2] of JSON.parse(acts)) {
  if (k === 'click') await p.mouse.click(a, b2);
  else if (k === 'type') await p.keyboard.type(a, { delay: 20 });
  else if (k === 'key') await p.keyboard.press(a);
  else if (k === 'scroll') await p.mouse.wheel(0, a);
  else if (k === 'wait') await p.waitForTimeout(a);
  await p.waitForTimeout(150);
}
await p.screenshot({ path: out }).catch(() => {});
console.log('address bar:', decodeURIComponent(p.url().replace(/^file:\/\/.*\//, '')));
console.log('left the page for:', left.length ? left.join(' , ') : 'nothing');
await b.close();
