# SoulForge Believability Engine — Architecture

Based on Disney Research "Olaf" paper (arXiv:2512.16705).

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    LLM Persona Engine                        │
│              (chat → structured JSON response)               │
└──────────────────────┬──────────────────────────────────────┘
                       │ CompositePrimitive (protobuf)
┌──────────────────────▼──────────────────────────────────────┐
│              Behavior Engine (3-Layer)                        │
│                                                              │
│  Layer 1: Ambient      ──→ breathing, saccades, micro-expr   │
│  Layer 2: Triggered    ──→ wave, nod, wiggle (ADSR envelope) │
│  Layer 3: Reactive     ──→ touch, proximity, IMU responses   │
│                                                              │
│  ChannelBlender: EXCLUSIVE / ADDITIVE / BLENDED mixing       │
│  6 transition curves: linear, ease, spring, critical_damp    │
└──────────────────────┬──────────────────────────────────────┘
                       │ channel values (20+ channels)
┌──────────────────────▼──────────────────────────────────────┐
│              Safety Constraint Layer                          │
│                                                              │
│  CBF (Control Barrier Function) per constraint:              │
│  • Joint limits     γ=20    (Olaf formula 5a-5c)             │
│  • Temperature      γ=0.3   (Olaf formula 6)                │
│  • Battery voltage  γ=0.5                                    │
│  • Volume           γ=1.0                                    │
│  • Velocity/Accel   γ=5/10                                   │
│                                                              │
│  Key: smooth deceleration, NOT hard clamping                 │
└──────────────────────┬──────────────────────────────────────┘
                       │ safe channel values
┌──────────────────────▼──────────────────────────────────────┐
│              Motion Smoother                                  │
│                                                              │
│  velocity limit → acceleration limit → upsample → Butterworth│
│  20Hz policy → 100Hz servo, 15Hz cutoff low-pass             │
│  Ref: Olaf Sec. VII-C (50Hz→600Hz, 37.5Hz cutoff)           │
└──────────────────────┬──────────────────────────────────────┘
                       │ smooth commands
┌──────────────────────▼──────────────────────────────────────┐
│              Mapping Engine                                   │
│                                                              │
│  Degradation Matrix: abstract primitive → best available     │
│  hardware expression. Falls back gracefully:                 │
│  servo → LED → vibration (never "no output")                 │
│                                                              │
│  3 hardware tiers: full(¥300) / mid(¥100) / basic(¥50)      │
└──────────────────────┬──────────────────────────────────────┘
                       │ HardwareCommands
┌──────────────────────▼──────────────────────────────────────┐
│  Physical Toy  /  Digital Twin Simulator                     │
└─────────────────────────────────────────────────────────────┘

                  RL Training Loop (offline)
┌─────────────────────────────────────────────────────────────┐
│  BelievabilityEnv (Gymnasium)                                │
│    obs → BelievabilityPolicy.predict() → action              │
│    action → BehaviorEngine → Safety → Simulator → state      │
│    state → BelievabilityMetrics → reward                     │
│                                                              │
│  6 dimensions: Coherence · Naturalness · Responsiveness      │
│                Personality · Physical · Safety                │
│                                                              │
│  PPO training: 3-layer MLP 256 units, CPU-only               │
└─────────────────────────────────────────────────────────────┘
```

## Key Design Principles

1. **Believability > Functionality**: When in conflict, prefer natural-looking behavior over precise execution.
2. **Graceful Degradation**: Every primitive has a fallback chain. A $50 toy expresses JOY differently from a $300 toy, but both express it.
3. **CBF over Hard Clamps**: Safety constraints slow motion smoothly instead of jarring stops.
4. **Ambient Life**: The toy is never completely still — breathing, eye saccades, and micro-expressions run continuously.
5. **Personality-Driven**: All parameters (breathing rate, saccade frequency, reaction speed) are modulated by the character's emotional state.

## Module Dependencies

```
protocol/      ← no deps (pure protobuf + JSON schema)
safety/        ← numpy only
motion/        ← numpy, scipy
engine/        ← depends on nothing external
believability/ ← numpy, gymnasium (optional), torch (optional)
simulator/     ← depends on safety/ (thermal model)
```
