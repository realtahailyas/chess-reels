"""One featured game -> one finished 1920x1080 long-form video.

No voiceover: the video is the game itself, paced by the engine's judgement —
opening theory moves fast, ordinary moves get time to be seen, and the
brilliant / losing moves are held long enough to land, with a badge on the
board and the moment card on the right.

Frames are streamed straight into ffmpeg as raw RGB. A held position is one
composed frame written N times, so a ten-minute video costs about as much
composition work as its moving parts.
"""

import json
import subprocess
import time

import chess
import numpy as np

import config
from src import animate, audioutil, music, sfx
from src import board as board_mod
from longform import engine, games, thumbnail
from longform import frame as F
from longform import lfconfig as C

SR = config.SAMPLE_RATE


# ── Pacing ────────────────────────────────────────────────────────────────

def pacing(game: dict, judg: list, book: int) -> list:
    """Seconds per ply, slide included, scaled toward the target length."""
    board = chess.Board(game["start_fen"])
    base, scalable = [], []
    last = len(game["moves"]) - 1
    for i, mv in enumerate(game["moves"]):
        glyph = judg[i]["glyph"]
        if i == last or glyph == "#":
            key = "last"
        elif glyph in C.PACE:
            key = glyph
        elif i < book:
            key = "book"
        elif board.gives_check(mv):
            key = "check"
        elif board.is_capture(mv):
            key = "capture"
        else:
            key = "normal"
        base.append(C.PACE[key])
        scalable.append(key != "book")
        board.push(mv)
    for i in range(len(base) - 1):
        if judg[i + 1]["glyph"] == "!!":
            base[i] += C.TENSION_BEFORE_KEY

    fixed = C.INTRO_S + C.INTRO_FADE_S + C.RESULT_HOLD_S + C.ENDCARD_S
    fixed += sum(b for b, s in zip(base, scalable) if not s)
    flex = sum(b for b, s in zip(base, scalable) if s)
    scale = 1.0
    if flex and fixed + flex < C.TARGET_MIN_S:
        scale = min(C.SCALE_MAX, (C.TARGET_MIN_S - fixed) / flex)
    elif flex and fixed + flex > C.TARGET_MAX_S:
        scale = max(C.SCALE_MIN, (C.TARGET_MAX_S - fixed) / flex)
    return [b * scale if s else b for b, s in zip(base, scalable)]


# ── ffmpeg sink ───────────────────────────────────────────────────────────

class Sink:
    def __init__(self, path, w: int = C.W, h: int = C.H):
        self.path = path
        self.frames = 0
        cmd = [
            config.FFMPEG, "-y", "-v", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
            "-r", str(C.FPS), "-i", "-",
            "-an", "-c:v", "libx264", "-preset", C.PRESET, "-crf", str(C.CRF),
            "-pix_fmt", "yuv420p", "-g", str(C.FPS * 2), "-threads", str(C.ENCODE_THREADS),
            "-movflags", "+faststart",
            str(path),
        ]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                                     creationflags=config.SUBPROCESS_NO_WINDOW)

    def write(self, img, count: int = 1):
        if count <= 0:
            return
        data = img.tobytes()
        for _ in range(count):
            self.proc.stdin.write(data)
        self.frames += count

    @property
    def t(self) -> float:
        return self.frames / C.FPS

    def close(self):
        self.proc.stdin.close()
        err = self.proc.stderr.read().decode("utf-8", "replace")
        if self.proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed: {err[-600:]}")


# ── Audio ─────────────────────────────────────────────────────────────────

def music_bed(duration: float, seed: str) -> tuple[np.ndarray, list]:
    """The user's tracks, shuffled per game and crossfaded end to end."""
    tracks = music.user_tracks()
    need = int(duration * SR)
    out = np.zeros(need + SR)
    if not tracks:
        return music.generate(duration, seed), ["generated"]
    order = sorted(tracks, key=lambda p: music._hash_index(seed + p.name, 10_000))
    xf = int(C.MUSIC_XFADE_S * SR)
    pos, used, k = 0, [], 0
    decoded = {}
    while pos < need:
        path = order[k % len(order)]
        k += 1
        if path not in decoded:
            s = audioutil.decode_to_mono(path, SR)
            r = audioutil.rms(s) or 1.0
            decoded[path] = s * (0.16 / r)      # level-match the tracks
        s = decoded[path].copy()
        if s.size <= 2 * xf:
            continue
        s[:xf] *= np.linspace(0, 1, xf)
        s[-xf:] *= np.linspace(1, 0, xf)
        audioutil.add_at(out, s, pos)
        used.append(path.name)
        pos += s.size - xf
    out = out[:need]
    fo = int(C.MUSIC_FADE_OUT_S * SR)
    out[-fo:] *= np.linspace(1, 0, fo)
    return out, used


def mix(events: list, duration: float, seed: str, wav_path) -> dict:
    bed, used = music_bed(duration, seed)
    track = np.zeros(int(duration * SR) + SR)
    audioutil.add_at(track, bed, 0, C.GAIN_MUSIC)
    for t, name, gain in events:
        audioutil.add_at(track, sfx.get(name), int(t * SR), C.GAIN_SFX * gain)
    track = track[:int(duration * SR)]
    peak = float(np.max(np.abs(track))) or 1.0
    track *= config.NORMALIZE_PEAK / peak
    audioutil.write_wav(wav_path, track)
    return {"music": used, "peak": round(peak, 3), "rms": round(audioutil.rms(track), 4)}


def mux(video, wav, out):
    # YouTube turns loud uploads down to about -14 LUFS but never turns quiet
    # ones up; the raw mix measured -22.7, so it is normalised here.
    cmd = [config.FFMPEG, "-y", "-v", "error", "-i", str(video), "-i", str(wav),
           "-af", f"loudnorm=I={C.LOUDNESS_LUFS}:TP=-1.5:LRA=11", "-ar", str(SR),
           "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
           "-movflags", "+faststart", str(out)]
    proc = subprocess.run(cmd, capture_output=True, creationflags=config.SUBPROCESS_NO_WINDOW)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[-600:])


# ── Build ─────────────────────────────────────────────────────────────────

class DullGame(Exception):
    """An auto-picked game whose engine run found nothing worth watching."""


def interesting(judg: list) -> bool:
    glyphs = [j["glyph"] for j in judg]
    if any(g in ("!!", "??", "#") for g in glyphs):
        return True
    return sum(g in ("!", "?") for g in glyphs) >= 3


def build(entry: dict, brand: str = "tchess", log=print, limit_plies: int = None,
          fmt: str = "wide") -> dict:
    """fmt "wide" = the 16:9 YouTube video; "reel" = the 9:16 Facebook reel."""
    t0 = time.time()
    g = games.load(entry)
    log(f"  {g['white']} vs {g['black']}, {g['event']} {g['year']} — {len(g['moves'])} plies")
    positions = engine.analyse(g, log=log)      # always the whole game, so the cache holds
    if limit_plies:
        g["moves"], g["sans"] = g["moves"][:limit_plies], g["sans"][:limit_plies]
        positions = positions[:limit_plies + 1]
    book = games.book_depth(g["start_fen"], g["moves"])
    judg = engine.judge(g, positions, book)
    openings = games.opening_names(g["start_fen"], g["moves"])
    durs = pacing(g, judg, book)
    marks = [(i, j["glyph"]) for i, j in enumerate(judg) if j["glyph"]]
    log(f"  book {book} plies · marks {' '.join(f'{g['sans'][i]}{m}' for i, m in marks)}")
    if entry.get("source") == "scored" and not interesting(judg):
        # Curated games are made whatever the engine says; an auto-picked
        # game with nothing to show is 8 minutes of shuffling pieces.
        raise DullGame(f"{g['id']}: no brilliant move, blunder or mate")

    if fmt == "reel":
        from longform.frame_vertical import VFrames
        R = VFrames(g, judg, positions, openings, brand)
    else:
        R = F.Frames(g, judg, positions, openings, brand)
    out_dir = C.OUTPUT_DIR / f"{g['id']}_{brand}{R.suffix}"
    out_dir.mkdir(parents=True, exist_ok=True)
    silent = out_dir / "video_silent.mp4"
    wav = out_dir / "audio.wav"
    final = out_dir / "video.mp4"
    sink = Sink(silent, R.W, R.H)
    events = []

    board = chess.Board(g["start_fen"])
    eval_prev = F.eval_bar(positions[0]["score"])
    bimg = board_mod.render_board(board, R.board_px)
    first = R.frame(bimg, R.panel(0, board, None), *eval_prev)

    # Intro: title over the dimmed starting position, then fade in.
    intro = R.intro(first)
    sink.write(intro, round(C.INTRO_S * C.FPS))
    nf = round(C.INTRO_FADE_S * C.FPS)
    for k in range(nf):
        sink.write(F.Image.blend(intro, first, F.ease((k + 1) / nf)))

    moment, moment_age = None, 99
    for i, mv in enumerate(g["moves"]):
        j = judg[i]
        glyph = j["glyph"]
        key = glyph in ("!!", "#")
        slide_s = C.SLIDE_KEY if key else C.SLIDE
        panel_before = R.panel(i, board, moment if moment_age <= 2 else None)

        if glyph == "!!":
            events.append((sink.t, "whoosh", 0.8))
        eval_next = F.eval_bar(positions[i + 1]["score"], positions[i + 1].get("terminal"))
        slides = list(animate.build_slide_frames(board, mv, R.board_px, C.FPS, slide_s))
        for k, simg in enumerate(slides):
            p = F.ease((k + 1) / len(slides))
            frac = eval_prev[0] + (eval_next[0] - eval_prev[0]) * p
            sink.write(R.frame(simg, panel_before, frac, eval_prev[1]))

        after, lastmove, check = animate.landed_board(board, mv)
        was_capture = board.is_capture(mv)
        landing = sink.t
        if after.is_checkmate():
            events.append((landing, "mate", 1.0))
        elif glyph == "!!":
            events.append((landing, "capture" if was_capture else "move", 1.0))
            events.append((landing + 0.05, "mate", 0.55))
        else:
            events.append((landing, "capture" if was_capture else "move", 1.0))
            if check is not None:
                events.append((landing + 0.08, "check", 0.45))

        new_m = F.moment_for(i, g, j)
        if new_m:
            moment, moment_age = new_m, 0
        else:
            moment_age += 1
        panel_after = R.panel(i + 1, after, moment if moment_age <= 2 else None)
        landed = board_mod.render_board(after, R.board_px, lastmove=lastmove, check=check)
        tint = (mv.to_square, C.GLYPH_COLORS["!!"], 95) if glyph == "!!" else None

        hold = max(1, round((durs[i] - slide_s) * C.FPS))
        if glyph and glyph != "#":
            npop = min(hold, round(C.BADGE_POP * C.FPS))
            for k in range(npop):
                sc = animate.ease_out_back((k + 1) / npop)
                sink.write(R.frame(landed, panel_after, *eval_next,
                                   badge=(mv.to_square, glyph, sc), tint=tint))
            still = R.frame(landed, panel_after, *eval_next,
                            badge=(mv.to_square, glyph, 1.0), tint=tint)
            sink.write(still, hold - npop)
        else:
            sink.write(R.frame(landed, panel_after, *eval_next), hold)

        eval_prev = eval_next
        board = after

    # Result card on the final position, then the end card.
    res_panel = R.panel(len(g["moves"]), board, F.result_moment(g))
    last_board = board_mod.render_board(board, R.board_px, lastmove=g["moves"][-1],
                                        check=board.king(board.turn) if board.is_check() else None)
    res_frame = R.frame(last_board, res_panel, *eval_prev)
    sink.write(res_frame, round(C.RESULT_HOLD_S * C.FPS))
    end = R.endcard()
    nf = round(0.8 * C.FPS)
    for k in range(nf):
        sink.write(F.Image.blend(res_frame, end, F.ease((k + 1) / nf)))
    sink.write(end, round(C.ENDCARD_S * C.FPS) - nf)
    duration = sink.t
    sink.close()

    audio = mix(events, duration, g["id"], wav)
    mux(silent, wav, final)
    silent.unlink(missing_ok=True)
    wav.unlink(missing_ok=True)
    if fmt == "reel":
        # A reel's cover is picked from the video; the title card is the one
        # frame that says what the reel is, so it is saved as the cover.
        thumb = out_dir / "cover.jpg"
        intro.save(thumb, quality=92)
    else:
        thumb = thumbnail.build(g, judg, out_dir / "thumbnail.jpg", brand=brand, log=log)

    meta = {
        "id": g["id"], "brand": brand, "title": g["title"], "source": entry.get("source", ""),
        "white": g["white"], "black": g["black"], "event": g["event"],
        "white_slug": g.get("white_slug"), "black_slug": g.get("black_slug"),
        "white_elo": g["white_elo"], "black_elo": g["black_elo"],
        "site": g["site"], "year": g["year"], "round": g.get("round", ""), "result": g["result"],
        "final_mate": g["final_board"].is_checkmate(),
        "opening": next((o for o in reversed(openings) if o), ""),
        "plies": len(g["moves"]), "book_plies": book,
        "duration_s": round(duration, 1), "audio": audio,
        "marks": [{"ply": i, "san": g["sans"][i], "glyph": m, "text": judg[i]["text"],
                   "mover": "white" if i % 2 == 0 else "black"} for i, m in marks],
        "chapters": chapters(g, judg, durs),
        "thumbnail": thumb.name,
        "render_s": round(time.time() - t0, 1),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    log(f"  done {final} — {duration / 60:.1f} min, rendered in {meta['render_s']:.0f}s")
    return meta


def chapters(g, judg, durs) -> list:
    """YouTube chapter timestamps: the opening, then each key moment."""
    t = C.INTRO_S + C.INTRO_FADE_S
    # YouTube only honours chapters that start at 0:00 and last 10s or more,
    # so the 4-second title card is folded into the opening.
    out = [{"t": 0, "label": "The opening"}]
    for i, j in enumerate(judg):
        if j["glyph"] in ("!!", "??", "#"):
            move_no = i // 2 + 1
            dots = "." if i % 2 == 0 else "..."
            label = {"!!": "Brilliant", "??": "Blunder", "#": "Checkmate"}[j["glyph"]]
            stamp = round(t - (C.TENSION_BEFORE_KEY if j["glyph"] == "!!" else 0))
            if stamp - out[-1]["t"] >= 10:
                out.append({"t": stamp, "label": f"{label}: {move_no}{dots} {g['sans'][i]}"})
        t += durs[i]
    if t - out[-1]["t"] >= 10:
        out.append({"t": round(t), "label": "Result"})
    return out
