"""CLI entry point for the chess reel pipeline.

    python run_batch.py --count 30
    python run_batch.py --count 3 --voice en-GB-RyanNeural
    python run_batch.py --count 10 --no-api        # skip Claude captions
    python run_batch.py --count 5 --theme greekGift
    python run_batch.py --retry-failed
    python run_batch.py --dry-run                  # select puzzles, no render
    python run_batch.py --smoke                    # one hardcoded puzzle

    python run_batch.py --variant gm_games --count 20
    python run_batch.py --variant gm_games --count 10 --gm-players "Magnus Carlsen,Hikaru Nakamura"
    python run_batch.py --variant gm_games --count 10 --eco B90      # Najdorf only
"""

import argparse
import multiprocessing
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Windows defaults stdout to cp1252 when the output is piped or redirected, and
# the box-drawing characters in the summary are not encodable there — the batch
# would finish every video and then die printing its own report. Force UTF-8 and
# fall back to replacement characters rather than ever crashing on output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass  # already a non-reconfigurable stream (e.g. a pytest capture)

# 🔴 LOAD .env HERE TOO, NOT ONLY IN publish.py. captions.generate() reads
# OPENAI_API_KEY straight off os.environ, so a build started any way other than
# as publish.py's child — a manual run, a scheduled top-up, the autopilot's own
# generate step — silently wrote PLACEHOLDER captions and logged one line about
# it. Every reel built that way has to be rebuilt before it can be posted.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:      # python-dotenv is in requirements.txt; never fatal
    pass

import config
from src import board as board_mod
from src import build as builder
from src import puzzles as puzzle_src
from src import queue as ledger

# Ships with the tool so the pipeline can be exercised without the 1 GB CSV.
SMOKE_PUZZLE = {
    "id": "smoke01",
    "fen": "r1bq1rk1/pp2bppp/2n1pn2/3p4/3P4/2NBPN2/PP3PPP/R1BQ1RK1 w - - 0 9",
    "solution": ["d3h7", "g8h7", "f3g5", "h7g8", "d1h5"],
    "rating": 1650,
    "themes": ["sacrifice", "greekGift"],
    "popularity": 95,
    "game_url": "https://lichess.org/training/smoke01",
    "theme_label": "Greek Gift Sacrifice",
    "sacrificed_piece": "bishop",
    "brilliant_index": 0,
}


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Turn Lichess sacrifice puzzles into vertical short-form videos.")
    p.add_argument("--count", type=int, default=3,
                   help="number of videos to build (default 3)")
    p.add_argument("--variant", choices=sorted(config.VARIANTS),
                   default=config.DEFAULT_VARIANT,
                    help="output format: simple (countdown), reaction (clip "
                        "band), gm_games (real top-player games from a local "
                        "PGN cache, eval bar), or app (in-app deliverable, "
                        "no watermark/CTA)")
    p.add_argument("--for-app", action="store_true",
                   help="convenience flag, equivalent to --variant app")
    p.add_argument("--voice", default=None,
                   help=f"edge-tts voice (default {config.TTS_VOICE})")
    p.add_argument("--no-api", action="store_true",
                   help="skip the Claude caption call and write placeholders")
    p.add_argument("--theme", default=None,
                   help="restrict to a Lichess theme tag, e.g. greekGift")
    p.add_argument("--gm-players", default=None,
                   help="comma-separated player names for --variant gm_games "
                        "(default: everyone with a cached PGN archive)")
    p.add_argument("--eco", default=None,
                   help="restrict --variant gm_games to games whose ECO code "
                        "starts with this, e.g. B90 for the Najdorf")
    p.add_argument("--rating-min", type=int, default=config.RATING_MIN)
    p.add_argument("--rating-max", type=int, default=config.RATING_MAX)
    p.add_argument("--output-dir", type=Path, default=config.OUTPUT_DIR)
    p.add_argument("--retry-failed", action="store_true",
                   help="rebuild puzzles whose output directory has no video")
    p.add_argument("--retry-captions", action="store_true",
                   help="regenerate placeholder captions via Claude, no re-render")
    p.add_argument("--dry-run", action="store_true",
                   help="select and print puzzles without rendering")
    p.add_argument("--keep-frames", action="store_true",
                   help="do not delete frames/ after a successful encode")
    p.add_argument("--jobs", type=int, default=1,
                   help="render N puzzles in parallel (default 1)")
    p.add_argument("--smoke", action="store_true",
                   help="build the bundled smoke puzzle, no CSV needed")
    p.add_argument("--download", action="store_true",
                   help="force a fresh download of the puzzle database")
    p.add_argument("--download-voice", action="store_true",
                   help="download the offline Piper voice model, then exit")
    return p.parse_args(argv)


def _worker(job):
    """Module-level so it survives pickling on Windows spawn."""
    puzzle, opts = job
    return builder.build_one(puzzle, **opts)


def select_puzzles(args) -> list:
    if args.smoke:
        return [dict(SMOKE_PUZZLE)]

    if args.retry_failed:
        pending = []
        for entry in ledger.load().get("pending", []):
            if not Path(entry.get("video_path", "")).exists():
                pending.append(entry["puzzle_id"])
        if not pending:
            print("nothing to retry — every pending entry has a video")
            return []
        print(f"retrying {len(pending)} puzzle(s) with missing video files")
        # Retry needs the full puzzle record, so re-select from the database.
        df = puzzle_src.load_and_filter(rating_min=args.rating_min,
                                        rating_max=args.rating_max,
                                        theme=args.theme)
        rows = df[df.PuzzleId.isin(pending)]
        out = [puzzle_src.build_puzzle(rows.loc[i]) for i in rows.index]
        return [p for p in out if p]

    variant_cfg = config.variant(args.variant)

    if variant_cfg.get("full_game"):
        # Real named GM games, sourced from a local PGN cache instead of
        # mining the (anonymous-games) Lichess puzzle CSV — see gm_source.py.
        from src import gm_source
        players = ([p.strip() for p in args.gm_players.split(",") if p.strip()]
                   if args.gm_players else None)
        return gm_source.select_games(
            args.count,
            players=players,
            exclude=ledger.posted_ids(),
            eco_prefix=args.eco,
            force_download=args.download,
            log=print,
        )

    puzzle_src.download(force=args.download)

    # A variant that cuts the video at the sacrifice needs a puzzle that HAS
    # one. select() already guarantees is_visual_sacrifice, but brilliant_index
    # is still None whenever the first move takes at least as much as it gives —
    # and such a puzzle has nothing to truncate at, no !! badge and no reaction
    # clip. Over-select and keep only the ones that qualify.
    want = args.count
    if variant_cfg.get("stop_after_brilliant"):
        want = args.count * 4

    picked = puzzle_src.select(
        want,
        exclude=ledger.posted_ids(),
        rating_min=args.rating_min,
        rating_max=args.rating_max,
        # An explicit --theme always wins; a variant may carry its own default
        # (promo_mate is the countdown reel restricted to mates).
        theme=args.theme or variant_cfg.get("theme"),
        ranked=(variant_cfg.get("selection") == "top"),
        full_game=False,
    )

    if variant_cfg.get("stop_after_brilliant"):
        qualified = [p for p in picked if p.get("brilliant_index") is not None]
        print(f"{len(qualified)} of {len(picked)} sampled puzzles have a "
              f"brilliant move; keeping {min(len(qualified), args.count)}")
        picked = qualified[:args.count]

    return picked


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.for_app:
        args.variant = "app"
    started = time.time()

    if args.download_voice:
        from src import speech
        print(f"downloading Piper voice '{config.PIPER_VOICE}' to {config.PIPER_DIR}")
        ok = speech.download_piper_model()
        print("done" if ok else "failed — retry, or use a VPN")
        return 0 if ok else 1

    if args.retry_captions:
        return retry_captions(args.output_dir)

    print(f"renderer  : {board_mod.active_renderer()}")
    print(f"ffmpeg    : {config.FFMPEG}")
    if shutil.which(config.FFMPEG) is None and not Path(config.FFMPEG).is_file():
        print("ERROR: ffmpeg not found. Install it and ensure it is on PATH.")
        return 2

    source = config.variant(args.variant).get("source")

    # Stills, not video: no encode, no audio, its own 4:5 canvas.
    if source == "carousel":
        from src import carousel
        variant_dir = args.output_dir / config.variant(args.variant)["output_subdir"]
        print(f"variant   : {args.variant}")
        start_index = builder.next_index(variant_dir)
        results = []
        for i in range(args.count):
            print(f"[{i + 1:2}/{args.count}] carousel")
            results.append(carousel.build_carousel(
                output_dir=variant_dir, seq=start_index + i,
                rating_min=args.rating_min, rating_max=args.rating_max,
                theme=args.theme, log=print))
        return summarize(results, variant_dir, time.time() - started)

    # The Play listing video: the same tour, re-laid-out for 16:9.
    if source == "tour_wide":
        from src import landscape
        variant_dir = args.output_dir / config.variant(args.variant)["output_subdir"]
        print(f"variant   : {args.variant}  (landscape, for Google Play)")
        results = [landscape.build_wide(
            voice=args.voice, keep_frames=args.keep_frames,
            output_dir=variant_dir, seq=builder.next_index(variant_dir), log=print)]
        return summarize(results, variant_dir, time.time() - started)

    # The ladder reel: roster cards read out of the app, no puzzle involved.
    if source == "bots":
        from src import bots as bots_mod
        variant_dir = args.output_dir / config.variant(args.variant)["output_subdir"]
        print(f"variant   : {args.variant}")
        if args.count != 1:
            print(f"note      : --count {args.count} ignored; the ladder is one reel")
        results = [bots_mod.build_bots(
            voice=args.voice, keep_frames=args.keep_frames,
            output_dir=variant_dir, seq=builder.next_index(variant_dir), log=print)]
        return summarize(results, variant_dir, time.time() - started)

    # The app tour renders no chess at all — it pans real device captures of
    # the app — so it never touches puzzle selection or build_one.
    if source == "screenshots":
        from src import tour
        variant_dir = args.output_dir / config.variant(args.variant)["output_subdir"]
        print(f"variant   : {args.variant}")
        print(f"shots     : {len(config.TOUR_SHOTS)} from {config.TOUR_SHOT_DIR}\n")
        if args.dry_run:
            for i, (f, caption, vo) in enumerate(config.TOUR_SHOTS, 1):
                print(f"[{i:2}/{len(config.TOUR_SHOTS)}] {f:22} {caption:22} {vo}")
            return 0
        # The tour is ONE deterministic reel — same shots, same captions, same
        # order — so --count does not apply. resolve_out_root reuses the
        # existing *_tour folder, which makes a rebuild land in place rather
        # than producing N identical copies.
        if args.count != 1:
            print(f"note      : --count {args.count} ignored; the tour is one reel "
                  f"and rebuilds in place")
        results = [tour.build_tour(
            voice=args.voice, keep_frames=args.keep_frames,
            output_dir=variant_dir, seq=builder.next_index(variant_dir),
            log=print)]
        return summarize(results, variant_dir, time.time() - started)

    selected = select_puzzles(args)
    if not selected:
        print("no puzzles selected")
        return 1

    print(f"variant   : {args.variant}")
    print(f"selected  : {len(selected)} puzzle(s)\n")
    if args.dry_run:
        for i, p in enumerate(selected, 1):
            print(f"[{i:2}/{len(selected)}] {p['id']:8} {p['theme_label']:26} "
                  f"{p['rating']}  {' '.join(p['solution'])}")
        return 0

    # Each variant writes to its own folder so the two never collide; variant A
    # ("simple") has an empty subdir, keeping its original output/<id> paths.
    variant_dir = args.output_dir / config.variant(args.variant)["output_subdir"]

    opts = {
        "voice": args.voice,
        "use_api": not args.no_api,
        "keep_frames": args.keep_frames,
        "output_dir": variant_dir,
        "variant": args.variant,
    }

    # Number folders sequentially from the next free global index, so the
    # batch lands as 0001_<id>, 0002_<id>, ... in selection order.
    start_index = builder.next_index(variant_dir)

    results = []
    if args.jobs > 1:
        jobs = [(p, {**opts, "seq": start_index + i})
                for i, p in enumerate(selected)]
        with multiprocessing.Pool(processes=args.jobs) as pool:
            for i, result in enumerate(pool.imap_unordered(_worker, jobs), 1):
                mark = "OK" if result["status"] == "ok" else "FAILED"
                print(f"[{i:2}/{len(selected)}] {result['puzzle_id']:8} {mark} "
                      f"({result['seconds']}s)")
                results.append(result)
    else:
        for i, puzzle in enumerate(selected, 1):
            print(f"[{i:2}/{len(selected)}] {puzzle['id']:8} "
                  f"{puzzle['theme_label']:26} {puzzle['rating']}")
            results.append(builder.build_one(
                puzzle, seq=start_index + i - 1, log=print, **opts))

    if args.variant == "app":
        export_app_artifacts(results, variant_dir)

    return summarize(results, variant_dir, time.time() - started)


def export_app_artifacts(results, variant_dir: Path) -> None:
    """Build thumb + preview + manifest.json for every successful app build.

    Runs once, after the whole batch, so a failure in one video's artifacts
    cannot clobber manifest entries already written for others in this run.
    R2 upload is a later, separate step — this only writes local files.
    """
    import json

    from src import app_export

    entries = []
    for r in results:
        if r["status"] != "ok":
            continue
        video_path = Path(r["video"])
        meta_path = video_path.parent / "meta.json"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            entries.append(app_export.export_one(meta, video_path, variant_dir,
                                                  log=print))
        except Exception as exc:
            print(f"        app-export FAILED {r['puzzle_id']}: "
                  f"{type(exc).__name__}: {exc}")

    if entries:
        manifest_path = variant_dir / "manifest.json"
        merged = app_export.merge_manifest(entries, path=manifest_path)
        print(f"\napp manifest: {len(entries)} new/updated, "
              f"{len(merged)} total -> {manifest_path}")


def retry_captions(output_dir: Path) -> int:
    """Regenerate captions for any build whose meta.json is a placeholder.

    Rewrites caption.txt and the caption block in meta.json in place; the
    video is not touched, so this is cheap and safe to rerun.
    """
    import json
    from src import captions

    # rglob catches both variant A (output/<id>) and B (output/reaction/<id>).
    metas = sorted(output_dir.rglob("meta.json"))
    if not metas:
        print(f"no builds found under {output_dir}")
        return 1

    fixed = failed = skipped = 0
    for meta_path in metas:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if not meta.get("caption", {}).get("needs_caption"):
            skipped += 1
            continue

        puzzle = {
            "id": meta["puzzle_id"], "fen": meta["fen"],
            "solution": meta["solution"], "rating": meta["rating"],
            "themes": meta.get("themes", []), "theme_label": meta["theme_label"],
            "sacrificed_piece": meta.get("sacrificed_piece"),
            "game_url": meta.get("game_url", ""),
        }
        print(f"[{meta['puzzle_id']}] {meta['theme_label']}")
        caption = captions.generate(puzzle, use_api=True, log=print)
        if caption["needs_caption"]:
            failed += 1
            continue

        captions.write_caption_file(meta_path.parent / "caption.txt", puzzle,
                                    caption, meta["video"]["duration"])
        meta["caption"] = caption
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        fixed += 1
        print(f"        ok -> {caption['hook']}")

    print(f"\nregenerated {fixed}, still placeholder {failed}, "
          f"already done {skipped}")
    return 0 if failed == 0 else 1


def summarize(results, output_dir: Path, elapsed: float) -> int:
    ok = [r for r in results if r["status"] == "ok"]
    bad = [r for r in results if r["status"] != "ok"]
    needs_caption = [r for r in ok if r.get("needs_caption")]

    disk = 0
    if output_dir.exists():
        disk = sum(f.stat().st_size for f in output_dir.rglob("*") if f.is_file())

    print("\n" + "─" * 52)
    print(f"succeeded : {len(ok)}")
    print(f"failed    : {len(bad)}")
    if ok:
        print(f"average   : {sum(r['seconds'] for r in ok) / len(ok):.1f}s per video")
    print(f"total time: {elapsed:.1f}s")
    print(f"disk used : {disk / 1e6:.1f} MB in {output_dir}")
    if needs_caption:
        print(f"note      : {len(needs_caption)} caption(s) are placeholders — "
              f"rerun with the Claude API before publishing")
    for r in bad:
        print(f"  FAILED {r['puzzle_id']}: {r['error']}")
    return 0 if ok and not bad else (1 if not ok else 0)


if __name__ == "__main__":
    raise SystemExit(main())
