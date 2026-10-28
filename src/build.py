"""Orchestration: one puzzle in, one finished video out.

build_one() never raises. Every failure returns a result dict so a single bad
puzzle cannot take down a 30-video batch.
"""

import json
import math
import shutil
import time
import traceback
from pathlib import Path as _P

import chess

import config
from src import animate, board as board_mod, captions, compose, encode
from src import mixer, puzzles as puzzles_mod, queue as ledger
from src import reactions as reactions_mod, speech
from src.mixer import AudioEvent


def _solver_move(index: int) -> bool:
    """Solution plies alternate; the solver plays the even ones."""
    return index % 2 == 0


def _subtitle_for(index: int, is_mate: bool, total: int) -> str:
    if is_mate:
        return "Checkmate."
    if index == 0:
        return "The sacrifice."
    if not _solver_move(index):
        return "Forced reply."
    if index == total - 1:
        return "And it lands."
    return "The attack continues."


def plan_timeline(puzzle, voiceovers, reaction_slot=None, hook_duration=None,
                  hold_final=None, outro_duration=None, log=print):
    """Compute per-move hold durations and the total video length.

    Voiceover clips are generated before this runs so a hold can be extended to
    outlast its narration — otherwise the next move cuts the line off.

    `reaction_slot` is (move_index, clip_duration): that move's hold is extended
    to fit voiceover, then the reaction, then a small tail — the clip decides
    the slot rather than a fixed length, so total video length varies.
    """
    hook_duration = config.HOOK_DURATION if hook_duration is None else hook_duration
    # A promo reel cuts to the end card the moment the line is over, so its last
    # hold is the narration's own length rather than a fixed 2.6s of stillness.
    hold_final = config.HOLD_FINAL if hold_final is None else hold_final
    outro_duration = (config.OUTRO_DURATION if outro_duration is None
                      else outro_duration)
    solution = puzzle["solution"]
    r_idx, r_dur = reaction_slot if reaction_slot else (None, 0.0)

    holds, floors = [], []
    for i, clip in enumerate(voiceovers):
        if i == 0:
            base = config.HOLD_SACRIFICE
        elif i == len(solution) - 1:
            base = hold_final
        else:
            base = config.HOLD_NORMAL
        floor = config.VO_DELAY_AFTER_MOVE + clip.duration + config.VO_TAIL
        if i == r_idx and r_dur > 0:
            # slide → land → sfx → voiceover → gap → reaction → tail
            floor = (config.VO_DELAY_AFTER_MOVE + clip.duration
                     + config.REACTION_GAP + r_dur + config.REACTION_TAIL)
        floors.append(floor)
        holds.append(max(base, floor))

    def total_of(hs):
        return (hook_duration + len(hs) * config.SLIDE_DURATION
                + sum(hs) + outro_duration)

    total = total_of(holds)

    # Long solutions with slow narration can overshoot the format. Trim only
    # the slack above each hold's floor, never the narration or the reaction.
    if total > config.DURATION_MAX:
        slack = sum(h - f for h, f in zip(holds, floors))
        excess = total - config.DURATION_MAX
        if slack > 0:
            keep = max(0.0, 1.0 - excess / slack)
            holds = [f + (h - f) * keep for h, f in zip(holds, floors)]
            total = total_of(holds)
    if total > config.DURATION_MAX:
        note = "reaction-bound" if r_dur > 0 else "narration-bound"
        log(f"        warn    duration {total:.1f}s over "
            f"{config.DURATION_MAX:.0f}s target ({note})")
    return holds, total


def plan_fast_game_timeline(solution, hook_duration=None):
    """Short, fixed pacing for a full-game replay variant."""
    hook_duration = config.GM_HOOK_DURATION if hook_duration is None else hook_duration
    holds = []
    for i in range(len(solution)):
        if i == 0:
            holds.append(config.GM_HOLD_FIRST)
        elif i == len(solution) - 1:
            holds.append(config.GM_HOLD_LAST)
        else:
            holds.append(config.GM_HOLD_MOVE)
    total = (hook_duration + len(solution) * config.GM_SLIDE_DURATION
             + sum(holds) + config.GM_OUTRO_DURATION)
    return holds, total


def _leading_index(name: str):
    """Return the leading NNNN_ number of a folder name, or None."""
    head = name.split("_", 1)[0]
    return int(head) if head.isdigit() else None


def next_index(output_dir) -> int:
    """Next global folder number = highest existing NNNN_ prefix + 1."""
    output_dir = _P(output_dir)
    highest = 0
    if output_dir.exists():
        for child in output_dir.iterdir():
            if child.is_dir():
                idx = _leading_index(child.name)
                if idx is not None:
                    highest = max(highest, idx)
    return highest + 1


def resolve_out_root(output_dir, pid: str, seq=None):
    """Pick the output folder for a puzzle.

    Reuses an existing folder for this puzzle id (keeps builds idempotent and
    lets retries land in place); otherwise creates a numbered folder so batches
    read 0001_<id>, 0002_<id>, ...
    """
    output_dir = _P(output_dir)
    # Reuse an existing folder for this puzzle — bare <id> or NNNN_<id>.
    if (output_dir / pid).is_dir():
        return output_dir / pid
    for child in sorted(output_dir.glob(f"*_{pid}")) if output_dir.exists() else []:
        if child.is_dir():
            return child

    if not config.OUTPUT_NUMBERING:
        return output_dir / pid
    if seq is None:
        seq = next_index(output_dir)
    return output_dir / f"{seq:0{config.OUTPUT_INDEX_WIDTH}d}_{pid}"


def build_one(puzzle: dict, *, voice=None, use_api=True, keep_frames=False,
              output_dir=None, ledger_path=None, seq=None,
              variant=None, log=print) -> dict:
    """Build one video. Returns a result dict and never raises.

    `ledger_path` overrides the dedupe ledger, so tests and throwaway runs do
    not mark puzzles as posted in the real one. `seq` is the 1-based batch
    index used to number the output folder; omit it to auto-number (or reuse
    an existing folder for this puzzle). `variant` selects the output format
    ("simple" = original; "reaction" = smaller board + bottom clip band).
    """
    started = time.time()
    pid = puzzle["id"]
    variant = variant or config.DEFAULT_VARIANT
    V = config.variant(variant)
    out_root = resolve_out_root(output_dir or config.OUTPUT_DIR, pid, seq)
    frames_dir = out_root / "frames"
    audio_dir = out_root / "audio"

    try:
        frames_dir.mkdir(parents=True, exist_ok=True)
        audio_dir.mkdir(parents=True, exist_ok=True)

        start_board = chess.Board(puzzle["fen"])
        solution = [chess.Move.from_uci(u) for u in puzzle["solution"]]
        game_meta = puzzle.get("game_meta")

        if V.get("full_game"):
            if game_meta is None:
                game_meta = puzzles_mod.load_full_game(puzzle["game_url"], log=log)
            start_board = chess.Board(game_meta["start_fen"])
            solution = [chess.Move.from_uci(u) for u in game_meta["moves"]]

        # Recompute the brilliant index when a puzzle dict lacks it (e.g. a
        # rebuild from meta.json), so the badge does not silently vanish.
        if "brilliant_index" in puzzle:
            brilliant_idx = puzzle["brilliant_index"]
        else:
            brilliant_idx = puzzles_mod.brilliant_index(
                puzzle["fen"], puzzle["solution"])

        if game_meta is not None:
            probe = start_board.copy()
            prefix_idx = None
            for i, move in enumerate(solution):
                if probe.fen() == puzzle["fen"]:
                    prefix_idx = i
                    break
                probe.push(move)
            if prefix_idx is not None and brilliant_idx is not None:
                brilliant_idx = prefix_idx + brilliant_idx
            else:
                brilliant_idx = None
            puzzle = dict(
                puzzle,
                fen=start_board.fen(),
                solution=[move.uci() for move in solution],
                series_label=game_meta.get("black_title") or "GM",
                theme_label="",
                top_label=game_meta.get("black_label", game_meta.get("black", "")),
                top_sub_label=game_meta.get("black_elo", ""),
                bottom_label=game_meta.get("white_label", game_meta.get("white", "")),
                bottom_sub_label=game_meta.get("white_elo", ""),
                game_result=game_meta.get("result"),
                end_summary=game_meta.get("outcome", ""),
            )
            V = {**V,
                 "series_label": puzzle["series_label"],
                 "top_label": puzzle["top_label"],
                 "top_sub_label": puzzle["top_sub_label"],
                 "bottom_label": puzzle["bottom_label"],
                 "bottom_sub_label": puzzle["bottom_sub_label"],
                 "end_summary": puzzle["end_summary"],
                 "show_cta": False}

        # Cut the reel at the sacrifice. brilliant_index() only ever returns 0
        # ("only the first solution move is ever considered"), so this leaves a
        # ONE-MOVE video: the sacrifice, the !! badge and the reaction clip are
        # the whole payoff and the follow-up moves are anticlimax. It must
        # happen before narration is synthesised — holds are planned from the
        # clip list, so a later truncation would leave the timeline stretched
        # for moves that are no longer rendered.
        if V.get("stop_after_brilliant") and brilliant_idx is not None:
            solution = solution[: brilliant_idx + 1]
            puzzle = dict(puzzle, solution=[m.uci() for m in solution])

        if V.get("full_game"):
            clips = []
            speech_meta = []
            all_sans = game_meta["sans"] if game_meta else []
            reaction = None
            react_idx = None
            holds, duration = plan_fast_game_timeline(
                solution, hook_duration=V.get("hook_duration"))
        else:
            # ── 1. Narration first: hold lengths depend on clip durations ──────
            clips = []
            walker = start_board.copy()
            speech_meta = []
            for i, move in enumerate(solution):
                text, san = speech.move_to_speech(walker, move)
                clip = speech.synthesize(text, audio_dir / f"vo_{i:02d}", voice)
                clips.append(clip)
                speech_meta.append({"san": san, "text": text, "source": clip.source,
                                    "duration": round(clip.duration, 2)})
                walker.push(move)

            engines = {c.source for c in clips}
            log(f"        speech  {len(clips)} clips ... {', '.join(sorted(engines))}")

            all_sans = [m["san"] for m in speech_meta]

            # Reaction clip: band variants only. WHICH move it lands on is a
            # variant decision (reaction_index) — the same puzzle reacting to
            # the sacrifice and reacting to the mate are two different reels.
            # Missing or unusable clips leave reaction=None and the video
            # builds without one.
            react_idx = reaction_index(V, brilliant_idx, len(solution))
            reaction = _resolve_reaction(puzzle, V, react_idx, log)
            reaction_slot = ((react_idx, reaction["duration"])
                             if reaction else None)
            hook_duration = (config.WATCH_DURATION if V["opening"] == "watch"
                             else config.HOOK_DURATION)

            holds, duration = plan_timeline(
                puzzle, clips, reaction_slot=reaction_slot,
                hook_duration=hook_duration,
                hold_final=V.get("hold_final"),
                outro_duration=(V.get("outro_duration", config.OUTRO_DURATION)
                                if V.get("show_outro", True) else 0.0),
                log=log)
            # A variant can ask for room to read. Applied AFTER planning so the
            # narration and reaction floors are still respected — scaling those
            # up is fine, scaling them down would cut a line off.
            scale = V.get("hold_scale")
            if scale and scale > 1:
                holds = [h * scale for h in holds]

        # ── 2. Frames + audio events, rendered together so they stay in sync ─
        # The promo banner and the theme label share the top row of the canvas,
        # so the RENDERED copy drops the label. caption.txt and meta.json keep
        # it: the motif is still what the post is about, it is just not printed
        # on a frame that already has the app's name across it.
        render_puzzle = (dict(puzzle, theme_label="")
                         if V.get("show_promo_banner") else puzzle)

        events = []
        opening = _OPENINGS[V["opening"]]
        frame_no = opening(render_puzzle, start_board, frames_dir, events, V, log)
        frame_no = _render_moves(render_puzzle, start_board, solution, clips,
                                 holds, frames_dir, events, frame_no,
                                 brilliant_idx, V, reaction, all_sans,
                                 react_idx=react_idx)
        # 🔴 A PROMO REEL HAS NO RATING SCREEN. show_outro=False skips the reveal
        # (and the slow zoom it sat on) so the last move cuts straight to the end
        # card. gm_games keeps it — that screen is "WHITE WINS", the actual
        # ending of a full-game replay, not a puzzle's difficulty number.
        if V.get("show_outro", True):
            frame_no = _render_outro(render_puzzle, start_board, solution,
                                     frames_dir, frame_no, V, all_sans)
        if V.get("show_endcard"):
            frame_no = _render_endcard(frames_dir, frame_no)

        actual_duration = frame_no / config.FPS
        log(f"        frames  {frame_no} ....... {actual_duration:.1f}s")

        # ── 3. Audio ───────────────────────────────────────────────────────
        wav_path = audio_dir / "mix.wav"
        report = mixer.mix(events, actual_duration, wav_path, seed_key=pid,
                           mood=V.get("music_mood"))
        flag = "ok" if report["ok"] else "CHECK"
        log(f"        audio   mixed ...... peak {report['peak']:.2f}  "
            f"rms {report['rms']:.3f}  {report['music']}  {flag}")

        # ── 4. Encode and verify ───────────────────────────────────────────
        mp4 = out_root / "video.mp4"
        dur_min = 5.0 if V.get("full_game") else None
        dur_max = 300.0 if V.get("full_game") else None
        info = encode.encode_and_verify(
            frames_dir, wav_path, mp4,
            crf=V.get("crf"), preset=V.get("preset"),
            audio_bitrate=V.get("audio_bitrate"), audio_channels=V.get("audio_channels"),
            duration_min=dur_min, duration_max=dur_max,
        )
        log(f"        encode  {info['width']}x{info['height']} ... "
            f"{info['filesize']/1e6:.1f} MB  {info['duration']:.1f}s")

        # ── 5. Caption + metadata ──────────────────────────────────────────
        caption = captions.generate(puzzle, use_api=use_api, log=log)
        caption_path = out_root / "caption.txt"
        captions.write_caption_file(caption_path, puzzle, caption,
                                    info["duration"])
        log(f"        caption {caption['source']} ...... "
            f"{'needs rerun' if caption['needs_caption'] else 'ok'}")

        meta = {
            "puzzle_id": pid,
            "variant": variant,
            "fen": puzzle["fen"],
            "solution": puzzle["solution"],
            # Raw pre-setup Lichess FEN/Moves (setup move first) — what the
            # PuzzleFlow app needs, distinct from the post-setup fen/solution
            # above that this renderer animates. Falls back to the post-setup
            # values when a puzzle dict has no CSV-sourced raw pair (e.g. the
            # hardcoded --smoke puzzle), which is not real Lichess data.
            "lichess_fen": puzzle.get("lichess_fen", puzzle["fen"]),
            "lichess_moves": puzzle.get("lichess_moves", " ".join(puzzle["solution"])),
            "san": captions.san_solution(puzzle["fen"], puzzle["solution"]),
            "rating": puzzle["rating"],
            "themes": puzzle.get("themes", []),
            "theme_label": puzzle["theme_label"],
            "series_label": puzzle.get("series_label", V.get("series_label", "")),
            "top_label": puzzle.get("top_label"),
            "top_sub_label": puzzle.get("top_sub_label"),
            "bottom_label": puzzle.get("bottom_label"),
            "bottom_sub_label": puzzle.get("bottom_sub_label"),
            "end_summary": puzzle.get("end_summary"),
            "white": game_meta.get("white") if game_meta else None,
            "black": game_meta.get("black") if game_meta else None,
            "result": game_meta.get("result") if game_meta else None,
            "termination": game_meta.get("termination") if game_meta else None,
            "sacrificed_piece": puzzle.get("sacrificed_piece"),
            "brilliant_index": brilliant_idx,
            "reaction": ({"category": reaction["clip"].category,
                          "file": reaction["clip"].file,
                          "duration": reaction["duration"]}
                         if reaction else None),
            "game_url": puzzle.get("game_url", ""),
            "video": {**info, "fps": config.FPS, "frames": frame_no},
            "audio": report,
            "speech": speech_meta,
            "caption": caption,
            "renderer": board_mod.active_renderer(),
            "build_seconds": round(time.time() - started, 1),
        }
        (out_root / "meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8")

        # ── 6. Only now is the puzzle safely spent ─────────────────────────
        if not keep_frames:
            shutil.rmtree(frames_dir, ignore_errors=True)
        ledger.record_success(puzzle, mp4, caption_path, info["duration"],
                              path=ledger_path)

        log(f"        OK      {mp4}")
        return {"status": "ok", "puzzle_id": pid, "video": str(mp4),
                "duration": info["duration"], "filesize": info["filesize"],
                "seconds": round(time.time() - started, 1),
                "needs_caption": caption["needs_caption"]}

    except Exception as exc:
        # Frames are deliberately left in place for debugging a failed build.
        log(f"        FAILED  {type(exc).__name__}: {exc}")
        return {"status": "failed", "puzzle_id": pid, "error": str(exc),
                "traceback": traceback.format_exc(),
                "seconds": round(time.time() - started, 1)}


# ── Frame rendering ───────────────────────────────────────────────────────

def _save(frame, frames_dir, index):
    # compress_level=1 keeps PNG writing fast; the frames are deleted after
    # encoding anyway, so file size does not matter.
    frame.save(frames_dir / f"f{index:05d}.png", compress_level=1)


def reaction_index(V, brilliant_idx, n_moves):
    """Which move the clip plays on, or None for no reaction.

    The clip is the punchline, so WHERE it lands changes what the reel is
    about: on the sacrifice it reacts to the idea, on the last move it reacts
    to the result. Those are different videos from the same puzzle, which is
    the cheapest variety this pipeline has.
    """
    if V["reaction_band"] is None or not n_moves:
        return None
    where = V.get("reaction_at", "brilliant")
    if where == "final":
        return n_moves - 1
    if where == "brilliant":
        return brilliant_idx          # None when the puzzle has no !! move
    raise ValueError(f"unknown reaction_at {where!r}")


def _resolve_reaction(puzzle, V, at_index, log):
    """Select and decode a reaction clip, or return None. Never raises.

    Timing (the hold length) uses the manifest duration; the decoded frames and
    audio are only for display and mixing.
    """
    if at_index is None:
        return None
    clip = reactions_mod.select(puzzle)
    if clip is None:
        log("        reaction none available")
        return None
    frames = reactions_mod.load_frames(clip)
    if not frames:
        log("        reaction decode failed — building without it")
        return None
    log(f"        reaction {clip.category}/{clip.file} ... {clip.duration:.2f}s")
    return {
        "clip": clip,
        "frames": frames,
        "audio": reactions_mod.load_audio(clip),
        "duration": clip.duration,     # manifest duration drives timing
    }


def _band_strip(V, sans, highlight=None):
    """Idle band content for variant B — the line played so far. None for A."""
    if V["reaction_band"] is None:
        return None
    return compose.render_band_strip(sans, highlight=highlight)


def _render_hook_countdown(puzzle, start_board, frames_dir, events, V, log) -> int:
    """Variant A opening: 3-2-1 countdown that invites the viewer to solve.

    A countdown is the right signal only when the format asks the viewer to
    find the move; variant B uses the watch opening instead.
    """
    n = int(round(config.HOOK_DURATION * config.FPS))
    board_img = board_mod.render_board(start_board, V["board_px"])
    eval_value = compose.simple_eval(start_board)
    turn = "WHITE TO PLAY" if start_board.turn == chess.WHITE else "BLACK TO PLAY"
    dots_total = len(puzzle["solution"]) + 1 if V["show_dots"] else 0
    subtitles = tuple(V.get("subtitles") or config.HOOK_SUBTITLES)

    step = config.COUNTDOWN_STEP
    numerals = ["3", "2", "1"]
    for k in range(len(numerals)):
        events.append(AudioEvent(k * step, "sfx", "tick"))

    for i in range(n):
        t = i / config.FPS
        idx = int(t // step)
        if idx < len(numerals):
            glyph = numerals[idx]
            within = (t - idx * step) / step
            # Pop: starts large, settles to 1.0 over the numeral's second.
            scale = 1.0 + (config.COUNTDOWN_POP_SCALE - 1.0) * max(0.0, 1 - within * 3)
            ring = 1.0 - within
        else:
            glyph = "?"
            within = (t - len(numerals) * step) / max(1e-6, config.COUNTDOWN_QMARK)
            scale = 1.0 + 0.12 * math.sin(within * math.pi)
            ring = 0.0

        state = compose.FrameState(
            board_img=board_img,
            theme_label=puzzle["theme_label"],
            headline=turn,
            subtitle=subtitles[int(t // config.SUBTITLE_ALTERNATE) % 2]
            if V["show_subtitle"] else "",
            eval_value=eval_value,
            dots_total=dots_total, dots_active=0,
            countdown=glyph, countdown_scale=scale, countdown_progress=ring,
            board_y_offset=V["board_y_offset"], headline_y=V["headline_y"],
            show_watermark=V["show_watermark"],
            series_label=V.get("series_label", ""),
            show_eval_bar=V.get("show_eval_bar", config.SHOW_EVAL_BAR),
            show_promo_banner=V.get("show_promo_banner", False),
            show_headline=V.get("show_headline", True),
        )
        _save(compose.compose_frame(state), frames_dir, i)
    return n


def _render_hook_watch(puzzle, start_board, frames_dir, events, V, log) -> int:
    """Variant B opening: a short static hold that says *watch*, not *solve*.

    Under two seconds, no countdown, no tick sounds — a countdown would ask
    the viewer to find the move, the wrong signal for the reaction format.
    """
    n = int(round(config.WATCH_DURATION * config.FPS))
    board_img = board_mod.render_board(start_board, V["board_px"])
    dots_total = len(puzzle["solution"]) + 1 if V["show_dots"] else 0
    band = _band_strip(V, [])          # no moves played yet

    for i in range(n):
        state = compose.FrameState(
            board_img=board_img,
            theme_label=puzzle["theme_label"],
            headline="WATCH CLOSELY",
            subtitle="A brilliant sacrifice." if V["show_subtitle"] else "",
            dots_total=dots_total, dots_active=0,
            board_y_offset=V["board_y_offset"], headline_y=V["headline_y"],
            band_content=band,
            show_watermark=V["show_watermark"],
            series_label=V.get("series_label", ""),
            show_eval_bar=V.get("show_eval_bar", config.SHOW_EVAL_BAR),
            show_promo_banner=V.get("show_promo_banner", False),
            show_headline=V.get("show_headline", True),
        )
        _save(compose.compose_frame(state), frames_dir, i)
    return n


def _render_hook_none(puzzle, start_board, frames_dir, events, V, log) -> int:
    """Variant "app" opening: a brief silent hold, no text at all.

    The in-app video is not trying to hook a scroll-past viewer, so there is
    no countdown, no "watch closely" prompt and no CTA — just the puzzle
    position, matching CHESS_APP_BLUEPRINT.md Section 13.1.
    """
    hook_duration = V.get("hook_duration", config.APP_HOOK_DURATION)
    n = int(round(hook_duration * config.FPS))
    board_img = board_mod.render_board(start_board, V["board_px"])
    dots_total = len(puzzle["solution"]) + 1 if V["show_dots"] else 0

    for i in range(n):
        state = compose.FrameState(
            board_img=board_img,
            dots_total=dots_total, dots_active=0,
            board_y_offset=V["board_y_offset"], headline_y=V["headline_y"],
            show_watermark=V["show_watermark"],
            series_label=V.get("series_label", ""),
            show_eval_bar=V.get("show_eval_bar", config.SHOW_EVAL_BAR),
            show_promo_banner=V.get("show_promo_banner", False),
            show_headline=V.get("show_headline", True),
        )
        _save(compose.compose_frame(state), frames_dir, i)
    return n


_OPENINGS = {
    "countdown": _render_hook_countdown,
    "watch": _render_hook_watch,
    "none": _render_hook_none,
}


def _render_moves(puzzle, start_board, solution, clips, holds, frames_dir,
                  events, frame_no, brilliant_idx=None, V=None, reaction=None,
                  all_sans=None, react_idx=None) -> int:
    """Slide + hold for each solution move, scheduling its audio.

    On the brilliant move only, and only in a band variant, a reaction clip
    plays in the bottom band strictly after the voiceover finishes; that move's
    hold was pre-extended to fit it. Every other band frame shows the line so
    far so the band never reads as dead space.
    """
    V = V or config.variant(config.DEFAULT_VARIANT)
    board_px = V["board_px"]
    dots_total = len(solution) + 1 if V["show_dots"] else 0
    show_sub = V["show_subtitle"]
    top_label = V.get("top_label", "") if V.get("full_game") else ""
    top_sub_label = V.get("top_sub_label", "") if V.get("full_game") else ""
    bottom_label = V.get("bottom_label", "") if V.get("full_game") else ""
    bottom_sub_label = V.get("bottom_sub_label", "") if V.get("full_game") else ""
    end_summary = V.get("end_summary", "") if V.get("full_game") else ""
    all_sans = all_sans or []
    live = start_board.copy()
    slide_duration = config.GM_SLIDE_DURATION if V.get("full_game") else config.SLIDE_DURATION

    def _state(**kw):
        kw.setdefault("theme_label", puzzle["theme_label"])
        kw.setdefault("dots_total", dots_total)
        kw.setdefault("top_label", top_label)
        kw.setdefault("top_sub_label", top_sub_label)
        kw.setdefault("bottom_label", bottom_label)
        kw.setdefault("bottom_sub_label", bottom_sub_label)
        kw["board_y_offset"] = V["board_y_offset"]
        kw["headline_y"] = V["headline_y"]
        kw["show_watermark"] = V["show_watermark"]
        return compose.FrameState(**kw)

    for i, move in enumerate(solution):
        slide_start = frame_no / config.FPS
        is_capture = live.is_capture(move)
        san = live.san(move)

        # Band shows the line through this move (idle content for variant B).
        strip = _band_strip(V, all_sans[:i + 1], highlight=i)

        # Slide.
        events.append(AudioEvent(slide_start, "sfx", "whoosh"))
        slide_frames = list(animate.build_slide_frames(
            live, move, board_px, config.FPS, slide_duration))
        label, colour = compose.move_label(san, i == 0)
        # The variant decides whether the notation is drawn at all; the label is
        # still computed because its COLOUR drives nothing else and callers below
        # read both. See VARIANTS["promo_guess"]["show_move_label"].
        move_label = label if V.get("show_move_label", True) else ""
        eval_before = compose.gm_eval(live) if V.get("full_game") else compose.simple_eval(live)

        for img in slide_frames:
            _save(compose.compose_frame(_state(
                board_img=img, headline=move_label, headline_color=colour,
                eval_value=eval_before, dots_active=i + 1, band_content=strip,
                series_label=V.get("series_label", ""),
                show_eval_bar=V.get("show_eval_bar", config.SHOW_EVAL_BAR),
                show_promo_banner=V.get("show_promo_banner", False),
                show_headline=V.get("show_headline", True),
            )), frames_dir, frame_no)
            frame_no += 1

        # Landed position.
        after, lastmove, check_sq = animate.landed_board(live, move)
        landed_at = frame_no / config.FPS
        is_mate = after.is_checkmate()

        events.append(AudioEvent(landed_at, "sfx",
                                 "capture" if is_capture else "move"))
        if is_mate:
            events.append(AudioEvent(landed_at + config.SFX_CHECK_DELAY, "sfx", "mate"))
        elif after.is_check():
            events.append(AudioEvent(landed_at + config.SFX_CHECK_DELAY, "sfx", "check"))
        if clips:
            events.append(AudioEvent(landed_at + config.VO_DELAY_AFTER_MOVE,
                                     "vo", clips[i]))

        board_img = board_mod.render_board(after, board_px,
                                           lastmove=lastmove, check=check_sq)
        eval_after = compose.gm_eval(after) if V.get("full_game") else compose.simple_eval(after)
        subtitle = _subtitle_for(i, is_mate, len(solution)) if show_sub else ""
        flash_this_move = (i == 0) or is_mate

        is_brilliant = (i == brilliant_idx)
        badge_square = move.to_square if is_brilliant else None

        # The badge marks the brilliant move; the CLIP lands wherever the
        # variant put it, which is not always the same move.
        react_this = reaction is not None and i == react_idx
        if react_this:
            react_start = (config.VO_DELAY_AFTER_MOVE + clips[i].duration
                           + config.REACTION_GAP)             # relative to hold
            react_frames = reaction["frames"]
            react_audio = reaction["audio"]
            if react_audio.size:
                events.append(AudioEvent(landed_at + react_start,
                                         "reaction", react_audio))

        hold_frames = int(round(holds[i] * config.FPS))
        for k in range(hold_frames):
            elapsed = k / config.FPS
            flash = 0.0
            if flash_this_move:
                flash = max(0.0, 1.0 - elapsed / config.FLASH_DECAY)

            # Badge pops in on landing, then holds at 1.0 for the rest.
            badge_scale = 1.0
            if is_brilliant and elapsed < config.BRILLIANT_POP:
                badge_scale = animate.ease_out_back(
                    elapsed / config.BRILLIANT_POP, config.BRILLIANT_OVERSHOOT)

            # During the reaction window the band shows the clip; otherwise the
            # line so far. The clip is never looped — if it is shorter than the
            # window, the strip simply returns.
            band = strip
            if react_this and elapsed >= react_start:
                fi = int(round((elapsed - react_start) * config.FPS))
                if fi < len(react_frames):
                    band = react_frames[fi]

            _save(compose.compose_frame(_state(
                board_img=board_img, headline=move_label, headline_color=colour,
                subtitle=subtitle, eval_value=eval_after, dots_active=i + 1,
                flash=flash, brilliant_square=badge_square,
                brilliant_scale=badge_scale, band_content=band,
                series_label=V.get("series_label", ""),
                show_eval_bar=V.get("show_eval_bar", config.SHOW_EVAL_BAR),
                show_promo_banner=V.get("show_promo_banner", False),
                show_headline=V.get("show_headline", True),
            )), frames_dir, frame_no)
            frame_no += 1

        live = after
    return frame_no


def _render_endcard(frames_dir, frame_no) -> int:
    """Full-screen TChess card after the outro: features, Play, tchess.app/android.

    No audio event is scheduled. The music bed already runs the whole video and
    mixer.mix is handed the duration computed from the FINAL frame count, so
    these frames are scored automatically.
    """
    n = int(round(config.ENDCARD_DURATION * config.FPS))
    fade = max(1, int(round(config.ENDCARD_FADE * config.FPS)))
    for i in range(n):
        _save(compose.endcard_frame(min(1.0, (i + 1) / fade)),
              frames_dir, frame_no)
        frame_no += 1
    return frame_no


def _render_outro(puzzle, start_board, solution, frames_dir, frame_no, V=None,
                  all_sans=None) -> int:
    """Rating reveal with a slow zoom on the final position."""
    V = V or config.variant(config.DEFAULT_VARIANT)
    final = start_board.copy()
    for move in solution:
        final.push(move)
    check_sq = final.king(final.turn) if final.is_check() else None
    board_img = board_mod.render_board(
        final, V["board_px"], lastmove=solution[-1], check=check_sq)

    n = int(round(V.get("outro_duration", config.OUTRO_DURATION) * config.FPS))
    dots_total = len(solution) + 1 if V["show_dots"] else 0
    subtitle = "Did you solve it?" if V["opening"] == "countdown" else "A brilliant finish."
    band = _band_strip(V, all_sans or [])       # the full line
    show_cta = V.get("show_cta", True)

    if V.get("full_game"):
        end_summary = V.get("end_summary", "")
        result = puzzle.get("game_result", V.get("result", ""))
        if result == "1-0":
            headline = puzzle.get("white_label", V.get("bottom_label", "")).upper() + " WINS"
        elif result == "0-1":
            headline = puzzle.get("black_label", V.get("top_label", "")).upper() + " WINS"
        elif result == "1/2-1/2":
            headline = "DRAW"
        else:
            headline = end_summary.upper()
        headline = f"  {headline}  "
        headline_color = config.ACCENT
        footer_text = end_summary
    else:
        headline = f"RATED {puzzle['rating']}"
        headline_color = config.ACCENT
        footer_text = "Follow for daily tactics" if show_cta else ""

    for i in range(n):
        p = i / max(1, n - 1)
        state = compose.FrameState(
            board_img=board_img,
            theme_label=puzzle["theme_label"],
            headline=headline,
            headline_color=headline_color,
            subtitle=subtitle if V["show_subtitle"] else "",
            footer=footer_text,
            eval_value=compose.gm_eval(final) if V.get("full_game") else compose.simple_eval(final),
            dots_total=dots_total, dots_active=dots_total - 1,
            zoom=1.0 + (config.OUTRO_ZOOM - 1.0) * p,
            board_y_offset=V["board_y_offset"], headline_y=V["headline_y"],
            band_content=band,
            show_watermark=V["show_watermark"],
            series_label=V.get("series_label", ""),
            show_eval_bar=V.get("show_eval_bar", config.SHOW_EVAL_BAR),
            show_promo_banner=V.get("show_promo_banner", False),
            show_headline=V.get("show_headline", True),
        )
        _save(compose.compose_frame(state), frames_dir, frame_no)
        frame_no += 1
    return frame_no
