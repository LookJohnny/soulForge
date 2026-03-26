import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import net from "node:net";

/**
 * Public chat API — no auth required.
 * Used by the mobile chat page (/chat/[id]).
 * Proxies to AI Core + persists messages.
 */

const AI_CORE_URL = new URL(process.env.AI_CORE_URL || "http://127.0.0.1:8100");
const AI_CORE_HOST = AI_CORE_URL.hostname;
const AI_CORE_PORT = parseInt(AI_CORE_URL.port || "8100");
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

// ── Hint / greeting generation based on archetype ──

const ARCHETYPE_HINTS: Record<string, string[]> = {
  ANIMAL: ["你好呀", "今天开心吗？", "给我讲个故事", "你最喜欢什么？"],
  HUMAN: ["最近在忙什么？", "有什么推荐的吗？", "聊聊天吧", "今天过得怎么样？"],
  FANTASY: ["你的世界是什么样的？", "给我讲个故事", "你有什么魔法？", "带我去冒险"],
  ABSTRACT: ["你好", "帮我想个主意", "今天有什么新鲜事？", "聊聊天"],
};

const ARCHETYPE_GREETINGS: Record<string, (name: string, species: string) => string> = {
  ANIMAL: (name) => `${name}正在等你呢～`,
  HUMAN: (name, species) => species ? `${species} · ${name}` : name,
  FANTASY: (name) => `${name}出现在你面前`,
  ABSTRACT: (name) => `${name}已就绪`,
};

function generateHints(char: { archetype: string; catchphrases: string[] | null }): string[] {
  const base = ARCHETYPE_HINTS[char.archetype] || ARCHETYPE_HINTS.ANIMAL;
  if (char.catchphrases?.length) {
    const phrase = char.catchphrases[Math.floor(Math.random() * char.catchphrases.length)];
    if (phrase.length <= 15) return [base[0], phrase, base[2], base[3]];
  }
  return base;
}

function generateGreeting(char: { name: string; species: string | null; archetype: string }): string {
  const fn = ARCHETYPE_GREETINGS[char.archetype] || ARCHETYPE_GREETINGS.ANIMAL;
  return fn(char.name, char.species || "");
}

// ── GET: character info + history ──

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const visitorId = req.nextUrl.searchParams.get("visitor");

  const character = await prisma.character.findUnique({
    where: { id },
    select: { id: true, name: true, species: true, archetype: true, backstory: true, brandId: true, catchphrases: true, personality: true },
  });

  if (!character) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const hints = generateHints(character);
  const greeting = generateGreeting(character);

  // Load chat history if visitorId provided
  let history: object[] = [];
  if (visitorId) {
    const messages = await prisma.chatMessage.findMany({
      where: { characterId: id, visitorId },
      orderBy: { createdAt: "asc" },
      take: 100,
      select: {
        id: true,
        role: true,
        content: true,
        action: true,
        thought: true,
        emotion: true,
        createdAt: true,
      },
    });
    history = messages;
  }

  return NextResponse.json({ ...character, hints, greeting, history });
}

// ── POST: proxy chat + save messages ──

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: characterId } = await params;
  const body = await req.json();
  const visitorId = body.visitorId || "anonymous";

  const character = await prisma.character.findUnique({
    where: { id: characterId },
    select: { brandId: true },
  });

  if (!character) {
    return NextResponse.json({ error: "Character not found" }, { status: 404 });
  }

  const brandId = character.brandId;

  // Save user message immediately
  if (visitorId !== "anonymous") {
    await prisma.chatMessage.create({
      data: {
        characterId,
        visitorId,
        role: "user",
        content: body.text || "",
      },
    });
  }

  const payload = {
    character_id: characterId,
    text: body.text || "你好",
    history: body.history || [],
    with_audio: body.withAudio !== false,
  };

  // Collect AI response data as we proxy the stream
  let aiDialogue = "";
  let aiAction = "";
  let aiThought = "";
  let aiEmotion = "";

  const jsonBody = JSON.stringify(payload);
  const stream = new ReadableStream({
    start(controller) {
      const socket = new net.Socket();
      let headerParsed = false;
      let buffer = "";
      let sseBuffer = "";

      socket.setTimeout(90000);
      socket.connect(AI_CORE_PORT, AI_CORE_HOST, () => {
        const headers = [
          `POST /chat/preview/stream HTTP/1.1`,
          `Host: ${AI_CORE_HOST}:${AI_CORE_PORT}`,
          "Content-Type: application/json",
          `Content-Length: ${Buffer.byteLength(jsonBody)}`,
          "Accept: text/event-stream",
        ];
        if (SERVICE_TOKEN) headers.push(`X-Service-Token: ${SERVICE_TOKEN}`);
        if (brandId) headers.push(`X-Brand-Id: ${brandId}`);
        const request = [...headers, "", jsonBody].join("\r\n");
        socket.write(request);
      });

      socket.on("data", (chunk) => {
        buffer += chunk.toString();
        if (!headerParsed) {
          const headerEnd = buffer.indexOf("\r\n\r\n");
          if (headerEnd === -1) return;
          buffer = buffer.slice(headerEnd + 4);
          headerParsed = true;
        }
        if (buffer) {
          // Parse SSE events to capture AI response for persistence
          sseBuffer += buffer;
          const lines = sseBuffer.split("\n");
          sseBuffer = lines.pop() || "";
          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            try {
              const ev = JSON.parse(line.slice(6).trim());
              if (ev.type === "text_replace") aiDialogue = ev.text || "";
              else if (ev.type === "action") aiAction = ev.text || "";
              else if (ev.type === "thought") aiThought = ev.text || "";
              else if (ev.type === "emotion") aiEmotion = ev.emotion || "";
            } catch {}
          }

          controller.enqueue(new TextEncoder().encode(buffer));
          buffer = "";
        }
      });

      socket.on("end", () => {
        // Save AI message after stream completes
        if (visitorId !== "anonymous" && aiDialogue) {
          prisma.chatMessage.create({
            data: {
              characterId,
              visitorId,
              role: "assistant",
              content: aiDialogue,
              action: aiAction || null,
              thought: aiThought || null,
              emotion: aiEmotion || null,
            },
          }).catch(() => {}); // fire-and-forget
        }
        controller.close();
      });
      socket.on("timeout", () => { socket.destroy(); controller.close(); });
      socket.on("error", () => controller.close());
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
