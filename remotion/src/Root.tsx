/**
 * The ten motion formats, registered.
 *
 * Durations are declared here rather than inside each component so the whole
 * library's pacing is visible in one place — and so `end` (when the card comes
 * up) and the composition length can never disagree, which is how a reel ends
 * up with two seconds of blank after the card.
 *
 * TAIL is the card's own time. Every format's `end` prop is therefore
 * (duration - TAIL), computed once below.
 */
import React from 'react';
import {Composition} from 'remotion';
import brand from './brand.json';
import {
  ChatStory,
  FeatureSpot,
  KineticHook,
  MythFact,
  OfflineFlex,
  QuoteCard,
  StatRise,
  StreakCalendar,
  ThisOrThat,
  TopFive,
} from './Formats';
import {BaitCard, Pov, RejectApprove, TierList, TwoBeat} from './MemeFormats';
import {Post} from './Post';
import {PROMO_FPS, PROMO_FRAMES, StorePromo} from './StorePromo';
import {StorePromoV2} from './StorePromoV2';
import {StorePromoV3} from './StorePromoV3';

const {w, h, fps} = brand.canvas;
const TAIL = brand.endcard.duration;

/** (id, component, total seconds). Body time is total - TAIL. */
const FORMATS: [string, React.FC<any>, number][] = [
  // Straight promo
  ['KineticHook', KineticHook, 11.5],
  ['TopFive', TopFive, 17.5],
  ['MythFact', MythFact, 12.5],
  ['StatRise', StatRise, 12.5],
  ['ThisOrThat', ThisOrThat, 12.5],
  ['OfflineFlex', OfflineFlex, 11.5],
  ['FeatureSpot', FeatureSpot, 11.5],
  ['ChatStory', ChatStory, 15.5],
  ['StreakCalendar', StreakCalendar, 12.5],
  ['QuoteCard', QuoteCard, 10.5],
  // Meme-shaped — same chrome, different register. See MemeFormats.tsx for
  // why none of them borrows a template image.
  ['RejectApprove', RejectApprove, 12.5],
  ['Pov', Pov, 10.5],
  ['TierList', TierList, 16.5],
  ['TwoBeat', TwoBeat, 11.5],
  ['BaitCard', BaitCard, 11.5],
];

export const RemotionRoot: React.FC = () => (
  <>
    {/* The personal-brand videos. ONE composition, driven entirely by props —
        every one of these posts is the same shape (a few beats of a claim,
        sometimes over a screenshot, with a voice reading it), so fifteen
        bespoke components would be fifteen copies of one layout. Duration is
        set per render from the voiceover length; the 1s default here only
        exists so the composition is selectable in the studio. */}
    <Composition
      id="Post"
      component={Post as React.FC<any>}
      durationInFrames={fps}
      fps={fps}
      width={w}
      height={h}
      defaultProps={{scenes: [{kind: 'text', title: 'Pass scenes as props', seconds: 1}]} as any}
      calculateMetadata={({props}: any) => ({
        // Duration comes from the SCENES, which were themselves timed from
        // their voiceovers in Python. Declaring a fixed length here would make
        // every video either cut a sentence off or end in silence.
        durationInFrames: Math.max(
          1,
          Math.round(
            (props.scenes ?? []).reduce((t: number, s: any) => t + (s.seconds ?? 0), 0) * fps,
          ),
        ),
        // …and so do the DIMENSIONS. The TChess formats are 9:16 because they
        // are made for Reels; the personal-brand posts are 4:5 because that is
        // the tallest ratio LinkedIn shows uncropped. Rather than a second
        // near-identical composition, the caller states the canvas — Remotion
        // 4 lets calculateMetadata override width/height per render.
        width: props.w ?? w,
        height: props.h ?? h,
      })}
    />
    {FORMATS.map(([id, Component, total]) => (
      <Composition
        key={id}
        id={id}
        component={Component}
        durationInFrames={Math.round(total * fps)}
        fps={fps}
        width={w}
        height={h}
        defaultProps={{end: total - TAIL} as any}
      />
    ))}
    {/* Play Store promo video (landscape). Not a reel: own size and length. */}
    <Composition
      id="StorePromo"
      component={StorePromo}
      durationInFrames={PROMO_FRAMES}
      fps={PROMO_FPS}
      width={1920}
      height={1080}
      defaultProps={{voice: 'liam' as const}}
    />
    {/* Promo v2 (vc55, 2026-10-27): the v5 screenshot beats, music only. */}
    <Composition
      id="StorePromoV2"
      component={StorePromoV2}
      durationInFrames={PROMO_FRAMES}
      fps={PROMO_FPS}
      width={1920}
      height={1080}
    />
    <Composition
      id="StorePromoV2Reel"
      component={StorePromoV2}
      durationInFrames={PROMO_FRAMES}
      fps={PROMO_FPS}
      width={1080}
      height={1920}
    />
    {/* Promo v3 (vc55, 2026-10-27): v2's beats, every screen a live recording. */}
    <Composition
      id="StorePromoV3"
      component={StorePromoV3}
      durationInFrames={PROMO_FRAMES}
      fps={PROMO_FPS}
      width={1920}
      height={1080}
    />
    <Composition
      id="StorePromoV3Reel"
      component={StorePromoV3}
      durationInFrames={PROMO_FRAMES}
      fps={PROMO_FPS}
      width={1080}
      height={1920}
    />
    {/* The same promo cut for Reels / Shorts. */}
    <Composition
      id="StorePromoReel"
      component={StorePromo}
      durationInFrames={PROMO_FRAMES}
      fps={PROMO_FPS}
      width={1080}
      height={1920}
      defaultProps={{voice: 'liam' as const}}
    />
  </>
);
