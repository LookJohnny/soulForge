/** Default personality trait values */
export const DEFAULT_PERSONALITY = {
  extrovert: 50,
  humor: 50,
  warmth: 50,
  curiosity: 50,
  energy: 50,
} as const;

/** Personality offset bounds */
export const PERSONALITY_OFFSET_MIN = -20;
export const PERSONALITY_OFFSET_MAX = 20;

/** Response length to token limit mapping */
export const RESPONSE_LENGTH_TOKENS: Record<string, number> = {
  SHORT: 100,
  MEDIUM: 200,
  LONG: 400,
};

/** Supported personality trait keys */
export const PERSONALITY_TRAITS = [
  "extrovert",
  "humor",
  "warmth",
  "curiosity",
  "energy",
] as const;
