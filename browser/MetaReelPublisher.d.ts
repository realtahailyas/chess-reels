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
export declare const META_PAGES: Record<string, MetaPageConfig>;
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
export declare const SCHEDULE_SLOTS_PKT: readonly ["04:30", "18:00", "22:00"];
export declare class MetaReelPublisher {
    /**
     * The composer deep-link. Going straight here skips the Business Suite home
     * page and the "create" menu entirely, which is both faster and far less
     * fragile than clicking through them.
     */
    static composerUrl(page: MetaPageConfig): string;
    publish(req: PublishRequest): Promise<PublishResult>;
    /**
     * Meta renders its own styled button rather than a visible file input, so the
     * click has to be paired with Playwright's file chooser.
     */
    private attachVideo;
    /**
     * Waits for the upload to finish. Meta shows no single reliable "done"
     * marker, so this waits for the Next control to become usable, which is the
     * behaviour that actually matters.
     */
    private waitForUpload;
    /**
     * Reads the value back after typing. A field that silently refuses input
     * would otherwise publish a reel with an empty title and look like a clean
     * run — the failure would only ever show up on the page itself.
     */
    private fillTitle;
    /**
     * The description is not a textarea and has no placeholder attribute — it is
     * a contenteditable div carrying an aria-label ("Write in the dialogue box
     * to include text with your post"). Matching it by placeholder found nothing
     * and the run timed out waiting for a field that was on screen the whole
     * time. It also has to be typed into rather than filled: `fill()` is
     * unreliable on contenteditable.
     */
    private fillDescription;
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
    private timingOption;
    /** The footer button that submits the reel. */
    private confirmButton;
    /** Present only once the Share step has rendered. */
    private publishButton;
    /**
     * Walks Create → Edit → Share.
     *
     * Uses the LAST "Next" rather than the first: the Create step renders two
     * matches, and the first is not the footer action — clicking it did nothing
     * and the run stalled on step one while looking like the button had been
     * pressed. Advances until the Share controls appear rather than assuming a
     * fixed number of steps.
     */
    private advanceToShare;
    /**
     * Chrome launched from inside Electron inherits Electron's own environment,
     * including vars a normally-launched browser never sees. Stripping them was
     * added after the desktop app died mid-automation.
     */
    private static cleanEnv;
}
//# sourceMappingURL=MetaReelPublisher.d.ts.map