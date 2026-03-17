/** Personality trait values (0-100 scale) */
export interface PersonalityTraits {
  extrovert: number;
  humor: number;
  warmth: number;
  curiosity: number;
  energy: number;
}

/** Personality offsets from user customization (-20 to +20) */
export type PersonalityOffsets = Partial<Record<keyof PersonalityTraits, number>>;

/** Emotion configuration for a character */
export interface EmotionConfig {
  happiness: number;
  sadness: number;
  anger: number;
  surprise: number;
  fear: number;
}

/** Character creation/update payload */
export interface CharacterInput {
  name: string;
  species: string;
  ageSetting?: number;
  backstory?: string;
  relationship?: string;
  personality: PersonalityTraits;
  catchphrases: string[];
  suffix?: string;
  topics: string[];
  forbidden: string[];
  responseLength: "SHORT" | "MEDIUM" | "LONG";
  voiceId?: string;
  voiceSpeed?: number;
  emotionConfig?: EmotionConfig;
  avatar?: string;
  status?: "DRAFT" | "PUBLISHED" | "ARCHIVED";
}
