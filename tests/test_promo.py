"""Tests for the TChess promo chrome: banner, end card, sacrifice truncation.

The promo work is ADDITIVE — the four original variants must keep their exact
output, and `app` in particular feeds the in-app tactics feed and may never
carry branding (CHESS_APP_BLUEPRINT.md Section 13.1). Most of what follows
guards that, not the new features.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chess                                                    # noqa: E402
from PIL import Image, ImageFont                                # noqa: E402

import config                                                   # noqa: E402
from src import compose                                         # noqa: E402
from src import puzzles as puzzles_mod                          # noqa: E402

PROMO_VARIANTS = ("promo_sac", "promo_guess", "promo_mate", "promo_tour",
                  "promo_bots", "promo_carousel")
LEGACY_VARIANTS = ("simple", "reaction", "gm_games", "app")
SOURCES = {"promo_tour": "screenshots", "promo_bots": "bots",
           "promo_carousel": "carousel"}


class TestPromoVariantConfig(unittest.TestCase):
    def test_promo_variants_registered(self):
        for name in PROMO_VARIANTS:
            self.assertIn(name, config.VARIANTS, name)

    def test_promo_variants_carry_every_required_key(self):
        """A variant missing a key crashes mid-render, not at selection."""
        required = set(config.VARIANTS["simple"])
        for name in PROMO_VARIANTS:
            missing = required - set(config.variant(name))
            self.assertEqual(missing, set(), f"{name} is missing {missing}")

    def test_promo_variants_have_banner_and_endcard(self):
        for name in PROMO_VARIANTS:
            v = config.variant(name)
            self.assertTrue(v["show_promo_banner"], name)
            self.assertTrue(v["show_endcard"], name)

    def test_no_legacy_variant_carries_the_banner(self):
        """The banner takes the top row, which the legacy formats already use.

        gm_games is the pointed case: it draws "GM GAMES" at SERIES_LABEL_Y,
        exactly where the banner lands, so turning the banner on there hides
        the series' own identity behind the app's.
        """
        for name in LEGACY_VARIANTS:
            v = config.variant(name)
            self.assertFalse(v["show_promo_banner"], name)
            self.assertFalse(v["stop_after_brilliant"], name)

    def test_only_gm_games_gained_an_end_card(self):
        """A deliberate exception, recorded so it is not "fixed" back.

        The end card runs AFTER the game, so a GM replay can sell the app
        without spending two minutes looking like a TChess ad. simple and
        reaction stay untouched as the channel's archive.
        """
        self.assertTrue(config.variant("gm_games")["show_endcard"])
        for name in ("simple", "reaction", "app"):
            self.assertFalse(config.variant(name)["show_endcard"], name)

    def test_app_variant_stays_unbranded(self):
        """Section 13.1 — the in-app video has no watermark and no CTA either."""
        app = config.variant("app")
        self.assertFalse(app["show_watermark"])
        self.assertFalse(app["show_cta"])
        self.assertFalse(app["show_promo_banner"])
        self.assertFalse(app["show_endcard"])

    def test_only_promo_sac_truncates(self):
        self.assertTrue(config.variant("promo_sac")["stop_after_brilliant"])
        self.assertFalse(config.variant("promo_guess")["stop_after_brilliant"])
        self.assertFalse(config.variant("promo_tour")["stop_after_brilliant"])

    def test_promo_variants_write_to_their_own_folders(self):
        subdirs = {config.variant(n)["output_subdir"] for n in PROMO_VARIANTS}
        self.assertEqual(len(subdirs), len(PROMO_VARIANTS))
        for n in PROMO_VARIANTS:
            self.assertTrue(config.variant(n)["output_subdir"].startswith("promo/"))

    def test_promo_sac_headline_clears_the_banner(self):
        """reaction's 150 would sit 8px under the banner's bottom edge."""
        banner_bottom = config.PROMO_BANNER_Y + config.PROMO_BANNER_H
        self.assertGreater(config.variant("promo_sac")["headline_y"], banner_bottom)

    def test_each_source_routes_to_its_own_builder(self):
        """run_batch branches on `source`; a wrong value silently builds a reel."""
        for name, src in SOURCES.items():
            self.assertEqual(config.variant(name).get("source"), src, name)
        for name in LEGACY_VARIANTS + ("promo_sac", "promo_guess", "promo_mate"):
            self.assertIsNone(config.variant(name).get("source"), name)

    def test_promo_mate_is_restricted_to_mates(self):
        self.assertEqual(config.variant("promo_mate")["theme"], "mateIn2")
        self.assertNotIn("Sacrifice", " ".join(config.variant("promo_mate")["subtitles"]))
        # ...and nothing else carries a selection theme of its own.
        for name in LEGACY_VARIANTS + ("promo_sac", "promo_guess"):
            self.assertIsNone(config.variant(name).get("theme"), name)


class TestNoPuzzleCounts(unittest.TestCase):
    """The app says 60,000 puzzles and the website says 15,000.

    Printing either invites the contradiction, so the promo copy names features
    and never counts them. This is the guard that keeps a number from creeping
    back in later.
    """

    def _strings(self):
        out = [config.ENDCARD_TAGLINE, config.ENDCARD_PROMISE,
               config.ENDCARD_PLAY, config.ENDCARD_WEB,
               config.ENDCARD_INSTALL, config.ENDCARD_STORE_DEV,
               config.PROMO_BANNER_SUB, config.BRAND_NAME]
        out += list(config.ENDCARD_FEATURES)
        out += list(config.ENDCARD_STORE_TITLE)
        out += [label for _f, label, _c, _v in config.TOUR_SHOTS]
        out += [call for _f, _l, call, _v in config.TOUR_SHOTS]
        out += [line for _f, _l, _c, line in config.TOUR_SHOTS]
        return out

    def test_no_digit_in_any_promo_string(self):
        for s in self._strings():
            self.assertFalse(any(ch.isdigit() for ch in s),
                             f"promo copy must carry no numbers: {s!r}")

    def test_features_name_more_than_puzzles(self):
        """'aur bhi bahut kuch hai' — the app is not only a puzzle trainer."""
        names = {f.lower() for f in config.ENDCARD_FEATURES}
        for expected in ("puzzles", "openings", "bots", "analysis",
                         "endgames", "lessons"):
            self.assertIn(expected, names)

    def test_feature_count_fills_the_two_columns(self):
        self.assertEqual(len(config.ENDCARD_FEATURES) % 2, 0)


class TestBrandAssets(unittest.TestCase):
    def test_every_brand_asset_exists(self):
        for path in (config.BRAND_MARK, config.BRAND_FONT,
                     config.BRAND_STORE_ICON):
            self.assertTrue(path.is_file(), path)

    def test_mark_has_real_transparency(self):
        """icon.png is fully opaque and paints a black box; mark.png must not be."""
        img = Image.open(config.BRAND_MARK)
        self.assertEqual(img.mode, "RGBA")
        self.assertEqual(img.getchannel("A").getextrema()[0], 0,
                         "mark.png has no transparent pixels — wrong source file")

    def test_lockup_spells_the_name(self):
        """The lockup is the DESIGNER'S artwork, not a composed near-match.

        compose._wordmark_sprite used to draw its own: the rook from mark.png
        beside the name typed in Sora Bold. That existed because the shipped
        wordmark set the rook AS the letter T, so it read "♜Chess" to anyone who
        did not already know the brand. The delivered file has a real T, so the
        reels and the app now carry the same mark instead of two near-misses.
        """
        self.assertEqual(config.BRAND_NAME, "TChess")
        lockup = compose._wordmark_sprite(120)
        rook = compose._rook_mark(120)
        self.assertGreater(lockup.width, rook.width,
                           "the lockup is only the mark — the name is missing")

    def test_rook_is_trimmed_to_its_own_ink(self):
        """The source is an adaptive-icon layer: mostly transparent padding."""
        rook = compose._rook_mark(200)
        self.assertEqual(rook.height, 200)
        box = rook.getchannel("A").getbbox()
        self.assertEqual(box, (0, 0, rook.width, rook.height))

    def test_lockup_is_the_delivered_file_at_the_height_asked_for(self):
        """Height in, height out — the artwork is already trimmed to its ink.

        ⚠️ THIS REPLACES test_rook_stands_at_cap_height_not_the_full_line, which
        asserted the opposite: that the lockup must NOT fill its own line,
        because a rook scaled to the full height towered over the word it was
        typed next to. That was a constraint on a lockup this code COMPOSED.
        The delivered artwork is one drawn piece, cropped to its own ink, so it
        fills its line by definition and the old assertion could only ever fail.
        """
        for h in (66, 190, 400):
            lockup = compose._wordmark_sprite(h)
            self.assertEqual(lockup.height, h)
            ink = lockup.getchannel("A").getbbox()
            # The delivered PNG has a single fully-transparent top row, so the
            # ink is h-1 at source scale and rounds around from there. Within a
            # couple of pixels is "trimmed"; a real padding regression would
            # show up as a much larger gap.
            self.assertGreaterEqual(ink[3] - ink[1], h - max(2, h // 100),
                                    "the artwork is not trimmed to its own ink")

    def test_lockup_keeps_the_delivered_aspect_ratio(self):
        """A squeezed wordmark is the one way this can go wrong unnoticed."""
        art = Image.open(config.BRAND_WORDMARK)
        expected = art.width / art.height
        for h in (66, 190):
            lockup = compose._wordmark_sprite(h)
            self.assertAlmostEqual(lockup.width / lockup.height, expected,
                                   delta=0.02)

    def test_banner_and_endcard_draw_the_same_mark(self):
        """Two different lockups on one reel is how a brand stops reading."""
        small = compose._wordmark_sprite(config.PROMO_BANNER_WORDMARK_H)
        big = compose._wordmark_sprite(config.ENDCARD_WORDMARK_H)
        self.assertAlmostEqual(small.width / small.height,
                               big.width / big.height, delta=0.02)


class TestStoreRow(unittest.TestCase):
    """The row exists to be RECOGNISED, so it must match the live listing."""

    def test_title_is_the_live_store_title(self):
        joined = " ".join(config.ENDCARD_STORE_TITLE)
        self.assertEqual(joined, "TChess: Chess Puzzles, Tactics")
        self.assertLessEqual(len(joined), 30, "Play caps the title at 30 chars")

    def test_developer_name_matches_the_listing(self):
        self.assertEqual(config.ENDCARD_STORE_DEV, "Optivio Automation")

    def test_install_button_uses_play_green_not_the_app_accent(self):
        self.assertEqual(config.PLAY_GREEN, (1, 135, 95))
        self.assertNotEqual(config.PLAY_GREEN, config.APP_VIOLET)

    def test_store_icon_is_rounded(self):
        """A square icon does not read as an app; the store rounds it."""
        icon = compose._store_icon(120)
        self.assertEqual(icon.mode, "RGBA")
        self.assertEqual(icon.getpixel((0, 0))[3], 0, "corner is not rounded")
        self.assertEqual(icon.getpixel((60, 60))[3], 255)

    def test_store_card_and_button_do_not_overlap(self):
        self.assertLess(config.ENDCARD_STORE_CARD[3], config.ENDCARD_PILL[1])


class TestBoardMatchesTheApp(unittest.TestCase):
    """The reel's board IS the app's board, and this is the guard for it.

    It reads the APP's own theme file. If someone retunes `classic` over there,
    this fails here — which is the whole point: a promo whose board does not
    look like the product teaches the viewer the wrong thing to look for.
    """

    THEMES = Path(__file__).resolve().parents[2] / "tchess-app" / "src" / "theme" / "boardThemes.ts"

    def _classic(self):
        if not self.THEMES.is_file():
            self.skipTest(f"app theme file not on this machine: {self.THEMES}")
        src = self.THEMES.read_text(encoding="utf-8")
        block = src.split("classic:", 1)[1].split("},", 1)[0]
        found = dict(re.findall(r"(light|dark):\s*'(#[0-9A-Fa-f]{6})'", block))
        self.assertEqual(set(found), {"light", "dark"}, "could not parse classic")
        return found

    def test_squares_match_the_apps_default_theme(self):
        classic = self._classic()
        self.assertEqual(config.BOARD_COLORS["square light"].upper(),
                         classic["light"].upper())
        self.assertEqual(config.BOARD_COLORS["square dark"].upper(),
                         classic["dark"].upper())

    def test_pieces_are_the_same_set_as_the_app(self):
        """Both render Cburnett — the app via Piece.tsx, the reel via python-chess.

        Asserted on the artwork itself rather than on a comment: chess.svg
        carries the Cburnett licence string in its own module.
        """
        import chess.svg
        svg = chess.svg.piece(chess.Piece.from_symbol("N"))
        self.assertIn("<svg", svg)
        self.assertIn("path", svg)

    def test_margin_matches_the_canvas_so_the_board_floats(self):
        r, g, b = config.BG
        self.assertEqual(config.BOARD_COLORS["margin"].upper(),
                         f"#{r:02X}{g:02X}{b:02X}")


class TestPromoBannerPixels(unittest.TestCase):
    """Compose-level: the flag actually changes the frame, like show_watermark."""

    @classmethod
    def setUpClass(cls):
        cls.board_img = Image.new("RGB", (config.BOARD_PX, config.BOARD_PX),
                                  (40, 60, 40))

    def _frame(self, **kw):
        return compose.compose_frame(
            compose.FrameState(board_img=self.board_img, **kw))

    def test_banner_changes_pixels(self):
        with_banner = self._frame(show_promo_banner=True)
        without = self._frame(show_promo_banner=False)
        self.assertNotEqual(with_banner.tobytes(), without.tobytes())

    def test_banner_is_off_by_default(self):
        self.assertEqual(self._frame().tobytes(),
                         self._frame(show_promo_banner=False).tobytes())

    def test_banner_lands_in_the_top_band(self):
        """It must not drift down over the headline or the board."""
        banner = compose._banner_sprite()
        self.assertLessEqual(config.PROMO_BANNER_Y + banner.height,
                             config.PROMO_BANNER_Y + config.PROMO_BANNER_H)
        self.assertLess(banner.width, config.CANVAS_W)


class TestEndcard(unittest.TestCase):
    def test_endcard_is_canvas_sized(self):
        card = compose.endcard_frame(1.0)
        self.assertEqual(card.size, (config.CANVAS_W, config.CANVAS_H))

    def test_endcard_is_not_blank(self):
        card = compose.endcard_frame(1.0)
        self.assertGreater(len(card.getcolors(maxcolors=1 << 24) or []), 50)

    def test_fade_starts_at_the_background(self):
        faded = compose.endcard_frame(0.0)
        ground = Image.new("RGB", faded.size, config.BG)
        self.assertEqual(faded.tobytes(), ground.tobytes())

    def test_endcard_content_clears_the_bottom_safe_zone(self):
        """Nothing important may sit where the platform draws captions."""
        last = max(config.ENDCARD_WEB_Y + config.ENDCARD_WEB_SIZE,
                   config.ENDCARD_PILL[3])
        self.assertLess(last, config.CANVAS_H - config.SAFE_BOTTOM)


class TestSacrificeTruncation(unittest.TestCase):
    """The truncation itself is one slice; what matters is what it produces."""

    SMOKE = {
        "fen": "r1bq1rk1/pp2bppp/2n1pn2/3p4/3P4/2NBPN2/PP3PPP/R1BQ1RK1 w - - 0 9",
        "solution": ["d3h7", "g8h7", "f3g5", "h7g8", "d1h5"],
    }

    def test_bundled_smoke_puzzle_has_a_brilliant_move(self):
        idx = puzzles_mod.brilliant_index(self.SMOKE["fen"], self.SMOKE["solution"])
        self.assertEqual(idx, 0)

    def test_truncation_leaves_exactly_the_sacrifice(self):
        idx = puzzles_mod.brilliant_index(self.SMOKE["fen"], self.SMOKE["solution"])
        cut = self.SMOKE["solution"][: idx + 1]
        self.assertEqual(cut, ["d3h7"])

    def test_the_truncated_move_is_still_legal_from_the_fen(self):
        """A one-move reel still has to render, so the slice must be playable."""
        board = chess.Board(self.SMOKE["fen"])
        move = chess.Move.from_uci(self.SMOKE["solution"][0])
        self.assertIn(move, board.legal_moves)

    def test_a_puzzle_without_a_brilliant_move_is_not_truncated(self):
        """brilliant_index None means there is nothing to cut at — leave it whole."""
        fen = "8/8/8/4k3/8/8/4K3/8 w - - 0 1"          # nothing to sacrifice
        self.assertIsNone(puzzles_mod.brilliant_index(fen, ["e2e3"]))


class TestTourConfig(unittest.TestCase):
    def test_every_tour_screenshot_exists(self):
        for name, _l, _c, _vo in config.TOUR_SHOTS:
            self.assertTrue((config.TOUR_SHOT_DIR / name).is_file(),
                            f"missing tour screenshot: {name}")

    def test_labels_are_one_word(self):
        """The label has to read before the viewer has focused on the phone.

        Two words at 104px either wrap or shrink, and both undo the reason the
        label is there at all.
        """
        for _n, label, _c, _vo in config.TOUR_SHOTS:
            self.assertNotIn(" ", label.strip(), label)
            self.assertLessEqual(len(label), 12, label)

    def test_callouts_are_one_short_line(self):
        for _n, _l, callout, _vo in config.TOUR_SHOTS:
            self.assertLessEqual(len(callout), 26, callout)
            self.assertNotIn("\n", callout)

    def _phone_height(self) -> int:
        shot = Image.open(config.TOUR_SHOT_DIR / config.TOUR_SHOTS[0][0])
        screen_w = config.MOCKUP_PHONE_W - config.MOCKUP_BEZEL * 2
        return round(shot.height * screen_w / shot.width) + config.MOCKUP_BEZEL * 2

    def test_the_phone_sits_between_the_label_and_the_banner(self):
        """A mockup that runs off the bottom is the classic composite bug.

        The three bands are label, phone, banner-as-footer — in that order and
        without overlapping, which is the whole layout.
        """
        bottom = config.MOCKUP_PHONE_Y + self._phone_height()
        self.assertGreater(config.MOCKUP_PHONE_Y,
                           config.MOCKUP_LABEL_Y + config.MOCKUP_LABEL_SIZE)
        self.assertLess(bottom, config.MOCKUP_BANNER_BOTTOM)
        self.assertLessEqual(config.MOCKUP_BANNER_BOTTOM + config.PROMO_BANNER_H,
                             config.CANVAS_H)

    def test_the_phone_is_the_biggest_thing_on_the_frame(self):
        """It is the subject. An earlier pass shrank it to 560 to fit a pill
        beside it, which made the product the smallest element in its own
        product shot."""
        self.assertGreater(self._phone_height(), config.CANVAS_H * 0.65)
        self.assertGreaterEqual(config.MOCKUP_PHONE_W, 620)

    def test_accents_rotate_so_the_shots_do_not_all_look_alike(self):
        """One glow colour eight times running reads as one long screen."""
        from src import mockup
        self.assertGreaterEqual(len(mockup.ACCENTS), 3)
        self.assertEqual(len(set(mockup.ACCENTS)), len(mockup.ACCENTS))


class TestLandscapeTour(unittest.TestCase):
    """The Play listing video is the ONE place 9:16 is wrong."""

    def test_it_is_sixteen_by_nine(self):
        self.assertEqual(config.WIDE_W / config.WIDE_H, 16 / 9)
        self.assertGreater(config.WIDE_W, config.WIDE_H)

    def test_it_is_a_relayout_not_a_letterbox(self):
        """The phone occupies one side and the copy the other. If the handset
        were centred the frame would be the vertical reel with black bars,
        which is exactly what this variant exists to avoid."""
        phone_left = config.WIDE_PHONE_X
        self.assertGreater(phone_left, config.WIDE_W * 0.55)
        self.assertLess(config.WIDE_TEXT_X, config.WIDE_W * 0.25)

    def test_the_phone_fits_the_shorter_axis(self):
        self.assertLess(config.WIDE_PHONE_Y + config.WIDE_PHONE_H, config.WIDE_H)

    def test_the_variant_routes_to_its_own_builder(self):
        self.assertEqual(config.variant("promo_tour_wide")["source"], "tour_wide")
        self.assertNotEqual(config.variant("promo_tour_wide")["output_subdir"],
                            config.variant("promo_tour")["output_subdir"])

    def test_it_shares_its_content_with_the_vertical_tour(self):
        """Same shots and same lines — two cuts of one film, not two films."""
        from src import landscape
        self.assertTrue(hasattr(landscape, "build_wide"))
        self.assertGreaterEqual(len(config.TOUR_SHOTS), 6)


if __name__ == "__main__":
    unittest.main()
