import { z } from "zod";

export const characterCreateSchema = z.object({
  name: z.string().min(1, "名称不能为空").max(50),
  archetype: z.enum(["ANIMAL", "HUMAN", "FANTASY", "ABSTRACT"]).optional().default("ANIMAL"),
  species: z.string().max(30).nullable().optional(),
  ageSetting: z.number().int().positive().nullable().optional(),
  backstory: z.string().max(2000).nullable().optional(),
  relationship: z.string().max(20).nullable().optional(),
  personality: z
    .object({
      extrovert: z.number().min(0).max(100).optional(),
      humor: z.number().min(0).max(100).optional(),
      warmth: z.number().min(0).max(100).optional(),
      curiosity: z.number().min(0).max(100).optional(),
      energy: z.number().min(0).max(100).optional(),
    })
    .optional()
    .default({}),
  catchphrases: z.array(z.string().max(50)).max(10).optional().default([]),
  suffix: z.string().max(20).nullable().optional(),
  topics: z.array(z.string().max(30)).max(20).optional().default([]),
  forbidden: z.array(z.string().max(30)).max(20).optional().default([]),
  responseLength: z.enum(["SHORT", "MEDIUM", "LONG"]).optional().default("SHORT"),
  voiceId: z.string().uuid().nullable().optional(),
  voiceSpeed: z.number().min(0.5).max(2.0).optional().default(1.0),
  llmProvider: z.string().max(50).nullable().optional(),
  llmModel: z.string().max(100).nullable().optional(),
  ttsProvider: z.string().max(50).nullable().optional(),
});

export const characterUpdateSchema = characterCreateSchema.partial();

export type CharacterCreateInput = z.infer<typeof characterCreateSchema>;
export type CharacterUpdateInput = z.infer<typeof characterUpdateSchema>;
