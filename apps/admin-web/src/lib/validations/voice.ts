import { z } from "zod";

export const voiceCreateSchema = z.object({
  name: z.string().min(1, "名称不能为空").max(50),
  referenceAudio: z.string().max(200).optional().default(""),
  description: z.string().max(500).nullable().optional(),
  tags: z.array(z.string().max(20)).max(10).optional().default([]),
  dashscopeVoiceId: z.string().max(100).nullable().optional(),
});

export type VoiceCreateInput = z.infer<typeof voiceCreateSchema>;
