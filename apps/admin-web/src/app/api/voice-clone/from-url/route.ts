import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";

const AI_CORE_URL = process.env.AI_CORE_URL || "http://127.0.0.1:8100";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

/**
 * POST /api/voice-clone/from-url
 *   Body: { audioUrl, title, description? }
 *   Returns: { fishAudioId, title, state } or { error }
 *
 * Proxies to AI Core /voice-clone/from-url. The returned fishAudioId
 * goes into Character.voiceCloneRefId on save.
 */
export async function POST(req: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  let body: { audioUrl?: string; title?: string; description?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const audioUrl = (body.audioUrl || "").trim();
  const title = (body.title || "").trim();
  if (!audioUrl || !/^https?:\/\//i.test(audioUrl)) {
    return NextResponse.json({ error: "audioUrl 必须是 http(s) URL" }, { status: 400 });
  }
  if (!title) {
    return NextResponse.json({ error: "title 不能为空" }, { status: 400 });
  }

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (SERVICE_TOKEN) headers["X-Service-Token"] = SERVICE_TOKEN;

  const resp = await fetch(`${AI_CORE_URL}/voice-clone/from-url`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      audio_url: audioUrl,
      title,
      description: body.description || `Cloned voice for ${title}`,
    }),
  });

  if (!resp.ok) {
    const err = await resp.text();
    return NextResponse.json(
      { error: `克隆失败: ${err.slice(0, 300)}` },
      { status: resp.status === 502 ? 502 : 500 }
    );
  }

  const result = await resp.json();
  return NextResponse.json({
    fishAudioId: result.fish_audio_id,
    title: result.title,
    state: result.state,
  });
}
