# Long-form GM games (YouTube, 1920×1080)

Full games of the greats, replayed move by move: no voiceover, no pauses, no
questions to the viewer. The engine decides the pace. Theory moves go fast,
ordinary moves get a few seconds, and the brilliant or losing moves are held
long enough to land. When that happens a badge pops on the board and the
moment card on the right says what happened. Both players' photos are on
the intro, the player cards and the thumbnail.

```bash
python longform_daily.py --dry-run                   # what would be built/scheduled, and when
python longform_daily.py                             # the autopilot (Task Scheduler runs this)
python longform_daily.py --retry-thumbnail byrne-fischer-1956_tchess  # API retry for an existing scheduled video
python make_longform.py --game byrne-fischer-1956 --brand tchess   # one video by hand
python make_longform.py --catalog                    # rebuild the game queue
python make_longform.py --photos                     # fetch any missing player photos
```

Output lands in `output/longform/<game id>_<brand>/`:
- `video.mp4`
- `thumbnail.jpg`
- `meta.json`: marks, YouTube chapters, music used and render time.

The owner/Codex verification and dashboard deployment record is in
the internal long-form handover notes (not published).

🔴 **This module never touches the shorts pipeline.** It only reads root
`config.py` and imports `src/` helpers:
- the board renderer, sfx and music decoding;
- the YouTube token loader and the pinned-channel guard from `src/publisher.py`;
- a best-effort write of `longform.json` through `src/status_bridge.py`.

It has its own output folder, data folder (`data/longform/`), ledger, log,
lock and scheduled task.

## Pipeline

| Step | File | What it does |
|---|---|---|
| Library | `library.py` | Header index of ~139k unique games from `data/longform/pgn/` (legends) and `data/gm_games/` (modern, read only) |
| Players | `players.py` | Star registry (PGN spellings → canonical names), portraits from Wikipedia/Commons with licence and author in `data/longform/photos/credits.json` |
| Catalogue | `catalog.py` | 28 curated famous games first, then ~960 scored decisive star-vs-star games. Channels get alternate games and never share one |
| Engine | `engine.py` | Stockfish on every position, then a deep re-check around every mark and every big eval jump. Cached in `data/longform/analysis/` |
| Judgement | `engine.judge` | `!!` sacrifice that is still best (including leaving an attacked piece en prise, like Be6!!) · `!` only move · `?!` `?` `??` · `#` |
| Pacing | `render.pacing` | Seconds per ply from the judgement, scaled toward 7.5–11 min |
| Frames | `frame.py` | Board + eval bar on the left. Brand, player cards with photos, opening, move list and moment card on the right |
| Render | `render.py` | Raw RGB piped into ffmpeg. A held position is one frame written N times. Loudness normalised to -15 LUFS |
| Thumbnail | `thumbnail.py` | The real position before the biggest sacrifice, with the move arrow, big words and both faces. AI only paints the background |
| Metadata | `metadata.py` | Title, description (chapters, key moments, photo credits, app link) and tags. Built from PGN headers and engine marks only |
| Publish | `publisher.py` | API upload as private with `publishAt`; YouTube makes it public at the slot. API thumbnail upload, playlists and ledger |

The shorts pipeline uploads as public at its scheduled task time. Long-form
uploads ahead of time so YouTube can process the full video and publish it
without the laptop being awake at the public slot. `publishAt` requires a
private video; unlisted is not used. The `--retry-thumbnail` command uses the
same channel-bound API credentials for a previously scheduled upload and
updates the ledger only after a successful response.

## Engine: why it is built this way

- **Single-thread engines with a node limit, never a time limit.** A
  multi-threaded search with a time cap gave a different verdict on every run.
  One run called Kasparov's 28.Qc3 a blunder and the next one didn't. A `??` on
  a famous move has to come out the same every time.
- **The engine's own best move is never an error.** A deep search of one
  position and a shallow search of the next can disagree. Without this rule the
  best move itself got marked `??`.
- **`??` only when the mover ends up worse.** Going from +8 to +2.8 is a `?`.
- **`consistent()` back-propagates evals through forcing stretches.** If the
  played move was the engine's best, the position is worth what the next one is
  worth. Without this the bar jumped +7 → +1 → +7 over three moves of a
  forced line. `!!` still uses the raw eval: a sacrifice is brilliant because
  the position did not yet LOOK won.
- **Light first pass, deep where it matters.**
  - Theory positions get 0.3M nodes.
  - Every other position gets 2M.
  - Positions around marks and eval jumps get 12M.
  - Compared with a flat 6M/20M: same marks on Kasparov–Topalov, and Be6!! now
    found in Byrne–Fischer, at 40–55% of the time.

## Cost per video (this laptop: i5-1245U, 16 GB)

| Stage | Time | Memory |
|---|---|---|
| Engine analysis (new game) | ~2.5–3.5 min | 6 engines, ~1.6 GB total |
| Render + encode | ~2 min | ~1 GB (python ~220 MB + ffmpeg, 6 threads) |
| Upload | ~1 min (35 MB) | small |

So a new video takes about 5–6 minutes; a re-render of an analysed game about
2 minutes. The autopilot runs **below normal priority** (the engines and ffmpeg
inherit it), at 04:00 PKT when the laptop is idle, with a 16:00 backup run.

## Thumbnail background

The owner chose not to use a paid image API, so everything is built locally:
- the board and the move arrow;
- the words and both player photos;
- the background: the same position, enlarged, blurred and lit with the
  brand colours (`thumbnail._free_bg`).

The cost is $0. `lfconfig.THUMB_IMAGE_MODELS` is empty on purpose.

## Facebook reels (Taha Chess TV Page only)

The same games, re-cut **9:16** for Facebook (`frame_vertical.VFrames`). The
screen is clean:
- brand;
- title and event;
- black's card;
- the 960 px board with badges;
- white's card;
- the last move, big ("17... Be6!!"), with what it was under it.

There is no eval bar and no move list. The bottom and top of the frame are
left clear for Facebook's own caption and header.

```bash
python make_longform.py --game <id> --brand tahachess --reel   # one reel by hand
python longform_daily.py --facebook --dry-run                  # what would post, or why not
```

- The 04:00 run renders the next reel (`facebook.prepare`). It re-cuts the
  oldest Taha Chess YouTube game without one; the analysis is cached, so this
  takes 2–3 min.
- The "ChessReel Longform FB" task (05:30, retry 06:20 PKT) posts it
  (`facebook.post`) through `src.publisher.post_facebook`. That is the shorts'
  Playwright composer path, unchanged.
- Rules, all covered by `tests/test_longform.py::FacebookRules`:
  - a game never goes to Facebook before its YouTube video is public;
  - at most one reel per PKT day;
  - reels (`"fmt": "reel"`) are never treated as YouTube uploads;
  - it waits while the shorts autopilot holds `publish.lock`;
  - a composer timeout becomes `check_page`, and a person looks at the Page
    before anything is re-posted.
