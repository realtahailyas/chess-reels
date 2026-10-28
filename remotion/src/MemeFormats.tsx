/**
 * Meme-shaped formats, built from OUR OWN visual language.
 *
 * 🔴 No borrowed templates. The Drake panels, the expanding brain and the rest
 * are somebody's copyright, and a strike on a business account costs more than
 * the post ever earns. The SHAPE of those jokes — reject/approve, setup/punch,
 * a ranked list — is not owned by anyone, and the shape is the part that
 * travels. Everything below is that shape drawn in the app's own palette.
 *
 * (The real meme clips in ../assets/reaction/ are a separate and genuine
 * exposure. They are other people's footage. That is the owner's call to make,
 * but it should be a made call rather than an assumed one.)
 */
import React from 'react';
import {spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {BODY, C, EndCard, FONT, Frame} from './Brand';
import {Body, Stack, Title} from './Kit';

const ease = {damping: 200} as const;

/* ── Reject / approve ─────────────────────────────────────────────────────
   The two-panel joke without the two-panel image: one option struck out in
   red, the other lit in green. */
export const RejectApprove: React.FC<{
  reject?: string;
  approve?: string;
  end?: number;
}> = ({
  reject = 'Six hours of opening theory',
  approve = 'One puzzle on the bus',
  end = 10,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const a = spring({frame: frame - fps * 0.4, fps, config: ease});
  const b = spring({frame: frame - fps * 2.0, fps, config: ease});

  const panel = (text: string, s: number, ok: boolean) => (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 30,
        width: '100%',
        padding: '46px 36px',
        borderRadius: 30,
        background: C.surface,
        border: `3px solid ${ok ? C.playGreen : '#F05252'}`,
        opacity: s,
        transform: `translateX(${(1 - s) * (ok ? 70 : -70)}px)`,
      }}
    >
      <div
        style={{
          width: 76,
          height: 76,
          borderRadius: 38,
          flex: 'none',
          background: ok ? C.playGreen : '#F05252',
          color: '#fff',
          fontFamily: FONT,
          fontSize: 44,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        {ok ? '✓' : '✕'}
      </div>
      <span
        style={{
          fontFamily: BODY,
          fontWeight: 600,
          fontSize: 48,
          textAlign: 'left',
          color: ok ? C.textHi : C.muted,
          textDecoration: ok ? 'none' : 'line-through',
        }}
      >
        {text}
      </span>
    </div>
  );

  return (
    <Frame glow={C.violet}>
      <Stack gap={34}>
        {panel(reject, a, false)}
        {panel(approve, b, true)}
      </Stack>
      <EndCard startAt={end * fps} />
    </Frame>
  );
};

/* ── POV ──────────────────────────────────────────────────────────────────
   One line, held. The whole format is a caption, which is why it costs
   nothing and travels further than most things that cost a lot. */
export const Pov: React.FC<{line?: string; punch?: string; end?: number}> = ({
  line = 'POV: you stopped watching chess content',
  punch = 'and started solving instead',
  end = 8,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const a = spring({frame, fps, config: ease});
  const b = spring({frame: frame - fps * 1.6, fps, config: ease});
  return (
    <Frame glow={C.boardDark}>
      <Stack gap={40}>
        <div style={{opacity: a, transform: `scale(${0.94 + a * 0.06})`}}>
          <Title size={100}>{line}</Title>
        </div>
        <div style={{opacity: b}}>
          <Title size={72} color={C.violet}>
            {punch}
          </Title>
        </div>
      </Stack>
      <EndCard startAt={end * fps} />
    </Frame>
  );
};

/* ── Tier list ────────────────────────────────────────────────────────────
   People argue with a tier list in the comments, every single time, which is
   the entire reason it is in the library. */
export const TierList: React.FC<{
  title?: string;
  tiers?: {tier: string; colour: string; items: string[]}[];
  end?: number;
}> = ({
  title = 'Tactics, ranked by how often they win the game',
  tiers = [
    {tier: 'S', colour: '#F05252', items: ['Back rank mate', 'Knight fork']},
    {tier: 'A', colour: '#F5A524', items: ['Pin', 'Discovered attack']},
    {tier: 'B', colour: '#6E8A54', items: ['Skewer', 'Deflection']},
    {tier: 'C', colour: '#8B8B90', items: ['Smothered mate']},
  ],
  end = 14,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return (
    <Frame glow={C.violet}>
      <Stack gap={22} top={-30}>
        <Title size={58}>{title}</Title>
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 16,
            width: '100%',
            marginTop: 16,
          }}
        >
          {tiers.map((t, i) => {
            const s = spring({frame: frame - fps * (0.7 + i * 1.9), fps, config: ease});
            return (
              <div
                key={t.tier}
                style={{
                  display: 'flex',
                  gap: 16,
                  opacity: s,
                  transform: `translateX(${(1 - s) * -60}px)`,
                }}
              >
                <div
                  style={{
                    width: 118,
                    flex: 'none',
                    borderRadius: 20,
                    background: t.colour,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontFamily: FONT,
                    fontSize: 66,
                    color: '#111',
                  }}
                >
                  {t.tier}
                </div>
                <div
                  style={{
                    flex: 1,
                    borderRadius: 20,
                    background: C.surface,
                    border: `1px solid ${C.hairline}`,
                    padding: '22px 26px',
                    display: 'flex',
                    alignItems: 'center',
                    fontFamily: BODY,
                    fontWeight: 600,
                    fontSize: 38,
                    color: C.textHi,
                  }}
                >
                  {t.items.join('   ·   ')}
                </div>
              </div>
            );
          })}
        </div>
      </Stack>
      <EndCard startAt={end * fps} />
    </Frame>
  );
};

/* ── Two-beat text meme ───────────────────────────────────────────────────
   The oldest shape there is, and it still works because the PAUSE between the
   lines does the joke, not the words. */
export const TwoBeat: React.FC<{
  setup?: string;
  beat?: string;
  punch?: string;
  end?: number;
}> = ({
  setup = 'Nobody:',
  beat = 'Me, at two in the morning:',
  punch = '“one more puzzle”',
  end = 9,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const at = (s: number) => spring({frame: frame - fps * s, fps, config: ease});
  const p = at(3.0);
  return (
    <Frame glow={C.violet}>
      <Stack gap={38}>
        <div style={{opacity: at(0.2)}}>
          <Title size={78} color={C.muted}>
            {setup}
          </Title>
        </div>
        <div style={{opacity: at(1.6)}}>
          <Title size={78} color={C.muted}>
            {beat}
          </Title>
        </div>
        <div style={{opacity: p, transform: `scale(${0.9 + p * 0.1})`}}>
          <Title size={104}>{punch}</Title>
        </div>
      </Stack>
      <EndCard startAt={end * fps} />
    </Frame>
  );
};

/* ── Bait card ────────────────────────────────────────────────────────────
   A claim with a number on it and a dare under it. Deliberately the ONLY
   format that talks like this: a feed where everything is bait stops being
   believed, and then none of it works. */
export const BaitCard: React.FC<{claim?: string; dare?: string; end?: number}> = ({
  claim = 'Nine out of ten players give the check here.',
  dare = 'It loses. Can you see why?',
  end = 9,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const a = spring({frame, fps, config: ease});
  const b = spring({frame: frame - fps * 1.5, fps, config: ease});
  const pulse = 1 + Math.sin(frame / 7) * 0.015;
  return (
    <Frame glow="#F05252">
      <Stack gap={44}>
        <div style={{opacity: a, transform: `scale(${(0.92 + a * 0.08) * pulse})`}}>
          <Title size={92}>{claim}</Title>
        </div>
        <div style={{width: 130, height: 9, borderRadius: 5, background: '#F05252', opacity: a}} />
        <div style={{opacity: b}}>
          <Body size={54} color={C.textHi}>
            {dare}
          </Body>
        </div>
      </Stack>
      <EndCard startAt={end * fps} />
    </Frame>
  );
};
