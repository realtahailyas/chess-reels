/**
 * The three primitives every format is laid out with.
 *
 * Extracted so fifteen formats do not each invent a centred stack and a
 * heading size. When they do, the library stops looking like one account —
 * which is the only thing holding fifteen different ideas together.
 */
import React from 'react';
import {AbsoluteFill} from 'remotion';
import {BODY, C, FONT} from './Brand';

export const Stack: React.FC<{
  children: React.ReactNode;
  gap?: number;
  top?: number;
}> = ({children, gap = 34, top = 0}) => (
  <AbsoluteFill
    style={{
      alignItems: 'center',
      justifyContent: 'center',
      flexDirection: 'column',
      gap,
      padding: '0 90px',
      transform: `translateY(${top}px)`,
      textAlign: 'center',
    }}
  >
    {children}
  </AbsoluteFill>
);

export const Title: React.FC<{
  children: React.ReactNode;
  size?: number;
  color?: string;
}> = ({children, size = 96, color = C.textHi}) => (
  <div
    style={{
      fontFamily: FONT,
      fontWeight: 700,
      fontSize: size,
      lineHeight: 1.06,
      letterSpacing: '-0.02em',
      color,
      textWrap: 'balance',
    }}
  >
    {children}
  </div>
);

export const Body: React.FC<{
  children: React.ReactNode;
  size?: number;
  color?: string;
}> = ({children, size = 46, color = C.muted}) => (
  <div style={{fontFamily: BODY, fontSize: size, lineHeight: 1.35, color}}>{children}</div>
);
