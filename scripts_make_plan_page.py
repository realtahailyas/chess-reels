"""Render plan.json as a standalone HTML page.

Generated, never hand-written: there are ninety-eight items and transcribing
them by hand is how a calendar ends up disagreeing with the pipeline that
builds it. Re-run after `python content_plan.py --export`.

    python scripts_make_plan_page.py <out.html>
"""

import base64
import html
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FONTS = {
    "Sora": ROOT / "assets" / "brand" / "Sora-Bold.ttf",
    "InterR": ROOT.parent / "tchess-app" / "node_modules" / "@expo-google-fonts"
              / "inter" / "400Regular" / "Inter_400Regular.ttf",
    "InterB": ROOT.parent / "tchess-app" / "node_modules" / "@expo-google-fonts"
              / "inter" / "600SemiBold" / "Inter_600SemiBold.ttf",
}

# Format -> (label, what it is, which signal colour). The colour encodes the
# KIND of asset, which is the one thing a person scanning the calendar needs:
# a reel to shoot, a still set to post, or a film already built.
KINDS = {
    "promo_guess":      ("Solve challenge", "board reel", "accent"),
    "promo_mate":       ("Mate in two", "board reel", "accent"),
    "gm_games":         ("GM replay", "board reel", "accent"),
    "promo_sac":        ("Sacrifice, cut at the sacrifice", "reaction", "accent"),
    "promo_carousel":   ("Quiz carousel", "still", "board"),
    "promo_tour":       ("App tour", "evergreen", "warm"),
    "promo_bots":       ("Bot ladder", "evergreen", "warm"),
}

# Remotion compositions arrive as "motion:<Id>" and have no board at all.
MOTION_TONE = "motion"


def font_face(name: str, path: Path, weight: int) -> str:
    if not path.is_file():
        return ""
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return (f"@font-face{{font-family:'{name}';font-style:normal;"
            f"font-weight:{weight};font-display:swap;"
            f"src:url(data:font/ttf;base64,{b64}) format('truetype');}}")


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def kind_of(variant: str):
    if variant.startswith("motion:"):
        return (variant.split(":", 1)[1], "motion", MOTION_TONE)
    return KINDS[variant]


def item_html(it: dict) -> str:
    label, kind, tone = kind_of(it["variant"])
    what = ("Built once, re-posted" if it["evergreen"]
            else " · ".join(x for x in (it["theme"], it["band"]) if x))
    return f"""<li class="item" data-tone="{tone}">
  <div class="item-head">
    <span class="chip chip--{tone}">{esc(label)}</span>
    <span class="kind">{esc(kind)}</span>
  </div>
  {f'<p class="what">{esc(what)}</p>' if what else ''}
  <p class="hook">{esc(it['hook'])}</p>
  <p class="angle"><span class="lbl">Caption</span>{esc(it['angle'])}</p>
  <code class="cmd">{esc(it['cmd'])}</code>
</li>"""


def day_html(d: dict) -> str:
    items = "\n".join(item_html(i) for i in d["items"])
    return f"""<article class="day">
  <header class="day-head">
    <span class="daynum">{d['day']}</span>
    <div class="day-meta">
      <h3>{esc(d['beat'])}</h3>
      <p>{esc(d['weekday'])} · {esc(d['date'])}</p>
    </div>
  </header>
  <ul class="items">{items}</ul>
</article>"""


def build(days: list) -> str:
    total = sum(len(d["items"]) for d in days)
    def count(kind):
        return sum(1 for d in days for i in d["items"]
                   if kind_of(i["variant"])[1] == kind)

    boards, reacts = count("board reel"), count("reaction")
    motion, stills = count("motion"), count("still")
    ever = count("evergreen")

    weeks = []
    for w in range(0, len(days), 7):
        chunk = days[w:w + 7]
        weeks.append(f"""<section class="week">
  <h2 class="week-h"><span>Week {w // 7 + 1}</span>
    <span class="week-dates">{esc(chunk[0]['date'])} – {esc(chunk[-1]['date'])}</span></h2>
  <div class="days">{''.join(day_html(d) for d in chunk)}</div>
</section>""")

    faces = (font_face("Sora", FONTS["Sora"], 700)
             + font_face("InterX", FONTS["InterR"], 400)
             + font_face("InterX", FONTS["InterB"], 600))

    legend = "".join(
        f'<li><span class="dot dot--{tone}"></span><b>{esc(label)}</b>'
        f'<span>{esc(kind)}</span></li>'
        for label, kind, tone in
        sorted({(v[1].title(), v[1], v[2]) for v in KINDS.values()}
               | {("Motion graphics", "motion", MOTION_TONE)},
               key=lambda x: (x[1], x[0])))

    return f"""<title>Thirty Days of TChess</title>
<style>
{faces}
:root {{
  --ground:#F3F4EF; --surface:#FFFFFF; --sunk:#ECEEE6;
  --ink:#16161A; --muted:#6E6E74; --line:#E1E3DA;
  --accent:#7C5CFF; --board:#5C7746; --warm:#B57A10; --motion:#0F7C86;
  --radius:14px;
  --display:'Sora',ui-sans-serif,system-ui,sans-serif;
  --body:'InterX',ui-sans-serif,system-ui,-apple-system,sans-serif;
  --mono:ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,monospace;
}}
@media (prefers-color-scheme:dark) {{
  :root:not([data-theme="light"]) {{
    --ground:#0B0B0D; --surface:#151517; --sunk:#101012;
    --ink:#E9E9EA; --muted:#8B8B90; --line:#26262A;
    --accent:#9B85FF; --board:#8FB06E; --warm:#F5A524; --motion:#4FD3DE;
  }}
}}
:root[data-theme="dark"] {{
  --ground:#0B0B0D; --surface:#151517; --sunk:#101012;
  --ink:#E9E9EA; --muted:#8B8B90; --line:#26262A;
  --accent:#9B85FF; --board:#8FB06E; --warm:#F5A524; --motion:#4FD3DE;
}}
*,*::before,*::after {{ box-sizing:border-box; }}
body {{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:var(--body); font-size:15px; line-height:1.55;
  -webkit-font-smoothing:antialiased;
}}
.wrap {{ max-width:1280px; margin:0 auto; padding:48px 24px 96px; }}

.masthead {{ border-bottom:2px solid var(--ink); padding-bottom:28px; margin-bottom:36px; }}
.eyebrow {{
  font-family:var(--body); font-weight:600; font-size:12px;
  letter-spacing:.16em; text-transform:uppercase; color:var(--muted); margin:0 0 10px;
}}
h1 {{
  font-family:var(--display); font-weight:700; font-size:clamp(34px,5.5vw,58px);
  line-height:1.02; letter-spacing:-.02em; margin:0 0 14px; text-wrap:balance;
}}
.lede {{ margin:0; max-width:62ch; color:var(--muted); font-size:17px; }}
.lede b {{ color:var(--ink); font-weight:600; }}

.stats {{ display:flex; flex-wrap:wrap; gap:32px; margin:28px 0 0; padding:0; list-style:none; }}
.stats li {{ display:flex; flex-direction:column; gap:2px; }}
.stats .n {{
  font-family:var(--display); font-weight:700; font-size:30px;
  line-height:1; font-variant-numeric:tabular-nums;
}}
.stats .k {{ font-size:12px; letter-spacing:.1em; text-transform:uppercase; color:var(--muted); }}

.legend {{
  display:flex; flex-wrap:wrap; gap:8px 22px; list-style:none; margin:34px 0 0; padding:0;
  font-size:13px;
}}
.legend li {{ display:flex; align-items:center; gap:8px; }}
.legend b {{ font-weight:600; }}
.legend span:last-child {{ color:var(--muted); }}
.dot {{ width:9px; height:9px; border-radius:50%; flex:none; }}
.dot--accent {{ background:var(--accent); }}
.dot--board {{ background:var(--board); }}
.dot--warm {{ background:var(--warm); }}
.dot--motion {{ background:var(--motion); }}

.week {{ margin-top:52px; }}
.week-h {{
  display:flex; align-items:baseline; justify-content:space-between; gap:16px;
  font-family:var(--display); font-weight:700; font-size:15px;
  letter-spacing:.13em; text-transform:uppercase;
  margin:0 0 18px; padding-bottom:9px; border-bottom:1px solid var(--line);
}}
.week-dates {{
  font-family:var(--body); font-weight:400; font-size:13px;
  letter-spacing:0; text-transform:none; color:var(--muted);
  font-variant-numeric:tabular-nums;
}}
.days {{ display:grid; gap:16px; grid-template-columns:repeat(auto-fill,minmax(305px,1fr)); }}

.day {{
  background:var(--surface); border:1px solid var(--line); border-radius:var(--radius);
  padding:16px 16px 8px; display:flex; flex-direction:column;
}}
.day-head {{ display:flex; align-items:center; gap:12px; margin-bottom:12px; }}
.daynum {{
  font-family:var(--display); font-weight:700; font-size:26px; line-height:1;
  font-variant-numeric:tabular-nums; color:var(--accent); min-width:1.7em;
}}
.day-meta h3 {{ font-family:var(--display); font-weight:700; font-size:15px; margin:0; letter-spacing:-.01em; }}
.day-meta p {{ margin:1px 0 0; font-size:12px; color:var(--muted); font-variant-numeric:tabular-nums; }}

.items {{ list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:12px; }}
.item {{ border-top:1px solid var(--line); padding-top:11px; }}
.item-head {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
.chip {{
  font-size:11px; font-weight:600; letter-spacing:.05em; text-transform:uppercase;
  padding:3px 8px; border-radius:999px; border:1px solid currentColor;
}}
.chip--accent {{ color:var(--accent); }}
.chip--board {{ color:var(--board); }}
.chip--warm {{ color:var(--warm); }}
.chip--motion {{ color:var(--motion); }}
.kind {{ font-size:11px; letter-spacing:.09em; text-transform:uppercase; color:var(--muted); }}
.what {{ margin:7px 0 0; font-size:12.5px; color:var(--muted); font-variant-numeric:tabular-nums; }}
.hook {{ margin:6px 0 0; font-size:14px; font-weight:600; line-height:1.4; text-wrap:pretty; }}
.hook::before {{ content:'\\201C'; }}
.hook::after {{ content:'\\201D'; }}
.angle {{ margin:6px 0 0; font-size:12.5px; color:var(--muted); }}
.lbl {{
  font-size:10px; font-weight:600; letter-spacing:.11em; text-transform:uppercase;
  color:var(--muted); margin-right:7px;
}}
.cmd {{
  display:block; margin-top:9px; padding:7px 9px; border-radius:8px;
  background:var(--sunk); border:1px solid var(--line);
  font-family:var(--mono); font-size:11px; line-height:1.45; color:var(--muted);
  overflow-x:auto; white-space:pre;
}}

.note {{
  margin-top:56px; padding:20px 22px; border-radius:var(--radius);
  border:1px solid var(--line); background:var(--surface);
}}
.note h2 {{ font-family:var(--display); font-weight:700; font-size:17px; margin:0 0 8px; }}
.note p {{ margin:0 0 9px; max-width:70ch; color:var(--muted); }}
.note p:last-child {{ margin-bottom:0; }}
.note b {{ color:var(--ink); font-weight:600; }}
code {{ font-family:var(--mono); font-size:.9em; }}
@media (max-width:640px) {{ .wrap {{ padding:32px 16px 64px; }} }}
</style>

<div class="wrap">
  <header class="masthead">
    <p class="eyebrow">TChess · content calendar</p>
    <h1>Thirty days of promotion</h1>
    <p class="lede">One asset per slot, posted to <b>Instagram Reels, YouTube Shorts and
      Facebook Reels unchanged</b>. Carousels go to Instagram and Facebook; that day's
      reel covers YouTube. Nothing is re-cut per platform — three versions of one idea
      is three times the work and changes nothing about how it performs.</p>
    <ul class="stats">
      <li><span class="n">{len(days)}</span><span class="k">days</span></li>
      <li><span class="n">{total}</span><span class="k">pieces</span></li>
      <li><span class="n">{boards}</span><span class="k">board reels</span></li>
      <li><span class="n">{reacts}</span><span class="k">reaction reels</span></li>
      <li><span class="n">{motion}</span><span class="k">motion pieces</span></li>
      <li><span class="n">{stills}</span><span class="k">carousels</span></li>
      <li><span class="n">{ever}</span><span class="k">evergreen posts</span></li>
    </ul>
    <ul class="legend">{legend}</ul>
  </header>

  {''.join(weeks)}

  <section class="note">
    <h2>How the month avoids repeating itself</h2>
    <p>Five formats across ninety-eight slots would be dull if the format were the only
      thing that changed. It is not. The <b>motif</b> rotates through the app's own
      seventeen themes, so no two solve challenges are the same puzzle twice, and the
      <b>rating band</b> alternates between beginner, club and sharp — a month of
      2200-rated positions reads as showing off, a month of 900s reads as beginner
      content.</p>
    <p>The two evergreen films — the app tour and the bot ladder — are built <b>once</b>
      and re-posted weekly. They are the only pieces that pitch the whole app rather than
      one tactic, so they should recur without being made again.</p>
    <p>Build a day with <code>python content_plan.py --build 1</code>, or a week with
      <code>--build 1-7</code>. Every command on this page is copied from
      <code>plan.json</code>, so the calendar and the pipeline cannot drift apart.</p>
  </section>
</div>
"""


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "plan.html"
    days = json.loads((ROOT / "plan.json").read_text(encoding="utf-8"))
    out.write_text(build(days), encoding="utf-8")
    print(f"wrote {out}  ({out.stat().st_size / 1024:.0f} KB, "
          f"{len(days)} days, generated {date.today()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
