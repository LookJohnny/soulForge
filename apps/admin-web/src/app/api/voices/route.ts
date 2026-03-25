import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { voiceCreateSchema } from "@/lib/validations/voice";
import { ZodError } from "zod";

// Voice profiles are a global shared library — all brands can read,
// only admin role can create. This is by design: voices are platform
// assets, not brand-specific content.

export async function GET() {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const voices = await prisma.voiceProfile.findMany({
    orderBy: { createdAt: "desc" },
  });
  return NextResponse.json(voices);
}

export async function POST(req: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  // Only admin can create voice profiles (they're shared platform assets)
  if (session.user.role !== "ADMIN") {
    return NextResponse.json({ error: "Only admins can create voice profiles" }, { status: 403 });
  }

  let body;
  try {
    body = voiceCreateSchema.parse(await req.json());
  } catch (e) {
    if (e instanceof ZodError) {
      return NextResponse.json({ error: "Validation failed", details: e.errors }, { status: 400 });
    }
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const voice = await prisma.voiceProfile.create({
    data: {
      name: body.name,
      referenceAudio: body.referenceAudio || "",
      description: body.description ?? null,
      tags: body.tags || [],
      dashscopeVoiceId: body.dashscopeVoiceId ?? null,
    },
  });

  return NextResponse.json({ id: voice.id }, { status: 201 });
}
