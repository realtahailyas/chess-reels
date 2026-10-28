"""Tests for the "app" variant (CHESS_APP_BLUEPRINT.md Section 13).

Run everything:      python -m unittest discover -s tests -v
Skip the slow build: SKIP_SMOKE=1 python -m unittest discover -s tests

Covers: per-variant watermark/CTA suppression (compose-level), the raw
pre-setup Lichess fen/moves round-trip (Section 3.1's "critical gotcha"),
the manifest.json entry shape (Section 13.3), and the thumb/preview ffmpeg
command builders. The end-to-end class at the bottom builds one real
app-variant video and checks the Section 8.1 encode spec plus the derived
artifacts; it is skipped under SKIP_SMOKE like the existing smoke test.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chess

import config
from src import app_export, board as board_mod, compose, puzzles


class TestAppVariantConfig(unittest.TestCase):
    """Section 13.1 — the "app" variant differs from "simple"/"reaction" only
    in the ways the blueprint calls for; everything else must be untouched."""

    def test_app_variant_registered(self):
        self.assertIn("app", config.VARIANTS)

    def test_gm_games_variant_registered(self):
        self.assertIn("gm_games", config.VARIANTS)

    def test_watermark_suppressed_only_for_app(self):
        self.assertTrue(config.variant("simple")["show_watermark"])
        self.assertTrue(config.variant("reaction")["show_watermark"])
        self.assertFalse(config.variant("app")["show_watermark"])

    def test_cta_suppressed_only_for_app(self):
        self.assertTrue(config.variant("simple")["show_cta"])
        self.assertTrue(config.variant("reaction")["show_cta"])
        self.assertFalse(config.variant("app")["show_cta"])

    def test_app_writes_under_its_own_output_subdir(self):
        self.assertEqual(config.variant("app")["output_subdir"], "app")

    def test_app_has_no_reaction_band(self):
        self.assertIsNone(config.variant("app")["reaction_band"])

    def test_app_board_is_larger_and_centred(self):
        simple, app = config.variant("simple"), config.variant("app")
        self.assertGreater(app["board_px"], simple["board_px"])
        self.assertEqual(app["board_y_offset"], 0)

    def test_app_opening_has_no_hook_text(self):
        # Neither the countdown ("simple") nor the "watch closely" hold
        # ("reaction") — Section 13.1's "no hook overlay".
        self.assertEqual(config.variant("app")["opening"], "none")
        self.assertNotIn(config.variant("app")["opening"], ("countdown", "watch"))

    def test_existing_variants_keep_todays_encode_values(self):
        for name in ("simple", "reaction"):
            v = config.variant(name)
            self.assertEqual(v["crf"], config.CRF)
            self.assertEqual(v["preset"], config.PRESET)
            self.assertEqual(v["audio_bitrate"], config.AUDIO_BITRATE)
            self.assertIsNone(v["audio_channels"])

    def test_gm_games_uses_eval_bar_and_top_selection(self):
        gm = config.variant("gm_games")
        self.assertTrue(gm["show_eval_bar"])
        self.assertEqual(gm["selection"], "top")
        self.assertEqual(gm["series_label"], "GM GAMES")
        self.assertTrue(gm["full_game"])
        self.assertFalse(gm["show_dots"])
        self.assertEqual(gm["opening"], "none")
        self.assertFalse(gm["show_cta"])

    def test_app_encode_settings_match_section_8_1(self):
        app = config.variant("app")
        self.assertEqual(app["crf"], 24)
        self.assertEqual(app["audio_bitrate"], "96k")
        self.assertEqual(app["audio_channels"], 1)

    def test_unknown_variant_still_raises(self):
        with self.assertRaises(ValueError):
            config.variant("nope")


class TestWatermarkPerVariant(unittest.TestCase):
    """Compose-level check: `show_watermark` actually changes the pixels."""

    @classmethod
    def setUpClass(cls):
        cls.board_img = board_mod.render_board(chess.Board(), config.BOARD_PX)

    @unittest.skipUnless(config.WATERMARK_TEXT, "watermark text disabled in config")
    def test_watermark_suppressed_when_flag_is_false(self):
        on = compose.compose_frame(
            compose.FrameState(board_img=self.board_img, show_watermark=True))
        off = compose.compose_frame(
            compose.FrameState(board_img=self.board_img, show_watermark=False))
        # The watermark sits bottom-centre, just ABOVE the SAFE_BOTTOM line —
        # it used to be 46px off the canvas edge, which put it under the
        # platform's own caption UI. Sample where it actually is now.
        top = config.CANVAS_H - config.SAFE_BOTTOM - 120
        region = (0, top, config.CANVAS_W, config.CANVAS_H - config.SAFE_BOTTOM)
        self.assertNotEqual(list(on.crop(region).getdata()),
                            list(off.crop(region).getdata()))

    def test_default_matches_watermark_on(self):
        # No caller passes show_watermark explicitly except the variant-aware
        # renderers in src/build.py — the dataclass default must stay True so
        # nothing else in the codebase silently loses its watermark.
        default = compose.compose_frame(compose.FrameState(board_img=self.board_img))
        on = compose.compose_frame(
            compose.FrameState(board_img=self.board_img, show_watermark=True))
        self.assertEqual(list(default.getdata()), list(on.getdata()))


class TestRawLichessFields(unittest.TestCase):
    """Section 3.1's gotcha: the app needs the pair *before* build_puzzle's
    own setup-move bookkeeping, threaded all the way from the CSV row."""

    class Row:
        PuzzleId = "abc12"
        FEN = "r1bq1rk1/pp2bppp/2n1pn2/3p4/3P4/2NBPN2/PP3PPP/R1BQ1RK1 b - - 0 8"
        Moves = "f6e8 d3h7 g8h7 f3g5"   # first move is the opponent's setup
        Rating = 1650
        Popularity = 94
        NbPlays = 1200
        Themes = "sacrifice short greekGift"
        GameUrl = "https://lichess.org/x"

    def test_build_puzzle_threads_the_raw_pair(self):
        puzzle = puzzles.build_puzzle(self.Row)
        self.assertIsNotNone(puzzle)
        self.assertEqual(puzzle["lichess_fen"], self.Row.FEN)
        self.assertEqual(puzzle["lichess_moves"], self.Row.Moves)

    def test_raw_pair_differs_from_the_renderer_pair(self):
        # fen/solution are post-setup-move (what this renderer animates);
        # lichess_fen/lichess_moves are pre-setup (what the app needs).
        puzzle = puzzles.build_puzzle(self.Row)
        self.assertNotEqual(puzzle["lichess_fen"], puzzle["fen"])
        self.assertEqual(puzzle["lichess_moves"].split()[1:], puzzle["solution"])


class TestManifestEntry(unittest.TestCase):
    """Section 13.3 — the manifest.json record shape."""

    META = {
        "puzzle_id": "abc12",
        "fen": "post-setup-fen-not-used-by-the-manifest",
        "solution": ["d3h7", "g8h7", "f3g5"],
        "lichess_fen": "r1bq1rk1/pp2bppp/2n1pn2/3p4/3P4/2NBPN2/PP3PPP/R1BQ1RK1 b - - 0 8",
        "lichess_moves": "f6e8 d3h7 g8h7 f3g5",
        "themes": ["sacrifice", "short", "greekGift"],
        "rating": 1650,
        "video": {"duration": 15.43},
        "caption": {"hook": "Only 12% find this",
                    "caption": "White to play. Can you spot the pattern?"},
    }

    def test_manifest_entry_shape_matches_section_13_3(self):
        entry = app_export.manifest_entry(self.META)
        self.assertEqual(set(entry), {
            "puzzle_id", "fen", "solution_uci", "theme", "rating",
            "duration_ms", "r2_key", "thumb_key", "preview_key",
            "caption", "hook_text",
        })

    def test_manifest_fen_and_solution_are_the_raw_lichess_pair(self):
        entry = app_export.manifest_entry(self.META)
        self.assertEqual(entry["fen"], self.META["lichess_fen"])
        self.assertEqual(entry["solution_uci"], self.META["lichess_moves"])
        self.assertNotEqual(entry["fen"], self.META["fen"])
        # setup move first, as the app's puzzleEngine expects to auto-play it
        self.assertEqual(entry["solution_uci"].split()[0], "f6e8")

    def test_manifest_r2_keys_match_section_8_1_layout(self):
        entry = app_export.manifest_entry(self.META)
        self.assertEqual(entry["r2_key"], "app/v1/abc12.mp4")
        self.assertEqual(entry["thumb_key"], "app/thumb/abc12.jpg")
        self.assertEqual(entry["preview_key"], "app/preview/abc12.mp4")

    def test_manifest_duration_ms_rounds_from_seconds(self):
        entry = app_export.manifest_entry(self.META)
        self.assertEqual(entry["duration_ms"], 15430)

    def test_manifest_theme_prefers_known_puzzleflow_slug(self):
        self.assertEqual(app_export.manifest_theme(["sacrifice", "greekGift"]),
                         "sacrifice")
        self.assertEqual(app_export.manifest_theme(["mateIn2", "sacrifice"]),
                         "mateIn2")
        self.assertEqual(app_export.manifest_theme([]), "sacrifice")
        self.assertIn(app_export.manifest_theme(["fork"]), config.APP_THEME_SLUGS)

    def test_merge_manifest_upserts_by_puzzle_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            first = app_export.manifest_entry(self.META)
            app_export.merge_manifest([first], path=path)

            updated_meta = dict(self.META, rating=1700)
            updated = app_export.manifest_entry(updated_meta)
            other_meta = dict(self.META, puzzle_id="xyz99",
                              lichess_fen="8/8/8/8/8/8/8/k1K5 w - - 0 1",
                              lichess_moves="a1a2 b2b3")
            other = app_export.manifest_entry(other_meta)

            merged = app_export.merge_manifest([updated, other], path=path)

            self.assertEqual(len(merged), 2)
            by_id = {e["puzzle_id"]: e for e in merged}
            self.assertEqual(by_id["abc12"]["rating"], 1700)   # updated in place
            self.assertIn("xyz99", by_id)                      # appended

            on_disk = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk, merged)


class TestFullGameLoad(unittest.TestCase):
    def test_load_full_game_parses_names_and_moves(self):
        from src import puzzles as puzzles_mod

        pgn = """[Event \"Live Chess\"]
[Site \"https://lichess.org/abcd1234\"]
    [WhiteTitle \"GM\"]
[White \"Magnus Carlsen\"]
    [WhiteElo \"2864\"]
    [BlackTitle \"GM\"]
[Black \"Hikaru Nakamura\"]
    [BlackElo \"2789\"]
[Result \"1-0\"]
    [Termination \"Checkmate\"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0
"""

        class Resp:
            status_code = 200
            text = pgn

            def raise_for_status(self):
                return None

        with mock.patch("src.puzzles.requests.get", return_value=Resp()) as get:
            info = puzzles_mod.load_full_game("https://lichess.org/abcd1234", log=lambda *_: None)

        self.assertEqual(info["white"], "Magnus Carlsen")
        self.assertEqual(info["black"], "Hikaru Nakamura")
        self.assertEqual(info["white_title"], "GM")
        self.assertEqual(info["black_title"], "GM")
        self.assertEqual(info["white_label"], "GM Magnus Carlsen")
        self.assertEqual(info["black_label"], "GM Hikaru Nakamura")
        self.assertEqual(info["white_elo"], "2864")
        self.assertEqual(info["black_elo"], "2789")
        self.assertEqual(info["result"], "1-0")
        self.assertEqual(info["termination_phrase"], "checkmate")
        self.assertIn("won by checkmate", info["outcome"])
        self.assertEqual(info["moves"][:4], ["e2e4", "e7e5", "g1f3", "b8c6"])
        self.assertEqual(get.call_count, 1)

    def test_top_gm_whitelist_matches_known_players(self):
        from src import puzzles as puzzles_mod

        self.assertTrue(puzzles_mod.is_top_gm_game({"white": "Magnus Carlsen", "black": "X"}))
        self.assertTrue(puzzles_mod.is_top_gm_game({"white": "X", "black": "Hikaru Nakamura"}))
        self.assertFalse(puzzles_mod.is_top_gm_game({"white": "X", "black": "Y"}))


class TestFullGameBuild(unittest.TestCase):
    def test_build_one_uses_full_game_replay(self):
        from src import build as builder

        puzzle = {
            "id": "abc12",
            "fen": chess.STARTING_FEN,
            "solution": ["e2e4", "e7e5"],
            "rating": 2500,
            "themes": ["sacrifice"],
            "theme_label": "Sacrifice",
            "sacrificed_piece": "piece",
            "game_url": "https://lichess.org/abcd1234",
        }
        full_game = {
            "start_fen": chess.STARTING_FEN,
            "moves": ["e2e4", "e7e5", "g1f3"],
            "sans": ["e4", "...e5", "Nf3"],
            "white": "Magnus Carlsen",
            "black": "Hikaru Nakamura",
            "result": "1-0",
        }

        blank = board_mod.render_board(chess.Board(), 16)

        def fake_render_board(*args, **kwargs):
            return blank.copy()

        def fake_slide_frames(*args, **kwargs):
            return [blank.copy()]

        def fake_landed_board(board, move):
            after = board.copy()
            after.push(move)
            return after, None, None

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "gm_games"
            with mock.patch("src.build.puzzles_mod.load_full_game", return_value=full_game) as load_game, \
                 mock.patch("src.build.board_mod.render_board", side_effect=fake_render_board), \
                 mock.patch("src.build.animate.build_slide_frames", side_effect=fake_slide_frames), \
                 mock.patch("src.build.animate.landed_board", side_effect=fake_landed_board), \
                 mock.patch("src.build._save", side_effect=lambda *args, **kwargs: None), \
                 mock.patch("src.build.mixer.mix", return_value={"ok": True, "peak": 0.2, "rms": 0.1, "music": "generated", "duration": 3.0}), \
                 mock.patch("src.build.encode.encode_and_verify", return_value={"width": 1080, "height": 1920, "video_codec": "h264", "audio_codec": "aac", "audio_channels": 1, "duration": 3.0, "filesize": 1234, "fps": 30, "frames": 90}), \
                 mock.patch("src.build.captions.generate", return_value={"source": "placeholder", "needs_caption": False, "hook": "x", "caption": "x", "hashtags": []}), \
                 mock.patch("src.build.captions.write_caption_file", side_effect=lambda *args, **kwargs: None), \
                 mock.patch("src.build.ledger.record_success", side_effect=lambda *args, **kwargs: None):
                result = builder.build_one(
                    dict(puzzle), variant="gm_games", output_dir=out,
                    ledger_path=out / "posted.json", use_api=False, log=lambda *_: None)

            self.assertEqual(result["status"], "ok", result.get("error"))
            load_game.assert_called_once()
            meta = json.loads((out / "0001_abc12" / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["white"], "Magnus Carlsen")
            self.assertEqual(meta["black"], "Hikaru Nakamura")
            self.assertEqual(meta["result"], "1-0")
            self.assertEqual(meta["solution"], full_game["moves"])


class TestAppExportCommands(unittest.TestCase):
    """Pure ffmpeg command builders — no subprocess, no real ffmpeg needed."""

    def test_thumb_command_grabs_one_frame_at_half_a_second(self):
        cmd = app_export.thumb_command(Path("v.mp4"), Path("t.jpg"))
        self.assertIn("-ss", cmd)
        self.assertIn(str(config.APP_THUMB_TIME), cmd)
        self.assertIn("-frames:v", cmd)
        self.assertIn(f"scale={config.APP_THUMB_W}:{config.APP_THUMB_H}", cmd)
        self.assertEqual(cmd[-1], str(Path("t.jpg")))

    def test_preview_command_is_video_only_and_small(self):
        cmd = app_export.preview_command(Path("v.mp4"), Path("p.mp4"))
        self.assertIn("-an", cmd)
        self.assertNotIn("-c:a", cmd)
        self.assertIn(str(config.APP_PREVIEW_DURATION), cmd)
        self.assertIn(f"scale={config.APP_PREVIEW_W}:{config.APP_PREVIEW_H}", cmd)
        self.assertIn(str(config.APP_PREVIEW_CRF), cmd)
        self.assertIn("+faststart", cmd)

    def test_overrides_are_honoured(self):
        cmd = app_export.thumb_command(Path("v.mp4"), Path("t.jpg"),
                                       at=1.2, width=100, height=200)
        self.assertIn("1.2", cmd)
        self.assertIn("scale=100:200", cmd)


@unittest.skipIf(os.environ.get("SKIP_SMOKE"), "SKIP_SMOKE set")
class TestAppVariantEndToEnd(unittest.TestCase):
    """Build one real app-variant video and verify the Section 8.1 spec plus
    the derived artifacts (Section 13.2)."""

    def test_app_variant_end_to_end(self):
        from run_batch import SMOKE_PUZZLE
        from src import build as builder, encode

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            result = builder.build_one(
                dict(SMOKE_PUZZLE), use_api=False, output_dir=out,
                ledger_path=out / "posted.json", variant="app",
                log=lambda *_: None)

            self.assertEqual(result["status"], "ok", result.get("error"))
            mp4 = Path(result["video"])
            info = encode.probe(mp4)
            self.assertEqual((info["width"], info["height"]), (1080, 1920))
            self.assertEqual(info["video_codec"], "h264")
            self.assertEqual(info["audio_codec"], "aac")
            self.assertEqual(info["audio_channels"], 1)

            meta = json.loads((mp4.parent / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["variant"], "app")
            self.assertIn("lichess_fen", meta)
            self.assertIn("lichess_moves", meta)

            thumb_path = out / "thumb.jpg"
            preview_path = out / "preview.mp4"
            app_export.make_thumb(mp4, thumb_path)
            app_export.make_preview(mp4, preview_path)

            self.assertTrue(thumb_path.exists())
            thumb_info = encode.probe(thumb_path)
            self.assertEqual((thumb_info["width"], thumb_info["height"]),
                            (config.APP_THUMB_W, config.APP_THUMB_H))

            self.assertTrue(preview_path.exists())
            preview_info = encode.probe(preview_path)
            self.assertIsNone(preview_info["audio_codec"])
            self.assertLess(preview_path.stat().st_size, 300_000)

            entry = app_export.manifest_entry(meta)
            self.assertEqual(entry["puzzle_id"], "smoke01")
            self.assertEqual(entry["r2_key"], "app/v1/smoke01.mp4")


if __name__ == "__main__":
    unittest.main(verbosity=2)
