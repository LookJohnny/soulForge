import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { characterCreateSchema } from "@/lib/validations/character";
import { ZodError } from "zod";

export async function GET() {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const characters = await prisma.character.findMany({
    where: { brandId: session.user.brandId },
    orderBy: { createdAt: "desc" },
    include: { voice: true },
  });
  return NextResponse.json(characters);
}

export async function POST(req: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  let body;
  try {
    body = characterCreateSchema.parse(await req.json());
  } catch (e) {
    if (e instanceof ZodError) {
      return NextResponse.json({ error: "Validation failed", details: e.errors }, { status: 400 });
    }
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  try {
    const character = await prisma.character.create({
      data: {
        brandId: session.user.brandId,
        name: body.name,
        archetype: body.archetype || "ANIMAL",
        species: body.species ?? null,
        ageSetting: body.ageSetting ?? null,
        backstory: body.backstory ?? null,
        relationship: body.relationship ?? null,
        personality: body.personality || {},
        catchphrases: body.catchphrases || [],
        suffix: body.suffix ?? null,
        topics: body.topics || [],
        forbidden: body.forbidden || [],
        responseLength: body.responseLength || "SHORT",
        voiceId: body.voiceId ?? null,
        voiceSpeed: body.voiceSpeed || 1.0,
        llmProvider: body.llmProvider ?? null,
        llmModel: body.llmModel ?? null,
        ttsProvider: body.ttsProvider ?? null,
        status: "DRAFT",
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
      } as any,
    });
    return NextResponse.json({ id: character.id }, { status: 201 });
  } catch (e) {
    console.error("Character create DB error:", e);
    return NextResponse.json({ error: "角色创建失败，请检查输入后重试" }, { status: 500 });
  }
}
