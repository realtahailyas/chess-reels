/**
 * The Play Store promo video v2 (2026-10-27, vc55 / 3.6.3): 1920x1080, 30 s.
 *
 * The same eight beats, words and order as the approved v5 store screenshots
 * (store/2026-10-v5). Three screens are live emulator recordings of vc55 (bot
 * game, puzzle, drill; cut to 720x1442 @30fps in public/promo2/clips); the
 * rest are the v5 Pro-account captures, so nothing shows a lock.
 *
 * Music only, no voice: the ElevenLabs free tier is non-commercial, and this
 * is an ad. The end card says "get it", never "free" (no free-forever promise).
 * v1 is StorePromo.tsx (vc41, 2026-10-02), kept as it was.
 */
import React, {useEffect, useState} from 'react';
import {
  AbsoluteFill,
  Audio,
  continueRender,
  delayRender,
  Easing,
  Img,
  interpolate,
  OffthreadVideo,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

import {PROMO_FPS, PROMO_FRAMES} from './StorePromo';
export {PROMO_FPS, PROMO_FRAMES};

const PURPLE = '#9D55E9';
const PURPLE_LIGHT = '#BF8DFE';
const WHITE = '#F2F2F3';
const DISPLAY = 'PromoUnbounded';

// Two layouts from one timeline. Landscape (Play listing): words left, screen
// right. Portrait (reels): words on top, screen below — the Set A screenshot
// arrangement. The clips are 720x1494, the phone's 1080x2240 content area.
type Geo = {
  w: number;
  h: number;
  screenH: number;
  screenW: number;
  screenCx: number;
  screenTop: number;
  words: React.CSSProperties;
  align: 'flex-start' | 'center';
  bigSize: (word: string) => number;
  lineSize: number;
  corner: React.CSSProperties;
};

const ratio = 720 / 1442;

const useGeo = (): Geo => {
  const {width, height} = useVideoConfig();
  if (width > height) {
    const screenH = 940;
    return {
      w: width,
      h: height,
      screenH,
      screenW: Math.round(screenH * ratio),
      screenCx: 1395,
      screenTop: (height - screenH) / 2 + 10,
      words: {left: 130, width: 980, top: 0, bottom: 0, justifyContent: 'center'},
      align: 'flex-start',
      bigSize: (word) => (word.length > 7 ? 128 : 148),
      lineSize: 50,
      corner: {left: 130, top: 70, height: 48},
    };
  }
  // Portrait: keep the bottom ~180px light, where Reels/Shorts draw captions.
  const screenH = 1180;
  return {
    w: width,
    h: height,
    screenH,
    screenW: Math.round(screenH * ratio),
    screenCx: width / 2,
    screenTop: 590,
    words: {left: 50, right: 50, top: 230, height: 300, justifyContent: 'flex-start'},
    align: 'center',
    bigSize: (word) => (word.length > 7 ? 120 : 140),
    lineSize: 46,
    corner: {left: (width - (56 * 1463) / 384) / 2, top: 96, height: 56},
  };
};

type Media = {kind: 'video'; src: string} | {kind: 'image'; src: string; zoom?: boolean};

type Scene = {
  from: number;
  dur: number;
  big: string;
  line: string;
  media: Media[];
  /** Frame (inside the scene) where the second media item takes over. */
  splitAt?: number;
};

const v = (name: string): Media => ({kind: 'video', src: `promo2/clips/${name}.mp4`});
const still = (name: string): Media => ({kind: 'image', src: `promo2/${name}.png`, zoom: true});

const SCENES: Scene[] = [
  // e4 c5, Nf3 c4 against Oscar.
  {from: 0, dur: 110, big: '77 BOTS', line: 'THAT FIGHT BACK', media: [v('bot')]},
  {from: 110, dur: 95, big: 'GROK', line: 'ROASTS YOUR MOVES', media: [still('grok')]},
  {from: 205, dur: 90, big: 'REAL AI', line: 'CHATGPT AND GROK', media: [still('play')]},
  // Re6+, Rxe7+, "First try" at ~2.9 s.
  {from: 295, dur: 105, big: '60,000', line: 'CHESS PUZZLES', media: [v('puz')]},
  // Kc3, Rd1, Ra1#: "Technique complete" at ~3.5 s.
  {from: 400, dur: 115, big: 'DRILLS', line: 'TRAIN ONE SKILL AT A TIME', media: [v('drill')]},
  {from: 515, dur: 95, big: 'REVIEW', line: 'EVERY MISTAKE EXPLAINED', media: [still('review')]},
  {from: 610, dur: 90, big: '300', line: 'LESSONS · ZERO TO MASTER', media: [still('learn')]},
  {from: 700, dur: 90, big: '160+', line: 'ENDGAMES TO MASTER', media: [still('endgames')]},
];
const END_FROM = 790;

/** Unbounded is variable; load it once and hold the render until it is in. */
const useDisplayFont = () => {
  const [handle] = useState(() => delayRender('Unbounded'));
  useEffect(() => {
    const face = new FontFace(DISPLAY, `url(${staticFile('promo2/Unbounded.ttf')})`, {
      weight: '200 900',
    });
    face
      .load()
      .then((f) => {
        (document.fonts as unknown as {add: (f: FontFace) => void}).add(f);
        continueRender(handle);
      })
      .catch(() => continueRender(handle));
  }, [handle]);
};

const Backdrop: React.FC = () => {
  const g = useGeo();
  const glowX = (g.screenCx / g.w) * 100;
  const glowY = ((g.screenTop + g.screenH / 2) / g.h) * 100;
  return (
  <AbsoluteFill style={{background: '#000'}}>
    <AbsoluteFill
      style={{
        backgroundImage:
          'repeating-conic-gradient(rgba(255,255,255,0.045) 0 25%, transparent 0 50%)',
        backgroundSize: '120px 120px',
        WebkitMaskImage: 'linear-gradient(90deg, #000 0%, rgba(0,0,0,0.35) 35%, transparent 60%)',
        maskImage: 'linear-gradient(90deg, #000 0%, rgba(0,0,0,0.35) 35%, transparent 60%)',
      }}
    />
    <AbsoluteFill
      style={{
        background: `radial-gradient(ellipse ${g.w > g.h ? '34% 62%' : '70% 40%'} at ${glowX}% ${glowY}%, rgba(157,85,233,0.42), rgba(157,85,233,0) 70%)`,
      }}
    />
  </AbsoluteFill>
  );
};

const Screen: React.FC<{scene: Scene}> = ({scene}) => {
  const g = useGeo();
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({frame, fps, config: {damping: 18, stiffness: 140, mass: 0.8}});
  const exit = interpolate(frame, [scene.dur - 6, scene.dur], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.in(Easing.cubic),
  });
  const y = interpolate(enter, [0, 1], [140, 0]) - exit * 90;
  const opacity = Math.min(enter * 1.4, 1) * (1 - exit);
  const scale = interpolate(enter, [0, 1], [0.94, 1]);

  const split = scene.splitAt ?? scene.dur;
  return (
    <div
      style={{
        position: 'absolute',
        left: g.screenCx - g.screenW / 2,
        top: g.screenTop,
        width: g.screenW,
        height: g.screenH,
        borderRadius: 40,
        overflow: 'hidden',
        background: '#000',
        boxShadow: '0 30px 120px rgba(157,85,233,0.45), 0 0 0 2px rgba(255,255,255,0.06)',
        transform: `translateY(${y}px) scale(${scale})`,
        opacity,
      }}
    >
      {scene.media.map((m, i) => {
        const from = i === 0 ? 0 : split;
        const dur = i === 0 ? split : scene.dur - split;
        return (
          <Sequence key={i} from={from} durationInFrames={dur} premountFor={fps}>
            <MediaFill media={m} dur={dur} />
          </Sequence>
        );
      })}
    </div>
  );
};

const MediaFill: React.FC<{media: Media; dur: number}> = ({media, dur}) => {
  const frame = useCurrentFrame();
  if (media.kind === 'video') {
    return (
      <OffthreadVideo
        src={staticFile(media.src)}
        muted
        style={{width: '100%', height: '100%', objectFit: 'cover'}}
      />
    );
  }
  // The Pro-phone stills are a touch wider than the recordings; `contain` on
  // black keeps the whole board in view instead of trimming its edges.
  const zoom = media.zoom ? interpolate(frame, [0, dur], [1, 1.07]) : 1;
  return (
    <Img
      src={staticFile(media.src)}
      style={{
        width: '100%',
        height: '100%',
        objectFit: 'contain',
        transform: `scale(${zoom})`,
        transformOrigin: '50% 30%',
      }}
    />
  );
};

const Words: React.FC<{scene: Scene}> = ({scene}) => {
  const g = useGeo();
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const exit = interpolate(frame, [scene.dur - 6, scene.dur], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const rise = (delay: number) => {
    const s = spring({frame: frame - delay, fps, config: {damping: 16, stiffness: 160}});
    return {
      opacity: Math.min(s * 1.3, 1) * (1 - exit),
      transform: `translateY(${interpolate(s, [0, 1], [50, 0]) - exit * 30}px)`,
    };
  };
  return (
    <div
      style={{
        position: 'absolute',
        ...g.words,
        display: 'flex',
        flexDirection: 'column',
        alignItems: g.align,
        textAlign: g.align === 'center' ? 'center' : 'left',
        fontFamily: DISPLAY,
      }}
    >
      <div
        style={{
          fontSize: g.bigSize(scene.big),
          lineHeight: 1,
          fontWeight: 900,
          letterSpacing: -4,
          color: PURPLE_LIGHT,
          ...rise(2),
        }}
      >
        {scene.big}
      </div>
      <div
        style={{
          marginTop: 26,
          fontSize: g.lineSize,
          lineHeight: 1.1,
          fontWeight: 800,
          letterSpacing: 1,
          color: WHITE,
          ...rise(7),
        }}
      >
        {scene.line}
      </div>
    </div>
  );
};

const Corner: React.FC = () => {
  const g = useGeo();
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 12, END_FROM - 10, END_FROM], [0, 0.9, 0.9, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <Img
      src={staticFile('promo2/wordmark.png')}
      style={{position: 'absolute', ...g.corner, opacity}}
    />
  );
};

const EndCard: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame, fps, config: {damping: 15, stiffness: 120}});
  const s2 = spring({frame: frame - 10, fps, config: {damping: 16, stiffness: 140}});
  const glow = interpolate(frame, [0, 40], [0, 1], {extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', fontFamily: DISPLAY}}>
      <AbsoluteFill
        style={{
          background: `radial-gradient(ellipse 45% 55% at 50% 50%, rgba(157,85,233,${0.5 * glow}), rgba(157,85,233,0) 70%)`,
        }}
      />
      <Img
        src={staticFile('promo2/wordmark.png')}
        style={{
          height: 170,
          opacity: s,
          transform: `scale(${interpolate(s, [0, 1], [0.85, 1])})`,
        }}
      />
      <div
        style={{
          marginTop: 56,
          padding: '20px 44px',
          borderRadius: 999,
          background: PURPLE,
          color: '#fff',
          fontSize: 40,
          fontWeight: 800,
          letterSpacing: 2,
          opacity: s2,
          transform: `translateY(${interpolate(s2, [0, 1], [30, 0])}px)`,
        }}
      >
        GET IT ON GOOGLE PLAY
      </div>
    </AbsoluteFill>
  );
};

export const StorePromoV2: React.FC = () => {
  useDisplayFont();
  const {fps, durationInFrames} = useVideoConfig();
  return (
    <AbsoluteFill style={{background: '#000'}}>
      <Backdrop />
      {SCENES.map((sc, i) => (
        <Sequence key={i} from={sc.from} durationInFrames={sc.dur} premountFor={fps}>
          <Screen scene={sc} />
          <Words scene={sc} />
        </Sequence>
      ))}
      <Corner />
      <Sequence from={END_FROM} premountFor={fps}>
        <EndCard />
      </Sequence>

      {/* Music: the loud part of the track, out on the card. */}
      <Audio
        src={staticFile('promo2/music.mp3')}
        startFrom={13 * fps}
        volume={(f) =>
          interpolate(f, [0, 8, durationInFrames - 30, durationInFrames], [0, 0.85, 0.85, 0], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          })
        }
      />
    </AbsoluteFill>
  );
};
