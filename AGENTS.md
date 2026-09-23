# OttoSmasher

The current specification is `docs/CURRENT_REQUIREMENTS.md`. The two root-level
historical requirement/architecture documents remain useful context; current user
instructions override them.

- Helper first: searchable original dialogue, explicit rhythmic constraints,
  original/tempo-matched audition, provenance, and non-destructive exports.
- Keep raw seconds, phones, mora, and perceptual rhythm anchors distinct.
- Separate approximate matches from matches achievable within a time-warp budget.
- Subtitle timestamps are coarse, with up to roughly 0.5 s error. Never present
  subtitle boundaries or uniformly divided text as measured phone boundaries.
- Keep media, model weights, third-party checkouts, environments and generated
  artifacts out of Git. Preserve original media and processing ancestry.
- No automatic destructive changes or unreviewed promotion of model output to
  manually verified annotations.
- The web page remains the shared analysis demo. Desktop migration is now authorized:
  Electron hosts independent search, cutter and library windows with real-file DAW handoff.
- Run pymss vocals extraction before production speech/phone analysis; no silent
  fallback to mixed audio. Keep analysis and rendered audio-version provenance aligned.
- Use isolated project environments; do not modify global shell configuration.
- On this Mac use `./scripts/git` or `.runtime/envs/core/bin/git`; `/usr/bin/git`
  is an unconfigured Apple Command Line Tools stub. Python is `.runtime/envs/core/bin/python`.
- Test meaningful timing, indexing, provenance and failure behavior. Real anime
  validation complements synthetic timing fixtures; no subjective quality claims
  based only on numerical tests.
