"""Caption generation via the OpenAI API.

OpenAI writes every caption and YouTube title — there is no template
library. If the API is unavailable the build still completes with a minimal
placeholder marked `needs_caption`, so one network failure cannot kill a
30-video batch; rerun `--retry-captions` later to fill those in.

Uses Structured Outputs (`response_format={"type": "json_schema", ...}`), so
the response is schema-valid JSON by construction and needs no
fence-stripping or regex repair.
"""

import json
import os
import re

import chess

import config

# gpt-4o-mini occasionally leaks a stray control character next to an emoji
# (seen: U+007F DEL). Strip everything except real whitespace before this
# text reaches a caption file or a publish API call.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(s: str) -> str:
    return _CONTROL_CHARS.sub("", s)

CAPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "hook": {
            "type": "string",
            "description": (
                "On-screen video text for the first 3 seconds, max 6 words. "
                "This is burned into the video — it is never posted as caption text."
            ),
        },
        "caption": {
            "type": "string",
            "description": (
                f"ONE caption, {config.CAPTION_WORDS_MIN}-{config.CAPTION_WORDS_MAX} words, "
                "posted identically to Facebook and Instagram. Short paragraphs. Do NOT "
                "include hashtags here — those go in the `hashtags` field."
            ),
        },
        "hashtags": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                f"Exactly {config.HASHTAG_COUNT} hashtags, each starting with #, chess-only. "
                "Mix 1-2 broad/searchable tags with 1-2 tags specific to this puzzle's "
                "actual theme — never more than "
                f"{config.HASHTAG_COUNT}."
            ),
        },
        "first_comment": {
            "type": "string",
            "description": "One short, natural comment to pin — a real question, no bait phrasing.",
        },
        "youtube_title": {
            "type": "string",
            "description": (
                f"A YouTube Shorts title, ideally {config.YOUTUBE_TITLE_TARGET_MIN_CHARS}-"
                f"{config.YOUTUBE_TITLE_TARGET_MAX_CHARS} characters, hard max "
                f"{config.YOUTUBE_TITLE_MAX_CHARS}. Curiosity-driven but names the real "
                "tactical idea. Distinct from the on-screen hook and from `caption` — "
                "written for someone scrolling Shorts. Max 1 emoji, no hashtags."
            ),
        },
        "youtube_description": {
            "type": "string",
            "description": (
                f"A YouTube Shorts description, {config.YOUTUBE_DESC_WORDS_MIN}-"
                f"{config.YOUTUBE_DESC_WORDS_MAX} words. Must NOT be `caption` reworded — "
                "same facts, different structure and wording, shorter. Do NOT include "
                "hashtags here — those go in the `hashtags` field."
            ),
        },
    },
    "required": [
        "hook", "caption", "hashtags", "first_comment",
        "youtube_title", "youtube_description",
    ],
    "additionalProperties": False,
}

PROMPT = """You are an expert chess content strategist and short-form copywriter
for a chess tactics channel and its companion app, TChess.

Puzzle details:
- Theme: {theme_label}
- Rating: {rating}
- Solution: {san_moves}
- Sacrificed piece: {piece_name}
- Result: {result}

First, understand the actual chess idea from the details above — do not
blindly repeat the supplied theme label if it doesn't match what's really
happening. If it's genuinely a sacrifice, explain what makes it work (escape
squares covered, a defender removed, the follow-up forced). If it's a fork,
name the pieces being forked. If it's a mating pattern, explain the
escape-square/control mechanism. If the exact tactical theme is unclear,
describe the position naturally instead of inventing a chess concept.
Accuracy beats hype.

Write the following fields:

CAPTION (Facebook + Instagram, identical, {words_min}-{words_max} words)
- Opens with a sharp hook sentence, not a greeting
- Explains WHY the move works as a repeatable pattern, not just this position
- Ends with a natural save/follow line — never "comment YES" style bait
- Maximum 2-3 emojis total, none stacked together
- No "watch till the end", no link to the source
- Sounds like a serious chess creator, not an AI: avoid "This insane move...",
  "You won't believe...", "only 1% can solve this", generic motivational
  lines, and repeating the same sentence in different wording
- If — and only if — it fits naturally without crowding out the chess
  content, add ONE short, compressed mention that TChess has unlimited
  puzzles, openings, bots, analysis and lessons, free and offline. Never
  force it, never include a link (links are posted separately in comments),
  never let it run past a sentence
- Do not include hashtags in this field

YOUTUBE_TITLE
- Ideally {yt_title_target_min}-{yt_title_target_max} characters, hard max
  {youtube_title_max}
- Curiosity-driven but must accurately name the tactical idea
- Distinct from both the hook and the caption
- Max 1 emoji, no hashtags

YOUTUBE_DESCRIPTION ({yt_words_min}-{yt_words_max} words)
- First sentence hooks the viewer
- Names the key move, explains the idea clearly, uses natural chess search
  keywords
- Must read like a different piece of writing from `caption` — same facts,
  shorter, restructured, not just reworded sentences
- Do not include hashtags in this field

HASHTAGS — exactly {hashtag_count}, chess-only, each starting with #. Mix
1-2 broad/searchable tags (e.g. #chess, #chesstactics, #chesspuzzle) with
1-2 tags specific to this puzzle's actual theme (e.g. #queensacrifice,
#backrankmate) — never invent a tag that doesn't match the real theme, never
a non-chess tag, never more than {hashtag_count}.

HOOK — on-screen video text for the first 3 seconds, at most 6 words. This is
burned into the video, not posted as caption text.

FIRST_COMMENT — one short, natural line inviting replies (e.g. a genuine
question about the position). No "comment YES" style bait."""


def san_solution(fen: str, solution) -> str:
    """Render a UCI solution as readable SAN, e.g. 'Bxh7+ Kxh7 Ng5+'."""
    board = chess.Board(fen)
    out = []
    for uci in solution:
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            break
        out.append(board.san(move))
        board.push(move)
    return " ".join(out)


def describe_result(fen: str, solution) -> str:
    """'mate in N' when the line ends in checkmate, else 'decisive attack'."""
    board = chess.Board(fen)
    for uci in solution:
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            return "decisive attack"
        board.push(move)
    if board.is_checkmate():
        # Solver moves are every other ply starting at index 0.
        return f"mate in {(len(solution) + 1) // 2}"
    return "decisive attack"


def _client():
    """Return an OpenAI client, or None when unavailable.

    A missing key is not an error here — the caller degrades to a placeholder.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        return None
    try:
        import openai
        return openai.OpenAI()
    except ImportError:
        return None


def generate(puzzle: dict, use_api: bool = True, log=print) -> dict:
    """Return a caption dict for a puzzle. Never raises.

    Uses exactly config.OPENAI_MODEL — no fallback to a different model if
    it's unreachable (user's explicit choice, 2026-08-26). If the call fails
    for any reason, this degrades to the needs_caption placeholder, same as
    always; it does not retry with another model.
    """
    san = san_solution(puzzle["fen"], puzzle["solution"])
    result = describe_result(puzzle["fen"], puzzle["solution"])

    if use_api:
        client = _client()
        if client is None:
            log("        caption OPENAI_API_KEY not set")
        else:
            try:
                return _call_openai(client, puzzle, san, result)
            except Exception as exc:
                log(f"        caption api failed .. {type(exc).__name__}: {exc}")

    return _placeholder(puzzle, san, result)


def _call_openai(client, puzzle, san, result) -> dict:
    prompt = PROMPT.format(
        theme_label=puzzle["theme_label"],
        rating=puzzle["rating"],
        san_moves=san,
        piece_name=puzzle.get("sacrificed_piece", "piece"),
        result=result,
        words_min=config.CAPTION_WORDS_MIN,
        words_max=config.CAPTION_WORDS_MAX,
        yt_words_min=config.YOUTUBE_DESC_WORDS_MIN,
        yt_words_max=config.YOUTUBE_DESC_WORDS_MAX,
        hashtag_count=config.HASHTAG_COUNT,
        yt_title_target_min=config.YOUTUBE_TITLE_TARGET_MIN_CHARS,
        yt_title_target_max=config.YOUTUBE_TITLE_TARGET_MAX_CHARS,
        youtube_title_max=config.YOUTUBE_TITLE_MAX_CHARS,
    )

    response = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        max_completion_tokens=config.CAPTION_MAX_TOKENS,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "reel_caption", "schema": CAPTION_SCHEMA, "strict": True},
        },
        messages=[{"role": "user", "content": prompt}],
    )

    choice = response.choices[0]
    if choice.finish_reason == "content_filter":
        raise RuntimeError("model declined the caption request (content filter)")

    data = json.loads(choice.message.content)     # schema-valid by construction

    for field in ("hook", "caption", "first_comment", "youtube_title", "youtube_description"):
        if field in data:
            data[field] = _clean(data[field])

    # Structured outputs' strict mode doesn't support minItems/maxItems, so
    # the model's word is not enough — hard-cap here regardless of what the
    # prompt asked for (this is the fix for the 10-hashtag drift). gpt-4o-mini
    # also occasionally leaks a leading space into a tag ("` #chesstactics`"),
    # which breaks concatenation into the posted caption text.
    hashtags = [_clean(tag).strip() for tag in (data.get("hashtags") or [])]
    data["hashtags"] = [tag for tag in hashtags if tag][:config.HASHTAG_COUNT]

    data["source"] = "openai"
    data["model"] = response.model
    data["needs_caption"] = False
    return data


def _placeholder(puzzle, san, result) -> dict:
    """Minimal stand-in so a failed API call cannot block the encode."""
    label = puzzle["theme_label"]
    return {
        "hook": label,
        "caption": (
            f"{label} — rated {puzzle['rating']}. Solution: {san} ({result}).\n\n"
            "Caption generation was unavailable for this post. "
            "Re-run with the OpenAI API enabled before publishing."
        ),
        "hashtags": ["#chess", "#chesstactics", "#chesspuzzle"],
        "first_comment": "What would you have played?",
        "youtube_title": f"{label} — Rated {puzzle['rating']} Chess Puzzle",
        "youtube_description": (
            f"{label} at {puzzle['rating']} rated. Solution: {san} ({result}). "
            "Caption generation was unavailable for this post."
        ),
        "source": "placeholder",
        "needs_caption": True,
    }


CAPTION_TEMPLATE = """\
═══════════════════════════════════════
POST: {puzzle_id} — {theme_label}
Format: {width}x{height} | {duration}s | Rating {rating}
═══════════════════════════════════════

HOOK (on-screen, first 3s):
{hook}

YOUTUBE TITLE:
{youtube_title}

─────────── CAPTION (FB + IG) ───────────
{caption}

─────────── YOUTUBE DESCRIPTION ───────────
{youtube_description}

─────────── HASHTAGS ───────────
{hashtags}

─────────── POSTING META ───────────
Best time     : 7–9 PM local
First comment : {first_comment}
Source        : {game_url}
Solution      : {san_moves}
"""


def write_caption_file(path, puzzle: dict, caption: dict, duration: float):
    """Write the human-facing caption file."""
    text = CAPTION_TEMPLATE.format(
        puzzle_id=puzzle["id"],
        theme_label=puzzle["theme_label"],
        width=config.CANVAS_W,
        height=config.CANVAS_H,
        duration=round(duration, 1),
        rating=puzzle["rating"],
        hook=caption["hook"],
        youtube_title=caption.get("youtube_title", caption["hook"]),
        caption=caption["caption"],
        youtube_description=caption.get("youtube_description", caption["caption"]),
        hashtags=" ".join(caption["hashtags"]),
        first_comment=caption["first_comment"],
        game_url=puzzle.get("game_url", ""),
        san_moves=san_solution(puzzle["fen"], puzzle["solution"]),
    )
    path.write_text(text, encoding="utf-8")
    return text
