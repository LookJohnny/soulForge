import type { PersonalityTraits, PersonalityOffsets } from "../types/character";

/** Clamp a value between min and max */
function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

/** Merge base personality with user offsets, clamped to 0-100 */
export function mergePersonality(
  base: PersonalityTraits,
  offsets?: PersonalityOffsets | null,
): PersonalityTraits {
  if (!offsets) return { ...base };
  const result = { ...base };
  for (const key of Object.keys(offsets) as (keyof PersonalityTraits)[]) {
    if (key in result && offsets[key] !== undefined) {
      result[key] = clamp(result[key] + offsets[key]!, 0, 100);
    }
  }
  return result;
}

/** Map personality traits to descriptive text (Chinese) */
export function personalityToText(traits: PersonalityTraits): string {
  const descriptions: string[] = [];

  if (traits.extrovert >= 70) descriptions.push("活泼外向");
  else if (traits.extrovert <= 30) descriptions.push("安静内敛");

  if (traits.humor >= 70) descriptions.push("幽默风趣");
  else if (traits.humor <= 30) descriptions.push("认真严肃");

  if (traits.warmth >= 70) descriptions.push("温暖贴心");
  else if (traits.warmth <= 30) descriptions.push("酷酷的");

  if (traits.curiosity >= 70) descriptions.push("充满好奇心");
  else if (traits.curiosity <= 30) descriptions.push("淡定从容");

  if (traits.energy >= 70) descriptions.push("元气满满");
  else if (traits.energy <= 30) descriptions.push("慢悠悠的");

  return descriptions.length > 0 ? descriptions.join("、") : "性格平和";
}
