# SoulForge Open Specifications

| spec | what it defines | reference implementation |
|---|---|---|
| [`soul-format.md`](soul-format.md) | `.soul` v2 — the portable identity container | `soulforge_harness.soul.pack` |
| [`embodiment-protocol.md`](embodiment-protocol.md) | Protocol 0.2 — the brain↔body WebSocket contract | `soulforge_harness.protocol` |

Both are MIT alongside `packages/soulforge-harness`. Readers MUST ignore unknown
fields/files (forward compatibility). Breaking changes bump the magic / protocol
version. Older, superseded documents live in `attic/docs/`.
