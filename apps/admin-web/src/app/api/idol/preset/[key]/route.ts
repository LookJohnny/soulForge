import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";

const AI_CORE_URL = process.env.AI_CORE_URL || "http://localhost:8100";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ key: string }> }
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { key } = await params;

  try {
    const res = await fetch(`${AI_CORE_URL}/idol/presets/${key}`, {
      headers: {
        "Content-Type": "application/json",
        "X-Service-Token": SERVICE_TOKEN,
      },
    });

    if (!res.ok) {
      const body = await res.text();
      console.error(`AI Core /idol/presets/${key} returned ${res.status}:`, body);
      return NextResponse.json(
        { error: `Preset '${key}' not found` },
        { status: res.status }
      );
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (e) {
    console.error("Failed to fetch idol preset from AI Core:", e);
    return NextResponse.json(
      { error: "AI Core service unavailable" },
      { status: 502 }
    );
  }
}
