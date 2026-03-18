import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import net from "node:net";

const AI_CORE_HOST = "127.0.0.1";
const AI_CORE_PORT = parseInt(process.env.AI_CORE_PORT || "8100");

function rawPost(path: string, body: object): Promise<{ status: number; data: unknown }> {
  return new Promise((resolve, reject) => {
    const jsonBody = JSON.stringify(body);
    const socket = new net.Socket();
    let response = "";

    socket.setTimeout(90000);
    socket.connect(AI_CORE_PORT, AI_CORE_HOST, () => {
      const request = [
        `POST ${path} HTTP/1.0`,
        `Host: ${AI_CORE_HOST}:${AI_CORE_PORT}`,
        "Content-Type: application/json",
        `Content-Length: ${Buffer.byteLength(jsonBody)}`,
        "Connection: close",
        "",
        jsonBody,
      ].join("\r\n");
      socket.write(request);
    });

    socket.on("data", (chunk) => { response += chunk.toString(); });
    socket.on("end", () => {
      const headerEnd = response.indexOf("\r\n\r\n");
      if (headerEnd === -1) { reject(new Error("Invalid HTTP response")); return; }
      const statusLine = response.split("\r\n")[0];
      const statusCode = parseInt(statusLine.split(" ")[1] || "500");
      const jsonStr = response.slice(headerEnd + 4);
      try { resolve({ status: statusCode, data: JSON.parse(jsonStr) }); }
      catch { resolve({ status: statusCode, data: { error: jsonStr.slice(0, 200) } }); }
    });
    socket.on("timeout", () => { socket.destroy(); reject(new Error("Request timeout")); });
    socket.on("error", reject);
  });
}

/** Stream SSE from ai-core through to browser */
function rawStream(path: string, body: object): ReadableStream {
  const jsonBody = JSON.stringify(body);

  return new ReadableStream({
    start(controller) {
      const socket = new net.Socket();
      let headerParsed = false;
      let buffer = "";

      socket.setTimeout(90000);
      socket.connect(AI_CORE_PORT, AI_CORE_HOST, () => {
        const request = [
          `POST ${path} HTTP/1.1`,
          `Host: ${AI_CORE_HOST}:${AI_CORE_PORT}`,
          "Content-Type: application/json",
          `Content-Length: ${Buffer.byteLength(jsonBody)}`,
          "Accept: text/event-stream",
          "",
          jsonBody,
        ].join("\r\n");
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
          controller.enqueue(new TextEncoder().encode(buffer));
          buffer = "";
        }
      });

      socket.on("end", () => controller.close());
      socket.on("timeout", () => { socket.destroy(); controller.close(); });
      socket.on("error", () => controller.close());
    },
  });
}

export async function POST(req: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const body = await req.json();

  if (body.type === "tts") {
    const payload = { text: body.text, voice: body.voice, speed: body.speed || 1.0 };
    try {
      const result = await rawPost("/tts/preview", payload);
      if (result.status >= 400) return NextResponse.json({ error: "AI Core error" }, { status: result.status });
      return NextResponse.json(result.data);
    } catch (e) {
      return NextResponse.json({ error: `AI Core unreachable: ${e instanceof Error ? e.message : "Unknown"}` }, { status: 503 });
    }
  }

  // Chat — streaming or regular
  const payload = {
    character_id: body.characterId,
    text: body.text || "你好呀",
    history: body.history || [],
    with_audio: body.withAudio !== false,
  };

  if (body.stream) {
    const stream = rawStream("/chat/preview/stream", payload);
    return new Response(stream, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      },
    });
  }

  try {
    const result = await rawPost("/chat/preview", payload);
    if (result.status >= 400) return NextResponse.json({ error: "AI Core error" }, { status: result.status });
    return NextResponse.json(result.data);
  } catch (e) {
    return NextResponse.json({ error: `AI Core unreachable: ${e instanceof Error ? e.message : "Unknown"}` }, { status: 503 });
  }
}
