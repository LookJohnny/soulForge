# soulforge-harness

Portable AI personality infrastructure: give any AI — a game NPC, a desktop
companion, a car assistant, a plush toy — a persistent, portable **soul**.

- **`.soul` format** — a character's identity (personality, voice, embodiment,
  expression tuning, knowledge) in one signed, optionally passphrase-encrypted
  file that moves across models, bodies and vendors.
- **Persona math** — PAD emotion baselines, five-axis relationships with staged
  progression, attachment-aware behavior.
- **Life runtime** — day/hour/minute planning, event-driven replanning,
  character↔character conversation, space & reflection (Generative-Agents style).
- **Embodiment protocol** — one WebSocket contract so a browser VRM, a robot
  or a voice pipeline can all be "bodies" of the same character.

Core is dependency-free Python. Extras: `soulforge-harness[crypto]` for
encrypted `.soul` files, `[ws]` to host the embodiment protocol server.

Docs & spec: see `spec/` in the SoulForge repository. Quickstart lands in WP3.
