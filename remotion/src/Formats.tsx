/**
 * Ten motion-graphics promo formats.
 *
 * WHY THESE LIVE IN REMOTION AND THE PUZZLE REELS DO NOT: none of them needs a
 * chessboard. The PIL pipeline owns anything with a board — it has the Cburnett
 * renderer, the animation, the TTS tiers, the mixer and the ledger, and porting
 * that here would be a second implementation of all of it. What Remotion is
 * genuinely better at is type in motion, springs and layout, which is exactly
 * what every format below is made of.
 *
 * Each one carries the same Frame (ground, banner, handle) and closes on the
 * same EndCard, so ten different ideas still read as one account.
 */
import React from 'react';
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {B, BODY, C, EndCard, FONT, Frame, Lockup} from './Brand';
import {Body, Stack, Title} from './Kit';

const ease = {damping: 200} as const;

/* ── 1. Kinetic hook ──────────────────────────────────────────────────────
   Words land one at a time. The format exists because the first second is the
   only one you are guaranteed, and a sentence that ASSEMBLES holds a thumb
   where the same sentence sitting still does not. */
export const KineticHook: React.FC<{words?: string[]; payoff?: string; end?: number}> = ({
  words = ['Every', 'chess', 'app', 'wants', 'your', 'money.'],
  payoff = 'This one does not.',
  end = 9,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const step = 7;
  return (
    <Frame glow={C.violet}>
      <Stack gap={44}>
        <div style={{display: 'flex', flexWrap: 'wrap', gap: '0 24px', justifyContent: 'center'}}>
          {words.map((w, i) => {
            const s = spring({frame: frame - i * step, fps, config: ease});
            return (
              <span
                key={i}
                style={{
                  fontFamily: FONT,
                  fontWeight: 700,
                  fontSize: 104,
                  lineHeight: 1.08,
                  color: C.textHi,
                  opacity: s,
                  transform: `translateY(${(1 - s) * 40}px)`,
                  display: 'inline-block',
                }}
              >
                {w}
              </span>
            );
          })}
        </div>
        <div
          style={{
            opacity: spring({frame: frame - words.length * step - 8, fps, config: ease}),
          }}
        >
          <Title size={92} color={C.violet}>
            {payoff}
          </Title>
        </div>
      </Stack>
      <EndCard startAt={end * fps} />
    </Frame>
  );
};

/* ── 2. Top-five countdown ────────────────────────────────────────────────
   Counts DOWN to one, because a list that ends on its strongest item is the
   only kind anyone watches to the end. */
export const TopFive: React.FC<{title?: string; items?: string[]; end?: number}> = ({
  title = 'Five tactics every club player should know',
  items = ['Back rank mate', 'Knight fork', 'Pin to the king', 'Deflection', 'Smothered mate'],
  end = 15,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const hold = 2.1;
  return (
    <Frame glow={C.boardDark}>
      <Stack gap={28} top={-40}>
        <Title size={62}>{title}</Title>
        <div style={{display: 'flex', flexDirection: 'column', gap: 22, width: '100%', marginTop: 20}}>
          {items.map((it, i) => {
            const s = spring({frame: frame - fps * (0.8 + i * hold), fps, config: ease});
            return (
              <div
                key={i}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 28,
                  padding: '22px 30px',
                  borderRadius: 22,
                  background: C.surface,
                  border: `1px solid ${C.hairline}`,
                  opacity: s,
                  transform: `translateX(${(1 - s) * -70}px)`,
                }}
              >
                <span style={{fontFamily: FONT, fontSize: 62, color: C.violet, minWidth: 74}}>
                  {items.length - i}
                </span>
                <span style={{fontFamily: BODY, fontWeight: 600, fontSize: 50, color: C.textHi}}>
                  {it}
                </span>
              </div>
            );
          })}
        </div>
      </Stack>
      <EndCard startAt={end * fps} />
    </Frame>
  );
};

/* ── 3. Myth vs fact ──────────────────────────────────────────────────────
   The myth is shown, then STRUCK THROUGH rather than cut away from. Watching
   a claim get crossed out is the beat; replacing it silently is just two
   slides. */
export const MythFact: React.FC<{myth?: string; fact?: string; end?: number}> = ({
  myth = 'You need a subscription to get good.',
  fact = 'Everything here is free, and stays free.',
  end = 10,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const strike = interpolate(frame, [fps * 2.2, fps * 3.0], [0, 100], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const f = spring({frame: frame - fps * 3.2, fps, config: ease});
  return (
    <Frame glow={C.violet}>
      <Stack gap={64}>
        <div style={{opacity: spring({frame: frame - 6, fps, config: ease})}}>
          <div style={{fontFamily: BODY, fontWeight: 700, fontSize: 34, letterSpacing: '0.16em', color: C.muted}}>
            MYTH
          </div>
          <div style={{position: 'relative', display: 'inline-block', marginTop: 18}}>
            <Title size={76}>{myth}</Title>
            <div
              style={{
                position: 'absolute',
                top: '50%',
                left: 0,
                height: 8,
                width: `${strike}%`,
                background: '#F05252',
                borderRadius: 4,
              }}
            />
          </div>
        </div>
        <div style={{opacity: f, transform: `translateY(${(1 - f) * 40}px)`}}>
          <div style={{fontFamily: BODY, fontWeight: 700, fontSize: 34, letterSpacing: '0.16em', color: C.playGreen}}>
            ACTUALLY
          </div>
          <div style={{marginTop: 18}}>
            <Title size={80} color={C.textHi}>
              {fact}
            </Title>
          </div>
        </div>
      </Stack>
      <EndCard startAt={end * fps} />
    </Frame>
  );
};

/* ── 4. Stat rise ─────────────────────────────────────────────────────────
   A number counting up plus the line that earned it. The count is the hook;
   the line is the proof, and without it the number is just a claim. */
export const StatRise: React.FC<{
  label?: string; from?: number; to?: number; caption?: string; end?: number;
}> = ({label = 'Puzzle rating', from = 800, to = 1183, caption = 'Thirty days of one puzzle a day', end = 10}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = interpolate(frame, [fps * 0.6, fps * 3.4], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const value = Math.round(from + (to - from) * p);
  const pts = Array.from({length: 31}, (_, i) => {
    const x = (i / 30) * 820;
    const noise = Math.sin(i * 1.7) * 26 + Math.sin(i * 0.6) * 18;
    const y = 300 - (i / 30) * 250 + noise;
    return `${x},${Math.max(10, Math.min(320, y))}`;
  });
  const shown = Math.max(2, Math.round(pts.length * p));

  return (
    <Frame glow={C.playGreen}>
      <Stack gap={26}>
        <Body size={38}>{label}</Body>
        <div style={{fontFamily: FONT, fontWeight: 700, fontSize: 190, lineHeight: 1, color: C.textHi, fontVariantNumeric: 'tabular-nums'}}>
          {value}
        </div>
        <svg width={820} height={330} style={{overflow: 'visible'}}>
          <polyline
            points={pts.slice(0, shown).join(' ')}
            fill="none"
            stroke={C.playGreen}
            strokeWidth={9}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <div style={{opacity: spring({frame: frame - fps * 3.6, fps, config: ease})}}>
          <Body size={44} color={C.textHi}>{caption}</Body>
        </div>
      </Stack>
      <EndCard startAt={end * fps} />
    </Frame>
  );
};

/* ── 5. This or that ──────────────────────────────────────────────────────
   Two options and a clock. The clock is not decoration: a choice with a
   deadline is the thing people answer in the comments. */
export const ThisOrThat: React.FC<{
  question?: string; a?: string; b?: string; end?: number;
}> = ({question = 'Which do you actually need?', a = 'A thousand videos', b = 'One puzzle a day', end = 10}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const ring = interpolate(frame, [fps * 1.2, fps * 5.2], [1, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  const card = (text: string, i: number, colour: string) => {
    const s = spring({frame: frame - fps * (0.5 + i * 0.35), fps, config: ease});
    return (
      <div
        style={{
          flex: 1,
          padding: '52px 30px',
          borderRadius: 28,
          background: C.surface,
          border: `3px solid ${colour}`,
          opacity: s,
          transform: `scale(${0.9 + s * 0.1})`,
          fontFamily: BODY,
          fontWeight: 700,
          fontSize: 52,
          color: C.textHi,
        }}
      >
        {text}
      </div>
    );
  };
  return (
    <Frame glow={C.violet}>
      <Stack gap={46}>
        <Title size={72}>{question}</Title>
        <div style={{display: 'flex', gap: 26, width: '100%', alignItems: 'stretch'}}>
          {card(a, 0, C.hairline)}
          {card(b, 1, C.violet)}
        </div>
        <svg width={150} height={150}>
          <circle cx={75} cy={75} r={62} stroke={C.hairline} strokeWidth={10} fill="none" />
          <circle
            cx={75} cy={75} r={62} stroke={C.violet} strokeWidth={10} fill="none"
            strokeDasharray={2 * Math.PI * 62}
            strokeDashoffset={2 * Math.PI * 62 * (1 - ring)}
            strokeLinecap="round"
            transform="rotate(-90 75 75)"
          />
        </svg>
      </Stack>
      <EndCard startAt={end * fps} />
    </Frame>
  );
};

/* ── 6. Offline flex ──────────────────────────────────────────────────────
   The signal dies and nothing else does. This is the app's single most
   unusual claim, and it is a claim that has to be SHOWN — said out loud it
   sounds like every other marketing line. */
export const OfflineFlex: React.FC<{claim?: string; end?: number}> = ({
  claim = 'Sixty thousand puzzles. No connection needed.',
  end = 9,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const bars = [0, 1, 2, 3];
  const die = interpolate(frame, [fps * 0.8, fps * 2.4], [4, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  const ok = spring({frame: frame - fps * 2.8, fps, config: ease});
  return (
    <Frame glow={C.boardDark}>
      <Stack gap={54}>
        <div style={{display: 'flex', alignItems: 'flex-end', gap: 16, height: 150}}>
          {bars.map((i) => (
            <div
              key={i}
              style={{
                width: 40,
                height: 40 + i * 34,
                borderRadius: 8,
                background: i < die ? C.textHi : C.hairline,
              }}
            />
          ))}
        </div>
        <Body size={40}>Airplane mode</Body>
        <div style={{opacity: ok, transform: `scale(${0.92 + ok * 0.08})`}}>
          <Title size={86}>{claim}</Title>
        </div>
        <div style={{opacity: ok}}>
          <Lockup height={110} />
        </div>
      </Stack>
      <EndCard startAt={end * fps} />
    </Frame>
  );
};

/* ── 7. Feature spotlight ─────────────────────────────────────────────────
   One feature, one sentence. The restraint IS the format — a reel that lists
   six things is a reel nobody can repeat back. */
export const FeatureSpot: React.FC<{
  kicker?: string; name?: string; line?: string; end?: number;
}> = ({kicker = 'Feature', name = 'Game Review', line = 'Every move graded, and the one that cost you the game named.', end = 9}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame, fps, config: ease});
  const l = spring({frame: frame - fps * 0.6, fps, config: ease});
  return (
    <Frame glow={C.violet}>
      <Stack gap={34}>
        <div style={{fontFamily: BODY, fontWeight: 700, fontSize: 34, letterSpacing: '0.18em', color: C.violet, opacity: s}}>
          {kicker.toUpperCase()}
        </div>
        <div style={{opacity: s, transform: `translateY(${(1 - s) * 46}px)`}}>
          <Title size={122}>{name}</Title>
        </div>
        <div style={{width: 130, height: 9, borderRadius: 5, background: C.violet, opacity: s}} />
        <div style={{opacity: l, transform: `translateY(${(1 - l) * 26}px)`}}>
          <Body size={52} color={C.textHi}>{line}</Body>
        </div>
      </Stack>
      <EndCard startAt={end * fps} />
    </Frame>
  );
};

/* ── 8. Chat story ────────────────────────────────────────────────────────
   An objection in someone else's voice, answered. People argue with an ad and
   agree with a conversation. */
export const ChatStory: React.FC<{lines?: {from: 'them' | 'us'; text: string}[]; end?: number}> = ({
  lines = [
    {from: 'them', text: 'every chess app is a paywall now'},
    {from: 'us', text: 'try TChess'},
    {from: 'them', text: 'how much'},
    {from: 'us', text: 'nothing. and it works on the metro'},
    {from: 'them', text: 'ok that is actually what i wanted'},
  ],
  end = 13,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return (
    <Frame glow={C.violet}>
      <AbsoluteFill style={{padding: '300px 80px 260px', justifyContent: 'center'}}>
        <div style={{display: 'flex', flexDirection: 'column', gap: 24}}>
          {lines.map((l, i) => {
            const s = spring({frame: frame - fps * (0.7 + i * 1.5), fps, config: ease});
            const us = l.from === 'us';
            return (
              <div
                key={i}
                style={{
                  alignSelf: us ? 'flex-end' : 'flex-start',
                  maxWidth: '78%',
                  padding: '26px 34px',
                  borderRadius: 34,
                  borderBottomRightRadius: us ? 8 : 34,
                  borderBottomLeftRadius: us ? 34 : 8,
                  background: us ? C.violet : C.surface,
                  border: us ? 'none' : `1px solid ${C.hairline}`,
                  color: us ? '#fff' : C.textHi,
                  fontFamily: BODY,
                  fontSize: 46,
                  lineHeight: 1.3,
                  opacity: s,
                  transform: `translateY(${(1 - s) * 26}px) scale(${0.94 + s * 0.06})`,
                }}
              >
                {l.text}
              </div>
            );
          })}
        </div>
      </AbsoluteFill>
      <EndCard startAt={end * fps} />
    </Frame>
  );
};

/* ── 9. Streak calendar ───────────────────────────────────────────────────
   A month filling in, one square at a time. The product's real promise is not
   a feature, it is a habit, and a habit is something you can only draw. */
export const StreakCalendar: React.FC<{title?: string; note?: string; end?: number}> = ({
  title = 'Thirty days. One puzzle each.',
  note = 'That is the whole method.',
  end = 10,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const filled = interpolate(frame, [fps * 0.7, fps * 4.2], [0, 30], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  return (
    <Frame glow={C.playGreen}>
      <Stack gap={50}>
        <Title size={78}>{title}</Title>
        <div style={{display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 20, width: '100%'}}>
          {Array.from({length: 30}, (_, i) => {
            const on = i < filled;
            const pop = spring({frame: frame - (fps * 0.7 + i * 3.5), fps, config: ease});
            return (
              <div
                key={i}
                style={{
                  aspectRatio: '1',
                  borderRadius: 18,
                  background: on ? C.playGreen : C.surface,
                  border: `1px solid ${on ? C.playGreen : C.hairline}`,
                  transform: `scale(${on ? 0.9 + pop * 0.1 : 0.9})`,
                }}
              />
            );
          })}
        </div>
        <div style={{opacity: spring({frame: frame - fps * 4.4, fps, config: ease})}}>
          <Body size={48} color={C.textHi}>{note}</Body>
        </div>
      </Stack>
      <EndCard startAt={end * fps} />
    </Frame>
  );
};

/* ── 10. Quote card ───────────────────────────────────────────────────────
   Borrowed authority, cheaply. It is the one format that is not about the app
   at all, which is exactly why a feed needs it — an account that only ever
   sells itself gets muted. */
export const QuoteCard: React.FC<{quote?: string; who?: string; end?: number}> = ({
  quote = 'Tactics flow from a superior position.',
  who = 'Bobby Fischer',
  end = 8,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame, fps, config: ease});
  const w = spring({frame: frame - fps * 0.9, fps, config: ease});
  return (
    <Frame glow={C.boardDark}>
      <Stack gap={44}>
        <div style={{fontFamily: FONT, fontSize: 180, lineHeight: 0.6, color: C.violet, opacity: s}}>
          &ldquo;
        </div>
        <div style={{opacity: s, transform: `translateY(${(1 - s) * 30}px)`}}>
          <Title size={88}>{quote}</Title>
        </div>
        <div style={{opacity: w, display: 'flex', alignItems: 'center', gap: 18}}>
          <div style={{width: 60, height: 3, background: C.muted}} />
          <Body size={44}>{who}</Body>
        </div>
      </Stack>
      <EndCard startAt={end * fps} />
    </Frame>
  );
};
