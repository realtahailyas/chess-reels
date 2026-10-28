#!/usr/bin/env node
/**
 * CLI bridge: Python calls this, it drives TikTokPublisher, and it answers with
 * exactly ONE line of JSON on stdout.
 *
 *   node browser/post_tiktok.js '<json request>'
 *
 * Request:
 *   {
 *     "videoPath":   "D:/.../video.mp4",
 *     "caption":     "...",
 *     "userDataDir": "C:/path/to/tiktok-profile",
 *     "handle":      "wwwtchessapp",
 *     "headless":    true,
 *     "dryRun":      true,          // default true: stops before Post
 *     "probeOnly":   false,         // open the upload page, describe it, stop
 *     "screenshotDir": "data/tt_shots/<id>",
 *     "timeoutMs":   600000
 *   }
 *
 * Response: { ok, published, unconfirmed?, step, error?, postUrl?, screenshots, log }
 *
 * 🔴 Human-readable output goes to stderr only. Python parses stdout as one
 * JSON document; a stray console.log there would turn a real post into a
 * "parse failure" that gets retried, and the video would be posted twice.
 */

const fs = require('fs');
const path = require('path');
const { TikTokPublisher } = require('./TikTokPublisher.js');

function respond(payload) {
  process.stdout.write(JSON.stringify(payload) + '\n');
}

(async () => {
  let req;
  try {
    req = JSON.parse(process.argv[2] || '');
  } catch (err) {
    respond({ ok: false, published: false, step: 'parse-request', error: String(err.message || err), screenshots: [], log: [] });
    process.exit(2);
  }
  if (!req.userDataDir || !fs.existsSync(req.userDataDir)) {
    respond({ ok: false, published: false, step: 'profile', error: `Chrome profile not found: ${req.userDataDir}`, screenshots: [], log: [] });
    process.exit(2);
  }

  const log = [];
  const onStep = (step, detail) => {
    const line = detail ? `${step}: ${detail}` : step;
    log.push(line);
    process.stderr.write(`[tiktok] ${line}\n`);
  };

  // Comment mode: {"commentOn": "<video url>", "text": "...", "pin": true}
  if (req.commentOn) {
    const res = await new TikTokPublisher().comment({
      userDataDir: req.userDataDir, videoUrl: req.commentOn, text: req.text || '',
      pin: req.pin !== false, headless: req.headless !== false, screenshotDir: req.screenshotDir, onStep,
    }).catch((err) => ({ ok: false, step: 'comment', error: String(err && err.message || err) }));
    respond({ ...res, log });
    process.exit(res.ok ? 0 : 1);
  }

  let result;
  try {
    result = await new TikTokPublisher().publish({
      ...req,
      videoPath: req.videoPath ? path.resolve(req.videoPath) : '',
      headless: req.headless !== false,
      dryRun: req.dryRun !== false,
      onStep,
    });
  } catch (err) {
    respond({ ok: false, published: false, step: 'publish', error: String(err && err.message || err), screenshots: [], log });
    process.exit(1);
  }
  respond({ ...result, log });
  process.exit(result.ok ? 0 : 1);
})();
