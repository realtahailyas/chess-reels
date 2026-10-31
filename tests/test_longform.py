"""Long-form pipeline: the rules that must not quietly break.

Fast: no engine, no render, no network. Reads the built catalogue and photo
folder when they exist and skips those checks when they do not.
"""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chess  # noqa: E402

import config  # noqa: E402
from longform import catalog, engine, metadata, players  # noqa: E402
from longform import lfconfig as C  # noqa: E402


class Names(unittest.TestCase):
    def test_archive_spellings_resolve(self):
        cases = {
            "Carlsen,M": "carlsen", "Carlsen, Magnus": "carlsen", "Kasparov, Gary": "kasparov",
            "Nakamura,Hi": "nakamura", "Ding Liren": "ding", "Gukesh,D": "gukesh",
            "Polgar,Ju": "polgar", "Fischer, Robert James": "fischer", "Tal, Mihail": "tal",
            "Byrne, Donald": "byrne_d", "Byrne, Robert E": "byrne_r", "So,W": "so",
            "Comp Deep Blue": "deepblue", "Lasker, Emanuel": "lasker",
        }
        for raw, slug in cases.items():
            self.assertEqual(players.identify(raw), slug, raw)

    def test_lookalikes_do_not_match(self):
        # Wrong Polgar, wrong Lasker, a stranger called Tal-something.
        for raw in ("Polgar,Zsuzsa", "Lasker, Edward", "Talla, X", "Soto, J"):
            self.assertIsNone(players.identify(raw), raw)


class Channels(unittest.TestCase):
    def test_each_brand_maps_to_a_real_account(self):
        for brand, b in C.BRANDS.items():
            self.assertIn(b["account"], config.ACCOUNTS, brand)
        self.assertNotEqual(C.BRANDS["tchess"]["account"], C.BRANDS["tahachess"]["account"])

    def test_long_slots_avoid_the_shorts_slots(self):
        """A long video never goes public within 45 min of the same channel's short."""
        tz = ZoneInfo(C.SLOT_TZ)
        pkt = ZoneInfo("Asia/Karachi")
        for month in (1, 7):                     # winter and summer time in New York
            for b in C.BRANDS.values():
                shorts = [int(h) * 60 + int(m) for h, m in
                          (s.split(":") for s in config.ACCOUNTS[b["account"]]["publish_times_pkt"])]
                for hhmm in b["slots_et"]:
                    h, m = map(int, hhmm.split(":"))
                    t = datetime(2026, month, 15, h, m, tzinfo=tz).astimezone(pkt)
                    mins = t.hour * 60 + t.minute
                    gap = min(min(abs(mins - s), 1440 - abs(mins - s)) for s in shorts)
                    self.assertGreaterEqual(gap, 45, f"{b['account']} {hhmm} ET in month {month}")

    @unittest.skipUnless(catalog.CATALOG.is_file(), "catalogue not built")
    def test_channels_never_share_a_game(self):
        a = {e["id"] for e in catalog.for_brand("tchess")}
        b = {e["id"] for e in catalog.for_brand("tahachess")}
        self.assertFalse(a & b)
        keys = [e["rec"]["key"] for e in catalog.load()]
        self.assertEqual(len(keys), len(set(keys)), "same game twice in the catalogue")


class Judgement(unittest.TestCase):
    def _game(self, sans):
        b = chess.Board()
        moves = []
        for s in sans:
            mv = b.parse_san(s)
            moves.append(mv)
            b.push(mv)
        return {"start_fen": chess.STARTING_FEN, "moves": moves}

    def test_engine_best_move_is_never_an_error(self):
        g = self._game(["e4", "e5"])
        pos = [
            {"score": {"cp": 30, "mate": None}, "second": None, "best": "e2e4"},
            # A shallower search of the next position disagrees wildly.
            {"score": {"cp": -400, "mate": None}, "second": None, "best": "e7e5"},
            {"score": {"cp": -400, "mate": None}, "second": None, "best": None},
        ]
        j = engine.judge(g, pos, book=0)
        self.assertIsNone(j[0]["glyph"])

    def test_consistent_carries_forcing_lines(self):
        g = self._game(["e4", "e5"])
        pos = [{"score": {"cp": 0, "mate": None}, "best": "e2e4"},
               {"score": {"cp": 50, "mate": None}, "best": "e7e5"},
               {"score": {"cp": 700, "mate": None}, "best": None}]
        out = engine.consistent(g, pos)
        self.assertEqual(out[0]["score"]["cp"], 700)
        self.assertEqual(out[0]["raw"]["cp"], 0)


class Metadata(unittest.TestCase):
    META = {
        "title": "", "source": "scored", "white": "Magnus Carlsen", "black": "Hikaru Nakamura",
        "white_slug": "carlsen", "black_slug": "nakamura", "white_elo": "2850", "black_elo": "2780",
        "event": "Norway Chess <Blitz>", "site": "Stavanger", "year": "2019", "round": "",
        "result": "1-0", "final_mate": False, "opening": "Sicilian Defense",
        "marks": [{"ply": 30, "san": "Rxf7", "glyph": "!!", "text": "Rook sacrifice", "mover": "white"}],
        "chapters": [{"t": 0, "label": "The opening"}, {"t": 120, "label": "Brilliant: 16. Rxf7"},
                     {"t": 400, "label": "Result"}],
    }

    def test_title_and_description_rules(self):
        t = metadata.title(self.META)
        self.assertLessEqual(len(t), 100)
        self.assertIn("Sacrifices His Rook", t)
        d = metadata.description(self.META)
        self.assertNotIn("<", d)
        self.assertNotIn(">", d)
        self.assertIn("0:00 Start", d)
        self.assertIn("2:00 Brilliant", d)

    def test_curated_title_keeps_its_name(self):
        m = dict(self.META, title="Kasparov's Immortal", white="Garry Kasparov", black="Veselin Topalov")
        self.assertTrue(metadata.title(m).startswith("Kasparov's Immortal | "))

    def test_facebook_caption_drops_chapters_keeps_credits_rules(self):
        cap = metadata.fb_caption(self.META)
        self.assertNotIn("Chapters", cap)
        self.assertNotIn("0:00", cap)
        self.assertIn("Key moments", cap)
        self.assertTrue(cap.startswith(metadata.title(self.META)))

    def test_photo_credit_cleanup(self):
        self.assertEqual(metadata.clean_author(
            "This photo was taken by Przemysław JahrAutorem zdjęcia jest Przemysław Jahr"), "Przemysław Jahr")
        self.assertEqual(metadata.clean_author("Unknown authorUnknown author"), "Unknown author")
        for handle in ("GibChess", "TheBoburshokh", "Stefan64"):      # usernames stay whole
            self.assertEqual(metadata.clean_author(handle), handle)


class FacebookRules(unittest.TestCase):
    """The reel poster must never lead YouTube, double-post, or leak a 9:16
    file into the YouTube uploader."""

    def _led(self, yt_publish_at, reel_status="built", posted_date=None):
        reel = {"game": "g1", "brand": "tahachess", "fmt": "reel", "status": reel_status,
                "at": "2026-09-29T00:00:00Z", "dir": "output/longform/g1_tahachess_reel"}
        if posted_date:
            reel.update(status="posted", posted_pkt_date=posted_date, posted_at="2026-09-29T00:30:00Z")
        return {"videos": {
            "g1_tahachess": {"game": "g1", "brand": "tahachess", "status": "scheduled",
                             "publish_at": yt_publish_at, "account": "tahachesstv", "at": "x"},
            "g1_tahachess_reel": reel,
        }, "playlists": {}}

    def test_reels_are_not_youtube_entries(self):
        import longform_daily
        led = self._led("2026-09-29T16:00:00Z")
        self.assertEqual([v["game"] for v in longform_daily.entries(led, "tahachess", "built")], [])
        self.assertEqual(len(longform_daily.entries(led, "tahachess")), 1)

    def test_never_posts_before_youtube_is_public(self):
        from unittest import mock
        from longform import facebook
        led = self._led("2999-01-01T00:00:00Z")
        with mock.patch("src.publisher.post_facebook") as post:
            self.assertIsNone(facebook.post(led, log=lambda s: None))
            post.assert_not_called()

    def test_one_reel_per_day(self):
        from datetime import datetime
        from unittest import mock
        from longform import facebook
        today = datetime.now(facebook.PKT).date().isoformat()
        led = self._led("2000-01-01T00:00:00Z", posted_date=today)
        led["videos"]["g2_tahachess_reel"] = dict(led["videos"]["g1_tahachess_reel"], game="g2",
                                                  status="built")
        led["videos"]["g2_tahachess_reel"].pop("posted_pkt_date")
        with mock.patch("src.publisher.post_facebook") as post:
            self.assertIsNone(facebook.post(led, log=lambda s: None))
            post.assert_not_called()


class LostBuilds(unittest.TestCase):
    """A built video whose folder was deleted must not block its channel."""

    def test_missing_files_return_the_game_to_the_queue(self):
        import tempfile
        from unittest import mock
        import longform_daily
        with tempfile.TemporaryDirectory() as tmp:
            kept = Path(tmp) / "kept"
            kept.mkdir()
            (kept / "video.mp4").write_bytes(b"x")
            (kept / "meta.json").write_text("{}")
            led = {"videos": {
                "gone_tchess": {"game": "gone", "brand": "tchess", "status": "built", "dir": "gone"},
                "kept_tchess": {"game": "kept", "brand": "tchess", "status": "built", "dir": "kept"},
                "old_tchess": {"game": "old", "brand": "tchess", "status": "published", "dir": "old"},
            }, "playlists": {}}
            with mock.patch.object(longform_daily, "ROOT", Path(tmp)), \
                 mock.patch.object(longform_daily.publisher, "save_ledger") as save:
                self.assertEqual(longform_daily.drop_lost_builds(led), ["gone_tchess"])
                save.assert_called_once()
            self.assertEqual(sorted(led["videos"]), ["kept_tchess", "old_tchess"])


if __name__ == "__main__":
    unittest.main()
