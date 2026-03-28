import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

const AI_CORE_URL = process.env.AI_CORE_URL || "http://127.0.0.1:8100";

/**
 * POST /api/voices/clone — upload audio → create cloned voice → save to DB.
 * Protected by middleware (admin auth required).
 */
export async function POST(req: NextRequest) {
  const formData = await req.formData();
  const audio = formData.get("audio") as File | null;
  const title = formData.get("title") as string;
  const characterId = formData.get("characterId") as string | null;

  if (!audio || !title) {
    return NextResponse.json({ error: "Missing audio or title" }, { status: 400 });
  }

  // Forward to AI Core voice-clone API
  const aiFormData = new FormData();
  aiFormData.append("audio", audio);
  aiFormData.append("title", title);
  aiFormData.append("description", `Cloned voice for ${title}`);

  const resp = await fetch(`${AI_CORE_URL}/voice-clone/create`, {
    method: "POST",
    body: aiFormData,
  });

  if (!resp.ok) {
    const err = await resp.text();
    return NextResponse.json({ error: `Clone failed: ${err}` }, { status: 502 });
  }

  const result = await resp.json();
  const fishAudioId = result.fish_audio_id;

  // Create VoiceProfile in database
  const voice = await prisma.voiceProfile.create({
    data: {
      name: title,
      referenceAudio: `fish_audio:${fishAudioId}`,
      description: `Fish Audio cloned voice (${result.state})`,
      fishAudioId: fishAudioId,
      tags: ["cloned", "fish-audio"],
    },
  });

  // Optionally assign to character
  if (characterId) {
    await prisma.character.update({
      where: { id: characterId },
      data: { voiceId: voice.id },
    });
  }

  return NextResponse.json({
    voiceId: voice.id,
    fishAudioId,
    state: result.state,
    characterAssigned: !!characterId,
  });
}
