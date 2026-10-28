"""All tunable values for the chess reel pipeline.

NON-NEGOTIABLE: no magic numbers in module code. Everything adjustable lives
here so a user can retune the format without touching pipeline logic.
"""

import os
import subprocess
import shutil
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
ASSETS_DIR = ROOT / "assets"
PUZZLE_CSV = DATA_DIR / "lichess_db_puzzle.csv"
POSTED_JSON = DATA_DIR / "posted.json"
PUZZLE_URL = "https://database.lichess.org/lichess_db_puzzle.csv.zst"

# Output folders are numbered so a batch produces 0001_<id>, 0002_<id>, ... in
# order and browsing is easy. Numbering is global and continues across batches;
# the puzzle id stays in the name for traceability. Set False for bare <id>.
OUTPUT_NUMBERING = True
OUTPUT_INDEX_WIDTH = 4

# ── Canvas ────────────────────────────────────────────────────────────────
CANVAS_W, CANVAS_H = 1080, 1920
FPS = 30
BOARD_PX = 960
BG = (16, 16, 19)
ACCENT = (255, 107, 53)
WHITE = (242, 240, 234)
MUTED = (146, 144, 138)

# Vertical layout (Section 7.1). Board is centred with a downward offset so it
# clears the platform's top UI chrome but stays above the caption overlay.
ACCENT_BAR_H = 9
THEME_LABEL_Y = 60
SERIES_LABEL_Y = 18
HEADLINE_Y = 290
BOARD_Y_OFFSET = 60      # 960px board sits higher so it clears the countdown
SUBTITLE_GAP = 50
DOTS_FROM_BOTTOM = 118

# Safe zones — nothing important may be drawn inside these margins.
SAFE_TOP = 180
SAFE_BOTTOM = 320
SAFE_RIGHT = 120

# Font sizes
FONT_THEME = 42
FONT_SERIES = 34
FONT_HEADLINE = 92
FONT_SUBTITLE = 50
FONT_COUNTDOWN = 105
FONT_OUTRO = 96
FONT_OUTRO_SMALL = 44
TEXT_SHADOW_PX = 3

# Countdown numeral sits in the gap between the headline and the board top.
COUNTDOWN_CY = 475
COUNTDOWN_RING_R = 58
COUNTDOWN_RING_W = 7

# Brilliant "!!" badge — Chess.com style, on the brilliant move's destination
# square (top-right corner, slight overflow). Fractions are of the cell size.
SHOW_BRILLIANT = True
BRILLIANT_COLOR = (38, 198, 218)     # #26C6DA cyan/teal
BRILLIANT_RADIUS = 0.26              # badge radius
BRILLIANT_OFFSET = 0.34              # corner offset from square centre
BRILLIANT_POP = 0.35                 # seconds of the pop-in animation
BRILLIANT_OVERSHOOT = 3.1            # ease_out_back constant → ~1.25x peak

# ── Board colours ─────────────────────────────────────────────────────────
# These ARE the TChess app's own board, not an approximation of it. A reel that
# advertises the app and then shows a different-looking board teaches the viewer
# the wrong thing to look for in the store; the board is the most recognisable
# surface either product has.
#
# Source of truth: tchess-app/src/theme/boardThemes.ts, the `classic` theme
# (the app's default). Its own header explains why these exact values —
# chess.com's #EBECD0 is calibrated for a white web page and reads as a lit
# sticker on black, so both squares are pulled down for a dark surround.
#
# The PIECES already match with no work: the app renders Cburnett, and
# python-chess's bundled artwork (src/board.py -> chess.svg.piece) is Cburnett
# too. Do not swap either one.
#
# ⚠️ python-chess wants SOLID colours, while the app tints a transparent
# overlay over the square. The four values below are therefore the app's
# overlay ALREADY COMPOSITED over each square colour — recompute them if the
# app's tokens move:
#     lastmove = color.warning #F5A524 at 0x4D   (the destination-square alpha)
#     check    = color.danger  #F05252 at 0x59
BOARD_COLORS = {
    "square light": "#DFE3CE",           # boardThemes.classic.light
    "square dark": "#6E8A54",            # boardThemes.classic.dark
    "square light lastmove": "#E6D09B",  # warning 0x4D over the light square
    "square dark lastmove": "#979246",   # warning 0x4D over the dark square
    "margin": "#101013",                 # = BG, so the board floats like it
    "coord": "#8B8B90",                  # the app's neutral textMid
}
CHECK_COLOR = "#F05252"                  # color.danger, as the app's check tint

# Renderer: "auto" prefers cairosvg and falls back to the built-in PIL
# rasterizer. Force one with "cairo" or "pil".
BOARD_RENDERER = os.environ.get("CHESS_REEL_RENDERER", "auto")
# Supersampling factor for the PIL rasterizer. 2 is a good quality/speed
# tradeoff; 3+ is noticeably slower for little visible gain.
PIL_SUPERSAMPLE = 2

# ── Timing ────────────────────────────────────────────────────────────────
SLIDE_DURATION = 0.42     # seconds per piece move
ARC_LIFT = 0.22           # fraction of cell size
HOOK_DURATION = 3.6       # countdown timer segment
HOLD_SACRIFICE = 2.3      # pause after the brilliant move
HOLD_NORMAL = 1.5         # pause after a forced/quiet move
HOLD_FINAL = 2.6          # pause after the last move
OUTRO_DURATION = 3.0      # rating reveal + CTA
FLASH_DECAY = 0.28        # seconds of impact flash

# Fast replay timing for the full-game GM variant: same board progression, no
# move counter feel, and short holds so an actual full PGN still fits in short
# form. Piece slides stay snappy (same speed as the puzzle variants) — the
# pacing comes from the hold after each move, not a slow-motion slide.
GM_HOOK_DURATION = 1.1
GM_SLIDE_DURATION = 0.42
GM_HOLD_FIRST = 3.20
GM_HOLD_MOVE = 2.00
GM_HOLD_LAST = 3.20
GM_OUTRO_DURATION = 2.2

# Optional engine path for the GM replay eval bar. If stockfish is not
# installed the code falls back to the simple material eval.
GM_STOCKFISH_PATH = os.environ.get("CHESS_REEL_STOCKFISH", "")
GM_EVAL_DEPTH = 8
GM_EVAL_TIME = 0.06

# Only these players are eligible for the GM full-game replay variant.
GM_TOP_PLAYERS = [
    "Magnus Carlsen",
    "Hikaru Nakamura",
    "Fabiano Caruana",
    "Arjun Erigaisi",
    "Nodirbek Abdusattorov",
    "D Gukesh",
    "Gukesh D",
    "Alireza Firouzja",
    "Ian Nepomniachtchi",
    "Wei Yi",
    "R Praggnanandhaa",
    "Praggnanandhaa R",
    "Praggnanandhaa Rameshbabu",
    "Wesley So",
    "Leinier Dominguez Perez",
    "Leinier Dominguez",
    "Ding Liren",
    "Vincent Keymer",
    "Jan-Krzysztof Duda",
    "Anish Giri",
    "Shakhriyar Mamedyarov",
    "Maxime Vachier-Lagrave",
    "Levon Aronian",
    "Le Quang Liem",
    "Yu Yangyi",
    "Richard Rapport",
    "Viswanathan Anand",
    "Parham Maghsoodloo",
    "Nihal Sarin",
    "Alexandr Predke",
    "Alexey Sarana",
    "Vladimir Fedoseev",
    "Hans Niemann",
    "Jorden van Foreest",
]

# ── GM game sourcing (full-game replay variant) ─────────────────────────────
# The Lichess puzzle CSV only holds anonymous online games (Lichess usernames
# in the White/Black PGN headers, never FIDE names), so mining it for
# GM_TOP_PLAYERS matches never works. Real named games instead come from
# pgnmentor.com's per-player PGN archives, downloaded once into GM_SOURCE_DIR
# and cached forever — a bulk run after the first touches no network at all.
GM_SOURCE_DIR = DATA_DIR / "gm_games"
PGNMENTOR_PLAYERS_URL = "https://www.pgnmentor.com/players/"
GM_SOURCE_MIN_PLIES = 20     # skip short draws — too little game to replay
GM_SOURCE_MAX_PLIES = 60     # skip long grinds — keeps the fast replay sane

# The two lines that alternate under the countdown. A variant can override them
# with a "subtitles" key — a mate reel should not say "sacrifice available".
HOOK_SUBTITLES = ("Can you find it?", "Sacrifice available.")

COUNTDOWN_STEP = 1.0      # seconds per numeral
COUNTDOWN_QMARK = 0.6     # trailing "?" duration
COUNTDOWN_POP_SCALE = 1.4  # numeral starts this big, settles to 1.0
SUBTITLE_ALTERNATE = 0.9  # seconds between hook subtitle swaps
OUTRO_ZOOM = 1.04         # board zoom at end of outro

# Duration guard rails (Section 1). Videos outside this are rejected.
DURATION_MIN, DURATION_MAX = 12.0, 22.0

# ── Eval bar ──────────────────────────────────────────────────────────────
EVAL_BAR_W = 22
EVAL_BAR_GAP = 40         # px to the left of the board
EVAL_CLAMP = 10.0

# ── Audio ─────────────────────────────────────────────────────────────────
SAMPLE_RATE = 44100
TTS_VOICE = "en-US-GuyNeural"
TTS_RATE = "+8%"
TTS_PITCH = "-2Hz"
TTS_VOICES = [
    "en-US-GuyNeural",                 # deep, confident — default
    "en-GB-RyanNeural",                # British, commentary feel
    "en-US-AndrewMultilingualNeural",  # warm, conversational
    "en-US-BrianMultilingualNeural",   # energetic
]

# Engine order. edge-tts is neural and best, but it needs
# speech.platform.bing.com, which some ISPs block outright. Piper is offline
# neural (near edge quality, no network). Windows SAPI is the robotic
# last resort. "auto" tries them in order, so a blocked network degrades the
# voice instead of shipping silent videos.
TTS_ENGINE = "auto"           # auto | edge | piper | sapi | silence
TTS_ORDER = ["edge", "piper", "sapi"]
SAPI_VOICE = "David"          # substring match against installed voice names
SAPI_RATE = 2                 # -10..10; brisk, keeps holds inside the format
TTS_TIMEOUT = 25              # seconds per clip before giving up on an engine

# Piper — offline neural TTS (tier 2). Model files live in PIPER_DIR; download
# once with `python run_batch.py --download-voice`.
PIPER_VOICE = "en_US-lessac-medium"
PIPER_DIR = ASSETS_DIR / "piper"
PIPER_LENGTH_SCALE = 0.92     # <1 speaks faster; keeps holds inside the format
PIPER_VOICE_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
    "en/en_US/lessac/medium/{file}"
)
# 🔴 WAS 0.26, WHICH MEASURED OUT AS INAUDIBLE. At 0.26 (-11.7 dB) the bed
# sits at ~-33.7 dBFS RMS while the narration lands near -17 — a 17 dB gap
# BEFORE DUCK_DB takes another 6 off under every spoken line and
# REACTION_DUCK_DB takes 16 off under the clip. On a 13s reel that is narration
# almost end to end, so the music was ducked for nearly its whole runtime and
# the reel read as "no music". 0.45 puts the bed ~12 dB under the voice between
# lines, which is where a bed belongs, and the duck still clears speech.
# ⚠️ THEN RAISED AGAIN, 0.45 -> 0.60, because 0.45 still read as too quiet on a
# built reel. Measured: the bed now lands near -22.6 dBFS RMS against a
# voiceover at about -17, so roughly 5-6 dB under it between lines and ~11 dB
# under while DUCK_DB is applied. That is a loud bed by narration standards and
# it is deliberate — this is a social reel, not a documentary. Do not push it
# further without listening to a narrated reel end to end; past ~0.7 the music
# stops sitting under the voiceover and starts competing with it.
GAIN_MUSIC = 0.60
GAIN_SFX = 0.75
GAIN_VO = 0.95
# 🔴 -5.0, NOT -6.0. On a 13s reel the narration is close to continuous, so the
# duck is the music's normal state rather than an occasional dip — every dB here
# is a dB off the whole track, not just off a few moments of it.
DUCK_DB = -5.0
DUCK_ATTACK = 0.12        # seconds to fade music down before a VO line
DUCK_RELEASE = 0.35       # seconds to fade music back up after
MUSIC_ROOTS = [98.0, 110.0, 73.4, 82.4, 65.4]   # G2 A2 D2 E2 C2
MUSIC_BPMS = [72, 76, 80, 84]

# Drop your own tracks in `Musics/` first; the legacy assets/music folder is a
# fallback. The chosen track is hashed by puzzle id so consecutive posts do not
# reuse the same bed. Empty folders = generated music.
MUSIC_DIR = ROOT / "Musics"
MUSIC_FALLBACK_DIR = ASSETS_DIR / "music"
MUSIC_FADE = 0.6          # seconds of fade OUT on a supplied track
# 🔴 THE REEL OPENS ON THE MUSIC, so the fade in is nearly nothing. At the 0.6s
# used for the tail, the first half-second of every reel — the half-second that
# decides whether anyone keeps watching — ramps up from silence. The fade out
# stays long: that one lands under the end card, where a hard stop is audible.
MUSIC_FADE_IN = 0.12      # seconds of fade IN

# Mood pools. Without these every variant draws from ONE folder, so a tense
# countdown bed lands under a meme reel as often as not — the tracks were
# written for different jobs and the pipeline could not tell them apart.
#
# Values are filename substrings, matched case-insensitively against the stem.
# A variant opts in with "music_mood"; a mood that matches nothing falls back to
# the whole folder rather than to silence, so adding a variant before its track
# exists degrades instead of breaking.
#
# Only the BOARD reels are wired. gm_games, the carousel, the tour and the bot
# ladder keep drawing from everything on purpose — they are not part of this
# rotation and their pacing is nothing like a puzzle reel's.
# 🔴 DEFINED BUT NOT WIRED UP RIGHT NOW. The variants' "music_mood" keys are
# commented out, so every board reel draws from the whole folder and the three
# remaining tracks rotate. Pinning needs at least two or three tracks PER MOOD:
# with one track per mood, "rotation" is one reel using one bed forever, which
# is worse than no pinning at all. Uncomment the keys once the folder can feed
# them — nothing else has to change.
MUSIC_MOODS = {
    "tension": ["tension"],          # countdown reels: promo_guess, promo_mate
    "payoff":  ["payoff"],           # the sacrifice + reaction family
}
NORMALIZE_PEAK = 0.92

# Audio verification thresholds (Section 8.5).
AUDIO_PEAK_MAX = 0.95
AUDIO_RMS_MIN, AUDIO_RMS_MAX = 0.03, 0.20
AUDIO_DEAD_WINDOW = 2.0
AUDIO_DEAD_RMS = 0.005

# Voiceover placement relative to the move landing (Section 8.6).
VO_DELAY_AFTER_MOVE = 0.22
SFX_CHECK_DELAY = 0.05
VO_TAIL = 0.3             # hold must outlast its VO clip by this much

# ── Puzzles ───────────────────────────────────────────────────────────────
RATING_MIN, RATING_MAX = 1800, 3000
MIN_POPULARITY = 85
MIN_PLAYS = 500
SOLUTION_MIN, SOLUTION_MAX = 2, 5

# ── Encoding ──────────────────────────────────────────────────────────────
CRF = 21
PRESET = "medium"
AUDIO_BITRATE = "192k"
VIDEO_CODEC = "libx264"
PIX_FMT = "yuv420p"
MIN_FILESIZE = 200_000
# Upper bound is generous so a longer reaction clip (variant B) doesn't trip the
# verifier; variant A videos still land in the 12-22s target band.
ENCODE_DURATION_MIN, ENCODE_DURATION_MAX = 10.0, 45.0

# ── Captions ──────────────────────────────────────────────────────────────
# Switched from Claude to OpenAI on 2026-08-22 (user's own key/model choice).
# Uses response_format={"type": "json_schema", ...}, so the response is
# schema-valid JSON by construction — no fence-stripping or regex repair.
#
# 2026-08-26: user's top model choice. ONE model only, no fallback chain to
# gpt-4o-mini or anything else — if this model is unreachable, generate()
# degrades straight to the needs_caption placeholder (see captions.py), it
# does not try a different model. Project's "Allowed models" list in the
# OpenAI dashboard was updated the same day to include this (Settings >
# Projects > this project > Limits > Model usage — it previously allowed
# only gpt-4o-mini).
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4")
CAPTION_MAX_TOKENS = 1200
# 2026-08-26: user rejected the story-length captions + 10-hashtag drift —
# structured outputs doesn't enforce array length (minItems/maxItems aren't
# in the supported strict subset), so captions.py also hard-truncates the
# hashtags list in code; this constant is the target, not just a hint.
HASHTAG_COUNT = 5
CAPTION_WORDS_MIN, CAPTION_WORDS_MAX = 80, 150
YOUTUBE_TITLE_TARGET_MIN_CHARS, YOUTUBE_TITLE_TARGET_MAX_CHARS = 40, 65
YOUTUBE_TITLE_MAX_CHARS = 100
YOUTUBE_DESC_WORDS_MIN, YOUTUBE_DESC_WORDS_MAX = 50, 100

# ── App promo (TChess) ──────────────────────────────────────────────────────
# The reels sell the CHANNEL via the watermark below; this block sells the APP.
# Assets are copies — see assets/brand/README.txt for their sources and for the
# two files that must NOT be substituted (the opaque icon, the Arial wordmark).
BRAND_DIR = ASSETS_DIR / "brand"
BRAND_MARK = BRAND_DIR / "mark.png"           # 1024x1024 RGBA, real alpha
BRAND_FONT = BRAND_DIR / "Sora-Bold.ttf"      # Sora 700, SIL OFL — the app's own
# 🔴 THIS FILE IS NOW DRAWN DIRECTLY, and the old warning here is dead.
# It said the shipped wordmark set the rook AS the letter T ("♜Chess"), which
# reads as "a rook next to the word Chess" to a stranger — so the promo lockup
# used to spell the name out itself in Sora Bold. The designer's wordmark has a
# real T (rook + "TChess"), so that objection is gone and the delivered artwork
# is what ships. Replacing this file changes every banner and end card, so its
# aspect ratio (3.82:1) is what PROMO_BANNER_WORDMARK_H and ENDCARD_WORDMARK_H
# are measured against.
# The designer's delivered lockup: chrome rook + "TChess", 1463x384 RGBA,
# tight-cropped to its own ink. This is what the banner and the end card now
# draw — see compose._wordmark_sprite.
BRAND_WORDMARK = BRAND_DIR / "wordmark.png"
BRAND_WORDMARK_LEGACY = BRAND_WORDMARK       # kept: old name, same file
BRAND_NAME = "TChess"

# 🔴 #9D55E9, NOT #7C5CFF. The app moved its accent (see
# tchess-app/src/theme/tokens.ts): #7C5CFF sits at hue 285 in OKLCH, which reads
# as violet-BLUE on a black screen; #9D55E9 is hue 303 and reads as violet. The
# reels were still on the old value, so the banner border and the end card's
# bullets were a different colour from every button in the app they advertise.
APP_VIOLET = (157, 85, 233)      # #9D55E9 — the app's ONE accent
APP_TEXT_HI = (233, 233, 234)    # #E9E9EA — brand rule: never pure #FFFFFF
APP_SURFACE = (20, 20, 22)
APP_HAIRLINE = (46, 46, 51)      # #2E2E33

# Top banner — drawn on EVERY frame of a promo variant, in place of the theme
# label. Deliberately a lockup (wordmark over a line), not a caption.
# 🔴 THE BANNER STARTS AT SAFE_TOP, NOT AT THE TOP OF THE CANVAS.
# It used to sit at y=20, which put the whole 122px pill (20..142) inside the
# SAFE_TOP=180 band every platform paints its own UI over — so the one element
# whose entire job is to say whose app this is was the one element reliably
# cropped away. Anything moved up from here goes back under that UI.
PROMO_BANNER_Y = SAFE_TOP
PROMO_BANNER_H = 108
PROMO_BANNER_PAD = 30
PROMO_BANNER_RADIUS = 24
PROMO_BANNER_BORDER_W = 3
PROMO_BANNER_WORDMARK_H = 66
# Lockup proportions, matched to the app's shipped wordmark
# (tchess-app/assets/images/logo-wordmark.png, written by
# tchess-app/scripts/generate-brand.py) so the two cannot look like different
# brands. ⚠️ That wordmark is now the DESIGNER'S artwork rather than something
# a script composed, so these numbers are no longer copied from a generator —
# they are measured against the delivered file and have to be re-checked by eye
# if the logo is ever replaced again. Getting them wrong is what makes a lockup
# read as a logo someone pasted next to a word:
#   * the rook stands at CAP height, not the full line — a piece as tall as the
#     ascenders towers over the word and stops reading as part of it;
#   * the text is sized so its CAPS match the rook, not so its point size does.
BRAND_ROOK_CAP = 0.78      # rook height as a fraction of the lockup line
BRAND_CAP_MATCH = 0.82     # text cap height as a fraction of the rook's height
# The shipped wordmark sets a tight gap because there the rook and the word are
# one drawn lockup. Here the rook is a mark standing before a complete
# word, so it needs real separation — at 0.04 the rook and the T collide and the
# thing reads "TTChess".
BRAND_GAP_RATIO = 0.16     # fraction of the rook's height
PROMO_BANNER_GAP = 8             # px between wordmark and the line under it
PROMO_BANNER_SUB = "FREE ON GOOGLE PLAY"
PROMO_BANNER_SUB_SIZE = 26
# The reaction family's board starts at y=320, so once the banner occupies
# 180..288 there is no 100px-tall headline row left above it. Those variants
# set show_headline=False and this value is only a fallback.
PROMO_HEADLINE_Y = 300           # headline once the banner has taken the top
# The countdown variants keep the board and the countdown where they are, so
# the headline lives in the gap the banner leaves: banner ends at 288, the
# countdown ring's top edge is COUNTDOWN_CY - COUNTDOWN_RING_R = 417, and a 92px
# headline drawn from here occupies 332..400. Moving the banner down ate the
# 206 this used to sit at; raising it again puts the text back under the pill.
PROMO_HEADLINE_COUNTDOWN_Y = 300

# Per-variant tail. The reel's last beats are a STATIC board and a STATIC card,
# so at the inherited 3.0 + 4.0 a twenty-second reel spends seven seconds — a
# third of itself — showing something that does not move. Promo variants get a
# tail that lands the payoff and gets out.
PROMO_OUTRO_DURATION = 1.5

# 🔴 THE RATING REVEAL IS OFF FOR EVERY PROMO REEL, AND SO IS THE PAUSE
# THAT LED INTO IT. The tail used to be: last move lands → HOLD_FINAL (2.6s, and
# the narration is usually done well before that) → a "RATED 1856" card on a
# slow zoom → the end card. That is roughly four seconds of a twenty-second reel
# spent after the payoff, on a number nobody scrolled for. Promo variants now
# cut from the last move straight to the end card:
#
#   show_outro  False -> _render_outro is not called at all (no rating screen)
#   hold_final  the base hold on the last move, so the cut follows the
#               voiceover instead of waiting out a fixed 2.6s. plan_timeline
#               still takes max(base, floor), so narration and the reaction clip
#               can never be cut off — only the dead air above them is.
#
# gm_games keeps its outro: that screen says "WHITE WINS", not a rating, and it
# is the whole ending of a full-game replay.
PROMO_HOLD_FINAL = 0.6

# End card — a full screen after the outro. NOTE: nothing here may carry a
# puzzle count. The app says 60,000 and the website says 15,000, so printing
# either invites the contradiction; features are named, never counted.
# tests/test_promo.py asserts no digit appears in any of these strings.
# Long enough to read the features and the store row, short enough that nobody
# swipes away during it. Was 4.0; see PROMO_OUTRO_DURATION for the reasoning.
ENDCARD_DURATION = 2.6
ENDCARD_FADE = 0.3
ENDCARD_TAGLINE = "Get good at tactics."
ENDCARD_FEATURES = ["Puzzles", "Openings", "Bots",
                    "Analysis", "Endgames", "Lessons"]   # 3 rows x 2 columns
ENDCARD_PROMISE = "Free \u00b7 No ads \u00b7 Offline"
ENDCARD_PLAY = "GET IT ON GOOGLE PLAY"
# 🔴 THE DEEP LINK, NOT THE BARE DOMAIN. tchess.app lands on the marketing
# site, where the visitor still has to find the download; /android goes straight
# to the Play listing. A reel viewer types this from memory into a phone
# keyboard, so the extra eight characters buy the one step that was losing them.
ENDCARD_WEB = "tchess.app/android"

ENDCARD_WORDMARK_H = 190         # lockup height; width follows the rook + name
ENDCARD_WORDMARK_Y = 300
ENDCARD_TAGLINE_Y, ENDCARD_TAGLINE_SIZE = 560, 52
ENDCARD_RULE_X0, ENDCARD_RULE_X1 = 140, 940
ENDCARD_RULE_TOP_Y, ENDCARD_RULE_BOT_Y = 700, 1020
ENDCARD_FEAT_Y, ENDCARD_FEAT_ROW_H = 726, 96
ENDCARD_FEAT_SIZE = 46
# Bullet x for the left and right columns. Chosen so the block's own centre
# (leftmost bullet to the longest right-hand word) lands on the canvas centre —
# columns hung off a round number read as left-shifted against the rules.
ENDCARD_FEAT_COL_X = (222, 622)
ENDCARD_FEAT_TEXT_DX = 38        # text offset from its bullet
ENDCARD_BULLET_R = 7
ENDCARD_PROMISE_Y, ENDCARD_PROMISE_SIZE = 1058, 40

# The Play Store row. The point of it is RECOGNITION: a viewer who has seen the
# real icon, the real listing title and the green Install button knows they are
# in the right place the moment the store opens. A generic "download our app"
# button does not do that, so this reproduces the listing rather than paraphrasing it.
BRAND_STORE_ICON = BRAND_DIR / "store-icon.png"     # 512x512, the listing icon
ENDCARD_STORE_TITLE = ("TChess: Chess Puzzles,", "Tactics")   # exact store title
ENDCARD_STORE_DEV = "Optivio Automation"
ENDCARD_INSTALL = "Install"
PLAY_GREEN = (1, 135, 95)        # #01875F — Google Play's own button green

ENDCARD_STORE_CARD = (140, 1150, 940, 1310)   # x0, y0, x1, y1
ENDCARD_STORE_RADIUS = 26
ENDCARD_STORE_ICON_PX = 116
ENDCARD_STORE_ICON_X = 176
ENDCARD_STORE_TEXT_X = 324
ENDCARD_STORE_TITLE_SIZE, ENDCARD_STORE_TITLE_LEAD = 38, 46
ENDCARD_STORE_DEV_SIZE = 30

ENDCARD_PILL = (140, 1338, 940, 1434)    # x0, y0, x1, y1 — the Install button
ENDCARD_PILL_RADIUS = 26
ENDCARD_PLAY_SIZE = 46
ENDCARD_WEB_Y, ENDCARD_WEB_SIZE = 1470, 40

# ── App tour (variant "promo_tour") ─────────────────────────────────────────
# No chess rendering at all — this reel pans REAL DEVICE captures of the app.
# They are 1080x2340, already canvas width, so the 420px of overhang IS the pan.
#
# These are the owner's own phone captures, not the curated store set in
# store/screenshots/ (1200x2400, emulator, older UI). Real captures show the
# current build and more of it — a live bot game with a running clock, the rush
# formats, the profile chart — which is the point of a tour.
TOUR_SHOT_DIR = ROOT.parent / "tchess-app" / "store" / "TChess-Real-Screenshots" / "TChess"
TOUR_TRIM_BOTTOM = 96            # drop Android's own nav bar from the capture
TOUR_SHOT_DURATION = 2.6         # floor; the shot's own voiceover usually wins
TOUR_SHOT_MAX_HOLD = 4.5         # past this the build warns: the line is too long
TOUR_CROSSFADE = 0.35

# Opening beat. Puzzles are the reason anyone installs a tactics app, so the
# tour leads with them and the shot order follows — the puzzles hub is shot one,
# not the home screen.
# "Unlimited" is the honest way to say "a lot" here: the free tier genuinely has
# no puzzle cap (DAILY_XP_CAP went to Infinity, there is no favourites limit),
# and it sidesteps the 60,000-vs-15,000 contradiction that bans a count.
TOUR_HOOK_DURATION = 2.0
TOUR_HOOK_TEXT = "Unlimited free puzzles"
TOUR_HOOK_SUB = "and a whole lot more"
TOUR_HOOK_SIZE, TOUR_HOOK_SUB_SIZE = 76, 44
# Narrates the headline only. The sub-line is already on screen, and reading it
# out pushed the opening beat to 3.9s — an opening that drags is the one place
# a reel cannot afford it.
TOUR_HOOK_VO = "Unlimited free puzzles"
TOUR_CAPTION_SIZE = 54
TOUR_CAPTION_H = 150             # bottom scrim height
TOUR_CAPTION_FROM_BOTTOM = 430   # scrim top, clear of SAFE_BOTTOM's caption UI
TOUR_TOP_SCRIM_PAD = 22          # dim strip extends this far past the banner
# Near-opaque on purpose: the scrims sit over the app's OWN chrome (its header,
# its buttons), so a light dim leaves two competing interfaces on screen.
TOUR_SCRIM_ALPHA = 238

# (screenshot file, on-screen caption, voiceover line). Captions are one line
# and countless, per the copy rules above.
#
# Keep every voiceover line under about two and a half seconds. tour._plan_shots
# floors each shot's hold at its own clip length, so a long line does not get
# cut off — it stretches the reel instead, and eight stretched shots is half a
# minute of narration nobody watches. Short is also better promo copy.
#
# 🔴 A FULL STOP INSIDE A LINE COSTS ABOUT HALF A SECOND. The TTS engines read
# it as a sentence break and pause there. "One position. One move." measured
# 3.41s for four words, while the comma form runs well under two — so word
# count is NOT what to tune here. Use commas, and no trailing period: the clip
# ends by itself.
# (screenshot, LABEL, callout, voiceover). The label is ONE WORD: it has to be
# readable before the viewer has focused on the phone, which a two-word label
# cannot do at this size.
# ⚠️ The callout now sits in the MARGIN beside the phone, not over it, so it has
# roughly 320px to live in — keep these to two or three short words or the pill
# runs off the frame.
TOUR_SHOTS = [
    ("Screenshot_20260808_205735_TChess.jpg", "Puzzles",  "Your level",     "Rush, sessions, endgames"),
    ("Screenshot_20260808_205739_TChess.jpg", "Motifs",   "All tracked",    "Forks, pins, skewers, all tracked"),
    ("Screenshot_20260808_205747_TChess.jpg", "Watch",    "It self-solves", "A feed that plays the solution"),
    ("Screenshot_20260808_205522_TChess.jpg", "Today",    "One screen",     "Everything in one place"),
    ("Screenshot_20260808_205603_TChess.jpg", "Bots",     "Eight of them",  "Eight bots, one ladder"),
    ("Screenshot_20260808_205637_TChess.jpg", "Play",     "Real clock",     "With a real clock, fully offline"),
    ("Screenshot_20260808_205754_TChess.jpg", "Learn",    "Ideas first",    "Lessons that teach the pattern"),
    ("Screenshot_20260808_205804_TChess.jpg", "Progress", "Rating, streak", "Your rating, your streak, your gaps"),
]

# ── Product mockups (src/mockup.py, used by the tour) ───────────────────────
# A phone, a one-word label and a floating callout — the shape every serious
# app's store strip uses, because a full-bleed screenshot reads as
# documentation rather than as a product.
# 🔴 NO BANNER AND NO HANDLE ON A MOCKUP. The 108px label is already this
# format's header, so a second one stacked above it is two headers arguing, and
# a burnt-in handle is a third brand mark on a frame whose end card carries the
# wordmark. Every other format keeps both; this one earned its way out.
# The banner goes at the BOTTOM. At the top it fought the 108px label — two
# headers stacked — and removing it altogether left the frame unbranded. Under
# the phone it is a footer, which is the one place a lockup does not compete.
MOCKUP_CHROME = True
MOCKUP_BANNER_BOTTOM = 1742       # banner's top edge

# 🔴 The callout is OFF. Squeezing the phone down to 560 to make room for a pill
# beside it made the product — the thing the shot is OF — the smallest it has
# ever been, to fit an annotation. Wrong trade: the phone is the subject. The
# pill can come back UNDER the label if a shot ever needs one, never over the
# glass and never by shrinking the handset.
MOCKUP_CALLOUT = False
MOCKUP_PHONE_W = 630
MOCKUP_PHONE_Y = 356
MOCKUP_PHONE_DX = 0               # centred; nothing shares its row any more
MOCKUP_BEZEL = 13
MOCKUP_RADIUS = 44
MOCKUP_BODY = (26, 26, 30)
MOCKUP_EDGE = (68, 68, 78)

MOCKUP_LABEL_Y, MOCKUP_LABEL_SIZE = 190, 108
MOCKUP_RULE_W, MOCKUP_RULE_H, MOCKUP_RULE_GAP = 128, 9, 28

# Ground. Flat black plus one bloom is "dark"; a gradient, a low accent bloom
# and a real vignette is composed. The vignette does the most work — it puts
# the phone in a room instead of on a colour.
MOCKUP_GRAD_TOP = (23, 23, 28)
MOCKUP_GRAD_BOTTOM = (6, 6, 8)
MOCKUP_VIGNETTE = 132             # 0-255 darkening at the corners
MOCKUP_GLOW_PX, MOCKUP_GLOW_Y, MOCKUP_GLOW_ALPHA = 1340, 500, 104

MOCKUP_CALLOUT_SIZE = 30
MOCKUP_CALLOUT_PAD = (26, 18)     # x, y padding inside the pill
MOCKUP_CALLOUT_DOT = 9
MOCKUP_CALLOUT_GAP = 14
MOCKUP_CALLOUT_BG = (240, 241, 236)
MOCKUP_CALLOUT_INK = (18, 18, 22)
MOCKUP_CALLOUT_AT = 0.34          # height fraction of the phone it sits at
MOCKUP_CALLOUT_EDGE = 26          # px from the canvas edge

# Staged entrance, in seconds. Three things arriving at once is a flash; three
# arriving in order is something the eye can follow.
MOCKUP_LABEL_IN = 0.36
MOCKUP_PHONE_DELAY, MOCKUP_PHONE_IN = 0.14, 0.46
MOCKUP_CALLOUT_DELAY, MOCKUP_CALLOUT_IN = 0.62, 0.34
MOCKUP_CALLOUT_OVERSHOOT = 2.6
MOCKUP_DRIFT, MOCKUP_DRIFT_OVER = 16, 3.0   # px, over seconds — never fully still

# ── Bot ladder (variant "promo_bots") ───────────────────────────────────────
# The roster and the portraits are read out of the APP at build time, so this
# reel cannot advertise bots it does not ship. ⚠️ Portraits come from the TS
# map, NOT from assets/bots/*.svg — those filenames do not all match the
# characters (there is an ayan.svg and no bot called Ayan).
BOTS_DEFS = ROOT.parent / "tchess-app" / "src" / "constants" / "bots.ts"
BOTS_PORTRAITS = ROOT.parent / "tchess-app" / "src" / "constants" / "botPortraits.ts"
BOTS_COUNT = 8                   # the ladder; Atlas is the engine, not a rung

BOTS_HOOK_DURATION = 2.0
BOTS_HOOK_TEXT = "Eight bots, one ladder"
BOTS_HOOK_SUB = "each one plays differently"
BOTS_HOOK_SIZE, BOTS_HOOK_SUB_SIZE = 76, 44
BOTS_HOOK_VO = "Eight bots, one ladder"

BOTS_CARD_DURATION = 2.2
BOTS_PORTRAIT_PX, BOTS_PORTRAIT_Y = 520, 300
BOTS_PORTRAIT_RADIUS = 0.16      # fraction of the portrait's side
BOTS_NAME_Y, BOTS_NAME_SIZE = 900, 88
BOTS_ELO_Y, BOTS_ELO_SIZE = 1030, 56
BOTS_ELO_PAD = (34, 16)          # x, y padding inside the rating pill
BOTS_TAGLINE_Y, BOTS_TAGLINE_SIZE = 1160, 46
BOTS_RUNG = (96, 14, 12)         # width, gap, height of one ladder rung
BOTS_RUNG_Y = 1320

# ── Carousel (still images, not video) ──────────────────────────────────────
# Instagram/Facebook carousels. 4:5 is the tallest ratio either platform will
# show uncropped in the feed, so it is the most screen a still post can occupy.
# Cheapest promo there is per hour of work: no encode, no audio, no TTS, and a
# set can be posted in one go.
CAROUSEL_W, CAROUSEL_H = 1080, 1350
CAROUSEL_SLIDES = 5              # puzzle slides between the cover and the CTA
CAROUSEL_BOARD_PX = 880
CAROUSEL_BOARD_Y = 322

CAROUSEL_KICKER_Y, CAROUSEL_KICKER_SIZE = 182, 38
CAROUSEL_HEADLINE_Y, CAROUSEL_HEADLINE_SIZE = 236, 66
CAROUSEL_FOOTER_Y, CAROUSEL_FOOTER_SIZE = 1246, 34

CAROUSEL_COVER_TITLE = ("Can you find", "all five?")
CAROUSEL_COVER_SIZE = 92
CAROUSEL_COVER_SUB = "Swipe →"
CAROUSEL_COVER_SUB_SIZE = 46
CAROUSEL_COVER_MARK_H = 260
# How much of the end card sits above its wordmark on the CTA slide. Small
# enough that the card's last line (tchess.app/android) clears the watermark row —
# _cta() raises rather than printing one over the other.
CAROUSEL_CTA_HEADROOM = 34

# The board slides say WHOSE move it is and name the motif; the answers live in
# the caption, which is what makes people comment.
CAROUSEL_PROMPT = {True: "White to play", False: "Black to play"}

# ── Watermark ───────────────────────────────────────────────────────────────
# Small channel handle burned into every frame of every video (both variants).
# The app's handle, not a personal one — everything here is TChess branding now.
# It is NOT redundant with the top banner: the banner is a store call to action
# ("install this"), the handle is a follow ("this account posts these"), and a
# clip that gets reposted keeps only the burnt-in one.
# ⚠️ This handle has to actually be claimed on Instagram / YouTube / Facebook,
# or every reel points at nothing. Nothing in this repo can check that.
# 🔴 A LINK, NOT A HANDLE, AND THE HANDLE IS NOT COMING BACK. This used to
# read "@tchessapp", which was wrong twice: the reels publish under TWO brands
# (tahachesstv and tchessapp — see ACCOUNTS), so half of them carried the other
# account's name; and a handle asks the viewer to search, while the whole reel
# exists to get an install. The URL is brand-neutral and is the same string the
# end card closes on, so the reel says it twice and spells it the same way.
WATERMARK_TEXT = "tchess.app/android"    # set "" to disable
WATERMARK_SIZE = 34
WATERMARK_ALPHA = 165            # 0-255; semi-transparent so it reads as a bug
# 🔴 MEASURED FROM THE SAFE LINE, NOT FROM THE CANVAS EDGE. At 46px above
# the bottom the handle landed at y~1834, which is 234px INSIDE SAFE_BOTTOM —
# under the caption and the like/share column on every platform. It has been
# invisible in the feed this whole time, which matters more now that it is a
# download link rather than a handle.
WATERMARK_MARGIN = 16            # px above the SAFE_BOTTOM line

# ── Facebook posting via the browser, not the Graph API ─────────────────────
# 🔴 FACEBOOK IS THE ONE PLATFORM HERE THAT IS NOT AN API CALL, and that is a
# finding, not a preference: the Graph API's Video Reels flow never returned a
# usable result for these Pages, which is why FACEBOOK_ENABLED sat at 0. The
# reel composer in Meta Business Suite does work, so Facebook is driven through
# it with Playwright against a real, already-signed-in Chrome profile.
#
# Instagram and YouTube deliberately DID NOT move. They have working APIs that
# return a post id, and that id is what per-post insights and the pinned promo
# comment are both keyed off — a browser crosspost yields neither. Facebook
# gets the browser because it has no alternative; nothing else does.
BROWSER_PUBLISHER_DIR = ROOT / "browser"
BROWSER_PUBLISHER_SCRIPT = BROWSER_PUBLISHER_DIR / "post_reel.js"
# 🔴 NOTHING THIS PIPELINE SPAWNS MAY PUT A WINDOW ON THE OWNER'S SCREEN.
# node.exe and python.exe are CONSOLE applications, so on Windows every spawn
# opens a console unless this flag is passed — and this pipeline spawns node
# for every Facebook and Instagram post, six times a day, at hours chosen
# because the owner is asleep or busy. A console stealing focus mid-game is the
# one way an unattended system makes itself somebody's problem.
#
# It only affects the WINDOW. Every call site already passes capture_output=True,
# so stdout and stderr are still read exactly as before.
SUBPROCESS_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

BROWSER_NODE = os.environ.get("BROWSER_NODE", "node")

# The Chrome user-data directory already signed in to Facebook. There is no
# login code and no password anywhere in this project — the session is reused.
# Only one process may hold a profile at a time, so a run fails with a plain
# message if that Chrome window is open.
BROWSER_PROFILE_DIR = os.environ.get("CHROME_PROFILE_DIR", "")

BROWSER_HEADLESS = os.environ.get("BROWSER_HEADLESS", "1").strip().lower() not in ("0", "false", "no")

# 🔴 CHESSREEL MUST NEVER LAUNCH CHROME ON THIS DIRECTORY. It is the profile
# the Jarvis desktop app posts its own two Pages from (D:\Jarvis,
# src/content/ContentPipeline.ts), on its own 04:30/18:00/22:00 PKT schedule.
# Chrome allows exactly one process per profile, so if both projects pointed
# here they would silently break each other: whichever ran second would fail,
# and a Jarvis post lost that way looks like a Jarvis bug from inside Jarvis.
# ChessReel therefore runs on its own COPY of the profile, and this constant
# exists so pointing it back is refused rather than merely discouraged.
JARVIS_PROFILE_DIR = os.environ.get("JARVIS_PROFILE_DIR", "")

# 🔴 DEFAULTS TO DRY RUN, like the library it drives. A browser publish is
# public and cannot be undone, and unlike an API call there is no request to
# inspect first — so live posting has to be switched on deliberately.
BROWSER_DRY_RUN = os.environ.get("BROWSER_DRY_RUN", "1").strip().lower() not in ("0", "false", "no")

BROWSER_TIMEOUT_SECONDS = 420      # a reel upload plus Meta's processing
BROWSER_SHOT_DIR = DATA_DIR / "fb_shots"

# After the browser posts, the reel's id is recovered from the Page's
# video_reels edge so the promo comment and insights still work. Reels take a
# little while to appear, hence the poll.
FB_ID_RECOVERY_ATTEMPTS = 10
FB_ID_RECOVERY_INTERVAL = 6        # seconds between attempts

# Recorded when a post demonstrably succeeded but its id could not be read
# back. 🔴 THE ALTERNATIVE — raising — WOULD BE WORSE: the entry would stay
# pending and the next run would post the same reel to the same Page again.
# A sentinel keeps the ledger honest ("this went out") while telling analytics
# there is nothing to fetch.
FB_UNRESOLVED_PREFIX = "unresolved:"

# ── Accounts (which brand a reel is published as) ───────────────────────────
# Two brands publish from this one pipeline, and THEY NEVER SHARE A REEL.
# Every ledger entry is stamped with exactly one account the first time it is
# picked up (see src/queue.py:assign_account), and from then on only that
# account can ever post it — that stamp, not a comparison of captions or
# files, is what guarantees a viewer following both accounts never sees the
# same reel twice.
#
# Everything else is deliberately shared: the caption engine, the hashtags,
# the YouTube title/description shape, the pinned first comment, the burnt-in
# @tchessapp watermark. Only the destination credentials and the clock
# differ.
#
# ⚠️ `platforms` here is the account's CEILING, not the final answer —
# src/queue.py:active_platforms(account) still filters it through
# FACEBOOK_ENABLED / TIKTOK_ENABLED. tchessapp has no Facebook Page at all,
# so "fb" is absent rather than disabled: an account can only lose platforms
# to those flags, never gain one.
#
# `env` maps a logical credential to the environment variable that holds it.
# tahachesstv's names are the ORIGINAL, unprefixed ones on purpose — the
# account layer must be a no-op for the channel that has been publishing
# since day one, so nothing in .env had to be renamed to add the second one.
DEFAULT_ACCOUNT = "tahachesstv"

ACCOUNTS = {
    "tahachesstv": {
        "label": "Taha Chess TV",
        # Exactly as each platform reports them — these are compared against
        # live API responses in scripts/verify_accounts.py, so a "close
        # enough" label here shows up as a spurious warning on a healthy
        # account. The YouTube channel is "Taha Chess", not "Taha Chess TV".
        "handles": {"ig": "@tahachesstv", "yt": "Taha Chess", "fb": "Taha Chess"},
        "platforms": ("fb", "ig", "yt"),
        # Three fixed daily slots (Pakistan time, the machine's local zone)
        # chosen for timezone coverage across chess' biggest audiences: 3pm
        # hits India/Australia evening, 11pm hits UK/Europe evening, 5am hits
        # US/Canada evening.
        "publish_times_pkt": ["15:00", "23:00", "05:00"],
        "env": {
            "fb_page_id": "FB_PAGE_ID",
            "fb_token": "FB_PAGE_TOKEN",
            "ig_user_id": "IG_USER_ID",
            "yt_token_path": "YT_TOKEN_PATH",
            # Optional. When set, publisher._assert_expected_channel refuses
            # to upload if the token turns out to be bound elsewhere. Left
            # unset for this brand by default — it has been uploading to the
            # right channel since day one, and making a brand-new required
            # variable the condition of that continuing would break the
            # working account in order to add the second one.
            "yt_channel_id": "YT_CHANNEL_ID",
        },
    },
    "tchessapp": {
        "label": "TChess App",
        # Exactly as each platform reports them — checked against live API
        # responses in scripts/verify_accounts.py. The YouTube channel is
        # named "TChess" (confirmed 2026-09-02 from the minted token), not
        # "TChess App"; the brand's display label is separate, above.
        "handles": {"ig": "@tchessapp", "yt": "TChess", "fb": "TChess", "tt": "@wwwtchessapp"},
        # Gained a Facebook Page on 2026-09-02 (TChess, id in FB_PAGE_ID_TCHESSAPP) — the
        # same link that finally made Instagram reachable through the Graph API.
        # "tt" added 2026-09-29: TikTok @wwwtchessapp, browser-published, and
        # still gated by TIKTOK_ENABLED (src/queue.active_platforms).
        "platforms": ("fb", "ig", "yt", "tt"),
        # 🔴 DELIBERATELY TWO HOURS AFTER EACH tahachesstv SLOT, NOT AT THE
        # SAME TIME AND NOT AT LEFTOVER HOURS. Picked from this project's own
        # posted-reel data (33 posts, 2026-08-22 → 09-01), not from a
        # generic "best time to post" table:
        #
        #   slot    n   IG views (median)   YT views (median)
        #   05:00   9        1510                1150
        #   15:00  10        1402                1136
        #   23:00   9        1617                1134
        #
        # No existing slot is weak — the three are within ~15% of each other,
        # so there is no bad hour to hand the new brand. The three accidental
        # off-slot posts are the useful signal, because they are the only
        # evidence about hours nobody scheduled on purpose, and all three beat
        # the median: 06:05 → 1947 IG (the single best IG number in the whole
        # dataset), 03:38 → 1916, 16:51 → 1743.
        #
        # So each tchessapp slot sits +2h from its tahachesstv counterpart:
        # same audience window (India/AU evening, UK/EU evening, US evening),
        # far enough apart that the two brands never post together, and two of
        # the three (07:00, 17:00) are the neighbourhoods those over-performing
        # off-slot posts actually landed in. Interleaved, the day reads
        # 05:00 TV · 07:00 app · 15:00 TV · 17:00 app · 23:00 TV · 01:00 app.
        "publish_times_pkt": ["17:00", "01:00", "07:00"],
        "env": {
            # Same Meta app + same "ChessReel Publisher" System User token as
            # tahachesstv — @tchessapp lives in the same Taha Pages Business
            # portfolio, so one token covers both once the IG asset is
            # assigned to that System User. The override exists only so a
            # separate token can be dropped in without a code change.
            "fb_page_id": "FB_PAGE_ID_TCHESSAPP",
            "fb_token": "FB_PAGE_TOKEN_TCHESSAPP",
            "ig_user_id": "IG_USER_ID_TCHESSAPP",
            # 🔴 A SEPARATE TOKEN FILE IS NOT OPTIONAL. Both channels live in
            # one Google account, but a YouTube OAuth credential is bound to
            # the single channel chosen in the consent screen's channel
            # picker — videos.insert has no "which channel" parameter. Reusing
            # YT_TOKEN_PATH here would silently upload the app's reels to Taha
            # Chess TV. scripts/yt_auth_account.py mints this one and prints
            # the channel it bound to so the choice can be verified.
            "yt_token_path": "YT_TOKEN_PATH_TCHESSAPP",
            # 🔴 SET THIS ONE. It is the only mechanical check that the right
            # channel was chosen in the consent picker, and choosing wrong is
            # the single failure here that is silent and public rather than
            # loud and local. scripts/yt_auth_account.py prints the value to
            # paste in.
            "yt_channel_id": "YT_CHANNEL_ID_TCHESSAPP",
        },
    },
}

# 🔴 OFF BY DEFAULT, AND THAT IS THE SAFETY FEATURE — the same reasoning as
# TIKTOK_ENABLED below. A new publishing target must never go live just
# because code shipped: @tchessapp needs its Instagram asset assigned to the
# System User in Business Manager and its own YouTube token minted first, and
# until both are done every attempted post is a guaranteed error on a real
# account. scripts/verify_accounts.py proves both, then this flips to 1.
#
# Turning it on does NOT release a backlog the way TikTok would: an entry is
# stamped for exactly one account, so tchessapp starts from unassigned
# content and tahachesstv's queue is untouched.
ACCOUNT_ENABLED = {
    "tahachesstv": True,   # publishing since day one; never gated
    "tchessapp": os.environ.get("TCHESSAPP_ENABLED", "").strip().lower() in ("1", "true", "yes"),
}

# How close to a configured slot a run has to be for that slot's account to be
# inferred from the clock. Only a fallback: the scheduled tasks pass
# `--account` explicitly, which always wins. Half the 2h brand offset, so the
# two accounts' windows can never overlap and claim each other's run.
ACCOUNT_SLOT_TOLERANCE_MIN = 60

# ── Publishing (Facebook / Instagram / YouTube autopilot) ───────────────────
# Secrets (tokens, IDs) live in .env / real environment variables, never here —
# see .env.example. Only non-secret tunables belong in this file.
PUBLISH_LOCK = DATA_DIR / "publish.lock"
PUBLISH_LOG = DATA_DIR / "publish.log"
PUBLISH_LOCK_MAX_AGE_HOURS = 2     # a lock older than this is a dead prior run

# The ledger's `pending` list is every build ever recorded, going back to
# early dev/test runs — not a clean "ready to post" queue. Autopilot must
# never touch that historical backlog on its own (confirmed with the user
# 2026-08-21): only entries built AFTER this cutoff are auto-published.
# Written once, on the first real publish.py run, as "now". Older items stay
# in `pending` forever unless posted manually via `publish.py --once <id>`.
#
# EXCEPTION (2026-08-22): output/promo/** is the user's own curated backlog,
# not dev/test debris — it's exempt from the cutoff so autopilot works
# through it. Everything else (reaction/, gm_games/, app/, root builds) stays
# cutoff-gated.
PUBLISH_CUTOFF_MARKER = DATA_DIR / "publish_since.txt"
PUBLISH_CUTOFF_EXEMPT_DIR = OUTPUT_DIR / "promo"

# Per-account slots now live in ACCOUNTS[...]["publish_times_pkt"] — the two
# brands post at different hours by design. This stays as the union of both,
# because it is what "when does this machine wake up at all" means, and
# several readers (status.json's next_run_pkt, the dashboard's countdown)
# ask exactly that question. Six triggers/day * PUBLISH_PER_RUN_CAP each =
# six reels/day, three per brand, not a plan.json-driven cadence.
PUBLISH_TIMES_PKT = sorted({
    t for name, acct in ACCOUNTS.items()
    if ACCOUNT_ENABLED.get(name) for t in acct["publish_times_pkt"]
})
PUBLISH_PER_RUN_CAP = 1

# ── Content runway (how many publishable reels are left) ───────────────────
# ⚠️ THIS IS A BUFFER GAUGE NOW, NOT A COUNTDOWN TO A STOP. It used to say
# "the engine does not refill this by itself, on purpose" — the rule then was
# that an empty backlog should halt the autopilot so an un-reviewed generator
# could not post to two live accounts. The three board formats have since been
# reviewed and signed off (src/autogen.AUTO_VARIANTS), and publish.py builds a
# reel at post time when its queue is empty. So hitting zero is no longer an
# outage; it just means every slot builds its own reel instead of drawing one.
#
# These watermarks still earn their place: a queue that sits at zero is a queue
# where every post waits on a build, so a slow build or a failed OpenAI call
# becomes a missed slot rather than a delayed one. Amber here means "top it up
# with the dashboard's Generate Reel button", not "the accounts are about to go
# quiet".
#
# Measured in reels, not days, because the two accounts drain the same
# unassigned pool: six a day between them, so 12 left is two days' warning.
CONTENT_LOW_WATERMARK = 12         # amber on the dashboard at or below this
CONTENT_CRITICAL_WATERMARK = 6     # red — one day or less

# The daily burn rate is NOT a constant here: publish.py:content_runway()
# derives it from the enabled accounts' own slot lists, so pausing a brand or
# retiming it moves the "days left" estimate with it instead of leaving the
# dashboard quoting a cadence nobody runs any more.

# Remembers the last content level announced, so a warning fires on the run
# that crosses into a level rather than on all six runs a day afterwards.
CONTENT_LEVEL_MARKER = DATA_DIR / "content_level.txt"

# When the last eligible reel has been published, pause the autopilot and
# stamp control.json with why. Nothing is lost by this — an unpaused
# autopilot with an empty queue just logs "nothing to publish" three times a
# day — but a *paused* one shows up on the dashboard as a deliberate stop
# with a reason, which is the signal the owner actually asked for. Resuming
# from the dashboard clears it; if the queue is still empty the next run
# simply pauses again.
# 🔴 GENERATE ON DEMAND — the queue is a buffer now, not the source.
# Until 2026-09-08 publish.py drew from a pile somebody built by hand, and when
# the pile ran out it stopped and posted nothing for a day and a half. It now
# builds a reel at post time when nothing is waiting. See src/autogen.py.
AUTOGEN_ENABLED = os.environ.get("AUTOGEN_ENABLED", "1").strip().lower() not in ("0", "false", "no")

# A build is ~20-60s of work plus a one-off ~1GB CSV load, and it runs inside a
# scheduled publish slot. Generous, because a timeout here means the slot posts
# nothing; the cap exists to stop a wedged ffmpeg holding the run open forever.
AUTOGEN_TIMEOUT = float(os.environ.get("AUTOGEN_TIMEOUT", "900"))

# Retries walk FORWARD through the rotation, so each attempt asks for a
# different motif and rating band. Three is enough to get past a combination
# the corpus is thin on without turning one bad slot into a build storm.
AUTOGEN_MAX_ATTEMPTS = 3

# ⚠️ STILL TRUE, BUT IT IS NOW THE LAST RESORT RATHER THAN THE FIRST
# RESPONSE. Pausing happens only after AUTOGEN_MAX_ATTEMPTS builds have failed —
# at that point the queue really is empty AND the generator cannot refill it,
# which is a genuine "come and look at this", not a routine run-out.
CONTENT_EXHAUSTED_AUTOPAUSE = True

# Neither Facebook's nor Instagram's Graph API exposes a real "pin comment"
# endpoint (only is_hidden exists on the Comment object) — this is posted as
# the first comment right after publishing, which is the closest automatable
# proxy for a pin. IG doesn't render links as clickable, hence the "link in
# bio" wording there instead of the raw URLs FB gets.
PROMO_COMMENT_FB = (
    "♟️ Get TChess — free unlimited puzzles, no ads & offline.\n\n"
    "\U0001f4f1 Android: https://tchess.app/android\n"
    "\U0001f310 Web: https://tchess.app/android"
)
PROMO_COMMENT_IG = (
    "♟️ Get TChess — free unlimited puzzles, no ads & offline.\n"
    "\U0001f517 Link in bio."
)
PROMO_COMMENT_YT = PROMO_COMMENT_FB  # YouTube renders links too, same text as FB

FB_GRAPH_API_VERSION = os.environ.get("FB_GRAPH_API_VERSION", "v26.0")

# GitHub Contents API doubles as a free, instant public host for the one file
# Instagram's Content Publishing API insists on fetching itself (video_url) —
# no Supabase/Cloudflare, and no wait for a Vercel deploy.
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")          # "user/chessreel-cdn"
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

IG_CONTAINER_POLL_SECONDS = 5
IG_CONTAINER_POLL_TIMEOUT = 90     # IG fetching from GitHub is usually <10s

YT_CATEGORY_ID = "20"              # Gaming — closest fit for chess puzzles

# Private GitHub repo used purely as an async status/control bridge between
# this laptop (which can't accept inbound connections) and the Vercel-hosted
# dashboard: local writes status.json/history.json, reads control.json for
# pause/retry/run-now commands issued from the dashboard.
# ── Facebook ──────────────────────────────────────────────────────────────
# 🔴 DEFAULTS TO ON, unlike TIKTOK_ENABLED, and the asymmetry is deliberate.
# Facebook has been publishing since day one, so an unset or misspelled
# variable must not silently stop it — only an explicit "0"/"false"/"no" does.
# TikTok defaults the other way because it has never published and turning it
# on releases a backlog.
#
# ⚠️ THIS STOPS POSTING ONLY. The page token, the Graph client and
# `analytics.fetch_facebook()` are untouched, so insights for everything
# already on the page keep updating — `analytics` reads the post ids recorded
# in the ledger and never consults this flag.
FACEBOOK_ENABLED = os.environ.get("FACEBOOK_ENABLED", "1").strip().lower() not in ("0", "false", "no")

# ── TikTok ────────────────────────────────────────────────────────────────
# Browser-published since 2026-09-29 (src/tiktok_browser.py → browser/
# post_tiktok.js), from Chrome profile Gmail_40, where @wwwtchessapp is signed
# in. The Content Posting API path (src/tiktok.py) is ABANDONED: the app was
# rejected at review. Only the tchessapp brand has "tt" in its platform
# ceiling, so Taha Chess TV never posts to TikTok.
#
# 🔴 OFF BY DEFAULT. `due_platforms()` asks this flag whether "tt" is a
# platform at all. Only entries still `pending` are affected, since posted
# entries are never revisited. On 2026-09-29 tchessapp had none: autogen
# builds each slot's reel on demand. So switching it on adds TikTok to NEW
# reels only.
TIKTOK_ENABLED = os.environ.get("TIKTOK_ENABLED", "").strip().lower() in ("1", "true", "yes")
TIKTOK_PROFILE_DIR = os.environ.get("TIKTOK_PROFILE_DIR", "")
TIKTOK_PUBLISHER_SCRIPT = BROWSER_PUBLISHER_DIR / "post_tiktok.js"
# Walks the whole upload but stops before Post. Default ON, like the Facebook
# composer's BROWSER_DRY_RUN: a missing .env line must never become a live post.
TIKTOK_DRY_RUN = os.environ.get("TIKTOK_DRY_RUN", "1").strip().lower() not in ("0", "false", "no")
TIKTOK_TIMEOUT_SECONDS = 600       # upload + processing + reading the post back
TIKTOK_CAPTION_MAX = 2200          # conservative; the web uploader counts to 4000
TIKTOK_SHOT_DIR = DATA_DIR / "tt_shots"
# The promo, in the owner's wording (2026-09-29). Same text as Instagram's.
# ⚠️ On 2026-09-29 the TikTok profile had NO clickable bio link: Edit profile
# offers no Website field until the account has 1,000 followers or is
# switched to a Business account. Until then "link in bio" points at the bio
# text ("👇 Get TChess").
TIKTOK_CAPTION_PROMO = "♟️ Get TChess — free unlimited puzzles, no ads & offline. 🔗 Link in bio."
PROMO_COMMENT_TT = TIKTOK_CAPTION_PROMO
TT_UNRESOLVED_PREFIX = "tt-unresolved:"   # posted, URL not read back: never re-post
TT_FAILED_PREFIX = "tt-failed:"           # failed: this reel skips TikTok, FB/IG/YT unaffected

# ── Giving up on one platform for one reel ─────────────────────────────────
# 🔴 A platform that keeps failing used to hold the WHOLE queue. From
# 2026-10-16 to 10-20 Facebook's composer was logged out; the oldest reel still
# owed "fb", every slot retried only that, and IG / YouTube / TikTok published
# nothing new for four days on both brands. After this many failed attempts the
# reel is marked skipped on that platform and the entry completes. TikTok keeps
# its own stricter rule (skip on the first failure, TT_FAILED_PREFIX).
PLATFORM_MAX_FAILURES = int(os.environ.get("PLATFORM_MAX_FAILURES", "3"))
PUBLISH_SKIPPED_PREFIX = "skipped:"       # gave up on this platform for this reel
# Values in an entry's "platforms" that complete it without being a post.
NOT_A_POST_PREFIXES = (TT_FAILED_PREFIX, PUBLISH_SKIPPED_PREFIX)

GITHUB_STATUS_REPO = os.environ.get("GITHUB_STATUS_REPO", "")
GITHUB_STATUS_BRANCH = os.environ.get("GITHUB_STATUS_BRANCH", "main")
STATUS_HISTORY_MAX = 500           # trim history.json to the most recent N events

# Per-post FB/IG/YouTube analytics (added 2026-08-22). watcher.py's 5-minute
# tick refreshes at most ANALYTICS_MAX_PER_TICK entries per run, and only
# ones whose last fetch is older than the cooldown — a full refresh of every
# recent post on every tick would burn through Meta's rate limits for no
# reason, since insights barely move minute to minute.
# 🔴 ALL TIME, NOT A WINDOW. This was 7, and 7 days is how long a post had
# to get its numbers read before it aged out forever. Measured 2026-09-09: of 63
# posted reels only 31 had any analytics at all — the other 32 were 7-17 days
# old and had simply fallen out of the window, so the dashboard's "total views
# across all platforms" was the sum of about half the account's work and kept
# drifting further from the truth as the back catalogue grew.
#
# Nothing else has to change to make this safe: the cooldown below still stops
# any one entry being re-read more than hourly, and MAX_PER_TICK still caps the
# calls per watcher tick, so a backfill of the whole history happens gradually
# over a few ticks instead of in one burst.
ANALYTICS_LOOKBACK_DAYS = 3650     # ~10 years, i.e. every post ever
ANALYTICS_REFRESH_COOLDOWN_MIN = 60
ANALYTICS_MAX_PER_TICK = 5

# ── Features ──────────────────────────────────────────────────────────────
SHOW_EVAL_BAR = False     # off by request — the bar read as clutter
SHOW_COUNTDOWN = True
SHOW_RATING_REVEAL = True
SHOW_REACTIONS = False    # old cartoon-face overlay — permanently off (Section 0)

# ── Variants ────────────────────────────────────────────────────────────────
# Output formats. "simple" (variant A) is the original, unchanged. "reaction"
# (variant B) uses a smaller board higher on the canvas, leaving a bottom band
# for a reaction video clip, and opens by telling the viewer to watch rather
# than solve. The reaction *clip* here is real footage — not the banned cartoon
# overlay above. "app" (CHESS_APP_BLUEPRINT.md §13.1) is the in-app deliverable:
# same board render, no watermark, no CTA end card, no countdown/hook overlay —
# just the move labels, full-bleed and centred. Layout, hook and per-variant
# encode settings live here so the render code stays branch-light.
DEFAULT_VARIANT = "simple"

WATCH_DURATION = 1.6      # variant B static opening, seconds (< 2s, no ticks)
APP_HOOK_DURATION = 1.0   # variant "app" opening: brief silent hold, no text
APP_BOARD_PX = 1000       # larger than BOARD_PX (960) — full-bleed for the app

# Variant B bottom band (full width) reserved for the reaction clip.
REACTION_BAND = (0, 1360, CANVAS_W, CANVAS_H)   # x0, y0, x1, y1

# Per-variant encode overrides (Section 8.1). Existing variants keep today's
# global values unchanged; "app" is smaller/quieter per the in-app spec.
APP_CRF = 24
APP_AUDIO_BITRATE = "96k"
APP_AUDIO_CHANNELS = 1        # mono

VARIANTS = {
    "simple": {
        "opening": "countdown",
        "output_subdir": "",
        "series_label": "",
        "board_px": BOARD_PX,              # 960
        "board_y_offset": BOARD_Y_OFFSET,  # 60
        "headline_y": HEADLINE_Y,          # 290
        "show_subtitle": True,
        "show_dots": True,
        "show_watermark": True,
        "show_cta": True,
        "reaction_band": None,
        "show_eval_bar": False,
        "show_promo_banner": False,
        "show_endcard": False,
        "stop_after_brilliant": False,
        "selection": "random",
        "crf": CRF,
        "preset": PRESET,
        "audio_bitrate": AUDIO_BITRATE,
        "audio_channels": None,            # None = let ffmpeg keep the source layout
    },
    "reaction": {
        "opening": "watch",
        "output_subdir": "reaction",
        "series_label": "",
        "board_px": 1000,                  # near full-bleed, filling the gap
                                            # above it (was 820, then 880)
        "board_y_offset": -140,            # higher up; bottom band left empty
        "headline_y": 150,                 # raised to clear the bigger board
        "show_subtitle": False,            # keep the band clear
        "show_dots": False,
        "show_watermark": True,
        "show_cta": True,
        "reaction_band": REACTION_BAND,
        "show_eval_bar": False,
        "show_promo_banner": False,
        "show_endcard": False,
        "stop_after_brilliant": False,
        "selection": "random",
        "crf": CRF,
        "preset": PRESET,
        "audio_bitrate": AUDIO_BITRATE,
        "audio_channels": None,
    },
    "gm_games": {
        "opening": "none",
        "output_subdir": "gm_games",
        "series_label": "GM GAMES",
        "board_px": BOARD_PX,
        "board_y_offset": BOARD_Y_OFFSET,
        "headline_y": HEADLINE_Y,
        "show_subtitle": False,
        "show_dots": False,
        "show_watermark": True,
        "show_cta": False,
        "reaction_band": None,
        "show_eval_bar": True,
        # ⚠️ Banner OFF on purpose, and this is not an oversight. gm_games is
        # its own series and draws "GM GAMES" at SERIES_LABEL_Y (18) — exactly
        # where the banner lands, so turning it on hides the series' own
        # identity behind the app's. The END CARD costs nothing though: it runs
        # after the game is over, so a GM replay still sells the app without
        # the reel pretending to be a TChess ad for two minutes.
        "show_promo_banner": False,
        "show_endcard": True,
        "stop_after_brilliant": False,
        "selection": "top",
        "full_game": True,
        "hook_duration": GM_HOOK_DURATION,
        "crf": CRF,
        "preset": PRESET,
        "audio_bitrate": AUDIO_BITRATE,
        "audio_channels": None,
    },
    "app": {
        "opening": "none",                 # no countdown, no "watch closely" text
        "output_subdir": "app",
        "series_label": "",
        "board_px": APP_BOARD_PX,          # 1000 — full-bleed
        "board_y_offset": 0,               # centred, no countdown to clear
        "headline_y": HEADLINE_Y,
        "show_subtitle": False,            # no hook prompts beyond move labels
        "show_dots": True,
        "show_watermark": False,           # no channel handle in the in-app video
        "show_cta": False,                 # no "Follow for daily tactics" end card
        "reaction_band": None,
        "show_eval_bar": False,
        "show_promo_banner": False,      # §13.1: the in-app video carries NO branding
        "show_endcard": False,
        "stop_after_brilliant": False,
        "selection": "random",
        "crf": APP_CRF,
        "preset": PRESET,
        "audio_bitrate": APP_AUDIO_BITRATE,
        "audio_channels": APP_AUDIO_CHANNELS,
    },
}

# ── Promo variants ──────────────────────────────────────────────────────────
# These are the ones that sell the APP. They are additive: every variant above
# keeps its exact output, which matters most for "app" (it feeds the in-app
# tactics feed and must never carry branding) and for "gm_games" (its own
# series). Each promo variant is an existing variant plus the top banner, the
# end card, and no theme label — the banner takes that row.
#
# To put the banner on the legacy reels too, add "show_promo_banner": True and
# "show_endcard": True to VARIANTS["reaction"] / ["simple"]. Nothing else needs
# to change.

VARIANTS["promo_sac"] = {
    **VARIANTS["reaction"],
    "output_subdir": "promo/sac",
    # "music_mood": "payoff",   # off: see MUSIC_MOODS
    "outro_duration": PROMO_OUTRO_DURATION,
    "show_outro": False,                 # no rating reveal — straight to the card
    "hold_final": PROMO_HOLD_FINAL,
    "show_promo_banner": True,
    "show_endcard": True,
    # Cut the video the moment the sacrifice lands. brilliant_index() only ever
    # returns 0, so this is a ONE-MOVE reel: the sacrifice, the !! badge and the
    # meme reaction are the whole payoff — the follow-up moves are anticlimax.
    "stop_after_brilliant": True,
    "headline_y": PROMO_HEADLINE_Y,      # reaction's 150 would touch the banner
    # 🔴 NO HEADLINE ROW, AND IT IS A SPACE PROBLEM, NOT A TASTE ONE.
    # This family's board starts at y=320 and the banner now starts at SAFE_TOP
    # (180) and is 108 tall, so 288..320 is everything left above the board — a
    # 92px headline does not fit in 32px. The move is still announced by the
    # voiceover and marked by the !! badge, so the top strip goes to the banner,
    # which is the element that was being cropped away entirely.
    "show_headline": False,
}

VARIANTS["promo_guess"] = {
    **VARIANTS["simple"],
    "output_subdir": "promo/guess",
    # 🔴 NO MOVE NOTATION ABOVE THE BOARD. "Bxh7+" in 92px type takes the
    # whole headline row to tell the viewer something the board already shows —
    # the piece moved, and it is lit. The row is kept for the countdown's
    # "WHITE TO PLAY", which is the one thing the board cannot say by itself.
    "show_move_label": False,
    # 🔴 THE BOTTOM STRIP BELONGS TO THE LINK. Below a 960px board there are
    # exactly 100 visible pixels (board ends at 1500, SAFE_BOTTOM starts at
    # 1600) and three things used to want them: the subtitle, the progress dots
    # and the watermark. The dots were already invisible at y=1802 and the
    # subtitle printed straight through the URL. A download link the viewer can
    # actually read beats a second copy of the question the countdown just
    # asked, so the other two are off here rather than overlapping.
    "show_subtitle": False,
    "show_dots": False,
    # "music_mood": "tension",   # off: see MUSIC_MOODS
    "show_promo_banner": True,
    "show_endcard": True,
    "outro_duration": PROMO_OUTRO_DURATION,
    "show_outro": False,                 # no rating reveal — straight to the card
    "hold_final": PROMO_HOLD_FINAL,
    "headline_y": PROMO_HEADLINE_COUNTDOWN_Y,
    # headline_y stays at HEADLINE_Y (290): this variant keeps the countdown at
    # COUNTDOWN_CY and a 170 headline would leave a hole between them.
}

# ── The reaction reel ────────────────────────────────────────
# 🔴 THERE USED TO BE FOUR OF THESE AND NOW THERE IS ONE. The family was
# promo_sac / promo_react_full / promo_react_end / promo_react_slow, and the two
# things that told them apart were whether the follow-up moves survived and
# whether the clip landed on the sacrifice or on the mate.
#
# The format is now: move plays, sacrifice lands, reaction plays, end card. The
# follow-up moves are not rendered at all — so "whole line vs cut" is gone, and
# with only one move left "react to the sacrifice vs react to the mate" is the
# same frame. All four rendered identical video; scheduling them meant posting
# one reel four times under four names.
#
# promo_react_slow was the last real difference (hold_scale 1.45, longer holds
# for somebody who stopped scrolling). It went too: a one-move reel is ~13s, and
# stretching the single hold does not make a second format out of it.
#
# If a second reaction reel is ever wanted, the axis that still has room is the
# CLIP — a category per mood in assets/reaction/<category>/ — not the timeline.

VARIANTS["promo_mate"] = {
    **VARIANTS["promo_guess"],
    "output_subdir": "promo/mate",
    # Selection filter. --theme still wins if it is passed explicitly.
    "theme": "mateIn2",
    "subtitles": ("Mate in two.", "Can you find it?"),
}

VARIANTS["promo_bots"] = {
    **VARIANTS["simple"],
    "source": "bots",                    # roster cards, no puzzle — src/bots.py
    "opening": "none",
    "output_subdir": "promo/bots",
    "show_promo_banner": True,
    "show_endcard": True,
    "show_subtitle": False,
    "show_dots": False,
}

VARIANTS["promo_tour_wide"] = {
    **VARIANTS["simple"],
    "source": "tour_wide",           # 16:9 — the Play listing video
    "opening": "none",
    "output_subdir": "promo/tour_wide",
    "show_promo_banner": True,
    "show_endcard": True,
    "show_subtitle": False,
    "show_dots": False,
}

VARIANTS["promo_carousel"] = {
    **VARIANTS["simple"],
    "source": "carousel",                # stills, not video — see src/carousel.py
    "output_subdir": "promo/carousel",
    "show_promo_banner": True,
    "show_endcard": True,
}

VARIANTS["promo_tour"] = {
    **VARIANTS["simple"],
    "source": "screenshots",             # no puzzle, no board — see src/tour.py
    "opening": "none",
    "output_subdir": "promo/tour",
    "show_promo_banner": True,
    "show_endcard": True,
    "show_subtitle": False,
    "show_dots": False,
}


def variant(name: str) -> dict:
    """Return a copy of a variant's layout config."""
    if name not in VARIANTS:
        raise ValueError(f"unknown variant {name!r}; choices: {list(VARIANTS)}")
    return dict(VARIANTS[name])


REACTION_BAND_W = REACTION_BAND[2] - REACTION_BAND[0]   # 1080
REACTION_BAND_H = REACTION_BAND[3] - REACTION_BAND[1]   # 560

# ── Reaction clips (variant B) ──────────────────────────────────────────────
# Raw clips live in reactions_raw/<category>/*, normalised copies + a manifest
# in reactions/. prepare_reactions.py does the one-time normalisation; the build
# reads durations from the manifest and never probes clip files at build time.
# Drop raw clips here — either loose (they become the "default" category) or in
# <category>/ subfolders. prepare_reactions.py normalises them into REACTION_DIR.
REACTION_RAW_DIR = ASSETS_DIR / "reaction"
REACTION_DIR = ASSETS_DIR / "reactions"
REACTION_MANIFEST = REACTION_DIR / "manifest.json"
REACTION_DEFAULT_CATEGORY = "default"

REACTION_MAX_DURATION = 8.0     # play up to this long, from the START of the clip

# Per-clip trim. Values are `seconds_to_skip` or `(seconds_to_skip, max_seconds)`;
# keys match as a substring of the RAW filename (downloaded names are long and
# full of punctuation, so anchoring on the recognisable part is what survives a
# re-download). prepare_reactions.py applies it, so an edit here only takes
# effect on the next `python prepare_reactions.py`.
#
# The whole point of a reaction clip is that its peak is in the first moment —
# that is why REACTION_MAX_DURATION cuts from the start rather than centring. A
# clip whose reaction is delayed breaks that: it opens on somebody sitting
# still, landing as a dead band under the board at exactly the moment the
# sacrifice hits.
#
# ⚠️ A HEAD TRIM CANNOT RESCUE A CLIP THAT IS FRAMED WRONG, and the Magnus
# table-slam is the worked example — see assets/reaction-unused/README.txt. Its
# slam was at 11.0s (fixable here) but it is also a wide venue shot with no face
# in it (not fixable here), so it was removed from the pool instead. Check what
# a candidate looks like CENTRE-CROPPED TO 1080x560 before reaching for this.
REACTION_CLIP_TRIM: dict[str, float | tuple[float, float]] = {
    # (The Magnus table-slam lived here and was removed — see
    # assets/reaction-unused/README.txt for why a trim could not save it.)
}
REACTION_FADE = 0.35            # fade out over the final fraction of a second
REACTION_GAP = 0.15             # silence between voiceover end and reaction start
REACTION_TAIL = 0.35            # hold after the reaction before moving on
REACTION_DUCK_DB = -16.0        # music duck while the reaction plays (deep)
REACTION_GAIN = 1.0             # the clip's own audio, full level
REACTION_LOUDNORM = "I=-16:TP=-1.5:LRA=11"   # EBU R128 target for prep

# Video extensions the prep script will pick up.
REACTION_VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


# ── App export: thumb / preview / manifest (Section 13.2/13.3) ──────────────
# Derived artifacts built only for the "app" variant, plus the manifest that
# wires the generator into the PuzzleFlow app's `import-videos.ts` script.
# R2 upload itself is a later step — nothing downstream of this touches the
# network; these are local paths and R2 *key* strings only.
APP_THUMB_W, APP_THUMB_H = 720, 1280
APP_THUMB_TIME = 0.5             # seconds into the video for the poster frame

APP_PREVIEW_DURATION = 3.0       # seconds, video-only
APP_PREVIEW_W, APP_PREVIEW_H = 540, 960
APP_PREVIEW_CRF = 32
APP_PREVIEW_PRESET = "veryfast"

# R2 key prefixes (Section 8.1 bucket layout). The puzzle_id is the filename;
# the numbered local output folder is a build-time convenience only.
R2_APP_PREFIX = "app/v1"
R2_THUMB_PREFIX = "app/thumb"
R2_PREVIEW_PREFIX = "app/preview"

# Default manifest location when a caller does not pass an explicit path
# (run_batch.py always passes <variant_dir>/manifest.json instead).
MANIFEST_PATH = OUTPUT_DIR / "app" / "manifest.json"

# The app's fixed 17-theme taxonomy (Section 3.3) — used to pick a single
# manifest `theme` slug out of a puzzle's (possibly multi-tag) Lichess themes.
APP_THEME_SLUGS = [
    "mateIn1", "mateIn2", "mateIn3", "fork", "pin", "skewer",
    "discoveredAttack", "doubleCheck", "backRankMate", "smotheredMate",
    "queensideAttack", "sacrifice", "deflection", "clearance", "attraction",
    "hangingPiece", "endgame",
]


def reaction_category(puzzle: dict) -> str:
    """Pick a reaction category for a puzzle (falls back to the whole pool)."""
    themes = [t.lower() for t in puzzle.get("themes", [])]
    if any("mate" in t for t in themes):
        return "mate"
    return "sacrifice"


def _find_binary(name: str) -> str:
    """Locate an ffmpeg-family binary.

    Checks PATH first, then the install locations Windows package managers use.
    A freshly installed tool often is not on PATH of an already-running shell,
    so falling back to known locations avoids a confusing hard failure.
    """
    found = shutil.which(name)
    if found:
        return found

    exe = f"{name}.exe" if os.name == "nt" else name
    candidates = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        pkgs = Path(local) / "Microsoft" / "WinGet" / "Packages"
        candidates += sorted(pkgs.glob(f"Gyan.FFmpeg*/**/bin/{exe}"))
        candidates.append(Path(local) / "Microsoft" / "WinGet" / "Links" / exe)
    candidates += [
        Path(r"C:\ffmpeg\bin") / exe,
        Path(r"C:\Program Files\ffmpeg\bin") / exe,
        Path("/usr/bin") / name,
        Path("/usr/local/bin") / name,
        Path("/opt/homebrew/bin") / name,
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return name  # let the caller fail with a clear "not found" error


FFMPEG = _find_binary("ffmpeg")
FFPROBE = _find_binary("ffprobe")


# ── Landscape tour (variant "promo_tour_wide") ──────────────────────────────
# 🔴 THE ONE PLACE 9:16 IS WRONG. Google Play's listing promo video is shown
# landscape, so the vertical tour would be pillarboxed into a stripe down the
# middle of the store page. This is that reel re-composed for 16:9 — not
# letterboxed, RE-LAID-OUT: phone on one side, the label and its line on the
# other, which is the only way a very tall screenshot fills a wide frame.
#
# Everything else on the account stays 9:16. Play is the exception, not a new
# default.
WIDE_W, WIDE_H = 1920, 1080

WIDE_PHONE_H = 880                # phone height; width follows the screenshot
WIDE_PHONE_X = 1210               # left edge of the handset
WIDE_PHONE_Y = 96
WIDE_BEZEL = 11
WIDE_RADIUS = 38

WIDE_TEXT_X = 130                 # the copy column
WIDE_LABEL_Y, WIDE_LABEL_SIZE = 330, 122
WIDE_RULE_W, WIDE_RULE_H, WIDE_RULE_GAP = 128, 9, 30
WIDE_CALLOUT_Y, WIDE_CALLOUT_SIZE = 560, 44

WIDE_BANNER_X, WIDE_BANNER_Y = 130, 830

WIDE_GRAD_TOP = (23, 23, 28)
WIDE_GRAD_BOTTOM = (6, 6, 8)
WIDE_VIGNETTE = 120
WIDE_GLOW_PX, WIDE_GLOW_XY, WIDE_GLOW_ALPHA = 1500, (760, -240), 100

WIDE_HOOK_SIZE, WIDE_HOOK_SUB_SIZE = 110, 52
WIDE_ENDCARD_MARK_H = 190
WIDE_ENDCARD_TAGLINE_SIZE = 56
