"""Test suite for the chess reel pipeline.

Run everything:      python -m unittest discover -s tests -v
Skip the slow build: SKIP_SMOKE=1 python -m unittest discover -s tests

The end-to-end smoke test renders and encodes a real video, so it takes a
minute or two; everything else runs in seconds.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chess
import numpy as np

import config
from src import animate, audioutil, board as board_mod, captions, compose
from src import mixer, music, puzzles, queue as ledger, reactions, sfx, speech
from src.mixer import AudioEvent


class TestCoordinateMath(unittest.TestCase):
    """Section 14.1 — the geometry every animated piece depends on."""

    def test_margin_and_cell_partition_the_board(self):
        for px in (600, 900, 1200):
            margin, cell = board_mod.board_metrics(px)
            self.assertAlmostEqual(2 * margin + 8 * cell, px, places=9,
                                   msg=f"board_px={px}")

    def test_known_values_at_900(self):
        margin, cell = board_mod.board_metrics(900)
        self.assertAlmostEqual(margin, 34.615384615, places=6)
        self.assertAlmostEqual(cell, 103.846153846, places=6)

    def test_a1_is_bottom_left_and_h8_is_top_right(self):
        x1, y1, _ = board_mod.square_center(chess.A1, 900)
        x8, y8, _ = board_mod.square_center(chess.H8, 900)
        self.assertLess(x1, 450)
        self.assertGreater(y1, 450)
        self.assertGreater(x8, 450)
        self.assertLess(y8, 450)

    def test_files_and_ranks_are_monotonic(self):
        xa, _, _ = board_mod.square_center(chess.A4, 900)
        xh, _, _ = board_mod.square_center(chess.H4, 900)
        _, y1, _ = board_mod.square_center(chess.D1, 900)
        _, y8, _ = board_mod.square_center(chess.D8, 900)
        self.assertLess(xa, xh)          # files increase to the right
        self.assertGreater(y1, y8)       # ranks increase upward (inverted y)


class TestPuzzleParsing(unittest.TestCase):
    """Section 14.2 — the setup-move semantics that make or break every puzzle."""

    class Row:
        PuzzleId = "abc12"
        # Position before the opponent's setup move.
        FEN = "r1bq1rk1/pp2bppp/2n1pn2/3p4/3P4/2NBPN2/PP3PPP/R1BQ1RK1 b - - 0 8"
        Moves = "f6e8 d3h7 g8h7 f3g5"   # first move is the opponent's setup
        Rating = 1650
        Popularity = 94
        NbPlays = 1200
        Themes = "sacrifice short greekGift"
        GameUrl = "https://lichess.org/x"

    def test_first_move_is_applied_before_the_puzzle_starts(self):
        board = chess.Board(self.Row.FEN)
        board.push_uci("f6e8")
        expected = board.fen()

        puzzle = puzzles.build_puzzle(self.Row)
        self.assertIsNotNone(puzzle)
        self.assertEqual(puzzle["fen"], expected)
        self.assertEqual(puzzle["solution"], ["d3h7", "g8h7", "f3g5"])  # Moves[1:]
        self.assertEqual(puzzle["theme_label"], "Greek Gift Sacrifice")
        self.assertEqual(puzzle["sacrificed_piece"], "bishop")

    def test_theme_label_prefers_queen_sacrifice(self):
        fen = "6k1/5ppp/8/8/8/8/5PPP/3Q2K1 w - - 0 1"
        label = puzzles.theme_label(fen, "d1d8", ["sacrifice", "mateIn2"])
        self.assertEqual(label, "Queen Sacrifice")

    def test_theme_label_falls_back(self):
        fen = "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"
        self.assertEqual(puzzles.theme_label(fen, "d1d8", ["sacrifice"]),
                         "Sacrifice")

    def test_validate_rejects_illegal_and_wrong_length(self):
        fen = "r1bq1rk1/pp2bpp1/2n1pn1p/3p4/3P4/2NBPN2/PP3PPP/R1BQ1RK1 w - - 0 9"
        self.assertFalse(puzzles.validate(fen, ["a1a2"]))          # too short
        self.assertFalse(puzzles.validate(fen, ["e1e2", "e2e3"]))  # illegal

    def test_capture_counts_as_a_visual_sacrifice(self):
        fen = "r1bq1rk1/pp2bpp1/2n1pn1p/3p4/3P4/2NBPN2/PP3PPP/R1BQ1RK1 w - - 0 9"
        self.assertTrue(puzzles.is_visual_sacrifice(fen, "d3h7"))

    def test_brilliant_index_flags_a_queen_sacrifice(self):
        # Qxh7+ gives the queen (9) for a pawn (1) on a defended square.
        fen = "3q2rk/1b1n1p1p/2pp1Pp1/8/3P3Q/2PB1R2/2P3PP/6K1 w - - 5 23"
        self.assertEqual(puzzles.brilliant_index(fen, ["h4h7", "h8h7", "f3h3"]), 0)

    def test_brilliant_index_rejects_a_winning_capture(self):
        # Rook takes an undefended queen — a great move, but not a sacrifice.
        fen = "3q2k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"
        self.assertIsNone(puzzles.brilliant_index(fen, ["d1d8", "g8h7"]))


class TestEdgeCases(unittest.TestCase):
    """Section 14.3 — castling, promotion and en passant piece bookkeeping."""

    def _piece_count(self, board):
        return len(board.piece_map())

    def test_castling_moves_both_king_and_rook(self):
        board = chess.Board("r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1")
        move = chess.Move.from_uci("e1g1")
        self.assertTrue(board.is_castling(move))

        frames = list(animate.build_slide_frames(board, move, 360, 30, 0.2))
        self.assertGreater(len(frames), 0)

        after = board.copy()
        after.push(move)
        self.assertEqual(after.piece_at(chess.G1),
                         chess.Piece(chess.KING, chess.WHITE))
        self.assertEqual(after.piece_at(chess.F1),
                         chess.Piece(chess.ROOK, chess.WHITE))
        self.assertIsNone(after.piece_at(chess.H1))
        self.assertEqual(self._piece_count(after), self._piece_count(board))

    def test_promotion_animates_and_promotes(self):
        board = chess.Board("8/P6k/8/8/8/8/8/7K w - - 0 1")
        move = chess.Move.from_uci("a7a8q")
        self.assertIn(move, board.legal_moves)

        frames = list(animate.build_slide_frames(board, move, 360, 30, 0.2))
        self.assertGreater(len(frames), 0)

        after = board.copy()
        after.push(move)
        self.assertEqual(after.piece_at(chess.A8),
                         chess.Piece(chess.QUEEN, chess.WHITE))

    def test_en_passant_captures_off_the_destination_square(self):
        board = chess.Board("8/8/8/3pP3/8/8/8/K6k w - d6 0 2")
        move = chess.Move.from_uci("e5d6")
        self.assertTrue(board.is_en_passant(move))

        # The captured pawn sits on d5, not on the destination d6.
        victim = animate.captured_square(board, move)
        self.assertEqual(victim, chess.D5)

        frames = list(animate.build_slide_frames(board, move, 360, 30, 0.2))
        self.assertGreater(len(frames), 0)

        after = board.copy()
        after.push(move)
        self.assertIsNone(after.piece_at(chess.D5))   # no ghost pawn
        self.assertEqual(self._piece_count(after), self._piece_count(board) - 1)

    def test_knight_slide_produces_frames(self):
        board = chess.Board()
        frames = list(animate.build_slide_frames(
            board, chess.Move.from_uci("g1f3"), 360, 30, 0.2))
        self.assertEqual(len(frames), 6)
        self.assertEqual(frames[0].size, (360, 360))


class TestSpeech(unittest.TestCase):
    """Section 14.4 — SAN to spoken text."""

    def test_capture_with_check(self):
        board = chess.Board(
            "r1bq1rk1/pp2bppp/2n1pn2/3p4/3P4/2NBPN2/PP3PPP/R1BQ1RK1 w - - 0 9")
        text, san = speech.move_to_speech(board, chess.Move.from_uci("d3h7"))
        self.assertEqual(san, "Bxh7+")
        self.assertEqual(text, "bishop takes H 7, check")

    def test_quiet_move(self):
        board = chess.Board()
        text, san = speech.move_to_speech(board, chess.Move.from_uci("g1f3"))
        self.assertEqual(san, "Nf3")
        self.assertEqual(text, "knight to F 3")

    def test_checkmate_is_announced(self):
        board = chess.Board("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1")
        text, san = speech.move_to_speech(board, chess.Move.from_uci("a1a8"))
        self.assertIn("#", san)
        self.assertTrue(text.endswith("Checkmate."))

    def test_castling(self):
        board = chess.Board("r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1")
        text, _ = speech.move_to_speech(board, chess.Move.from_uci("e1g1"))
        self.assertEqual(text, "castles king side")

    def test_engine_order_prefers_offline_neural_over_sapi(self):
        # Piper (offline neural) must be tried before SAPI (robotic).
        self.assertEqual(config.TTS_ORDER, ["edge", "piper", "sapi"])
        self.assertLess(config.TTS_ORDER.index("piper"),
                        config.TTS_ORDER.index("sapi"))

    def test_empty_text_yields_silence(self):
        vo = speech.synthesize("", Path(tempfile.gettempdir()) / "none")
        self.assertEqual(vo.source, "silence")
        self.assertFalse(vo.ok)

    def test_promotion_is_announced(self):
        board = chess.Board("8/P6k/8/8/8/8/8/7K w - - 0 1")
        text, _ = speech.move_to_speech(board, chess.Move.from_uci("a7a8q"))
        self.assertIn("promotes to queen", text)


class TestAudio(unittest.TestCase):
    """Section 14.5 — a mixed track must not clip, go silent, or drop out."""

    def test_every_sfx_is_bounded(self):
        for name in sfx.names():
            buf = sfx.get(name)
            self.assertGreater(buf.size, 0, name)
            self.assertLessEqual(float(np.max(np.abs(buf))), 1.0, name)

    def test_generated_music_is_bounded_and_long_enough(self):
        bed = music.generate(6.0, "seed")
        self.assertAlmostEqual(bed.size / config.SAMPLE_RATE, 6.0, places=1)
        self.assertLessEqual(float(np.max(np.abs(bed))), 1.0)

    def test_music_rotates_with_the_puzzle_id(self):
        a = music.generate(2.0, "aaa")
        b = music.generate(2.0, "zzz")
        self.assertFalse(np.allclose(a, b))

    def test_mix_passes_peak_rms_and_dead_air_checks(self):
        silent_vo = speech.Voiceover("x", np.zeros(config.SAMPLE_RATE), 1.0, "silence")
        events = [
            AudioEvent(0.2, "sfx", "tick"),
            AudioEvent(1.2, "sfx", "whoosh"),
            AudioEvent(1.6, "sfx", "capture"),
            AudioEvent(2.0, "vo", silent_vo),
            AudioEvent(4.0, "sfx", "mate"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            report = mixer.mix(events, 8.0, Path(tmp) / "m.wav", "seed")
        self.assertLessEqual(report["peak"], config.AUDIO_PEAK_MAX)
        self.assertGreaterEqual(report["rms"], config.AUDIO_RMS_MIN)
        self.assertLessEqual(report["rms"], config.AUDIO_RMS_MAX)
        self.assertFalse(report["dead_air"])
        self.assertTrue(report["ok"])

    def test_verify_flags_dead_air(self):
        track = np.zeros(config.SAMPLE_RATE * 5)
        report = mixer.verify(track)
        self.assertTrue(report["dead_air"])
        self.assertFalse(report["ok"])

    def test_wav_roundtrip(self):
        data = np.sin(np.linspace(0, 40, config.SAMPLE_RATE)) * 0.5
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.wav"
            audioutil.write_wav(path, data)
            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, 1000)


class TestComposition(unittest.TestCase):
    """Layout rules that carry the format."""

    def test_sacrifice_label_respects_brilliant_badge_setting(self):
        # With the badge on, the "!!" lives on the board, not the headline.
        label, colour = compose.move_label("Bxh7+", True)
        self.assertEqual(colour, config.ACCENT)
        if config.SHOW_BRILLIANT:
            self.assertEqual(label, "Bxh7+")
        else:
            self.assertEqual(label, "Bxh7+ !!")

    def test_normal_move_is_plain_white(self):
        label, colour = compose.move_label("Nf3", False)
        self.assertEqual(label, "Nf3")
        self.assertEqual(colour, config.WHITE)

    def test_checkmate_uses_accent(self):
        _, colour = compose.move_label("Qh7#", False)
        self.assertEqual(colour, config.ACCENT)

    def test_eval_dips_on_a_sacrifice_and_spikes_at_mate(self):
        board = chess.Board(
            "r1bq1rk1/pp2bppp/2n1pn2/3p4/3P4/2NBPN2/PP3PPP/R1BQ1RK1 w - - 0 9")
        before = compose.simple_eval(board)
        board.push_uci("d3h7")     # bishop takes a pawn
        board.push_uci("g8h7")     # ...and is recaptured: material dip
        self.assertLess(compose.simple_eval(board), before)

        mate = chess.Board("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1")
        mate.push_uci("a1a8")
        self.assertEqual(compose.simple_eval(mate), config.EVAL_CLAMP)

    def test_frame_is_the_right_size(self):
        board = chess.Board()
        img = board_mod.render_board(board, config.BOARD_PX)
        frame = compose.compose_frame(compose.FrameState(
            board_img=img, headline="TEST", dots_total=4, dots_active=1))
        self.assertEqual(frame.size, (config.CANVAS_W, config.CANVAS_H))

    def test_reactions_stay_disabled(self):
        # Section 0: reaction overlays are permanently removed.
        self.assertFalse(config.SHOW_REACTIONS)


class TestQueue(unittest.TestCase):
    """Ledger must be atomic and must dedupe."""

    def test_record_and_dedupe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "posted.json"
            puzzle = {"id": "abc12", "rating": 1500, "theme_label": "Sacrifice"}

            ledger.record_success(puzzle, "v.mp4", "c.txt", 15.0, path=path)
            ledger.record_success(puzzle, "v.mp4", "c.txt", 15.0, path=path)

            data = ledger.load(path)
            self.assertEqual(data["posted"].count("abc12"), 1)
            self.assertEqual(len(data["pending"]), 1)
            self.assertIn("abc12", ledger.posted_ids(path))

    def test_corrupt_ledger_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "posted.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(ledger.load(path), {"posted": [], "pending": []})

    def test_mark_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "posted.json"
            puzzle = {"id": "z1", "rating": 1500, "theme_label": "Sacrifice"}
            ledger.record_success(puzzle, "v.mp4", "c.txt", 15.0, path=path)
            ledger.mark_status("z1", "posted", path=path)
            self.assertEqual(ledger.load(path)["pending"][0]["status"], "posted")
            self.assertEqual(ledger.pending(path), [])


class TestCaptions(unittest.TestCase):
    """Captions must always produce a usable file, API or not."""

    PUZZLE = {
        "id": "smoke01",
        "fen": "r1bq1rk1/pp2bppp/2n1pn2/3p4/3P4/2NBPN2/PP3PPP/R1BQ1RK1 w - - 0 9",
        "solution": ["d3h7", "g8h7", "f3g5", "h7g8", "d1h5"],
        "rating": 1650,
        "theme_label": "Greek Gift Sacrifice",
        "sacrificed_piece": "bishop",
        "game_url": "https://lichess.org/x",
    }

    def test_san_rendering(self):
        san = captions.san_solution(self.PUZZLE["fen"], self.PUZZLE["solution"])
        self.assertTrue(san.startswith("Bxh7+ Kxh7 Ng5+"))

    def test_placeholder_is_marked_and_complete(self):
        caption = captions.generate(self.PUZZLE, use_api=False, log=lambda *_: None)
        self.assertTrue(caption["needs_caption"])
        for key in ("hook", "caption", "hashtags", "first_comment",
                    "youtube_title", "youtube_description"):
            self.assertIn(key, caption)

    def test_caption_file_is_written(self):
        caption = captions.generate(self.PUZZLE, use_api=False, log=lambda *_: None)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "caption.txt"
            text = captions.write_caption_file(path, self.PUZZLE, caption, 18.0)
            self.assertIn("POST: smoke01", text)
            self.assertIn("Bxh7+", text)
            self.assertTrue(path.exists())

    def test_schema_is_strict(self):
        self.assertFalse(captions.CAPTION_SCHEMA["additionalProperties"])
        self.assertEqual(sorted(captions.CAPTION_SCHEMA["required"]),
                         ["caption", "first_comment", "hashtags", "hook",
                          "youtube_description", "youtube_title"])


class TestOutputNumbering(unittest.TestCase):
    """Numbered output folders, idempotent per puzzle."""

    def test_first_folder_is_numbered_one(self):
        from src import build as builder
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(builder.next_index(root), 1)
            out = builder.resolve_out_root(root, "abc12")
            self.assertEqual(out.name, "0001_abc12")

    def test_index_continues_past_existing(self):
        from src import build as builder
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0001_aaa").mkdir()
            (root / "0007_bbb").mkdir()
            (root / "notnumbered").mkdir()
            self.assertEqual(builder.next_index(root), 8)
            self.assertEqual(builder.resolve_out_root(root, "ccc").name, "0008_ccc")

    def test_existing_folder_is_reused(self):
        from src import build as builder
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0003_abc12").mkdir()
            # Same puzzle resolves back to its folder rather than a new number.
            self.assertEqual(builder.resolve_out_root(root, "abc12").name,
                             "0003_abc12")

    def test_explicit_seq_is_honoured(self):
        from src import build as builder
        with tempfile.TemporaryDirectory() as tmp:
            out = builder.resolve_out_root(Path(tmp), "xyz", seq=42)
            self.assertEqual(out.name, "0042_xyz")


class TestVariants(unittest.TestCase):
    """Variant config — A unchanged, B distinct."""

    def test_simple_matches_module_defaults(self):
        v = config.variant("simple")
        self.assertEqual(v["board_px"], config.BOARD_PX)
        self.assertEqual(v["board_y_offset"], config.BOARD_Y_OFFSET)
        self.assertEqual(v["opening"], "countdown")
        self.assertEqual(v["output_subdir"], "")
        self.assertIsNone(v["reaction_band"])

    def test_reaction_board_is_higher_and_clears_the_band(self):
        """The board sits higher and must not eat the reaction band.

        This used to assert the board was also SMALLER than variant A's. That
        stopped being true on purpose — the board went 820 -> 880 -> 1000 to
        fill the gap above the band (see config.VARIANTS["reaction"]), so it is
        now larger than simple's 960 and the old assertion was testing a
        decision that had been reversed. What actually matters is the geometry
        below: a board that overlaps REACTION_BAND covers the meme clip, which
        is the whole variant.
        """
        a, b = config.variant("simple"), config.variant("reaction")
        self.assertLess(b["board_y_offset"], a["board_y_offset"])
        self.assertEqual(b["opening"], "watch")
        self.assertEqual(b["output_subdir"], "reaction")
        self.assertIsNotNone(b["reaction_band"])

        top = (config.CANVAS_H - b["board_px"]) // 2 + b["board_y_offset"]
        self.assertGreaterEqual(top, 0)
        self.assertLessEqual(top + b["board_px"], b["reaction_band"][1])

    def test_reaction_band_is_roughly_bottom_quarter(self):
        _, top, _, bottom = config.REACTION_BAND
        band_h = bottom - top
        self.assertGreater(band_h, config.CANVAS_H * 0.2)
        self.assertLess(band_h, config.CANVAS_H * 0.4)

    def test_watch_opening_is_short(self):
        self.assertLess(config.WATCH_DURATION, 2.0)

    def test_unknown_variant_raises(self):
        with self.assertRaises(ValueError):
            config.variant("nope")


class TestReactionSelection(unittest.TestCase):
    """Deterministic, varied, and safe when clips are missing."""

    MANIFEST = {
        "sacrifice": [{"file": "a.mp4", "duration": 2.5},
                      {"file": "b.mp4", "duration": 1.8},
                      {"file": "c.mp4", "duration": 2.2}],
        "mate": [{"file": "m.mp4", "duration": 2.0}],
    }

    def test_empty_manifest_returns_none(self):
        self.assertIsNone(reactions.select({"id": "x", "themes": []}, manifest={}))

    def test_category_mapping(self):
        self.assertEqual(config.reaction_category({"themes": ["mateIn2"]}), "mate")
        self.assertEqual(config.reaction_category({"themes": ["sacrifice"]}),
                         "sacrifice")

    def test_random_selection_covers_the_pool(self):
        import random
        import unittest.mock as mock
        rng = random.Random(1234)
        picks = []
        # select() checks path.exists(); bypass so the temp manifest resolves.
        with mock.patch("pathlib.Path.exists", return_value=True):
            for _ in range(40):
                r = reactions.select({"id": "x", "themes": ["sacrifice"]},
                                     manifest=self.MANIFEST, rng=rng)
                picks.append(r.file)
        # Random over 3 clips across 40 draws should hit all three.
        self.assertEqual(set(picks), {"a.mp4", "b.mp4", "c.mp4"})


@unittest.skipIf(os.environ.get("SKIP_SMOKE"), "SKIP_SMOKE set")
class TestEndToEnd(unittest.TestCase):
    """Section 14.6 — build one real video and verify the encode."""

    def test_smoke_puzzle_produces_a_valid_mp4(self):
        from run_batch import SMOKE_PUZZLE
        from src import build as builder
        from src import encode

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            # ledger_path keeps the real data/posted.json untouched.
            result = builder.build_one(
                dict(SMOKE_PUZZLE), use_api=False, output_dir=out,
                ledger_path=out / "posted.json", log=lambda *_: None)

            self.assertEqual(result["status"], "ok", result.get("error"))
            mp4 = Path(result["video"])
            self.assertTrue(mp4.exists())
            # Folder is numbered, not a bare puzzle id.
            folder = mp4.parent
            self.assertEqual(folder.name, "0001_smoke01")

            info = encode.probe(mp4)
            self.assertEqual((info["width"], info["height"]), (1080, 1920))
            self.assertEqual(info["video_codec"], "h264")
            self.assertEqual(info["audio_codec"], "aac")   # audio must exist
            self.assertGreater(info["filesize"], 200_000)
            self.assertTrue(10.0 < info["duration"] < 30.0)

            meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["puzzle_id"], "smoke01")
            self.assertTrue(meta["audio"]["ok"])

            # The puzzle is marked posted only after the encode verified.
            self.assertIn("smoke01", ledger.posted_ids(out / "posted.json"))

            self.assertTrue((folder / "caption.txt").exists())
            self.assertFalse((folder / "frames").exists(),
                             "frames must be deleted after a verified encode")


if __name__ == "__main__":
    unittest.main(verbosity=2)
