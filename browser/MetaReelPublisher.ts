import { chromium, BrowserContext, Page } from 'playwright';
import fs from 'fs';
import path from 'path';

/**
 * Publishes a video as a Facebook Reel through Meta Business Suite's reel
 * composer.
 *
 * Deliberately standalone: it imports nothing from the rest of this project,
 * only Playwright and Node builtins. The same file is meant to be dropped into
 * other projects (D:/Tchess-platform) that post to their own pages with their
 * own video sources, so the page list and the content are inputs rather than
 * anything baked in here.
 *
 * A page is identified by its `assetId` — that is what the composer URL keys
 * off, and it is what makes this reusable: adding a page means adding a config
 * entry, not touching this code.
 */

export interface MetaPageConfig {
  /** Short stable handle used in logs and by callers. */
  key: string;
  /** The page name as it appears in the composer's "Post to" field. */
  name: string;
  /** Identifies the page to the composer. This is the important one. */
  assetId: string;
  businessId: string;
  /** Present for some pages; harmless when absent. */
  pageId?: string;
}

export interface PublishRequest {
  page: MetaPageConfig;
  videoPath: string;
  title?: string;
  description?: string;
  /**
   * Chrome user-data directory holding the logged-in Facebook session. On this
   * machine that is the profile behind the "Quanta" desktop shortcut.
   */
  userDataDir: string;
  /**
   * Headless is faster and unattended, but leave it off while the flow is
   * still being learned — watching it is how the real selectors get found, and
   * Meta is more likely to challenge an automated-looking session.
   */
  headless?: boolean;
  /**
   * Walk the entire flow but stop before the final publish click. The default,
   * because posting is public and irreversible.
   */
  dryRun?: boolean;
  /** Where to drop a screenshot after each step, for reviewing a run. */
  screenshotDir?: string;
  onStep?: (step: string, detail?: string) => void;
  timeoutMs?: number;
}

export interface PublishResult {
  ok: boolean;
  published: boolean;
  step: string;
  error?: string;
  screenshots: string[];
}

/** The two pages Jarvis posts to today. Others live in their own project. */
export const META_PAGES: Record<string, MetaPageConfig> = {
  'nature-battle-arena': {
    key: 'nature-battle-arena',
    name: 'Nature Battle Arena',
    assetId: process.env.FB_PAGE_ID_NATURE ?? '',
    businessId: process.env.META_BUSINESS_ID ?? '',
  },
  'echoes-of-tomorrow': {
    key: 'echoes-of-tomorrow',
    name: 'Echoes of Tomorrow',
    assetId: process.env.FB_PAGE_ID_ECHOES ?? '',
    businessId: process.env.META_BUSINESS_ID ?? '',
    pageId: process.env.FB_PAGE_ID_ECHOES ?? '',
  },
};

/**
 * When to post, in Pakistan local time (UTC+5).
 *
 * Timing is driven by whatever runs this file on a schedule — Facebook's own
 * "Schedule" option is deliberately not used, so every post goes out live at
 * the moment the script runs.
 *
 * Chosen against the US day rather than the local one, because that is the
 * audience. The first draft used 05:30 and 10:30 PKT, but those are 20:30 and
 * 01:30 US Eastern — the second lands in the middle of the American night, so
 * two of the three slots were effectively competing for one audience. These
 * spread across it instead (US Eastern in brackets, DST):
 *
 *   04:30 PKT  →  19:30 ET  US evening, the strongest window for Reels
 *   18:00 PKT  →  09:00 ET  US morning
 *   22:00 PKT  →  13:00 ET  US early afternoon
 */
export const SCHEDULE_SLOTS_PKT = ['04:30', '18:00', '22:00'] as const;

export class MetaReelPublisher {
  /**
   * The composer deep-link. Going straight here skips the Business Suite home
   * page and the "create" menu entirely, which is both faster and far less
   * fragile than clicking through them.
   */
  static composerUrl(page: MetaPageConfig): string {
    const params = new URLSearchParams({
      asset_id: page.assetId,
      business_id: page.businessId,
    });
    if (page.pageId) {
      params.set('page_id', page.pageId);
      params.set('global_scope_id', page.businessId);
    }
    return `https://business.facebook.com/latest/reels_composer/?${params.toString()}`;
  }

  async publish(req: PublishRequest): Promise<PublishResult> {
    const log = req.onStep ?? (() => {});
    const timeout = req.timeoutMs ?? 120000;
    const shots: string[] = [];
    let step = 'start';
    let context: BrowserContext | null = null;

    const shot = async (page: Page, name: string) => {
      if (!req.screenshotDir) return;
      try {
        fs.mkdirSync(req.screenshotDir, { recursive: true });
        const file = path.join(req.screenshotDir, `${String(shots.length + 1).padStart(2, '0')}_${name}.png`);
        await page.screenshot({ path: file, fullPage: false });
        shots.push(file);
      } catch {
        // a missing screenshot must never fail a publish
      }
    };

    try {
      if (!fs.existsSync(req.videoPath)) {
        return { ok: false, published: false, step: 'video', error: `Video not found: ${req.videoPath}`, screenshots: shots };
      }

      step = 'launch';
      log(step, req.userDataDir);
      context = await chromium.launchPersistentContext(req.userDataDir, {
        channel: 'chrome',
        headless: !!req.headless,
        viewport: null,
        args: [
          '--start-maximized',
          // Automation kills these profiles far less gracefully than a person
          // closes a browser, so without this the "didn't shut down correctly"
          // bubble appears on every run and there is no DOM to dismiss it from.
          '--disable-session-crashed-bubble',
          '--hide-crash-restore-bubble',
        ],
        env: MetaReelPublisher.cleanEnv(),
      });

      const page = context.pages()[0] ?? (await context.newPage());
      page.setDefaultTimeout(timeout);

      step = 'open-composer';
      const url = MetaReelPublisher.composerUrl(req.page);
      log(step, url);
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout });
      await page.waitForTimeout(4000);
      await shot(page, 'composer');

      // If the session is gone the composer never renders and everything below
      // times out with a confusing selector error instead of the real reason.
      if (/login|checkpoint/i.test(page.url())) {
        return { ok: false, published: false, step, error: 'Facebook is asking this profile to log in again.', screenshots: shots };
      }

      // Confirm the composer really opened on the intended page before
      // uploading anything. The destination comes from a URL parameter, so a
      // wrong or stale asset id fails silently by loading a *different* page's
      // composer — and posting to the wrong page is public and awkward to
      // undo. Cheap check, expensive mistake.
      step = 'verify-page';
      const postTo = await page
        .getByText(req.page.name, { exact: false })
        .first()
        .count()
        .catch(() => 0);
      if (postTo === 0) {
        return {
          ok: false,
          published: false,
          step,
          error: `Composer did not open on "${req.page.name}" — check this page's assetId (${req.page.assetId}).`,
          screenshots: shots,
        };
      }
      log(step, req.page.name);

      step = 'add-video';
      log(step, req.videoPath);
      await this.attachVideo(page, req.videoPath, timeout);
      await shot(page, 'video-attached');

      step = 'wait-upload';
      log(step);
      await this.waitForUpload(page, timeout);
      await shot(page, 'uploaded');

      if (req.title) {
        step = 'title';
        log(step, req.title);
        await this.fillTitle(page, req.title);
      }

      if (req.description) {
        step = 'description';
        log(step);
        await this.fillDescription(page, req.description);
      }
      await shot(page, 'details-filled');

      step = 'next';
      log(step);
      // The composer walks Create → Edit → Share; how many Next clicks that
      // takes varies, so advance until the publish control appears rather than
      // assuming a fixed count.
      const reachedShare = await this.advanceToShare(page);
      await shot(page, 'share-step');
      if (!reachedShare) {
        return { ok: false, published: false, step, error: 'Could not reach the final share step.', screenshots: shots };
      }

      step = 'timing';
      // Always "Share now": the schedule is owned by whatever runs this, not
      // by Facebook's own scheduler.
      log(step, 'now');
      await this.timingOption(page, 'now').click();
      await page.waitForTimeout(2500);
      await shot(page, 'timing-selected');

      if (req.dryRun !== false) {
        step = 'dry-run-stop';
        log(step, 'stopped before publishing');
        return { ok: true, published: false, step, screenshots: shots };
      }

      step = 'publish';
      log(step);
      await this.confirmButton(page).click();
      await page.waitForTimeout(8000);
      await shot(page, 'published');

      // Facebook answers a successful submit with a "Reel processing" dialog
      // naming the reel. Without checking for it, any failure after the click
      // would still be reported as published — the click landing is not the
      // same as Facebook accepting the upload.
      step = 'confirm';
      const accepted = await page
        .getByText(/reel processing|your reel (is|has been)|will be published/i)
        .first()
        .count()
        .catch(() => 0);
      if (accepted === 0) {
        return {
          ok: false,
          published: false,
          step,
          error: 'Clicked Share but Facebook never confirmed the reel — check the last screenshot.',
          screenshots: shots,
        };
      }
      log('confirmed', 'Facebook accepted the reel');

      return { ok: true, published: true, step: 'done', screenshots: shots };
    } catch (err) {
      const message = (err as Error).message;
      // Chrome refuses to open a profile a running window already holds, and
      // says so in a way that reads like a Playwright bug rather than "your
      // browser is open".
      if (/already in use|existing browser session/i.test(message)) {
        return {
          ok: false,
          published: false,
          step,
          error: `That Chrome profile is already open — close the "Quanta" browser window and run again. (${req.userDataDir})`,
          screenshots: shots,
        };
      }
      return { ok: false, published: false, step, error: message, screenshots: shots };
    } finally {
      try { await context?.close(); } catch { /* already closed */ }
    }
  }

  /**
   * Meta renders its own styled button rather than a visible file input, so the
   * click has to be paired with Playwright's file chooser.
   */
  private async attachVideo(page: Page, videoPath: string, timeout: number): Promise<void> {
    const trigger = page.getByText('Add video', { exact: false }).first();
    const [chooser] = await Promise.all([
      page.waitForEvent('filechooser', { timeout }),
      trigger.click(),
    ]);
    await chooser.setFiles(videoPath);
  }

  /**
   * Waits for the upload to finish. Meta shows no single reliable "done"
   * marker, so this waits for the Next control to become usable, which is the
   * behaviour that actually matters.
   */
  private async waitForUpload(page: Page, timeout: number): Promise<void> {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      const next = page.getByRole('button', { name: /^next$/i }).last();
      if (await next.count() > 0) {
        // `isEnabled()` is not meaningful here: Meta renders its actions as
        // divs with role="button", which Playwright always reports as enabled.
        // While the video is still processing the control is greyed out and
        // marked aria-disabled, and clicking it silently does nothing — which
        // is what stalled an earlier run on step one.
        const disabled = await next.getAttribute('aria-disabled').catch(() => null);
        if (disabled !== 'true') return;
      }
      await page.waitForTimeout(2000);
    }
    throw new Error('Video upload did not finish in time.');
  }

  /**
   * Reads the value back after typing. A field that silently refuses input
   * would otherwise publish a reel with an empty title and look like a clean
   * run — the failure would only ever show up on the page itself.
   */
  private async fillTitle(page: Page, title: string): Promise<void> {
    const field = page.getByPlaceholder(/add a title/i).first();
    await field.click();
    await field.fill(title);
    const got = (await field.inputValue().catch(() => '')).trim();
    if (got !== title.trim()) {
      throw new Error(`Title did not take. Wanted ${JSON.stringify(title)}, field holds ${JSON.stringify(got)}`);
    }
  }

  /**
   * The description is not a textarea and has no placeholder attribute — it is
   * a contenteditable div carrying an aria-label ("Write in the dialogue box
   * to include text with your post"). Matching it by placeholder found nothing
   * and the run timed out waiting for a field that was on screen the whole
   * time. It also has to be typed into rather than filled: `fill()` is
   * unreliable on contenteditable.
   */
  private async fillDescription(page: Page, description: string): Promise<void> {
    const byLabel = page.getByRole('textbox', { name: /write in the dialogue box/i }).first();
    const field = (await byLabel.count()) > 0
      ? byLabel
      : page.locator('div[role="textbox"][contenteditable="true"]').first();
    await field.click();
    await page.keyboard.type(description);

    const got = (await field.innerText().catch(() => '')).trim();
    // Compared loosely: the editor re-wraps text and may render hashtags as
    // their own nodes, so an exact match is not a fair check.
    const head = description.trim().slice(0, 25);
    if (!got.includes(head)) {
      throw new Error(`Description did not take. Expected it to start ${JSON.stringify(head)}, field holds ${JSON.stringify(got.slice(0, 80))}`);
    }
  }

  /**
   * On the final step Meta shows two different things that both say "share",
   * and they do different jobs:
   *
   *  - "Share now" / "Schedule" / "Save as draft" choose *when* it goes out.
   *  - The footer "Share" button is what actually submits.
   *
   * Clicking only the first selects a timing option and posts nothing, which
   * looks like a successful run that quietly did not publish.
   */
  private timingOption(page: Page, when: 'now' | 'schedule') {
    const label = when === 'now' ? /^share now$/i : /^schedule$/i;
    return page.getByRole('button', { name: label }).first();
  }

  /** The footer button that submits the reel. */
  private confirmButton(page: Page) {
    return page.getByRole('button', { name: /^share$/i }).last();
  }

  /** Present only once the Share step has rendered. */
  private publishButton(page: Page) {
    return this.timingOption(page, 'now');
  }

  /**
   * Walks Create → Edit → Share.
   *
   * Uses the LAST "Next" rather than the first: the Create step renders two
   * matches, and the first is not the footer action — clicking it did nothing
   * and the run stalled on step one while looking like the button had been
   * pressed. Advances until the Share controls appear rather than assuming a
   * fixed number of steps.
   */
  private async advanceToShare(page: Page, maxSteps = 4): Promise<boolean> {
    for (let i = 0; i < maxSteps; i++) {
      if (await this.publishButton(page).count() > 0) return true;
      const next = page.getByRole('button', { name: /^next$/i });
      if (await next.count() === 0) break;
      const target = next.last();
      await target.scrollIntoViewIfNeeded().catch(() => {});
      await target.click({ timeout: 20000 });
      await page.waitForTimeout(5000);
    }
    return (await this.publishButton(page).count()) > 0;
  }

  /**
   * Chrome launched from inside Electron inherits Electron's own environment,
   * including vars a normally-launched browser never sees. Stripping them was
   * added after the desktop app died mid-automation.
   */
  private static cleanEnv(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(process.env)) {
      if (v === undefined) continue;
      if (k.startsWith('ELECTRON_')) continue;
      if (k.startsWith('GOOGLE_API_')) continue;
      out[k] = v;
    }
    return out;
  }
}
