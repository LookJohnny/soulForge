import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
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

export async function GET() {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const packs = await prisma.soulPack.findMany({
    where: { brandId: session.user.brandId },
    orderBy: { createdAt: "desc" },
  });
  return NextResponse.json(packs);
}

export async function POST(req: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const body = await req.json();
  const action = body.action;

  if (action === "export") {
    try {
      const result = await rawPost("/soul-packs/export", {
        character_id: body.characterId,
        brand_id: session.user.brandId,
      });
      if (result.status >= 400) {
        return NextResponse.json({ error: "Export failed" }, { status: result.status });
      }
      return NextResponse.json(result.data);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      return NextResponse.json({ error: `AI Core unreachable: ${msg}` }, { status: 503 });
    }
  }

  if (action === "import") {
    try {
      const result = await rawPost("/soul-packs/import", {
        brand_id: session.user.brandId,
        soulpack_b64: body.soulpackB64,
      });
      if (result.status >= 400) {
        return NextResponse.json({ error: "Import failed" }, { status: result.status });
      }
      return NextResponse.json(result.data);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      return NextResponse.json({ error: `AI Core unreachable: ${msg}` }, { status: 503 });
    }
  }

  return NextResponse.json({ error: "Invalid action" }, { status: 400 });
}
