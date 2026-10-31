"""Tunables for the landscape long-form GM-game videos.

Kept apart from the root config.py on purpose: the shorts pipeline reads that
file, and nothing here may change how a short renders. This module only READS
root config (board colours, ffmpeg path, sample rate) and never writes it.
"""

from pathlib import Path

import config

ROOT = config.ROOT
DATA = config.DATA_DIR / "longform"
PGN_DIR = DATA / "pgn"
ANALYSIS_DIR = DATA / "analysis"
OPENINGS_DIR = DATA / "openings"
OUTPUT_DIR = config.ROOT / "output" / "longform"
LEDGER = DATA / "ledger.json"

# Bundled engine (data/longform/bin). A system Stockfish on PATH also works.
STOCKFISH = DATA / "bin" / "stockfish" / "stockfish-windows-x86-64-universal.exe"
ENGINE_PROCS = 6              # parallel single-thread engines; leaves the laptop usable
ENGINE_NODES_BOOK = 300_000   # opening-theory positions (played fast, never judged)
ENGINE_NODES = 2_000_000      # every other position
ENGINE_NODES_DEEP = 12_000_000  # re-check around every mark and every big eval jump
ENGINE_HASH_MB = 32
ENGINE_DEEP_ROUNDS = 2
WP_SWING_RECHECK = 15         # neighbours this far apart get a deep re-check

# ── Canvas ────────────────────────────────────────────────────────────────
W, H = 1920, 1080
FPS = 30
CRF = 20
PRESET = "medium"
ENCODE_THREADS = 6            # caps x264 RAM (~770 MB at auto) and leaves cores free

# App tokens (tchess-app/src/theme/tokens.ts). Pure black and one accent.
BG = (0, 0, 0)
SURFACE = (12, 12, 13)
SURFACE_ALT = (20, 20, 22)
BORDER = (31, 31, 35)
BORDER_LIT = (46, 46, 51)
TEXT_HI = (233, 233, 234)
TEXT_MID = (139, 139, 144)
TEXT_LOW = (90, 90, 96)
PRIMARY = (157, 85, 233)
PRIMARY_BRIGHT = (191, 141, 254)
GOLD = (255, 201, 74)

# Annotation glyph colours — the chess.com vocabulary viewers already read.
GLYPH_COLORS = {
    "!!": (38, 198, 218),     # brilliant, the shorts' own badge cyan
    "!": (92, 139, 176),      # great / only move
    "?!": (247, 199, 72),
    "?": (255, 164, 89),
    "??": (240, 82, 82),
    "#": (240, 82, 82),
}
GLYPH_TITLES = {
    "!!": "BRILLIANT MOVE",
    "!": "GREAT MOVE",
    "?!": "INACCURACY",
    "?": "MISTAKE",
    "??": "BLUNDER",
    "#": "CHECKMATE",
}

# ── Layout (1920x1080) ────────────────────────────────────────────────────
BOARD_PX = 1000
BOARD_X, BOARD_Y = 118, 40
EVAL_X, EVAL_W = 52, 34

PANEL_X, PANEL_W = 1178, 690
BRAND_Y = 44
CARD_TOP_Y = 104              # black's card
CARD_H = 132
CARD_BOTTOM_Y = 1040 - CARD_H  # white's card, flush with the board's bottom
OPENING_Y = 262
MOVES_Y = 330
MOVE_ROW_H = 44
MOVE_ROWS = 8
MOMENT_Y = 704
MOMENT_H = 184

# ── Pacing (seconds per ply, slide included) ──────────────────────────────
SLIDE = 0.45
SLIDE_KEY = 0.75               # the brilliant / checkmate move travels slower
PACE = {
    "book": 1.6,
    "normal": 3.3,
    "capture": 3.7,
    "check": 3.9,
    "?!": 3.9,
    "?": 5.0,
    "??": 6.0,
    "!": 5.5,
    "!!": 7.5,
    "last": 5.5,
}
TENSION_BEFORE_KEY = 1.6       # extra hold on the position before a !! lands
BADGE_POP = 0.35
# Soft duration target. Holds are scaled toward it, never past these clamps,
# so a short game stays short rather than crawling.
TARGET_MIN_S, TARGET_MAX_S = 450, 660
SCALE_MIN, SCALE_MAX = 0.8, 1.35

INTRO_S = 3.6
INTRO_FADE_S = 0.6
RESULT_HOLD_S = 5.0
ENDCARD_S = 10.0

# ── Audio ────────────────────────────────────────────────────────────────
GAIN_MUSIC = 0.55
GAIN_SFX = 0.8
MUSIC_XFADE_S = 2.5
MUSIC_FADE_OUT_S = 3.0
LOUDNESS_LUFS = -15

# ── Engine judgement thresholds (win-probability points, 0..100) ──────────
WP_INACCURACY = 6
WP_MISTAKE = 11
WP_BLUNDER = 18
WP_BLUNDER_LANDS_BELOW = 45    # ?? only if the mover is now worse
WP_BRILLIANT_SLACK = 3         # a !! must be within this of the engine's best
WP_ONLY_MOVE_GAP = 20          # best minus second-best for a "!"
WP_BRILLIANT_MAX_BEFORE = 85   # already totally winning -> no !!
WP_GREAT_MAX_BEFORE = 78       # no "only move" praise once the game is decided
WP_STILL_WINNING = 80          # errors that leave the mover this far ahead don't count

# Channel branding and publishing. Each channel's videos carry its own lockup,
# and `account` is the key into root config.ACCOUNTS: the SAME OAuth token and
# pinned channel id the shorts use, so a long video can only ever land on the
# channel its brand belongs to.
#
# Publish slots are set in NEW YORK time, not PKT: the premium (US/UK) audience
# is the one the slot is chosen for, and pinning to its clock keeps the slot
# right across US daylight-saving changes. Both avoid the shorts' own slots:
#   tahachess 12:00 ET = 21:00 PKT (22:00 in winter): UK evening and US
#             lunchtime. Its shorts go out at 15:00 / 23:00 / 05:00 PKT.
#   tchess    17:30 ET = 02:30 PKT (03:30 in winter): US evening prime time.
#             Its shorts go out at 17:00 / 01:00 / 07:00 PKT.
BRANDS = {
    "tchess": {"name": "TChess", "mark": config.BRAND_MARK,
               "tagline": "Legendary games, every day",
               "account": "tchessapp", "slots_et": ["17:30"]},
    # The Taha Chess channel carries the TChess lockup too (rook + wordmark),
    # like its shorts carry the @tchessapp watermark: the owner's call,
    # 2026-09-29. The brand key stays separate because the ACCOUNT differs.
    "tahachess": {"name": "TChess", "mark": config.BRAND_MARK,
                  "tagline": "Legendary games, every day",
                  "account": "tahachesstv", "slots_et": ["12:00"]},
}
SLOT_TZ = "America/New_York"

# The same games as 9:16 reels, on the Taha Chess TV Facebook Page only
# (longform/facebook.py). The composer posts live, so the slot is simply when
# the "ChessReel Longform FB" task fires:
#   05:30 PKT = 20:30 New York (19:30 in winter): US prime time.
#   It is clear of the shorts, whose Facebook posts on the same Chrome
#   profile run at about xx:02-xx:06 around 05:00 and 07:00.
FACEBOOK = {
    "enabled": False,              # paused by the owner: no reel renders, no Page posts
    "brand": "tahachess",          # whose YouTube games it follows (lockup comes from BRANDS)
    "account": "tahachesstv",      # config.ACCOUNTS key: Taha Chess TV's Page
    "slot_pkt": "05:30",
    "retry_pkt": "06:20",          # second trigger; one reel per day at most
    "timeout_s": 900,              # composer budget for a multi-minute reel
}

SORA = config.BRAND_FONT

# Thumbnail backdrop models, newest first. Each is tried in turn, and one the
# project has no access to (403/404) is skipped, so enabling a newer model in
# the OpenAI dashboard is all it takes to move up. On 2026-09-29 the project
# had gpt-image-1 only. gpt-image-2.5-flare is OpenAI's recommended default
# (developers.openai.com/api/docs/models). If none works, the glow is used.
#
# EMPTY ON PURPOSE: the owner chose zero cost over an AI backdrop (2026-09-29),
# so thumbnails use the free blurred-board background. To bring AI back, put
# the model names here again; nothing else changes.
THUMB_IMAGE_MODELS = []
