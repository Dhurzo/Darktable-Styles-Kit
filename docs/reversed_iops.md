# reversed_iops — IOP Discovery Ledger

Internal ledger for the IOP reverse-engineering workflow
(see `docs/iop_translation_workflow.md`).

> **Before starting a discovery session, read this list first.** Only work
> on IOPs that are not listed, or that are listed as `FAIL` / `UNVERIFIED`.
> Never re-do an IOP already marked `PASS`. Retries update the existing
> entry — never duplicate it.

| IOP | Status | Version | pack_format / size | Notes |
|-----|--------|---------|--------------------|-------|
| exposure | PASS | v7 | `<iffffii` / 28B | verified against real presets + visual loop |
| temperature | FAIL (3/3) | v4 | `<4fi` / 20B | blob decodes but render shows no color shift; blendop suspect |
| lowlight | PASS | v1 | `<13f` / 52B | struct mapped from C; round-trips both real preset blobs; visual loop passed on WebP test image (blue cast in midtones/highlights, shadow darkening) — see `docs/reversed_iops/lowlight.md` |
| hazeremoval | PASS | v3 | `<ffii` / 16B (legacy v2 `<ffi` / 12B, v1 `<ff` / 8B in official styles) | real v2 blob round-trips (dehaze strong preset); visual loop passed on ref_01 + ref_03 (sat +35/+122%, local contrast +2/+16%, veil removal) — see `docs/reversed_iops/hazeremoval.md` |
| highlights | PASS | v4 | `<i5f2i2fif` / 48B | real blob (Fujifilm_X-E1) decodes to exact defaults; visual loop: blown test image clip 16.8% → 0.0% with strength=1/clip=0.5 — see `docs/reversed_iops/highlights.md` |
| rgblevels | PASS | v1 | `<2i9f` / 44B | levels[3][3]={black,mid,white} per channel, auto-gamma anchors mid; visual loop PASS after diagnosing mid-anchor darkening — see `docs/reversed_iops/rgblevels_graduatednd_agx_channelmixerrgb.md` |
| graduatednd | PASS | v1 | `<6f` / 24B | visual loop: blue ND gradient (density 3, hue .55, sat .6) → top-vs-bottom delta -0.114, R-B -0.073 — see same doc |
| agx | PASS | v7 | `<5f3f8fi2f2i6f2f6fi` / 144B | 36 fields, full AgX tone mapping; visual loop: global tone shift + highlight compression with defaults — see same doc |
| channelmixerrgb | PASS | v3 | `<24f10i4f2i` / 160B | 40 fields (mix matrix 4/ch + WB CAT16 + gamut); visual loop: illuminant 7500K → warmer (+R-B) per module semantics — see same doc |
| primaries | PASS | v1 | `<8f` / 32B | 3 real blobs decode with exact field order (blue-LED-fix presets); visual loop: blue purity 1→0.3 desaturates blues — see `docs/reversed_iops/batch3_iops.md` |
| diffuse | PASS | v2 | `<ifi2f4ff4fi` / 60B | real blob (sharpen+diffuse preset) decodes cleanly; anisotropic solver sharpens OR smooths per speed signs (+10.9% lstd) — see same doc |
| negadoctor | PASS | v2 | `<i18f` / 76B | defaults on a positive → massive negative-remap (MAE 125) = documented purpose; only for scanned negatives — see same doc |
| defringe | PASS | v1 | `<2fi` / 12B | synthetic-CA test: CA metric -18%; conditional module (no-CA → passthrough) — see same doc |
| cacorrectrgb | PASS | v1 | `<i2f2i` / 20B | synthetic-CA test: CA metric -57% (strength 2.5, radius 12) — see same doc |
| globaltonemap | PASS | v3 | `<i3f` / 16B | Drago defaults → lum +0.085, lstd +17.4% (highlight compression) — see same doc |
| profile_gamma | PASS | v2 | `<i6f` / 28B | GOTCHA: op name has underscore (add_iop profile_gamma); wrong name silently no-ops. Correct name + extreme values → MAE 8.17 — see same doc |

## Status legend

- `PASS` — reverse-engineered, round-trips, visual loop passed (§4 of the workflow).
- `FAIL (n/3)` — visual loop failed after n attempts; diagnosis in Notes.
- `UNVERIFIED` — plausible entry, no visual evidence yet (e.g. IOP absent from the 534-preset library).
