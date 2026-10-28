'use strict';
/**
 * Publishes a video to TikTok through TikTok Studio's web uploader, driven by
 * Playwright from an already signed-in Chrome profile. The same idea as
 * MetaReelPublisher: no password, no API. The TikTok Content Posting API was
 * rejected at app review, and its inbox endpoint only makes drafts anyway.
 *
 * Standalone: Playwright and Node builtins only.
 *
 * Flow (each step screenshotted when screenshotDir is given):
 *   launch → open-upload → attach → wait-upload → caption → [dry-run stop]
 *   → post → confirm → resolve-id
 *
 * dryRun defaults to TRUE: posting is public and irreversible, so a missing
 * flag must never become a live post.
 */

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const UPLOAD_URL = 'https://www.tiktok.com/tiktokstudio/upload?from=webapp&lang=en';

// Profiles that belong to other automations. Chrome allows one process per
// profile, so opening one of these would kill a Facebook post (Gmail_38,
// ChessReel) or a Jarvis post (Gmail_39) mid-task.
const FORBIDDEN_PROFILES = [/(^|[\\/])gmail_38[\\/]?$/i, /(^|[\\/])gmail_39[\\/]?$/i, /(^|[\\/])fb_autopost[\\/]?$/i];

// Pop-ups TikTok Studio shows on some sessions. Clicked away whenever seen;
// none of them changes what is posted. Order matters: the safe "no" first.
const DISMISS_LABELS = [/^not now$/i, /^got it$/i, /^skip$/i, /^ok$/i, /^close$/i, /^cancel$/i];

function cleanEnv() {
  const out = {};
  for (const [k, v] of Object.entries(process.env)) {
    if (v === undefined || k.startsWith('ELECTRON_') || k.startsWith('GOOGLE_API_')) continue;
    out[k] = v;
  }
  return out;
}

class TikTokPublisher {
  async publish(req) {
    const shots = [];
    const log = req.onStep || (() => {});
    const timeout = req.timeoutMs || 10 * 60 * 1000;
    let step = 'start';
    let context;

    const shot = async (page, name) => {
      if (!req.screenshotDir) return;
      try {
        fs.mkdirSync(req.screenshotDir, { recursive: true });
        const file = path.join(req.screenshotDir, `${String(shots.length + 1).padStart(2, '0')}_${name}.png`);
        await page.screenshot({ path: file, fullPage: false });
        shots.push(file);
      } catch (_) {
        // a missing screenshot must never fail a publish
      }
    };
    const fail = (error) => ({ ok: false, published: false, step, error, screenshots: shots });

    if (FORBIDDEN_PROFILES.some((re) => re.test(String(req.userDataDir || '').trim()))) {
      step = 'profile';
      return fail(`Refusing to use ${req.userDataDir}: that profile belongs to another automation.`);
    }
    if (!req.probeOnly && (!req.videoPath || !fs.existsSync(req.videoPath))) {
      step = 'video';
      return fail(`Video not found: ${req.videoPath}`);
    }

    try {
      step = 'launch';
      log(step, req.userDataDir);
      const headless = req.headless !== false;
      try {
        context = await chromium.launchPersistentContext(req.userDataDir, {
          channel: 'chrome',
          headless,
          // Headless has no window to maximise; without an explicit size the
          // page lays out tiny and clicks start missing.
          viewport: headless ? { width: 1600, height: 1000 } : null,
          args: [
            ...(headless ? ['--headless=new', '--window-size=1600,1000'] : ['--start-maximized']),
            '--mute-audio',
            '--disable-session-crashed-bubble',
            '--hide-crash-restore-bubble',
          ],
          env: cleanEnv(),
        });
      } catch (err) {
        const msg = String(err && err.message || err);
        if (/exitCode=21|user data directory is already in use|ProcessSingleton/i.test(msg)) {
          return fail(`Chrome profile ${req.userDataDir} is already open. Close that Chrome window; only one process may hold a profile.`);
        }
        throw err;
      }
      const page = context.pages()[0] || (await context.newPage());
      page.setDefaultTimeout(60 * 1000);

      // The profile's newest video BEFORE posting: after the post, the new
      // video is the first one that is not this.
      let beforeUrl = null;
      if (req.handle && !req.probeOnly) {
        step = 'read-profile';
        beforeUrl = await this.readNewest(context, req.handle).catch(() => null);
        log(step, beforeUrl || 'no videos yet');
      }

      step = 'open-upload';
      log(step, UPLOAD_URL);
      await page.goto(UPLOAD_URL, { waitUntil: 'domcontentloaded', timeout: 90 * 1000 });
      await page.waitForTimeout(6000);
      await shot(page, 'upload-page');
      if (/\/login/i.test(page.url())) {
        return fail('TikTok is asking this profile to log in again.');
      }
      await this.dismissPopups(page, log);

      if (req.probeOnly) {
        step = 'probe';
        const dump = await this.describe(page);
        log(step, JSON.stringify(dump).slice(0, 4000));
        return { ok: true, published: false, step, screenshots: shots, probe: dump };
      }

      step = 'attach';
      log(step, req.videoPath);
      const input = page.locator('input[type="file"]').first();
      await input.waitFor({ state: 'attached', timeout: 60 * 1000 });
      await input.setInputFiles(req.videoPath);
      await page.waitForTimeout(3000);
      await shot(page, 'attached');

      step = 'wait-upload';
      log(step);
      await this.waitForUpload(page, timeout);
      await this.dismissPopups(page, log);
      await shot(page, 'uploaded');

      step = 'caption';
      log(step, `${(req.caption || '').length} chars`);
      await this.fillCaption(page, req.caption || '');
      await page.waitForTimeout(1500);
      await this.dismissPopups(page, log);
      await shot(page, 'caption');
      const written = await page.locator('.public-DraftEditor-content, [contenteditable="true"]').first()
        .innerText().catch(() => '');
      log(step, `editor now holds ${written.length} chars`);
      if (req.caption && written.trim().length < Math.min(20, req.caption.length / 2)) {
        return fail('the caption did not land in the editor');
      }

      const postBtn = this.postButton(page);
      await postBtn.waitFor({ state: 'visible', timeout: 60 * 1000 });
      if (req.dryRun !== false) {
        step = 'dry-run-stop';
        log(step, 'stopped before Post');
        await shot(page, 'dry-run-stop');
        return { ok: true, published: false, step, screenshots: shots };
      }

      step = 'post';
      log(step);
      await this.waitEnabled(postBtn, 5 * 60 * 1000);
      await postBtn.click();
      await page.waitForTimeout(4000);
      // "Continue to post?" appears when TikTok's content check is still
      // running. Posting now is what a person would click.
      const postNow = page.getByRole('button', { name: /^post now$/i });
      if (await postNow.count().catch(() => 0)) {
        log(step, 'confirming "Post now"');
        await postNow.first().click().catch(() => {});
        await page.waitForTimeout(3000);
      }
      await shot(page, 'post-clicked');

      step = 'confirm';
      const confirmed = await this.waitForConfirmation(page, 3 * 60 * 1000);
      await shot(page, 'confirmed');
      if (!confirmed) {
        // Post was clicked; the page just never said so. Reported as
        // published-but-unconfirmed so nothing re-posts it automatically.
        log(step, 'no confirmation seen');
        return { ok: true, published: true, unconfirmed: true, step, screenshots: shots };
      }
      log(step, 'TikTok accepted the post');

      step = 'resolve-id';
      let postUrl = null;
      if (req.handle) {
        postUrl = await this.newestVideoUrl(context, req.handle, beforeUrl).catch(() => null);
        log(step, postUrl || 'not found yet');
      }
      return { ok: true, published: true, step, screenshots: shots, postUrl };
    } catch (err) {
      return fail(String(err && err.message || err));
    } finally {
      if (context) await context.close().catch(() => {});
    }
  }

  postButton(page) {
    return page.locator('button[data-e2e="post_video_button"]')
      .or(page.getByRole('button', { name: /^post$/i }))
      .first();
  }

  async waitEnabled(locator, ms) {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      const disabled = await locator.evaluate((el) =>
        el.disabled || el.getAttribute('aria-disabled') === 'true' || el.getAttribute('data-disabled') === 'true'
      ).catch(() => true);
      if (!disabled) return;
      await new Promise((r) => setTimeout(r, 2000));
    }
    throw new Error('Post button never became enabled');
  }

  async waitForUpload(page, ms) {
    // Done when the page stops saying "Uploading"/showing a percentage and the
    // Post button is enabled. Either signal alone has been seen to lie briefly.
    const end = Date.now() + ms;
    let stable = 0;
    while (Date.now() < end) {
      const state = await page.evaluate(() => {
        const text = document.body.innerText || '';
        const uploading = /uploading|\b\d{1,2}%/i.test(text) && !/uploaded/i.test(text);
        const failed = /upload failed|couldn.t upload|something went wrong/i.test(text);
        const btn = document.querySelector('button[data-e2e="post_video_button"]')
          || [...document.querySelectorAll('button')].find((b) => /^\s*post\s*$/i.test(b.innerText));
        const enabled = !!btn && !btn.disabled && btn.getAttribute('aria-disabled') !== 'true'
          && btn.getAttribute('data-disabled') !== 'true';
        return { uploading, failed, enabled };
      }).catch(() => ({ uploading: true, failed: false, enabled: false }));
      if (state.failed) throw new Error('TikTok reported the upload failed');
      if (!state.uploading && state.enabled) {
        stable += 1;
        if (stable >= 3) return;
      } else {
        stable = 0;
      }
      await new Promise((r) => setTimeout(r, 2000));
    }
    throw new Error('upload did not finish in time');
  }

  async fillCaption(page, caption) {
    // TikTok's editor is Draft.js. Text inserted faster than it re-renders
    // can be dropped: the first dry run lost a whole line. So each line gets
    // a pause, the result is checked line by line, and a second, slower
    // typing pass runs if anything is missing.
    const editor = page.locator('.public-DraftEditor-content, [contenteditable="true"]').first();
    await editor.waitFor({ state: 'visible', timeout: 60 * 1000 });
    const lines = caption.split('\n');
    const norm = (s) => s.replace(/\s+/g, ' ').trim();

    for (let attempt = 1; attempt <= 2; attempt++) {
      await editor.click();
      // TikTok pre-fills the file name; clear it (and any first attempt).
      await page.keyboard.press('Control+A');
      await page.keyboard.press('Backspace');
      await page.waitForTimeout(400);
      for (let i = 0; i < lines.length; i++) {
        if (lines[i]) {
          if (attempt === 1) await page.keyboard.insertText(lines[i]);
          else await page.keyboard.type(lines[i], { delay: 8 });
          await page.waitForTimeout(attempt === 1 ? 300 : 500);
        }
        if (i < lines.length - 1) {
          await page.keyboard.press('Shift+Enter');
          await page.waitForTimeout(200);
        }
      }
      // Close any #hashtag / @mention suggestion list left open by the last word.
      await page.keyboard.press('Escape').catch(() => {});
      await page.waitForTimeout(800);
      const text = norm(await editor.innerText().catch(() => ''));
      const missing = lines.map(norm).filter((l) => l && !text.includes(l));
      if (!missing.length) return;
      if (attempt === 2) throw new Error(`caption incomplete, missing: ${missing[0].slice(0, 60)}`);
    }
  }

  async waitForConfirmation(page, ms) {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      const url = page.url();
      if (/tiktokstudio\/content|\/manage/i.test(url)) return true;
      const text = await page.evaluate(() => document.body.innerText || '').catch(() => '');
      if (/your video (has been|is being) (posted|uploaded)|video published|manage your posts|view profile/i.test(text)) {
        return true;
      }
      await new Promise((r) => setTimeout(r, 3000));
    }
    return false;
  }

  async newestVideoUrl(context, handle, beforeUrl) {
    // Read from TikTok Studio → Posts, not the public profile: a new post is
    // listed there at once, while the profile hides it until review clears
    // (the first live post was "not found" on the profile for minutes).
    const end = Date.now() + 3 * 60 * 1000;
    while (Date.now() < end) {
      const href = await this.readNewest(context, handle).catch(() => null);
      if (href && href !== beforeUrl) return href;
      await new Promise((r) => setTimeout(r, 15000));
    }
    return null;
  }

  async dismissPopups(page, log) {
    // Feature tours ("New editing features added → Got it") are popovers, not
    // dialogs, and sit over the caption box, so "Got it" / "Not now" are
    // looked for anywhere on the page. "Cancel"/"Close" only count inside a
    // real dialog, where they mean "no thanks", never on the page itself,
    // where a Cancel could abandon the upload.
    for (let round = 0; round < 4; round++) {
      let clicked = false;
      for (const label of [/^got it$/i, /^not now$/i, /^skip$/i]) {
        const btn = page.getByRole('button', { name: label }).first();
        if (await btn.isVisible().catch(() => false)) {
          log('popup', String(label));
          await btn.click().catch(() => {});
          await page.waitForTimeout(800);
          clicked = true;
          break;
        }
      }
      if (!clicked) {
        const dialogs = page.locator('[role="dialog"], .TUXModal');
        if (await dialogs.count().catch(() => 0)) {
          for (const label of DISMISS_LABELS) {
            const btn = dialogs.getByRole('button', { name: label }).first();
            if (await btn.isVisible().catch(() => false)) {
              const text = await dialogs.first().innerText().catch(() => '');
              log('popup', `${label} (${text.replace(/\s+/g, ' ').slice(0, 80)})`);
              await btn.click().catch(() => {});
              await page.waitForTimeout(800);
              clicked = true;
              break;
            }
          }
        }
      }
      if (!clicked) return;
    }
  }

  async describe(page) {
    return page.evaluate(() => {
      const vis = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
      return {
        url: location.href,
        title: document.title,
        buttons: [...document.querySelectorAll('button')].filter(vis)
          .map((b) => `${(b.innerText || '').trim().slice(0, 40)}|${b.getAttribute('data-e2e') || ''}|${b.disabled ? 'disabled' : ''}`)
          .slice(0, 60),
        fileInputs: [...document.querySelectorAll('input[type=file]')].map((i) => i.getAttribute('accept')),
        editors: [...document.querySelectorAll('[contenteditable="true"]')].map((e) => e.className.slice(0, 80)),
        dialogs: [...document.querySelectorAll('[role="dialog"]')].filter(vis).map((d) => (d.innerText || '').slice(0, 120)),
      };
    });
  }

  /**
   * Post the promo comment on one of our own videos, then try to pin it.
   * The video page's comment panel: [data-e2e=comment-icon] opens it, the
   * input is a Draft.js editor inside [data-e2e=comment-input], and
   * [data-e2e=comment-post] sends it. Posting is verified by the text
   * appearing in the list. Pinning is best-effort and never fails the comment.
   */
  async comment(req) {
    const log = req.onStep || (() => {});
    const shots = [];
    let step = 'launch';
    let context;
    const shot = async (page, name) => {
      if (!req.screenshotDir) return;
      try {
        fs.mkdirSync(req.screenshotDir, { recursive: true });
        const file = path.join(req.screenshotDir, `c${String(shots.length + 1).padStart(2, '0')}_${name}.png`);
        await page.screenshot({ path: file });
        shots.push(file);
      } catch (_) { /* never fail on a screenshot */ }
    };
    if (FORBIDDEN_PROFILES.some((re) => re.test(String(req.userDataDir || '').trim()))) {
      return { ok: false, step: 'profile', error: `Refusing to use ${req.userDataDir}`, screenshots: shots };
    }
    try {
      context = await chromium.launchPersistentContext(req.userDataDir, {
        channel: 'chrome', headless: req.headless !== false, viewport: { width: 1600, height: 1000 },
        args: ['--headless=new', '--window-size=1600,1000', '--mute-audio', '--disable-session-crashed-bubble'],
        env: cleanEnv(),
      });
      const page = context.pages()[0] || (await context.newPage());
      page.setDefaultTimeout(45 * 1000);
      step = 'open-video';
      log(step, req.videoUrl);
      await page.goto(req.videoUrl, { waitUntil: 'domcontentloaded', timeout: 90 * 1000 });
      await page.waitForTimeout(7000);
      await this.dismissPopups(page, log);

      // 🔴 A CAPTCHA IS A STOP SIGN, NEVER A PUZZLE TO SOLVE. TikTok shows one
      // when it wants a human; working around it is bot-detection evasion and
      // puts the account at risk. The comment is simply skipped for this video.
      const captcha = () => page.getByText(/drag the puzzle piece|verify to continue|select 2 objects|rotate the/i)
        .first().isVisible().catch(() => false);
      if (await captcha()) {
        await shot(page, 'captcha');
        return { ok: false, step: 'captcha', error: 'TikTok showed a CAPTCHA; comment skipped (not solved, by design)', screenshots: shots };
      }

      step = 'open-comments';
      await page.locator('[data-e2e="comment-icon"]').first().click({ timeout: 15000 });
      await page.waitForTimeout(3000);
      if (await captcha()) {
        await shot(page, 'captcha');
        return { ok: false, step: 'captcha', error: 'TikTok showed a CAPTCHA; comment skipped (not solved, by design)', screenshots: shots };
      }
      const input = page.locator('[data-e2e="comment-input"] [contenteditable="true"], [data-e2e="comment-input"]').first();
      await input.waitFor({ state: 'visible' });
      await shot(page, 'comments-open');

      step = 'type';
      await input.click();
      await page.keyboard.insertText(req.text);
      await page.waitForTimeout(1500);
      await page.keyboard.press('Escape').catch(() => {});   // close an @/# suggestion list

      step = 'send';
      const send = page.locator('[data-e2e="comment-post"]').first();
      await send.click();
      await page.waitForTimeout(5000);

      step = 'verify';
      const probe = req.text.slice(0, 30);
      const listed = await page.evaluate((t) =>
        [...document.querySelectorAll('[data-e2e^="comment-level"], [data-e2e="comment-text"], [class*="CommentItem"]')]
          .some((el) => (el.innerText || '').includes(t)), probe).catch(() => false);
      await shot(page, 'comment-sent');
      if (!listed) {
        return { ok: false, step, error: 'comment was sent but did not appear in the list', screenshots: shots };
      }
      log(step, 'comment is visible');

      let pinned = false;
      if (req.pin) {
        step = 'pin';
        pinned = await this.pinComment(page, probe, log).catch(() => false);
        log(step, pinned ? 'pinned' : 'not pinned (left as the first comment)');
        await shot(page, 'pin');
      }
      return { ok: true, step: 'done', pinned, screenshots: shots };
    } catch (err) {
      return { ok: false, step, error: String(err && err.message || err), screenshots: shots };
    } finally {
      if (context) await context.close().catch(() => {});
    }
  }

  async pinComment(page, probe, log) {
    // Our comment → its "…" menu → "Pin". TikTok only shows the menu on hover.
    const item = page.locator('[data-e2e^="comment-level-1"], [class*="CommentItemContainer"], [class*="DivCommentItem"]')
      .filter({ hasText: probe }).first();
    await item.hover();
    await page.waitForTimeout(800);
    const more = item.locator('[data-e2e="comment-more-icon"], [aria-label*="more" i], [class*="More"]').first();
    if (!(await more.count())) return false;
    await more.click();
    await page.waitForTimeout(800);
    const pin = page.getByText(/^pin$/i).first();
    if (!(await pin.isVisible().catch(() => false))) return false;
    await pin.click();
    await page.waitForTimeout(2500);
    const ok = await page.getByText(/pinned/i).first().isVisible().catch(() => false);
    return ok;
  }

  /** The account's newest post URL (TikTok Studio → Posts), or null. */
  async readNewest(context, handle) {
    const page = await context.newPage();
    try {
      await page.goto('https://www.tiktok.com/tiktokstudio/content?lang=en', { waitUntil: 'domcontentloaded', timeout: 60 * 1000 });
      await page.waitForTimeout(7000);
      return await page.evaluate((h) => {
        const a = [...document.querySelectorAll('a[href*="/video/"]')]
          .find((el) => !h || el.href.includes(`/@${h}/`)) || document.querySelector('a[href*="/video/"]');
        return a ? a.href.split('?')[0] : null;
      }, handle);
    } finally {
      await page.close().catch(() => {});
    }
  }
}

module.exports = { TikTokPublisher, UPLOAD_URL };
