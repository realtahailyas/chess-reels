"""Stockfish analysis and move judgement (!!, !, ?!, ?, ??, #).

Every position of the game is analysed once and cached to
data/longform/analysis/<game id>.json, so re-rendering a video (layout tweaks,
new music) never re-runs the engine.
"""

import json
import math
import shutil

import chess
import chess.engine

from longform import lfconfig as C

VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
         chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
PIECE_NAME = {chess.PAWN: "Pawn", chess.KNIGHT: "Knight", chess.BISHOP: "Bishop",
              chess.ROOK: "Rook", chess.QUEEN: "Queen", chess.KING: "King"}
MATE_CP = 10000


def engine_path() -> str:
    if C.STOCKFISH.is_file():
        return str(C.STOCKFISH)
    found = shutil.which("stockfish")
    if not found:
        raise FileNotFoundError(f"Stockfish not found at {C.STOCKFISH} or on PATH")
    return found


def _score_dict(pov: chess.engine.PovScore) -> dict:
    w = pov.white()
    return {"cp": w.score(), "mate": w.mate()}


def as_cp(s: dict) -> int:
    """White-POV centipawns, with mate folded in as a large finite number."""
    if s is None:
        return 0
    if s.get("mate") is not None:
        m = s["mate"]
        if m == 0:
            return 0
        return (MATE_CP - abs(m) * 10) * (1 if m > 0 else -1)
    return s.get("cp") or 0


def win_prob(cp: int) -> float:
    """Lichess's expected-score curve, 0..100, for the side the cp favours."""
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def fmt_eval(s: dict) -> str:
    if s is None:
        return "0.0"
    if s.get("mate") is not None:
        m = s["mate"]
        return f"M{abs(m)}" if m != 0 else "#"
    cp = s.get("cp") or 0
    return f"{cp / 100:+.1f}"


class _Pool:
    """N single-threaded engines. Threads=1 plus a node limit makes every
    analysis reproducible — a multi-threaded search with a time cap gives a
    different verdict on each run, and a "??" on a famous move has to be one
    the engine will stand behind every time."""

    def __init__(self, n: int):
        self.engines = []
        for _ in range(n):
            e = chess.engine.SimpleEngine.popen_uci(engine_path())
            e.configure({"Threads": 1, "Hash": C.ENGINE_HASH_MB})
            self.engines.append(e)

    def map(self, boards: list, nodes) -> list:
        """`nodes` is one limit for all boards, or a list with one per board."""
        limits = nodes if isinstance(nodes, list) else [nodes] * len(boards)
        from concurrent.futures import ThreadPoolExecutor
        import queue
        free = queue.Queue()
        for e in self.engines:
            free.put(e)

        def work(job):
            b, n = job
            e = free.get()
            try:
                return _analyse_position(e, b, n)
            finally:
                free.put(e)

        with ThreadPoolExecutor(len(self.engines)) as ex:
            return list(ex.map(work, zip(boards, limits)))

    def close(self):
        for e in self.engines:
            try:
                e.quit()
            except Exception:
                pass


def _boards(game: dict) -> list:
    b = chess.Board(game["start_fen"])
    out = [b.copy()]
    for mv in game["moves"]:
        b.push(mv)
        out.append(b.copy())
    return out


def analyse(game: dict, log=print) -> list:
    """Return one record per position (len(moves) + 1), cached on disk.

    Two passes: every position at ENGINE_NODES, then the positions around any
    move judged !!, ? or ?? again at ENGINE_NODES_DEEP, so the loud verdicts
    come from the deeper search.
    """
    C.ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    cache = C.ANALYSIS_DIR / f"{game['id']}.json"
    sig = _sig()
    if cache.is_file():
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("sig") == sig and len(data["positions"]) == len(game["moves"]) + 1:
            return consistent(game, data["positions"])

    from longform import games as _g
    boards = _boards(game)
    book = _g.book_depth(game["start_fen"], game["moves"])
    # Opening theory is known ground and is played fast on screen: a light
    # search is enough there, and it is a fifth of most games.
    first = [C.ENGINE_NODES_BOOK if i <= book else C.ENGINE_NODES for i in range(len(boards))]
    pool = _Pool(C.ENGINE_PROCS)
    try:
        log(f"        engine  {len(boards)} positions × {C.ENGINE_NODES:,} nodes ({book + 1} book)")
        positions = pool.map(boards, first)
        done = set(range(book + 1))     # never deep-check theory
        for rnd in range(C.ENGINE_DEEP_ROUNDS):
            want = set()
            for i, j in enumerate(judge(game, positions, book)):
                if j["glyph"] in ("!!", "!", "?", "??"):
                    want |= {i, i + 1}
            # A big jump between neighbours means one of them was misjudged by
            # the shallow search; look at both again.
            for i in range(len(positions) - 1):
                a = win_prob(as_cp(positions[i]["score"]))
                b = win_prob(as_cp(positions[i + 1]["score"]))
                if abs(a - b) >= C.WP_SWING_RECHECK:
                    want |= {i, i + 1}
            idx = sorted(want - done)
            if not idx:
                break
            log(f"        engine  deep pass {rnd + 1}: {len(idx)} positions at {C.ENGINE_NODES_DEEP:,} nodes")
            for k, rec in zip(idx, pool.map([boards[k] for k in idx], C.ENGINE_NODES_DEEP)):
                positions[k] = rec
            done |= set(idx)
    finally:
        pool.close()
    cache.write_text(json.dumps({"sig": sig, "positions": positions}), encoding="utf-8")
    return consistent(game, positions)


def _sig() -> str:
    return f"v4:{C.ENGINE_NODES_BOOK}:{C.ENGINE_NODES}:{C.ENGINE_NODES_DEEP}:{C.ENGINE_DEEP_ROUNDS}"


def is_cached(game: dict) -> bool:
    """True if analyse() would return from disk without starting an engine."""
    cache = C.ANALYSIS_DIR / f"{game['id']}.json"
    if not cache.is_file():
        return False
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
    except ValueError:
        return False
    return data.get("sig") == _sig() and len(data["positions"]) == len(game["moves"]) + 1


def consistent(game: dict, positions: list) -> list:
    """Make the evals agree with the game's own continuation.

    Where the side to move played the engine's best move, that position is
    worth what the next one is — and the later position, being closer to where
    the tactics resolve, is the better-informed search. Walking backwards,
    each forcing stretch takes the value of its end. Without this, a sharp line
    the search only half sees makes the bar jump +7, +1, +7 on three moves in a
    row, and a viewer reads that as the players blundering back and forth.
    """
    out = [dict(p, raw=p["score"]) for p in positions]
    for i in range(len(game["moves"]) - 1, -1, -1):
        if not out[i].get("terminal") and out[i].get("best") == game["moves"][i].uci():
            out[i]["score"] = out[i + 1]["score"]
    return out


def _analyse_position(eng, board: chess.Board, nodes: int) -> dict:
    if board.is_game_over():
        if board.is_checkmate():
            # The side to move is mated; the bar goes all the way to the winner.
            winner_white = board.turn == chess.BLACK
            return {"score": {"cp": MATE_CP if winner_white else -MATE_CP, "mate": None},
                    "second": None, "best": None, "pv": [], "terminal": "mate"}
        return {"score": {"cp": 0, "mate": None}, "second": None, "best": None,
                "pv": [], "terminal": "draw"}
    infos = eng.analyse(board, chess.engine.Limit(nodes=nodes), multipv=2,
                        game=object())   # fresh search each time: no carried-over hash
    top = infos[0]
    return {
        "score": _score_dict(top["score"]),
        "second": _score_dict(infos[1]["score"]) if len(infos) > 1 else None,
        "best": top["pv"][0].uci() if top.get("pv") else None,
        "pv": [m.uci() for m in top.get("pv", [])[:6]],
    }


# ── Judgement ─────────────────────────────────────────────────────────────

def _loss_on(board: chess.Board, square: int, owner: bool) -> int:
    """What `owner` loses if the piece on `square` is taken and they recapture once."""
    p = board.piece_at(square)
    if p is None or p.piece_type == chess.KING:
        return 0
    defended = bool(board.attackers(owner, square))
    takers = []
    for s in board.attackers(not owner, square):
        t = board.piece_at(s)
        if t.piece_type == chess.KING and defended:
            continue                      # the king cannot take a defended piece
        takers.append(VALUE[t.piece_type])
    if not takers:
        return 0
    return VALUE[p.piece_type] - (min(takers) if defended else 0)


def _worst_hanging(board: chess.Board, owner: bool):
    """(material at risk, piece type) of `owner`'s most exposed piece."""
    best = (0, None)
    for sq, p in board.piece_map().items():
        if p.color == owner and p.piece_type not in (chess.PAWN, chess.KING):
            v = _loss_on(board, sq, owner)
            if v > best[0]:
                best = (v, p.piece_type)
    return best


def sacrifice(board: chess.Board, move: chess.Move):
    """(material given up, piece type) for a sacrifice, else (0, None).

    Two shapes count: the moved piece lands where it can be taken for less
    (24.Rxd4!!), and a move that leaves ANOTHER piece to be taken, like
    Fischer's 17...Be6!! walking away from his queen. Only material newly
    put at risk by this move counts, net of anything the move captured.
    """
    mover = board.turn
    if board.is_en_passant(move):
        cap_val = 1
    else:
        cap = board.piece_at(move.to_square)
        cap_val = VALUE[cap.piece_type] if cap else 0
    before, _ = _worst_hanging(board, mover)
    after = board.copy()
    after.push(move)
    risk, ptype = _worst_hanging(after, mover)
    given = risk - cap_val
    if given < 2:
        return 0, None
    if risk > before:
        return given, ptype
    # The piece was already attacked and the mover chose to leave it there.
    # Not when escaping check (no choice), and not when the move itself gives
    # check (an in-between move that usually saves the piece next turn).
    if risk == before and not board.is_check() and not after.is_check():
        return given, ptype
    return 0, None


def sacrifice_value(board: chess.Board, move: chess.Move) -> int:
    return sacrifice(board, move)[0]


def judge(game: dict, positions: list, book: int) -> list:
    """Per ply: {"glyph", "loss", "sac", "text", "eval_before", "eval_after"}."""
    board = chess.Board(game["start_fen"])
    out = []
    prev_move = None
    for i, mv in enumerate(game["moves"]):
        pos, nxt = positions[i], positions[i + 1]
        sign = 1 if board.turn == chess.WHITE else -1
        best_wp = win_prob(sign * as_cp(pos["score"]))
        # How the position looked from the board, before hindsight from the
        # rest of the game: a sacrifice that WINS is brilliant precisely
        # because the position did not yet look won.
        seen_wp = win_prob(sign * as_cp(pos.get("raw", pos["score"])))
        played_wp = win_prob(sign * as_cp(nxt["score"]))
        raw_played_wp = played_wp
        if pos.get("best") == mv.uci():
            # The engine's own choice is never an error, whatever a
            # differently-deep search of the next position happens to say.
            played_wp = max(played_wp, best_wp)
        loss = max(0.0, best_wp - played_wp)
        second_wp = win_prob(sign * as_cp(pos["second"])) if pos.get("second") else None
        sac, sac_piece = sacrifice(board, mv)
        is_recapture = (prev_move is not None and board.is_capture(mv)
                        and mv.to_square == prev_move.to_square)
        legal = board.legal_moves.count()

        after = board.copy()
        after.push(mv)
        glyph = None
        text = ""
        # An error only counts if it changed what the position is: a winning
        # side that is still winning, or a lost side still lost, did not err.
        matters = played_wp < C.WP_STILL_WINNING and best_wp > 100 - C.WP_STILL_WINNING
        if after.is_checkmate():
            glyph = "#"
            text = "Checkmate"
        elif not matters:
            pass
        elif i >= book and loss >= C.WP_BLUNDER and played_wp < C.WP_BLUNDER_LANDS_BELOW:
            glyph = "??"
        elif i >= book and loss >= C.WP_MISTAKE:
            # A big drop that still leaves the mover better is a mistake, not a
            # blunder: "??" is kept for moves that actually throw the game.
            glyph = "?"
        elif i >= book and loss >= C.WP_INACCURACY:
            glyph = "?!"
        if glyph is None and (sac and loss <= C.WP_BRILLIANT_SLACK and seen_wp <= C.WP_BRILLIANT_MAX_BEFORE
              and raw_played_wp >= 45):
            glyph = "!!"
            text = f"{PIECE_NAME[sac_piece]} sacrifice"
        elif (glyph is None and i >= book and second_wp is not None and legal > 1
              and not is_recapture and seen_wp <= C.WP_GREAT_MAX_BEFORE
              and best_wp - second_wp >= C.WP_ONLY_MOVE_GAP and loss <= C.WP_BRILLIANT_SLACK
              and raw_played_wp >= 40):
            glyph = "!"
            text = "The only good move in the position"

        out.append({
            "glyph": glyph,
            "loss": round(loss, 1),
            "sac": sac,
            "text": text,
            "eval_before": pos["score"],
            "eval_after": nxt["score"],
            "best": pos.get("best"),
        })
        prev_move = mv
        board.push(mv)
    return out
