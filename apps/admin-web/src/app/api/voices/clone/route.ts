import { auth } from "@/lib/auth";
import { getAiCoreServiceHeaders, invalidateCharacterCache } from "@/lib/ai-core-admin";
import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

const AI_CORE_URL = process.env.AI_CORE_URL || "http://127.0.0.1:8100";
const SUPPORTED_AUDIO_MIME = new Set([
  "audio/mpeg",
  "audio/mp3",
  "audio/wav",
  "audio/x-wav",
  "audio/wave",
]);

function isSupportedAudioFile(file: File) {
  const name = file.name.toLowerCase();
  return SUPPORTED_AUDIO_MIME.has(file.type) || name.endsWith(".mp3") || name.endsWith(".wav");
}

/**
 * POST /api/voices/clone — upload audio → create cloned voice → save to DB.
 * Protected by middleware (admin auth required).
 */
export async function POST(req: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const formData = await req.formData();
  const audio = formData.get("audio") as File | null;
  const title = formData.get("title") as string;
  const characterId = formData.get("characterId") as string | null;

  if (!audio || !title) {
    return NextResponse.json({ error: "缺少音频文件或音色名称" }, { status: 400 });
  }
  if (!isSupportedAudioFile(audio)) {
    return NextResponse.json({ error: "仅支持 MP3 或 WAV 音频文件" }, { status: 400 });
  }
  if (characterId) {
    const character = await prisma.character.findFirst({
      where: { id: characterId, brandId: session.user.brandId },
      select: { id: true },
    });
    if (!character) {
      return NextResponse.json({ error: "Character not found" }, { status: 404 });
    }
  }

  // Forward to AI Core voice-clone API
  const aiFormData = new FormData();
  aiFormData.append("audio", audio);
  aiFormData.append("title", title);
  aiFormData.append("description", `Cloned voice for ${title}`);

  const resp = await fetch(`${AI_CORE_URL}/voice-clone/create`, {
    method: "POST",
    headers: getAiCoreServiceHeaders(session.user.brandId),
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
      data: {
        voiceId: voice.id,
        voiceCloneRefId: fishAudioId,
        voiceCloneUrl: null,
      },
    });
    await invalidateCharacterCache(session.user.brandId, characterId);
  }

  return NextResponse.json({
    voiceId: voice.id,
    fishAudioId,
    state: result.state,
    characterAssigned: !!characterId,
  });
}
