/**
 * One data-driven composition for the personal-brand videos.
 *
 * Fifteen bespoke components made sense for the TChess library, where each
 * format IS a different idea. These are different: every one is the same
 * shape — a few beats of a claim, sometimes over a real screenshot, with a
 * voice reading it. So it is one component taking scenes as props, and the
 * scripts live in Python next to the plan they came from.
 *
 * SCENE DURATIONS ARE COMPUTED FROM THE VOICEOVER, in Python, before this ever
 * runs. A scene that outlasts its line leaves dead air; a scene that ends early
 * cuts the sentence in half. Neither is fixable here, because this side cannot
 * measure audio.
 */
import React from 'react';
import brand from './brand.json';
import {
  AbsoluteFill,
  Audio,
  Img,
  interpolate,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

export type Scene = {
  kind: 'text' | 'image' | 'stat';
  title?: string;
  sub?: string;
  /** stat only — drawn huge, the whole point of the frame */
  value?: string;
  /** image only — a file in remotion/public/ */
  src?: string;
  /** seconds; computed from the scene's own voiceover */
  seconds: number;
  /** voiceover wav in remotion/public/vo/ */
  vo?: string;
  tone?: 'ink' | 'accent' | 'ok' | 'bad';
};

export type PostProps = {
  scenes: Scene[];
  handle?: string;
  site?: string;
};

const C = {
  bg: '#0A0A0B',
  ink: '#E9E9EA',
  mut: '#8A8A90',
  accent: '#E8A33D',
  ok: '#2FCB6A',
  bad: '#F05252',
  line: '#2A2A2E',
};

const DISP = 'PostDisplay';
// Body copy stays on the platform UI stack — it is set small and a
// second inlined face would add ~450KB per video for very little.
const BODY = 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif';
const ease = {damping: 200} as const;

const toneOf = (t?: string) =>
  t === 'accent' ? C.accent : t === 'ok' ? C.ok : t === 'bad' ? C.bad : C.ink;

/**
 * The display face, inlined.
 *
 * 🔴 Remotion renders in headless Chrome with no network and no system font
 * book to fall back to usefully — a missing @font-face does not error, it
 * silently renders the whole video in Times. That is not a typo-level bug:
 * every frame ships wrong and nothing reports it. The data URI already lives
 * in brand.json, so it is reused here rather than declared twice.
 */
export const PostFonts: React.FC = () => (
  <style>{`@font-face{font-family:'${DISP}';font-weight:700;font-style:normal;`
    + `src:url(${brand.asset.font}) format('truetype');}`}</style>
);

const Chrome: React.FC<{handle: string; site: string}> = ({handle, site}) => (
  <>
    <div style={{position: 'absolute', top: 0, left: 0, right: 0, height: 8, background: C.accent}} />
    <div
      style={{
        position: 'absolute',
        bottom: 54,
        left: 70,
        right: 70,
        display: 'flex',
        justifyContent: 'space-between',
        fontFamily: BODY,
        fontWeight: 600,
        fontSize: 32,
        color: C.mut,
      }}
    >
      <span>{handle}</span>
      <span>{site}</span>
    </div>
  </>
);

const SceneBody: React.FC<{scene: Scene; local: number; fps: number}> = ({
  scene,
  local,
  fps,
}) => {
  const s = spring({frame: local, fps, config: ease});
  const rise = (1 - s) * 34;
  // The canvas is 9:16 for the chess reels and 4:5 for the LinkedIn posts.
  // Width is 1080 either way, so the type sizes carry over — but a padding
  // tuned for 1920px of height eats a third of a 1350px frame, and the
  // screenshot ends up smaller than the caption under it.
  const {height} = useVideoConfig();
  const vh = height / 1920;

  if (scene.kind === 'image' && scene.src) {
    // The screenshot is the argument. It gets the room; the words sit under it
    // as a caption rather than over it, because text on a screenshot covers
    // the evidence it is pointing at.
    return (
      <AbsoluteFill
        style={{
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: `${Math.round(150 * vh)}px 60px ${Math.round(260 * vh)}px`,
        }}
      >
        <div
          style={{
            opacity: s,
            transform: `scale(${0.96 + s * 0.04})`,
            width: '100%',
            flex: 1,
            minHeight: 0,
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
          }}
        >
          <Img
            src={staticFile(scene.src)}
            style={{
              // CONTAIN, not width:100%. A phone capture is 1080x2340 — three
              // times taller than it is wide — so sizing it by width runs it
              // a full canvas past the bottom of the frame and the caption
              // renders on top of nothing. Constraining both axes lets a wide
              // browser shot fill the width and a tall phone shot fill the
              // height, with one rule.
              maxWidth: '100%',
              maxHeight: '100%',
              objectFit: 'contain',
              borderRadius: 18,
              border: `1px solid ${C.line}`,
              display: 'block',
            }}
          />
        </div>
        {scene.title ? (
          <div
            style={{
              marginTop: 44,
              opacity: interpolate(local, [fps * 0.3, fps * 0.7], [0, 1], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              }),
              fontFamily: DISP,
              fontSize: 62,
              lineHeight: 1.15,
              color: toneOf(scene.tone),
              textAlign: 'center',
              textWrap: 'balance',
            }}
          >
            {scene.title}
          </div>
        ) : null}
      </AbsoluteFill>
    );
  }

  if (scene.kind === 'stat') {
    return (
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', padding: '0 80px'}}>
        <div
          style={{
            fontFamily: DISP,
            fontSize: 200,
            lineHeight: 1,
            color: toneOf(scene.tone ?? 'accent'),
            opacity: s,
            transform: `scale(${0.9 + s * 0.1})`,
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {scene.value}
        </div>
        {scene.title ? (
          <div style={{marginTop: 36, fontFamily: DISP, fontSize: 68, color: C.ink, textAlign: 'center', opacity: s}}>
            {scene.title}
          </div>
        ) : null}
        {scene.sub ? (
          <div style={{marginTop: 22, fontFamily: BODY, fontSize: 44, color: C.mut, textAlign: 'center', opacity: s}}>
            {scene.sub}
          </div>
        ) : null}
      </AbsoluteFill>
    );
  }

  return (
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', padding: '0 80px', textAlign: 'center'}}>
      <div
        style={{
          fontFamily: DISP,
          fontSize: 92,
          lineHeight: 1.1,
          letterSpacing: '-0.02em',
          color: toneOf(scene.tone),
          opacity: s,
          transform: `translateY(${rise}px)`,
          textWrap: 'balance',
        }}
      >
        {scene.title}
      </div>
      {scene.sub ? (
        <div
          style={{
            marginTop: 34,
            fontFamily: BODY,
            fontSize: 48,
            lineHeight: 1.35,
            color: C.mut,
            opacity: interpolate(local, [fps * 0.35, fps * 0.75], [0, 1], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            }),
          }}
        >
          {scene.sub}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

export const Post: React.FC<PostProps> = ({
  scenes,
  handle = '@tahailyas',
  site = 'tahailyas.com',
}) => {
  const {fps} = useVideoConfig();
  let at = 0;

  return (
    <AbsoluteFill style={{background: C.bg}}>
      <PostFonts />
      {scenes.map((scene, i) => {
        const from = at;
        const dur = Math.max(1, Math.round(scene.seconds * fps));
        at += dur;
        return (
          <Sequence key={i} from={from} durationInFrames={dur}>
            <SceneInner scene={scene} fps={fps} />
          </Sequence>
        );
      })}
      <Chrome handle={handle} site={site} />
    </AbsoluteFill>
  );
};

/** Split out so useCurrentFrame() reads the SEQUENCE-local frame, not the
 *  composition's — inside a Sequence it rebases, and that is what makes each
 *  scene's entrance start at its own zero. */
const SceneInner: React.FC<{scene: Scene; fps: number}> = ({scene, fps}) => {
  const local = useCurrentFrame();
  return (
    <>
      {scene.vo ? <Audio src={staticFile(`vo/${scene.vo}`)} /> : null}
      <SceneBody scene={scene} local={local} fps={fps} />
    </>
  );
};
