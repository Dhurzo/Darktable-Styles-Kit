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

## Status legend

- `PASS` — reverse-engineered, round-trips, visual loop passed (§4 of the workflow).
- `FAIL (n/3)` — visual loop failed after n attempts; diagnosis in Notes.
- `UNVERIFIED` — plausible entry, no visual evidence yet (e.g. IOP absent from the 534-preset library).
