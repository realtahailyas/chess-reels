TChess brand assets — copies, not references.
=============================================

These are COPIES so chess-reels stays self-contained. The originals live in the
app repo and are written by `tchess-app/scripts/generate-brand.py`, which reads
the DESIGNER'S OWN pack at `tchess-app/assets/images/Logo Files/` and writes
straight into this folder as its last step. So a brand refresh is `npm run
brand` in puzzleflow — there is nothing to copy by hand any more.

  Sora-Bold.ttf <-  tchess-app\node_modules\@expo-google-fonts\sora\700Bold\
                    Sora_700Bold.ttf -- the app's own display face.
                    SIL OFL, safe to publish.
                    Used ONLY for the promo lockup (compose._wordmark_sprite).
                    Do NOT drop it in as assets/font-bold.ttf: that is the
                    chain src/fonts.py walks, and it would restyle every
                    headline in every reel.
                    ⚠️ NOT written by the generator — it is a font, not art.

  store-icon.png    512x512 RGB. The actual Play listing icon (identical to
                    tchess-app/store/listing-icon-512.png), so the end card's
                    store row is recognisable when the store page opens.

  wordmark.png      1463x384 RGBA. The designer's wordmark: the chrome rook
                    followed by "TChess".

                    ⚠️ THE OLD WARNING HERE IS DEAD AND THE REASON MATTERS.
                    It said this file "sets the rook AS the letter T, so it
                    renders (rook)Chess", which reads as "a rook next to the
                    word Chess" to a stranger — and that is why the promo
                    lockup spells the name out itself in Sora Bold. The
                    designer's wordmark HAS a real T: it is rook + "TChess",
                    so the objection no longer applies and this file can be
                    used directly. `compose._wordmark_sprite` still draws its
                    own; switching it to this asset is a live option now, not
                    a regression waiting to happen.

                    The other old warning is also gone: there is no longer a
                    second wordmark set in Arial Rounded MT Bold with an
                    unresolved licence. There is one wordmark, and it was
                    drawn for this project by its designer.

  mark.png          1024x1024 RGBA, real transparency — the chrome rook alone,
                    at the same size and position as the app's adaptive-icon
                    foreground layer.
                    Do NOT use puzzleflow's icon.png instead: it is fully
                    opaque (alpha 255 everywhere), so compositing it paints a
                    visible black rectangle wherever it lands.

Brand rules that apply when these are drawn (from tchess-app/src/theme/tokens.ts):

  accent      #9D55E9   the ONE accent colour (hue 303 — it was #7C5CFF, which
                        sits at hue 285 and reads as blue on a black screen)
  text high   #E9E9EA   never pure #FFFFFF -- it halates on near-black
  background  #000000   true black; those pixels are OFF on an OLED panel
