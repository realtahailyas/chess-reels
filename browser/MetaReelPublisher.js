"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.MetaReelPublisher = exports.SCHEDULE_SLOTS_PKT = exports.META_PAGES = void 0;
const playwright_1 = require("playwright");
const fs_1 = __importDefault(require("fs"));
const path_1 = __importDefault(require("path"));
/** The two pages Jarvis posts to today. Others live in their own project. */
/**
 * The two Facebook Pages this project posts to.
 *
 * 🔴 `instagramUsername` IS A SAFETY FIELD, NOT A LABEL. Each of these Pages is
 * linked to an Instagram account, so Meta's composer defaults its "Post to" to
 * BOTH ("TChess and tchessapp") and one submit would publish to Instagram as
 * well. Instagram is already published by the Graph API in this project — with
 * a real media id, which is what per-post insights and the pinned promo
 * comment are keyed off — so a crosspost here would put a SECOND, duplicate
 * reel on a live account with no id attached to it.
 *
 * This is the handle the deselect step looks for and then proves is gone. If
 * it is wrong or missing, the run aborts rather than risking that duplicate.
 */
exports.META_PAGES = {
    'tahachesstv': {
        key: 'tahachesstv',
        name: 'Taha Chess',
        assetId: process.env.FB_PAGE_ID || '',
        businessId: process.env.META_BUSINESS_ID || '',
        pageId: process.env.FB_PAGE_ID || '',
        instagramUsername: 'tahachesstv',
    },
    'tchessapp': {
        key: 'tchessapp',
        name: 'TChess',
        assetId: process.env.FB_PAGE_ID_TCHESSAPP || '',
        businessId: process.env.META_BUSINESS_ID || '',
        pageId: process.env.FB_PAGE_ID_TCHESSAPP || '',
        instagramUsername: 'tchessapp',
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
exports.SCHEDULE_SLOTS_PKT = ['04:30', '18:00', '22:00'];
class MetaReelPublisher {
    /**
     * The composer deep-link. Going straight here skips the Business Suite home
     * page and the "create" menu entirely, which is both faster and far less
     * fragile than clicking through them.
     */
    static composerUrl(page) {
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
    async publish(req) {
        const log = req.onStep ?? (() => { });
        const timeout = req.timeoutMs ?? 120000;
        const shots = [];
        let step = 'start';
        let context = null;
        const shot = async (page, name) => {
            if (!req.screenshotDir)
                return;
            try {
                fs_1.default.mkdirSync(req.screenshotDir, { recursive: true });
                const file = path_1.default.join(req.screenshotDir, `${String(shots.length + 1).padStart(2, '0')}_${name}.png`);
                await page.screenshot({ path: file, fullPage: false });
                shots.push(file);
            }
            catch {
                // a missing screenshot must never fail a publish
            }
        };
        try {
            // A probe never uploads, so it legitimately has no video to check.
            if (!req.probeOnly && !fs_1.default.existsSync(req.videoPath)) {
                return { ok: false, published: false, step: 'video', error: `Video not found: ${req.videoPath}`, screenshots: shots };
            }
            step = 'launch';
            log(step, req.userDataDir);
            context = await playwright_1.chromium.launchPersistentContext(req.userDataDir, {
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
            // 🔴 THE MOST DANGEROUS STEP ON THIS PAGE, AND IT HAPPENS BEFORE
            // ANY UPLOAD ON PURPOSE. These Pages are linked to Instagram
            // accounts, so the composer opens with "Post to" set to BOTH and a
            // single Share would publish to Instagram too — a duplicate,
            // id-less copy of a reel this project already posted through the
            // Graph API. Deselecting is not optional and not best-effort: if
            // the handle cannot be proven gone, the run stops here, having
            // published nothing.
            if (req.crosspostInstagram !== true) {
                step = 'deselect-instagram';
                log(step, req.page.instagramUsername || '(no handle configured)');
                const deselect = await this.deselectInstagram(page, req.page);
                await shot(page, 'post-to-facebook-only');
                if (!deselect.ok) {
                    return { ok: false, published: false, step, error: deselect.error, screenshots: shots };
                }
                log(step, deselect.detail);
            }
            // A profile check stops here: session valid, composer opened on the
            // right Page, Instagram proven deselected — everything that can go
            // wrong with a NEW profile — without uploading a video or leaving
            // any trace on the Page. Seconds instead of minutes.
            if (req.probeOnly) {
                step = 'probe-ok';
                log(step, 'session, page and destination all verified');
                return { ok: true, published: false, step, screenshots: shots };
            }
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
        }
        catch (err) {
            const message = err.message;
            // Chrome refuses to open a profile a running window already holds, and
            // says so in a way that reads like a Playwright bug rather than "your
            // browser is open".
            // 🔴 CHROME DOES NOT SAY "PROFILE IN USE" — IT JUST DIES.
            // When another window already holds the user-data-dir, Chrome's
            // ProcessSingleton exits with code 21 and Playwright reports the
            // generic "Target page, context or browser has been closed",
            // buried in a 4KB launch dump. Left unmatched, the single most
            // common operational failure here reads like a Playwright bug and
            // sends whoever is on call reading selector code.
            if (/already in use|existing browser session/i.test(message)
                || /exitCode=21/.test(message)
                || (/browser has been closed/i.test(message) && /<launched> pid=/.test(message))) {
                return {
                    ok: false,
                    published: false,
                    step,
                    error: `That Chrome profile is already open — close the "Quanta" browser window and run again. (${req.userDataDir})`,
                    screenshots: shots,
                };
            }
            return { ok: false, published: false, step, error: message, screenshots: shots };
        }
        finally {
            try {
                await context?.close();
            }
            catch { /* already closed */ }
        }
    }
    /**
     * Meta renders its own styled button rather than a visible file input, so the
     * click has to be paired with Playwright's file chooser.
     */
    /**
     * Turns the composer's destination into "this Facebook Page only".
     *
     * Meta's "Post to" control is a summary line ("TChess and tchessapp") that
     * opens a list of destinations with toggles. The Instagram row has to be
     * switched off, and — because getting this wrong publishes a duplicate to
     * a live Instagram account — the result is PROVEN by reading the summary
     * back, not assumed from a click landing.
     *
     * Returns {ok,detail|error} instead of throwing, so publish() can abort
     * with an explanation before a single byte is uploaded.
     */
    async deselectInstagram(page, pageConfig) {
        const handle = pageConfig.instagramUsername;
        if (!handle) {
            return {
                ok: false,
                error: `No instagramUsername configured for "${pageConfig.name}". Refusing to post: ` +
                       'without it there is no way to prove Instagram is deselected, and a crosspost ' +
                       'would duplicate a reel the Graph API already published.',
            };
        }

        // Already Facebook-only (Meta sometimes remembers the last choice).
        const before = await this.postToText(page);
        if (before && !new RegExp(handle, 'i').test(before)) {
            return { ok: true, detail: `already Facebook-only ("${before}")` };
        }

        // Open the destination picker. The control carrying the summary is the
        // combobox; matching it by the handle it currently displays is what
        // distinguishes it from every other button on the page.
        const opener = page.locator('div[role="combobox"], div[role="button"]')
            .filter({ hasText: new RegExp(handle, 'i') })
            .first();
        if (await opener.count() === 0) {
            return { ok: false, error: 'Could not find the "Post to" control to open.' };
        }
        await opener.click({ timeout: 20000 });
        await page.waitForTimeout(3000);

        // 🔴 THESE ARE role="option" WITH aria-selected — NOT checkboxes or
        // switches. The first version of this looked for
        // role="checkbox"/"switch", found nothing, clicked nothing, and was
        // caught only by the verification below. The menu holds one option per
        // destination: the Page, the linked Instagram account, and any groups.
        // Only the Instagram one may be turned off, and it is identified by
        // its text being exactly the handle — "tchessapp" must not also match
        // "TChess" or "TChess Community Public group".
        const options = page.locator('[role="option"]');
        const total = await options.count();
        let clicked = false;
        for (let i = 0; i < total; i++) {
            const option = options.nth(i);
            const text = ((await option.innerText().catch(() => '')) || '').replace(/\s+/g, ' ').trim();
            if (text.toLowerCase() !== handle.toLowerCase()) continue;
            const selected = await option.getAttribute('aria-selected').catch(() => null);
            if (selected === 'false') {
                clicked = true;   // already off
                break;
            }
            // Since 2026-10-02 another layer of the picker (a role="list"
            // subtree) sits over the options and swallows a real pointer click
            // until the timeout. A click event sent straight to the option is
            // what React listens for. It is safe because the read-back below
            // still has to prove the handle is gone before anything uploads.
            try {
                await option.click({ timeout: 8000 });
            } catch {
                await option.dispatchEvent('click');
            }
            await page.waitForTimeout(2000);
            clicked = true;
            break;
        }
        if (!clicked) {
            return {
                ok: false,
                error: `No destination option matching "${handle}" in the "Post to" menu ` +
                       `(${total} option(s) found). Stopping rather than posting to an ` +
                       'unverified destination.',
            };
        }

        // Close the picker so the summary re-renders.
        await page.keyboard.press('Escape').catch(() => {});
        await page.waitForTimeout(2000);

        const after = await this.postToText(page);
        if (after === null) {
            return {
                ok: false,
                error: 'Could not read the composer\'s "Post to" destination back, so Instagram ' +
                       'deselection cannot be proven. Stopping rather than risking a duplicate ' +
                       'Instagram post. Re-run with headless:false to watch it.',
            };
        }
        if (new RegExp(handle, 'i').test(after)) {
            return {
                ok: false,
                error: `"Post to" still includes @${handle} ("${after}") — Instagram was not ` +
                       'deselected. Stopping: publishing now would put a duplicate reel on that ' +
                       'Instagram account.',
            };
        }
        // The Page itself must still be selected — turning off the wrong row
        // would leave a composer with no destination at all, which fails much
        // later and much more confusingly.
        if (!new RegExp(pageConfig.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i').test(after)) {
            return {
                ok: false,
                error: `"Post to" no longer names the Page "${pageConfig.name}" ("${after}") — ` +
                       'the wrong destination was switched off. Stopping.',
            };
        }
        return { ok: true, detail: `destination is now "${after}"` };
    }

    async postToText(page) {
        const label = page.getByText(/^post to$/i).first();
        if (await label.count().catch(() => 0) === 0) return null;
        const value = await label
            .locator('xpath=following::*[@role="button" or @role="combobox"][1]')
            .first()
            .innerText()
            .catch(() => null);
        return value ? value.replace(/\s+/g, ' ').trim() : null;
    }

    async attachVideo(page, videoPath, timeout) {
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
    async waitForUpload(page, timeout) {
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
                if (disabled !== 'true')
                    return;
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
    async fillTitle(page, title) {
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
    async fillDescription(page, description) {
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
    timingOption(page, when) {
        const label = when === 'now' ? /^share now$/i : /^schedule$/i;
        return page.getByRole('button', { name: label }).first();
    }
    /** The footer button that submits the reel. */
    confirmButton(page) {
        return page.getByRole('button', { name: /^share$/i }).last();
    }
    /** Present only once the Share step has rendered. */
    publishButton(page) {
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
    async advanceToShare(page, maxSteps = 4) {
        for (let i = 0; i < maxSteps; i++) {
            if (await this.publishButton(page).count() > 0)
                return true;
            const next = page.getByRole('button', { name: /^next$/i });
            if (await next.count() === 0)
                break;
            const target = next.last();
            await target.scrollIntoViewIfNeeded().catch(() => { });
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
    static cleanEnv() {
        const out = {};
        for (const [k, v] of Object.entries(process.env)) {
            if (v === undefined)
                continue;
            if (k.startsWith('ELECTRON_'))
                continue;
            if (k.startsWith('GOOGLE_API_'))
                continue;
            out[k] = v;
        }
        return out;
    }
}
exports.MetaReelPublisher = MetaReelPublisher;
//# sourceMappingURL=MetaReelPublisher.js.map