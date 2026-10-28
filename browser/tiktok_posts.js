#!/usr/bin/env node
/**
 * Read-only: list the newest posts in TikTok Studio → Posts, with their
 * privacy, review status and video link. Posts nothing.
 *
 *   node browser/tiktok_posts.js '{"userDataDir":"C:/path/to/tiktok-profile"}'
 *
 * Answers with ONE JSON line on stdout: { ok, posts: [{text, privacy, status, url}], error? }
 */
const { chromium } = require('playwright');

(async () => {
  const req = JSON.parse(process.argv[2] || '{}');
  let context;
  try {
    context = await chromium.launchPersistentContext(req.userDataDir, {
      channel: 'chrome', headless: req.headless !== false, viewport: { width: 1600, height: 1000 },
      args: ['--headless=new', '--window-size=1600,1000', '--mute-audio', '--disable-session-crashed-bubble'],
    });
    const page = context.pages()[0] || (await context.newPage());
    await page.goto('https://www.tiktok.com/tiktokstudio/content?lang=en', { waitUntil: 'domcontentloaded', timeout: 90000 });
    await page.waitForTimeout(8000);
    const posts = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('[data-tt="components_PostTable_Container"] > div, [role="row"], tr')];
      const out = [];
      for (const row of rows) {
        const text = (row.innerText || '').replace(/\s+/g, ' ').trim();
        if (!text || /^Posts \(Created on\)/i.test(text)) continue;
        const a = row.querySelector('a[href*="/video/"]');
        out.push({
          text: text.slice(0, 160),
          privacy: (text.match(/Everyone|Only me|Friends/i) || [null])[0],
          status: (text.match(/Content under review|Under review|Not eligible[^.]*|Removed|Posted/i) || [null])[0],
          url: a ? a.href.split('?')[0] : null,
        });
      }
      if (!out.length) {
        const links = [...document.querySelectorAll('a[href*="/video/"]')].map((a) => a.href.split('?')[0]);
        return links.map((url) => ({ text: null, privacy: null, status: null, url }));
      }
      return out.slice(0, 10);
    });
    process.stdout.write(JSON.stringify({ ok: true, posts }) + '\n');
  } catch (err) {
    process.stdout.write(JSON.stringify({ ok: false, error: String(err && err.message || err) }) + '\n');
  } finally {
    if (context) await context.close().catch(() => {});
  }
})();
