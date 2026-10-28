# Chess Reel Generator — Build Specification

**Read this entire file before writing any code.**

Build a fully automated pipeline that turns Lichess sacrifice puzzles into
vertical short-form videos (Instagram Reels / YouTube Shorts / Facebook Reels)
with animated boards, neural voiceover, sound effects, background music, and
auto-generated captions.

Target: **30 finished videos per unattended batch run.**

---

## 0. NON-NEGOTIABLE RULES

Read these first. Violating any of them means the build is wrong.

1. **No reaction faces.** Earlier prototypes had cartoon reaction overlays.
   They are removed. Do not add emoji overlays, meme faces, or reaction images
   anywhere in the composition.
2. **Sacrifice move always gets `!!`** appended to its move label, rendered in
   the accent colour. Every other move renders in white without `!!`.
3. **Everything runs offline except two optional network calls**: edge-tts
   (voiceover) and the Claude API (captions). Both must have offline fallbacks
   so a run never hard-fails without internet.
4. **No GPU. No ML models. No PyTorch.** CPU-only, must run on 8 GB RAM.
5. **Idempotent + resumable.** Re-running a batch must never duplicate a
   posted puzzle and must skip work already completed.
6. **Every tunable value lives in `config.py`.** No magic numbers scattered in
   module code.
7. **Use the exact coordinate math in Section 5.2.** Do not guess it. Getting
   this wrong makes pieces animate to visibly wrong squares.

---

## 1. FINAL OUTPUT SPEC

Each generated video must be:

| Property | Value |
|---|---|
| Resolution | 1080 × 1920 (9:16 vertical) |
| Frame rate | 30 fps |
| Video codec | H.264 (`libx264`), `yuv420p`, CRF 21 |
| Audio codec | AAC, 192 kbps, 44100 Hz |
| Duration | 12–22 seconds |
| Container | MP4, `+faststart` |
| File size | Under 8 MB typical |

Alongside each video, produce:
- `caption.txt` — post caption, hashtags, posting metadata
- `meta.json` — machine-readable record of everything about the post

---

## 2. PROJECT STRUCTURE

Create exactly this layout:

```
chess-reels/
├── config.py               # ALL tunable values
├── requirements.txt
├── README.md               # user-facing setup + usage
│
├── src/
│   ├── __init__.py
│   ├── puzzles.py          # Lichess CSV download, filter, select
│   ├── board.py            # SVG→PNG rendering, coordinate math, sprites
│   ├── animate.py          # frame generation, easing, piece slides
│   ├── speech.py           # SAN→spoken text, TTS engines + fallbacks
│   ├── sfx.py              # synthesized sound effects
│   ├── music.py            # generated background music bed
│   ├── mixer.py            # audio event timeline → single WAV
│   ├── compose.py          # PIL layout: text, timer, eval bar, dots
│   ├── captions.py         # Claude API + template fallback
│   ├── encode.py           # ffmpeg invocation
│   ├── queue.py            # Supabase / local JSON queue
│   └── build.py            # orchestrator: one puzzle → one finished video
│
├── run_batch.py            # CLI entry point
├── data/
│   ├── lichess_db_puzzle.csv       # downloaded, gitignored
│   └── posted.json                 # local dedupe ledger
└── output/
    └── <puzzle_id>/
        ├── frames/                 # deleted after encode
        ├── audio/
        ├── video.mp4
        ├── caption.txt
        └── meta.json
```

---

## 3. DEPENDENCIES

`requirements.txt`:

```
python-chess>=1.999
cairosvg>=2.7.0
Pillow>=10.0.0
numpy>=1.24.0
scipy>=1.11.0
pandas>=2.0.0
edge-tts>=6.1.0
requests>=2.31.0
zstandard>=0.22.0
anthropic>=0.39.0      # optional, captions only
supabase>=2.0.0        # optional, queue only
```

**System requirements:**
- Python 3.10+
- FFmpeg on PATH (`ffmpeg` and `ffprobe`)
- Cairo graphics library

**Install commands to put in README:**

```bash
# Ubuntu/Debian
sudo apt install ffmpeg libcairo2 python3-dev

# macOS
brew install ffmpeg cairo pkg-config

# Windows
# 1. Download FFmpeg from gyan.dev, add bin/ to PATH
# 2. pip install pipwin && pipwin install cairocffi
#    (or use WSL2 — strongly recommended on Windows)

pip install -r requirements.txt
```

**Verify install** — the README must include this check:

```bash
python -c "import chess, cairosvg, numpy, scipy, pandas; print('py ok')"
ffmpeg -version | head -1
edge-tts --list-voices | head -3
```

---

## 4. PHASE 1 — PUZZLE SOURCING (`src/puzzles.py`)

### 4.1 Download

Source: `https://database.lichess.org/lichess_db_puzzle.csv.zst`

- Public domain (CC0). No attribution or licensing constraint.
- Compressed ~250 MB, decompressed ~1 GB, roughly 5 million puzzles.
- Download once, cache in `data/`. Skip if file exists and is non-empty.
- Decompress with `zstandard` streaming — do **not** load the whole
  compressed blob into memory.
- Show a progress indicator; this download takes several minutes.

### 4.2 CSV Schema

Columns present in the file:

```
PuzzleId, FEN, Moves, Rating, RatingDeviation, Popularity,
NbPlays, Themes, GameUrl, OpeningTags
```

Critical semantics — **get this right or every puzzle will be wrong**:

- `FEN` is the position **before the opponent's setup move**.
- `Moves` is a space-separated UCI list. **The FIRST move in the list is
  played by the opponent**, not the solver. It sets up the puzzle.
- Therefore: **apply `Moves[0]` to the FEN first**. The resulting position
  is the puzzle position shown to the viewer. The solution is `Moves[1:]`.
- The first move of `Moves[1:]` is the sacrifice / brilliant move.

```python
board = chess.Board(row.FEN)
board.push_uci(moves[0])          # opponent setup move
puzzle_fen = board.fen()          # THIS is what the viewer sees
solution   = moves[1:]            # THIS is what we animate
```

### 4.3 Filter

```python
mask = (
    df.Themes.str.contains("sacrifice", na=False, case=False)
    & df.Themes.str.contains("short|mateIn2|mateIn3", na=False, regex=True)
    & df.Rating.between(1400, 1800)
    & (df.Popularity > 85)
    & (df.NbPlays > 500)
)
```

Rationale for each condition (keep these in code comments):
- `sacrifice` — the content niche
- `short|mateIn2|mateIn3` — caps solution at 2–5 plies, keeps videos 12–22 s
- `Rating 1400–1800` — hard enough to feel clever, easy enough that viewers
  can solve it; this drives comments
- `Popularity > 85` — community-upvoted, filters out ugly positions
- `NbPlays > 500` — battle-tested, low chance of a broken puzzle

Expected yield: **15,000–25,000 puzzles.** At 3 per day that is over 15 years
of content. Log the count after filtering so the user can see it.

### 4.4 Validation

Every selected puzzle must pass all of these before entering the queue.
Reject and pick another if any fail:

```python
def validate(fen, solution):
    board = chess.Board(fen)
    if len(solution) < 2 or len(solution) > 5:
        return False
    for uci in solution:
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            return False
        board.push(move)
    # First move must be a genuine sacrifice: a capture or a piece
    # offered on a defended square
    return True
```

Additionally verify the first solution move is a capture OR that the moving
piece lands on a square attacked by the opponent. If neither, it is not
visually a sacrifice — skip it.

### 4.5 Selection

- Load `data/posted.json` (a list of `PuzzleId` strings already used).
- Exclude those.
- Sample `N` puzzles randomly from the remainder (random, not top-N, to keep
  variety across runs).
- Append chosen IDs to `posted.json` **only after successful encode**, never
  before — a crash must not burn puzzles.

### 4.6 Output Schema

`puzzles.py` returns a list of dicts:

```python
{
  "id": "abc12",
  "fen": "...",                 # position AFTER the setup move
  "solution": ["d3h7", "g8h7", "f3g5", "h7g8", "d1h5"],
  "rating": 1650,
  "themes": ["sacrifice", "mateIn3", "kingsideAttack"],
  "popularity": 94,
  "game_url": "https://lichess.org/...",
  "theme_label": "Greek Gift Sacrifice",   # human-readable, see 4.7
}
```

### 4.7 Theme Labels

Map raw Lichess theme tags to display names. Pick the most specific match:

```python
THEME_LABELS = {
    "greekGift":        "Greek Gift Sacrifice",
    "smotheredMate":    "Smothered Mate",
    "doubleCheck":      "Double Check",
    "deflection":       "Deflection Sacrifice",
    "attraction":       "King Attraction",
    "clearance":        "Clearance Sacrifice",
    "sacrifice":        "Queen Sacrifice",   # if queen is the sacrificed piece
    "mateIn2":          "Mate in 2",
    "mateIn3":          "Mate in 3",
}
```

If the sacrificed piece is a queen, prefer "Queen Sacrifice" regardless of
other tags — it is the strongest hook. Determine the sacrificed piece from
`board.piece_at(first_move.from_square)`.

Fallback label: `"Sacrifice"`.

---

## 5. PHASE 2 — BOARD RENDERING (`src/board.py`)

### 5.1 SVG → PNG

Use `chess.svg.board()` then `cairosvg.svg2png()`. Return a PIL `RGBA` image.

```python
svg = chess.svg.board(
    board,
    size=BOARD_PX,
    lastmove=lastmove,          # chess.Move or None
    check=check_square,         # square int or None
    arrows=arrows,              # list of chess.svg.Arrow
    colors=BOARD_COLORS,
    coordinates=True,
)
png_bytes = cairosvg.svg2png(
    bytestring=svg.encode(),
    output_width=BOARD_PX,
    output_height=BOARD_PX,
)
img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
```

Colour palette (`config.py`):

```python
BOARD_COLORS = {
    "square light":          "#EDE7DC",
    "square dark":           "#6F8F6B",
    "square light lastmove": "#F5D97A",
    "square dark lastmove":  "#CBAF45",
    "margin":                "#161613",
    "coord":                 "#EDE7DC",
}
```

### 5.2 COORDINATE MATH — EXACT, DO NOT GUESS

`python-chess` always emits `viewBox="0 0 390 390"` regardless of the `size`
parameter. Internally: **15 units margin + 360 units board + 15 units margin**,
so each cell is **45 units**.

The scale factor is therefore `BOARD_PX / 390`.

```python
VIEWBOX      = 390.0
MARGIN_UNITS = 15.0
CELL_UNITS   = 45.0

def square_center(square: int, board_px: int):
    """Return (x, y, cell_px) — pixel centre of a square within the board image."""
    scale  = board_px / VIEWBOX
    margin = MARGIN_UNITS * scale
    cell   = CELL_UNITS  * scale
    f = chess.square_file(square)          # 0..7, a..h
    r = chess.square_rank(square)          # 0..7, rank1..rank8
    x = margin + cell * f + cell / 2
    y = margin + cell * (7 - r) + cell / 2   # SVG y-axis is inverted
    return x, y, cell
```

Sanity check that must hold: `2 * margin + 8 * cell == board_px`.
For `board_px = 900`: `margin = 34.62`, `cell = 103.85`. Assert this in tests.

**This assumes the board is NOT flipped** (white on bottom). If you ever add
board flipping, invert both `f` and `r`.

### 5.3 Piece Sprites

For animation you need a single piece rendered on transparent background:

```python
def piece_sprite(piece: chess.Piece, px: int) -> Image.Image:
    svg = chess.svg.piece(piece, size=px)
    png = cairosvg.svg2png(bytestring=svg.encode(),
                           output_width=px, output_height=px)
    return Image.open(io.BytesIO(png)).convert("RGBA")
```

Sprite size must equal the cell size: `int(cell)` from `square_center()`.

Cache sprites in a dict keyed by `(piece.symbol(), px)` — regenerating them
every frame is the single biggest performance mistake in this pipeline.

---

## 6. PHASE 3 — ANIMATION (`src/animate.py`)

### 6.1 Easing

```python
def ease_in_out_cubic(t: float) -> float:
    return 4*t*t*t if t < 0.5 else 1 - pow(-2*t + 2, 3) / 2
```

### 6.2 Slide Animation — The Core Trick

To animate a piece from square A to square B, you must render a board that
contains **neither** the moving piece nor the captured piece, then paste the
sprite on top at interpolated positions.

```python
def build_slide_frames(board, move, board_px, fps, duration):
    piece       = board.piece_at(move.from_square)
    is_capture  = board.is_capture(move)

    # Board with the moving piece and any captured piece removed
    stage = board.copy()
    stage.remove_piece_at(move.from_square)
    if is_capture:
        target = move.to_square
        if board.is_en_passant(move):
            # Captured pawn is NOT on the destination square
            target = move.to_square + (-8 if board.turn == chess.WHITE else 8)
        stage.remove_piece_at(target)
    base = render_board(stage, board_px)

    x0, y0, cell = square_center(move.from_square, board_px)
    x1, y1, _    = square_center(move.to_square,   board_px)
    sprite = piece_sprite(piece, int(cell))

    frames = []
    n = int(duration * fps)
    for k in range(n):
        p  = ease_in_out_cubic(k / n)
        cx = x0 + (x1 - x0) * p
        cy = y0 + (y1 - y0) * p
        arc = -math.sin(p * math.pi) * cell * ARC_LIFT     # 0.22
        f = base.copy()
        f.paste(sprite,
                (int(cx - cell/2), int(cy - cell/2 + arc)),
                sprite)
        frames.append(f)
    return frames
```

### 6.3 Edge Cases — Handle All Four

**Castling.** `board.is_castling(move)` is true. The king slides normally, but
the rook must also move. Remove **both** king and rook from the staging board,
animate the king sprite, and paste the rook at its destination on the final
frame. Rook squares:

```python
# King-side: rook h1→f1 (white), h8→f8 (black)
# Queen-side: rook a1→d1 (white), a8→d8 (black)
```

**Promotion.** `move.promotion` is not `None`. Animate the **pawn** sprite
across, then the landed board naturally shows the promoted piece. Add a brief
flash on the destination square at the moment of landing.

**En passant.** `board.is_en_passant(move)` is true. The captured pawn sits on
a different square than the destination — see the offset in 6.2. Getting this
wrong leaves a ghost pawn on the board.

**Knight moves.** Knights slide in a straight line in this implementation.
That is acceptable and reads fine. Do not attempt L-shaped pathing.

### 6.4 Timing Constants (`config.py`)

```python
SLIDE_DURATION   = 0.42     # seconds per piece move
ARC_LIFT         = 0.22     # fraction of cell size
HOOK_DURATION    = 3.6      # countdown timer segment
HOLD_SACRIFICE   = 2.3      # pause after the brilliant move
HOLD_NORMAL      = 1.5      # pause after a forced/quiet move
HOLD_FINAL       = 2.6      # pause after the last move
OUTRO_DURATION   = 3.0      # rating reveal + CTA
FLASH_DECAY      = 0.28     # seconds of impact flash
```

---

## 7. PHASE 4 — COMPOSITION (`src/compose.py`)

### 7.1 Canvas Layout

Canvas: 1080 × 1920, background `#101013`.

Vertical zones, top to bottom:

| Zone | Y range | Content |
|---|---|---|
| Accent bar | 0–9 | Solid accent stripe |
| Theme label | 60–110 | Theme name, uppercase, muted grey, 42 px |
| Headline | ~350 | Move label (`Bxh7+ !!`), 92 px bold, centred |
| Board | centred +95 offset | 900 × 900 board image |
| Subtitle | board_bottom + 55 | Short annotation, 50 px regular |
| Eval bar | left of board | See 7.4 |
| Progress dots | H − 118 | One dot per move + hook |

Safe zones — **nothing important within**:
- Top 180 px (platform UI)
- Bottom 320 px (caption overlay, CTA buttons)
- Right 120 px (like/share rail)

The board sits centred so it survives all three platforms' crops.

### 7.2 Text Rendering

All text centred horizontally with a 3 px black drop shadow for legibility.

```python
def centred_text(draw, y, text, font, fill, shadow=True):
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (CANVAS_W - (bbox[2] - bbox[0])) // 2
    if shadow:
        draw.text((x + 3, y + 3), text, font=font, fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=fill)
```

Font: DejaVu Sans Bold, bundled with most Linux distros. Bundle a fallback in
`assets/` and resolve in this order:
1. `assets/font-bold.ttf`
2. `/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf`
3. `ImageFont.load_default()`

### 7.3 The `!!` Rule

```python
label = san
if is_sacrifice_move:              # always index 0 of the solution
    label = f"{san} !!"
    colour = ACCENT                # #FF6B35
else:
    colour = WHITE                 # #F2F0EA
```

Checkmate (`#` in SAN) also renders in accent colour.

### 7.4 Eval Bar

A thin vertical bar to the left of the board showing material/position swing.

- Width 22 px, height equal to board height, positioned 40 px left of board.
- White portion fills from the bottom, black from the top.
- **No Stockfish dependency.** Compute a simple material count plus a mate
  override:

```python
PIECE_VALUES = {chess.PAWN:1, chess.KNIGHT:3, chess.BISHOP:3,
                chess.ROOK:5, chess.QUEEN:9, chess.KING:0}

def simple_eval(board):
    if board.is_checkmate():
        return -10.0 if board.turn == chess.WHITE else 10.0
    score = 0
    for sq, piece in board.piece_map().items():
        v = PIECE_VALUES[piece.piece_type]
        score += v if piece.color == chess.WHITE else -v
    return max(-10.0, min(10.0, score))
```

This intentionally shows the sacrifice as a **material dip** followed by a
**mate spike** — which is exactly the dramatic arc you want visible.

Animate the bar smoothly between values over ~0.3 s rather than snapping.

### 7.5 Countdown Timer Hook

The first 3.6 seconds. This is the single highest-impact retention feature —
build it carefully.

- Show the puzzle position, static.
- Headline: `"WHITE TO PLAY"` (or `"BLACK TO PLAY"` — derive from `board.turn`).
- Large countdown numeral centred **below** the headline, above the board:
  `3` → `2` → `1`, one second each, then 0.6 s of `"?"`.
- Each numeral scales from 1.4× down to 1.0× over its second (pop effect).
- Numeral colour: accent.
- A tick sound fires on each numeral (see 8.3).
- Subtitle alternates between `"Can you find it?"` and `"Sacrifice available."`
  every 0.9 s.
- Draw a thin circular progress ring around the numeral that depletes.

### 7.6 Rating Reveal Outro

The last 3.0 seconds:

- Final position, mate highlighted.
- Headline: `"RATED {rating}"` in accent.
- Subtitle: `"Did you solve it?"`
- Below that, smaller: `"Follow for daily tactics"`
- Slow zoom on the board (1.0× → 1.04×) for motion.

### 7.7 Impact Flash

On the sacrifice move and on checkmate, tint the background toward accent for
`FLASH_DECAY` seconds with linear falloff:

```python
intensity = max(0.0, 1.0 - elapsed / FLASH_DECAY)
```

Blend the background colour only — never wash out the board itself.

---

## 8. PHASE 5 — AUDIO

### 8.1 SAN → Spoken Text (`src/speech.py`)

Convert a move into natural narration. **Build the text from the board state
before the move, not by parsing the SAN string.**

```python
PIECE_WORDS = {"K":"king","Q":"queen","R":"rook",
               "B":"bishop","N":"knight","P":"pawn"}
FILE_WORDS  = {"a":"A","b":"B","c":"C","d":"D",
               "e":"E","f":"F","g":"G","h":"H"}

def move_to_speech(board, move):
    san = board.san(move)
    if board.is_castling(move):
        text = "castles king side" if chess.square_file(move.to_square) > 4 \
               else "castles queen side"
    else:
        piece = board.piece_at(move.from_square)
        name  = PIECE_WORDS[piece.symbol().upper()]
        verb  = "takes" if board.is_capture(move) else "to"
        sq    = chess.square_name(move.to_square)
        text  = f"{name} {verb} {FILE_WORDS[sq[0]]} {sq[1]}"
    if move.promotion:
        text += f", promotes to {PIECE_WORDS[chess.piece_symbol(move.promotion).upper()]}"
    if "#" in san:
        text += ". Checkmate."
    elif "+" in san:
        text += ", check"
    return text, san
```

Note: files are uppercased (`"A"`, `"H"`) because TTS engines pronounce a
lone lowercase `h` as "aitch" inconsistently. Ranks stay as digits — TTS
reads them correctly.

### 8.2 TTS Engines — Three Tiers with Automatic Fallback

**Tier 1 — edge-tts (default).** Free, no API key, neural quality.

```python
import edge_tts, asyncio

async def _edge(text, path, voice, rate, pitch):
    tts = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await tts.save(path)

def edge_speak(text, path):
    asyncio.run(_edge(text, path,
                      voice=config.TTS_VOICE,
                      rate=config.TTS_RATE,
                      pitch=config.TTS_PITCH))
```

Recommended voices — expose in config, let the user try each:

| Voice | Character |
|---|---|
| `en-US-GuyNeural` | Deep, confident — default choice |
| `en-GB-RyanNeural` | British, commentary feel |
| `en-US-AndrewMultilingualNeural` | Warm, conversational |
| `en-US-BrianMultilingualNeural` | Energetic |

Settings: `rate="+8%"`, `pitch="-2Hz"` — slightly faster and lower reads as
more authoritative for tactical commentary.

**Tier 2 — Piper (offline fallback).** If edge-tts fails (no network,
throttling), fall back to Piper. It is fully local, ~60 MB per voice model,
and runs comfortably on CPU. Download `en_US-lessac-medium` on first use.

**Tier 3 — Silence.** If both fail, emit silence of the correct duration and
log a warning. **The build must still complete.** A video with music and SFX
but no voiceover is far better than a crashed batch.

Implement as a chain that tries each tier in order and never raises.

**Do not implement ElevenLabs account rotation.** It violates their terms,
their multi-account detection will ban the accounts, and their free tier
does not permit commercial use — which monetized pages are. If higher quality
than edge-tts is genuinely needed later, the correct path is a paid plan.

### 8.3 Sound Effects (`src/sfx.py`)

All synthesized with numpy at 44100 Hz. No sample files, no licensing risk.

| SFX | Trigger | Character |
|---|---|---|
| `move` | Quiet move lands | Short wooden click, ~90 ms |
| `capture` | Capture lands | Heavier thud with low body, ~160 ms |
| `check` | Check delivered | Rising two-tone sting, ~420 ms |
| `mate` | Checkmate | Low boom + minor chord stab, ~1.1 s |
| `whoosh` | Piece begins sliding | Filtered noise sweep, ~300 ms |
| `tick` | Each countdown numeral | Sharp high click, ~60 ms |

Synthesis approach for each:

```python
def sfx_move(sr=44100):
    n = int(0.09 * sr); t = np.arange(n) / sr
    sig  = np.random.randn(n) * np.exp(-t * 55) * 0.5      # attack noise
    sig += 0.4 * np.sin(2*np.pi*190*t) * np.exp(-t * 40)   # wood body
    sig += 0.2 * np.sin(2*np.pi*420*t) * np.exp(-t * 60)   # overtone
    return sig * 0.8

def sfx_capture(sr=44100):
    n = int(0.16 * sr); t = np.arange(n) / sr
    sig  = np.random.randn(n) * np.exp(-t * 22) * 0.6
    sig += 0.55 * np.sin(2*np.pi*110*t) * np.exp(-t * 18)
    sig += 0.30 * np.sin(2*np.pi* 70*t) * np.exp(-t * 12)
    return sig * 0.9

def sfx_check(sr=44100):
    n = int(0.42 * sr); t = np.arange(n) / sr
    f = np.linspace(600, 1250, n)                          # rising sweep
    sig  = 0.5 * np.sin(2*np.pi*np.cumsum(f)/sr)
    sig += 0.3 * np.sin(2*np.pi*np.cumsum(f*1.5)/sr)
    return sig * np.exp(-t * 4.5) * 0.75

def sfx_mate(sr=44100):
    n = int(1.1 * sr); t = np.arange(n) / sr
    sig = 0.7 * np.sin(2*np.pi*np.linspace(90, 45, n)*t) * np.exp(-t*3.2)
    for f in (196, 233, 294, 392):                          # G minor
        sig += 0.22 * np.sin(2*np.pi*f*t) * np.exp(-t*2.6)
    sig += np.random.randn(n) * np.exp(-t*30) * 0.3
    return sig * 0.85

def sfx_tick(sr=44100):
    n = int(0.06 * sr); t = np.arange(n) / sr
    sig  = np.random.randn(n) * np.exp(-t * 120) * 0.4
    sig += 0.5 * np.sin(2*np.pi*1400*t) * np.exp(-t * 90)
    return sig * 0.7
```

`whoosh`: filtered white noise with a Hann-squared amplitude envelope and a
300→3000 Hz sweep modulating it.

### 8.4 Background Music (`src/music.py`)

Generate a lo-fi bed procedurally. No copyright exposure, no Content ID
claims, no licensing fees.

- Minor key progression: `i – VI – III – VII` (moody, tension-appropriate)
- Root note and BPM **rotate per video** so consecutive posts do not sound
  identical. Rotate root across `[G2, A2, D2, E2, C2]` and BPM across
  `[72, 76, 80, 84]`, selected by hashing the puzzle ID.
- Layers: sustained chord pad, bass root, soft kick on beats 1 and 3,
  closed hi-hat on offbeats, low-level vinyl noise (~0.006 amplitude).
- Sidechain: duck the music by ~6 dB during voiceover segments for clarity.

### 8.5 Audio Mixing (`src/mixer.py`)

Build an **event timeline** during frame generation, then render it once.

```python
events = [
    (0.35,  "sfx", "tick"),
    (1.35,  "sfx", "tick"),
    (2.35,  "sfx", "tick"),
    (3.60,  "sfx", "whoosh"),
    (4.02,  "sfx", "capture"),
    (4.07,  "sfx", "check"),
    (4.24,  "vo",  "bishop takes H 7, check"),
    ...
]
```

Mixing procedure:

1. Allocate a zero array of `duration * 44100 + 44100` samples.
2. Add the music bed at gain 0.34.
3. Apply sidechain ducking windows around every `vo` event.
4. Add each SFX at gain 0.75 at its sample offset.
5. Render each `vo` to a temp MP3 via TTS, decode to numpy (use ffmpeg to
   convert MP3 → 44100 Hz mono WAV, then `scipy.io.wavfile.read`), add at
   gain 0.95.
6. Clip to [−1, 1], then normalize peak to 0.92.
7. Write 16-bit mono WAV.

**Verification step — the build must assert these:**
- Peak ≤ 0.95 (no clipping)
- Overall RMS between 0.03 and 0.20 (not silent, not crushed)
- No 2-second window with RMS below 0.005 (no dead air)

Log these values per build so problems are visible.

### 8.6 Voiceover Timing

Voiceover must land **after** the move completes, not during the slide:

```
slide starts    → whoosh
slide ends      → move/capture SFX
+0.05 s         → check/mate SFX (if applicable)
+0.22 s         → voiceover begins
```

TTS clip length is unknown until generated. Generate all voiceover clips
**before** computing hold durations, then extend any hold that is shorter than
its voiceover clip plus 0.3 s of tail. This prevents narration being cut off
by the next move.

---

## 9. PHASE 6 — CAPTIONS (`src/captions.py`)

### 9.1 Claude API Mode

Model: `claude-sonnet-4-6`. One call per puzzle.

Prompt structure:

```
You are writing an Instagram caption for a chess tactics reel.

Puzzle details:
- Theme: {theme_label}
- Rating: {rating}
- Solution: {san_moves}
- Sacrificed piece: {piece_name}
- Result: {mate_in_n or "decisive attack"}

Write a caption that:
- Opens with a sharp observation, not a greeting
- Explains WHY the sacrifice works as a repeatable pattern, not just
  this one position
- Lists the concrete conditions that make the pattern work
- Ends with a save/follow prompt
- 120-180 words, short paragraphs, no emoji in the body
- Analytical and confident in tone, never hype or motivational

Return ONLY valid JSON, no markdown fences:
{
  "hook": "on-screen text, max 6 words",
  "caption": "the full caption body",
  "hashtags": ["#tag1", ...],   // exactly 10
  "first_comment": "a comment to pin that invites replies"
}
```

Parse defensively — strip ` ```json ` fences before `json.loads`, and wrap in
try/except with fallback to template mode.

Cost: roughly $0.01–0.02 per caption. At 3/day that is under $2/month.

### 9.2 Template Mode (no API key)

Must produce usable output with zero network. Build from string templates
keyed on theme, filling in the move list, rating, and piece names. Ship at
least 5 template variants per major theme so captions do not repeat verbatim.

Select the variant by hashing the puzzle ID.

### 9.3 Caption File Format

```
═══════════════════════════════════════
POST: {puzzle_id} — {theme_label}
Format: 1080x1920 | {duration}s | Rating {rating}
═══════════════════════════════════════

HOOK (on-screen, first 3s):
{hook}

─────────── CAPTION ───────────
{caption}

─────────── HASHTAGS ───────────
{hashtags joined by space}

─────────── POSTING META ───────────
Best time     : 7–9 PM local
First comment : {first_comment}
Source        : {game_url}
Solution      : {san_moves}
```

---

## 10. PHASE 7 — ENCODING (`src/encode.py`)

Write frames as `frames/f%05d.png`, then:

```python
cmd = [
    "ffmpeg", "-y",
    "-framerate", str(FPS),
    "-i", f"{frames_dir}/f%05d.png",
    "-i", audio_wav,
    "-c:v", "libx264",
    "-preset", "medium",
    "-crf", "21",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac",
    "-b:a", "192k",
    "-movflags", "+faststart",
    "-shortest",
    output_mp4,
]
subprocess.run(cmd, check=True, capture_output=True)
```

**Post-encode verification via ffprobe — assert all of these:**

```python
assert width == 1080 and height == 1920
assert video_codec == "h264"
assert audio_codec == "aac"          # audio stream MUST exist
assert 10.0 < duration < 30.0
assert filesize > 200_000            # catch empty/broken encodes
```

If any assertion fails, mark the puzzle failed, keep the frames for debugging,
and continue to the next puzzle. Never let one bad encode kill the batch.

Delete `frames/` only after successful verification. At 1080×1920 PNG, 500
frames is roughly 250 MB — leaving them around will fill the disk within a
few runs.

---

## 11. PHASE 8 — QUEUE (`src/queue.py`)

### 11.1 Local Mode (default)

`data/posted.json`:

```json
{
  "posted": ["abc12", "def34"],
  "pending": [
    {
      "puzzle_id": "ghi56",
      "video_path": "output/ghi56/video.mp4",
      "caption_path": "output/ghi56/caption.txt",
      "created_at": "2026-07-24T02:00:00Z",
      "status": "pending",
      "rating": 1650,
      "theme": "Greek Gift Sacrifice"
    }
  ]
}
```

Write atomically — serialize to a temp file, then `os.replace()`. A crash
mid-write must not corrupt the ledger.

### 11.2 Supabase Mode (optional)

Table `chess_reels`:

```sql
create table chess_reels (
  id           uuid primary key default gen_random_uuid(),
  puzzle_id    text unique not null,
  video_url    text,
  caption      text,
  hashtags     text[],
  rating       int,
  theme        text,
  duration     float,
  status       text default 'pending',   -- pending | posted | failed
  created_at   timestamptz default now(),
  posted_at    timestamptz
);
create index on chess_reels (status, created_at);
```

Upload the MP4 to a Supabase storage bucket, store the public URL. Enable only
when `SUPABASE_URL` and `SUPABASE_KEY` are present in the environment.

---

## 12. PHASE 9 — ORCHESTRATION

### 12.1 `src/build.py` — One Puzzle

```python
def build_one(puzzle) -> dict:
    """Returns a result dict. Never raises."""
    # 1. Validate puzzle, set up output dirs
    # 2. Pre-generate all voiceover clips, measure durations
    # 3. Compute the full timeline (frame counts + audio events)
    # 4. Generate hook frames (countdown)
    # 5. For each solution move: slide frames + hold frames
    # 6. Generate outro frames (rating reveal)
    # 7. Mix audio
    # 8. Encode + verify
    # 9. Generate caption + meta.json
    # 10. Clean up frames, update queue
```

Every step wrapped so a failure returns
`{"status": "failed", "error": str(e), "puzzle_id": ...}`
rather than propagating.

### 12.2 `run_batch.py` — CLI

```bash
python run_batch.py --count 30
python run_batch.py --count 3 --voice en-GB-RyanNeural
python run_batch.py --count 10 --no-api        # template captions
python run_batch.py --count 5 --theme greekGift
python run_batch.py --retry-failed
python run_batch.py --dry-run                  # select puzzles, no render
```

Arguments: `--count`, `--voice`, `--no-api`, `--theme`, `--rating-min`,
`--rating-max`, `--output-dir`, `--retry-failed`, `--dry-run`, `--keep-frames`.

Progress output per puzzle:

```
[ 4/30] ghi56  Greek Gift Sacrifice  1650
        frames  528 ....... 12.3s
        audio   mixed ...... peak 0.92  rms 0.079
        encode  1080x1920 ... 3.8 MB  17.6s
        caption claude ...... ok
        ✓ output/ghi56/video.mp4
```

End-of-run summary: succeeded, failed, total time, average per video, total
disk used.

### 12.3 Performance

Baseline on a 4-core CPU, 8 GB RAM:

| Stage | Time per video |
|---|---|
| Frame generation | ~14 s |
| TTS (network) | ~4 s |
| Audio mixing | ~2 s |
| FFmpeg encode | ~11 s |
| Caption (API) | ~3 s |
| **Total** | **~35 s** |

30 videos ≈ 18 minutes. On 2 cores with 4 GB RAM, roughly double.

Optimizations to implement:
- Cache piece sprites (biggest single win)
- Cache the composed static background layer; only redraw changed regions
- `--jobs N` flag to run puzzles in parallel via `multiprocessing.Pool`,
  defaulting to `cpu_count() - 1`

Do not attempt to parallelize within a single video — FFmpeg already
threads internally and the two will contend.

---

## 13. CONFIG FILE

`config.py` must contain every tunable value:

```python
# ── Canvas ────────────────────────────────
CANVAS_W, CANVAS_H = 1080, 1920
FPS       = 30
BOARD_PX  = 900
BG        = (16, 16, 19)
ACCENT    = (255, 107, 53)
WHITE     = (242, 240, 234)
MUTED     = (146, 144, 138)

# ── Timing ────────────────────────────────
SLIDE_DURATION = 0.42
ARC_LIFT       = 0.22
HOOK_DURATION  = 3.6
HOLD_SACRIFICE = 2.3
HOLD_NORMAL    = 1.5
HOLD_FINAL     = 2.6
OUTRO_DURATION = 3.0
FLASH_DECAY    = 0.28

# ── Audio ─────────────────────────────────
SAMPLE_RATE   = 44100
TTS_VOICE     = "en-US-GuyNeural"
TTS_RATE      = "+8%"
TTS_PITCH     = "-2Hz"
GAIN_MUSIC    = 0.34
GAIN_SFX      = 0.75
GAIN_VO       = 0.95
DUCK_DB       = -6.0
MUSIC_ROOTS   = [98.0, 110.0, 73.4, 82.4, 65.4]
MUSIC_BPMS    = [72, 76, 80, 84]

# ── Puzzles ───────────────────────────────
RATING_MIN, RATING_MAX = 1400, 1800
MIN_POPULARITY = 85
MIN_PLAYS      = 500
SOLUTION_MIN, SOLUTION_MAX = 2, 5

# ── Encoding ──────────────────────────────
CRF       = 21
PRESET    = "medium"
AUDIO_BITRATE = "192k"

# ── Features ──────────────────────────────
SHOW_EVAL_BAR       = True
SHOW_COUNTDOWN      = True
SHOW_RATING_REVEAL  = True
SHOW_REACTIONS      = False   # permanently off — do not enable
```

---

## 14. TESTING

Include `tests/` with at least:

1. **Coordinate math** — assert `2*margin + 8*cell == board_px` for sizes
   600, 900, 1200. Assert `square_center(chess.A1)` is bottom-left and
   `square_center(chess.H8)` is top-right.
2. **Puzzle parsing** — a known Lichess row produces the expected position
   after applying the setup move.
3. **Edge cases** — castling, promotion, and en passant each produce frames
   with the correct piece count on the board.
4. **Speech conversion** — `Bxh7+` yields `"bishop takes H 7, check"`.
5. **Audio verification** — a mixed track passes the peak/RMS/dead-air checks.
6. **End-to-end smoke test** — build one hardcoded puzzle, assert the MP4
   exists, has both streams, and is over 200 KB.

Ship one hardcoded puzzle for the smoke test so it runs without the CSV:

```python
SMOKE_PUZZLE = {
    "id": "smoke01",
    "fen": "r1bq1rk1/pp2bppp/2n1pn2/3p4/3P4/2NBPN2/PP3PPP/R1BQ1RK1 w - - 0 9",
    "solution": ["d3h7", "g8h7", "f3g5", "h7g8", "d1h5"],
    "rating": 1650,
    "theme_label": "Greek Gift Sacrifice",
    "themes": ["sacrifice", "greekGift"],
}
```

---

## 15. README.md (user-facing)

Generate this too. It must contain:

1. What the tool does, with a sample frame image
2. Requirements (OS, Python, FFmpeg, RAM)
3. Install steps for Linux, macOS, Windows/WSL
4. Verification commands
5. First run: `python run_batch.py --count 1`
6. All CLI flags in a table
7. Config reference table
8. Voice options and how to preview them
9. Cost breakdown (free vs. Claude captions)
10. Troubleshooting:
    - `cairosvg` import errors → install Cairo system library
    - `ffmpeg not found` → PATH setup
    - edge-tts timeouts → automatic Piper fallback, or `--no-tts`
    - Disk filling → confirm frame cleanup is running
    - Pieces animating to wrong squares → coordinate math, Section 5.2
11. Content licensing note: Lichess puzzles are CC0; generated music and SFX
    are original; board rendering is from python-chess (GPL — note that the
    *output videos* are unaffected, only redistribution of the library code
    carries obligations)

---

## 16. BUILD ORDER

Implement and verify in this sequence. Do not move on until each step's
verification passes.

| Step | Deliverable | Verify by |
|---|---|---|
| 1 | `config.py` | Imports cleanly |
| 2 | `board.py` | Render start position, open the PNG, confirm 900×900 |
| 3 | Coordinate tests | All assertions in Section 14.1 pass |
| 4 | `animate.py` | 30 slide frames; scrub them, piece moves smoothly |
| 5 | `compose.py` | One composed frame; check layout and safe zones |
| 6 | Countdown + outro | Frames render with correct numerals and rating |
| 7 | `sfx.py` | Write each SFX to WAV, listen to each |
| 8 | `music.py` | 20 s bed, listen, confirm it loops without clicks |
| 9 | `speech.py` | Generate one clip, listen, confirm pronunciation |
| 10 | `mixer.py` | Mixed WAV passes peak/RMS/dead-air checks |
| 11 | `encode.py` | Smoke puzzle → MP4, ffprobe shows both streams |
| 12 | `puzzles.py` | Download, filter, print count and 3 samples |
| 13 | `captions.py` | Both API and template modes produce valid output |
| 14 | `queue.py` | Ledger writes atomically, dedupe works |
| 15 | `run_batch.py` | `--count 3` produces 3 verified videos |
| 16 | `README.md` | A fresh machine can follow it start to finish |

---

## 17. COMMON MISTAKES TO AVOID

These are the failure modes most likely to occur. Guard against each.

1. **Using `row.FEN` directly as the puzzle position.** The first move in
   `Moves` must be applied first. Section 4.2.
2. **Guessing the board margin.** It is `15/390` of the image, not 4% or 5%.
   Section 5.2.
3. **Regenerating piece sprites every frame.** Cache them.
4. **Leaving a ghost piece on the source square** during the slide. The
   staging board must have it removed.
5. **En passant leaving the captured pawn visible.** The captured pawn is not
   on the destination square.
6. **Voiceover cut off by the next move.** Measure TTS clip length first, then
   extend holds.
7. **Not deleting frames.** Disk fills after a handful of runs.
8. **Letting one failure kill the batch.** Every puzzle is independent.
9. **Not verifying the audio stream exists** in the final MP4. A silent video
   passes a naive file-exists check.
10. **Burning puzzle IDs before success.** Only mark posted after verification.
11. **Adding reaction overlays.** They are removed. Section 0.
12. **Missing `!!` on the sacrifice.** It is the visual payoff of the format.

---

## 18. DEFINITION OF DONE

The build is complete when:

- `python run_batch.py --count 3` produces 3 MP4s with no manual intervention
- Each MP4 is 1080×1920, 30 fps, has both video and audio streams
- Each video opens with a working 3-2-1 countdown and tick sounds
- The sacrifice move displays `!!` in accent colour
- Voiceover narrates each move clearly and is not clipped by the next move
- Music plays throughout without clipping or dead air
- The eval bar dips on the sacrifice and spikes at mate
- The outro shows the puzzle rating
- No reaction faces appear anywhere
- Each video has a matching `caption.txt` and `meta.json`
- Re-running never repeats a puzzle
- The full test suite passes
- README lets someone set this up from scratch on a clean machine
