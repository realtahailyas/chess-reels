/**
 * Shared brand furniture: the banner, the end card, the lockup.
 *
 * Every value comes from brand.json, which `python export_brand.py` writes out
 * of config.py. Nothing here hard-codes a colour or a string. That is the whole
 * reason the file exists — the PIL reels and these motion pieces have to look
 * like one product, and two hand-maintained palettes drift the first time one
 * of them is edited.
 */
import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Img,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import brand from './brand.json';

export const C = brand.color;
export const B = brand.brand;

export const FONT = 'TChessDisplay';
export const BODY =
  'Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif';

/** Injected once per composition; Remotion renders in headless Chrome, so a
 *  @font-face from a data URI is the only way the face is guaranteed present. */
export const FontFace: React.FC = () => (
  <style>{`@font-face{font-family:'${FONT}';src:url(${brand.asset.font}) format('truetype');font-weight:700;font-style:normal;}`}</style>
);

/** The rook, then the name spelled out. NOT the app's shipped wordmark, which
 *  sets the rook AS the T and reads as "(rook)Chess" to anyone who does not
 *  already know the icon. Proportions mirror compose._wordmark_sprite. */
export const Lockup: React.FC<{height: number; color?: string}> = ({
  height,
  color = C.textHi,
}) => {
  const rook = height * brand.lockup.rookCap;
  // 🔴 CSS `font-size` is the EM, not the cap height, so sizing the text at
  // rook * capMatch directly renders it about a quarter too small against the
  // mark. Divide by the face's measured cap ratio to land on the same optical
  // size PIL reaches. (The mark itself is pre-trimmed to its ink in
  // export_brand.py — the raw file is half transparent padding, which is what
  // made the rook look tiny in the first version of this component.)
  const size = (rook * brand.lockup.capMatch) / brand.lockup.capRatio;
  return (
    <div style={{display: 'flex', alignItems: 'center', gap: rook * brand.lockup.gap, height}}>
      <Img src={brand.asset.mark} style={{height: rook, width: 'auto'}} />
      <span
        style={{
          fontFamily: FONT,
          fontWeight: 700,
          fontSize: size,
          lineHeight: 1,
          color,
          letterSpacing: '-0.01em',
        }}
      >
        {B.name}
      </span>
    </div>
  );
};

/** Top banner, on every frame of every format — same lockup, same violet edge
 *  and same "FREE ON GOOGLE PLAY" line as the PIL reels. */
export const Banner: React.FC = () => (
  <div
    style={{
      position: 'absolute',
      top: 20,
      left: 0,
      right: 0,
      display: 'flex',
      justifyContent: 'center',
    }}
  >
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 6,
        padding: '16px 34px 14px',
        borderRadius: 24,
        background: C.surface + 'EB',
        border: `3px solid ${C.violet}`,
      }}
    >
      <Lockup height={62} />
      <span
        style={{
          fontFamily: BODY,
          fontWeight: 700,
          fontSize: 26,
          letterSpacing: '0.02em',
          color: C.violet,
        }}
      >
        {B.bannerSub}
      </span>
    </div>
  </div>
);

export const Handle: React.FC = () => (
  <div
    style={{
      position: 'absolute',
      bottom: 46,
      left: 0,
      right: 0,
      textAlign: 'center',
      fontFamily: BODY,
      fontWeight: 700,
      fontSize: 34,
      color: C.muted,
      opacity: 0.72,
    }}
  >
    {B.handle}
  </div>
);

/**
 * The music bed, at the reels' own gain, with a fade at both ends.
 *
 * The track is chosen by hashing the composition id, so ten formats do not all
 * open on the same four bars — the same trick the PIL pipeline plays with the
 * puzzle id. A silent motion piece next to a scored reel does not read as a
 * quieter post; it reads as a broken upload.
 */
export const Track: React.FC = () => {
  const {durationInFrames, fps, id} = useVideoConfig();
  const tracks = brand.music.tracks;
  if (!tracks.length) return null;

  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  const file = tracks[h % tracks.length];
  const fade = Math.max(1, Math.round(brand.music.fade * fps));

  return (
    <Audio
      src={staticFile(file)}
      volume={(f) =>
        brand.music.gain *
        interpolate(
          f,
          [0, fade, durationInFrames - fade, durationInFrames],
          [0, 1, 1, 0],
          {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
        )
      }
    />
  );
};

/** Ground + banner + handle + music. Every format sits inside this so the
 *  chrome is identical across all ten and can only be changed in one place. */
export const Frame: React.FC<{children: React.ReactNode; glow?: string}> = ({
  children,
  glow,
}) => (
  <AbsoluteFill style={{background: C.bg}}>
    {glow ? (
      <AbsoluteFill
        style={{
          background: `radial-gradient(60% 42% at 50% 34%, ${glow}2E 0%, ${glow}00 70%)`,
        }}
      />
    ) : null}
    <div style={{position: 'absolute', top: 0, left: 0, right: 0, height: 9, background: C.accent}} />
    <FontFace />
    <Track />
    {children}
    <Banner />
    <Handle />
  </AbsoluteFill>
);

/**
 * The closing card: features, the promise line, the real Play listing row and
 * the green Install button. It reproduces the LIVE listing rather than
 * paraphrasing it — the row's whole job is that the store page looks like this
 * frame when it opens.
 */
export const EndCard: React.FC<{startAt: number}> = ({startAt}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = (frame - startAt) / fps;
  if (t < 0) return null;
  const o = interpolate(t, [0, 0.3], [0, 1], {extrapolateRight: 'clamp'});

  return (
    <AbsoluteFill style={{background: C.bg, opacity: o}}>
      <FontFace />
      <div style={{position: 'absolute', top: 0, left: 0, right: 0, height: 9, background: C.accent}} />
      <div
        style={{
          position: 'absolute',
          inset: '270px 70px auto',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 40,
        }}
      >
        <Lockup height={180} />
        <div style={{fontFamily: BODY, fontWeight: 700, fontSize: 52, color: C.textHi}}>
          {B.tagline}
        </div>

        <div style={{width: '100%', height: 1, background: C.hairline}} />
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            rowGap: 30,
            columnGap: 40,
            width: '100%',
            padding: '0 40px',
          }}
        >
          {B.features.map((f) => (
            <div key={f} style={{display: 'flex', alignItems: 'center', gap: 20}}>
              <div style={{width: 14, height: 14, borderRadius: 7, background: C.violet}} />
              <span style={{fontFamily: BODY, fontSize: 46, color: C.textHi}}>{f}</span>
            </div>
          ))}
        </div>
        <div style={{width: '100%', height: 1, background: C.hairline}} />

        <div style={{fontFamily: BODY, fontSize: 40, color: C.muted}}>{B.promise}</div>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 26,
            width: '100%',
            padding: 22,
            borderRadius: 26,
            background: C.surface,
            border: `1px solid ${C.hairline}`,
          }}
        >
          <Img
            src={brand.asset.storeIcon}
            style={{width: 116, height: 116, borderRadius: 26, flex: 'none'}}
          />
          <div style={{display: 'flex', flexDirection: 'column', gap: 4}}>
            {B.storeTitle.map((line) => (
              <span
                key={line}
                style={{fontFamily: BODY, fontWeight: 700, fontSize: 38, color: C.textHi}}
              >
                {line}
              </span>
            ))}
            <span style={{fontFamily: BODY, fontSize: 30, color: C.playGreen}}>{B.storeDev}</span>
          </div>
        </div>

        <div
          style={{
            width: '100%',
            padding: '22px 0',
            borderRadius: 26,
            background: C.playGreen,
            textAlign: 'center',
            fontFamily: BODY,
            fontWeight: 700,
            fontSize: 46,
            color: '#fff',
          }}
        >
          {B.install}
        </div>
        <div style={{fontFamily: BODY, fontWeight: 700, fontSize: 40, color: C.muted}}>
          {B.web}
        </div>
      </div>
      <Handle />
    </AbsoluteFill>
  );
};

/** Seconds -> frames, so durations read in seconds everywhere. */
export const sec = (s: number, fps: number) => Math.round(s * fps);
