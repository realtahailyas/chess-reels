# MetaReelPublisher — Facebook Reels posting, standalone

Posts a video file to a Facebook Page as a Reel, through Meta Business Suite's
reel composer, driven by Playwright.

Built and proven inside Jarvis, but it imports **nothing** from that project —
only `playwright` and Node builtins — so this folder is the whole thing. Drop it
into any project.

## Files

| File | Use |
| --- | --- |
| `MetaReelPublisher.ts` | Source. Use this in a TypeScript project. |
| `MetaReelPublisher.js` | Compiled CommonJS. Use this from plain Node. |
| `MetaReelPublisher.d.ts` | Types for the compiled version. |

## What it needs

```
npm install playwright
```

Real Google Chrome must be installed — it launches `channel: 'chrome'`, not
Playwright's bundled Chromium.

## How it logs in

There is **no login code and no password anywhere**. It opens a **Chrome
user-data directory that is already signed in to Facebook** and reuses that
session.

- The directory comes from `CHROME_PROFILE_DIR` in `.env`.
- It launches with `chromium.launchPersistentContext(userDataDir, ...)`, which
  is a **real, persistent profile — not an isolated/incognito context**. That is
  deliberate: an isolated context has no cookies, so Facebook would just show a
  login page.
- Only one process can hold a profile at a time. If that Chrome window is open
  the launch fails, and the publisher returns a plain-English error saying to
  close it.

## Headless

`headless: true` works for the entire flow and is what runs in production —
verified end to end, including real published posts. Use `headless: false` only
when a selector has broken and you need to watch it happen.

## Usage

```js
const { MetaReelPublisher, META_PAGES } = require('./MetaReelPublisher.js');

const result = await new MetaReelPublisher().publish({
  page: META_PAGES['nature-battle-arena'],   // or your own config object
  videoPath: 'E:/videos/clip.mp4',
  title: 'Gecko vs Desert Hairy Scorpion Battle',
  description: 'Two desert hunters meet. Who wins? #wildlife #nature',
  userDataDir: process.env.CHROME_PROFILE_DIR,
  headless: true,
  dryRun: true,          // walks everything, stops before posting. DEFAULT.
  screenshotDir: './shots',
  onStep: (step, detail) => console.log(step, detail ?? ''),
});
// -> { ok, published, step, error?, screenshots: [...] }
```

**`dryRun` defaults to `true`.** You must pass `dryRun: false` to actually
publish, because posting is public and cannot be undone.

## Adding a page

A page is identified by its `asset_id`, which is the only thing the composer URL
really keys off:

```js
const myPage = {
  key: 'my-page',
  name: 'My Page',              // must match the composer's "Post to" field
  assetId: '1234567890',
  businessId: process.env.META_BUSINESS_ID,
  pageId: '1234567890',         // some pages need this, harmless if absent
};
```

Get `asset_id` from the composer URL in your browser:
`business.facebook.com/latest/reels_composer/?asset_id=<this>&business_id=<this>`

## The flow it drives

1. Open the composer deep link (skips Business Suite's home and Create menu).
2. **Verify the destination page** is the one you asked for, before uploading.
3. "Add video" → Playwright file chooser → set the file.
4. Wait for the upload to finish.
5. Fill Title, then Description.
6. `Next` → `Next` (Create → Edit → Share).
7. Choose "Share now", then click the footer "Share".
8. Confirm Facebook actually accepted it.

## Things that will bite you if you rewrite this

These were all found by running it, not by reading the page:

- **"Add video" is not a file input.** It is a styled button. Pair the click with
  `page.waitForEvent('filechooser')`.
- **Do not use `isEnabled()` to detect that the upload finished.** Meta renders
  its actions as `div[role="button"]`, which Playwright always reports as
  enabled. While the video processes, the button is greyed and marked
  `aria-disabled="true"`, and clicking it does nothing. Check that attribute.
- **The Create step has TWO "Next" buttons.** Use `.last()`. The first is not the
  footer action, and clicking it silently does nothing — a run stalls on step one
  while looking like the button was pressed.
- **Description has no `placeholder` attribute.** It is a
  `div[role="textbox"][contenteditable]` with
  `aria-label="Write in the dialogue box to include text with your post"`.
  Matching by placeholder finds nothing and times out on a field that is visible
  the whole time. It must be **typed** into — `fill()` is unreliable on
  contenteditable.
- **"Share now" is a timing option, not the submit button.** The footer "Share"
  is what submits. Clicking only "Share now" selects a timing and posts nothing,
  which looks like a successful run.
- **Clicking Share is not proof of publishing.** Facebook answers a real submit
  with a "Reel processing" dialog naming the reel. This code requires that text
  before reporting success. The page's Content → Published list is the final
  proof.
- **Automation kills these profiles ungracefully**, so Chrome's "didn't shut down
  correctly" bubble would appear every run. Launched with
  `--disable-session-crashed-bubble` and `--hide-crash-restore-bubble` — a native
  bubble has no DOM and cannot be clicked away by Playwright.
- **Launching Chrome from inside Electron** passes Electron's own env vars to it.
  `cleanEnv()` strips `ELECTRON_*` and `GOOGLE_API_*`.

## Scheduling

There is none in here, on purpose. Facebook's own "Schedule" is not used — every
post goes out live when `publish()` runs. Drive the timing from whatever calls
this (cron, Task Scheduler, your own loop).

For reference, the slots used in production are Pakistan time, chosen against the
US day: `04:30` (≈19:30 US Eastern, evening — strongest for Reels), `18:00`
(≈09:00 ET), `22:00` (≈13:00 ET).
