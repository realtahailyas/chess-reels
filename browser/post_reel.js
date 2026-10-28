#!/usr/bin/env node
/**
 * CLI bridge: Python calls this, it drives MetaReelPublisher, and it answers
 * with exactly one line of JSON on stdout.
 *
 *   node browser/post_reel.js '<json request>'
 *   echo '<json request>' | node browser/post_reel.js
 *
 * Request:
 *   {
 *     "account":     "tchessapp" | "tahachesstv",
 *     "videoPath":   "D:/.../video.mp4",
 *     "title":       "...",
 *     "description": "...",
 *     "userDataDir": "C:/path/to/chrome-profile",
 *     "headless":    true,
 *     "dryRun":      true,
 *     "screenshotDir": "data/fb_shots/<puzzle_id>"
 *   }
 *
 * Response (always one JSON line, even on a crash):
 *   { "ok": bool, "published": bool, "step": "...", "error": "...", "screenshots": [...], "log": [...] }
 *
 * 🔴 EVERYTHING HUMAN-READABLE GOES TO stderr, NEVER stdout. Python parses
 * stdout as a single JSON document; one stray console.log there and a
 * successful post is reported to the publisher as a parse failure, which would
 * then be retried — posting the same reel to a live Page twice.
 */

const fs = require('fs');
const path = require('path');
const { MetaReelPublisher, META_PAGES } = require('./MetaReelPublisher.js');

function respond(payload) {
  process.stdout.write(JSON.stringify(payload) + '\n');
}

async function readRequest() {
  const arg = process.argv[2];
  if (arg && arg.trim()) return JSON.parse(arg);
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString('utf8').trim();
  if (!raw) throw new Error('No request given (pass JSON as argv[2] or on stdin)');
  return JSON.parse(raw);
}

(async () => {
  let req;
  try {
    req = await readRequest();
  } catch (err) {
    respond({ ok: false, published: false, step: 'parse-request', error: err.message, screenshots: [], log: [] });
    process.exit(2);
  }

  const pageConfig = META_PAGES[req.account];
  if (!pageConfig) {
    respond({
      ok: false, published: false, step: 'account',
      error: `Unknown account "${req.account}" (known: ${Object.keys(META_PAGES).join(', ')})`,
      screenshots: [], log: [],
    });
    process.exit(2);
  }

  if (!req.probeOnly && (!req.videoPath || !fs.existsSync(req.videoPath))) {
    respond({
      ok: false, published: false, step: 'video',
      error: `Video not found: ${req.videoPath}`, screenshots: [], log: [],
    });
    process.exit(2);
  }

  const log = [];
  const onStep = (step, detail) => {
    const line = detail ? `${step}: ${detail}` : step;
    log.push(line);
    process.stderr.write(`[meta] ${line}\n`);
  };

  let result;
  try {
    result = await new MetaReelPublisher().publish({
      page: pageConfig,
      videoPath: req.videoPath ? path.resolve(req.videoPath) : '',
      title: req.title,
      description: req.description,
      userDataDir: req.userDataDir,
      headless: req.headless !== false,
      // 🔴 Mirrors the library's own default: dryRun is true unless the caller
      // explicitly passes false. A typo in the request must not become a live
      // post on a real Page.
      dryRun: req.dryRun !== false,
      // Never crosspost: Instagram is published separately through the Graph
      // API, which returns the media id that insights and the pinned promo
      // comment both depend on. See MetaReelPublisher.deselectInstagram.
      crosspostInstagram: false,
      // Verify a profile without touching the Page: stops after the
      // destination is proven, before any upload.
      probeOnly: req.probeOnly === true,
      screenshotDir: req.screenshotDir,
      timeoutMs: req.timeoutMs,
      onStep,
    });
  } catch (err) {
    respond({
      ok: false, published: false, step: 'publish',
      error: err && err.message ? err.message : String(err),
      screenshots: [], log,
    });
    process.exit(1);
  }

  respond({ ...result, log });
  process.exit(result.ok ? 0 : 1);
})();
