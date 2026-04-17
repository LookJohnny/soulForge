import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { invalidateCharacterCache } from "@/lib/ai-core-admin";
import { prisma } from "@/lib/prisma";
import { characterUpdateSchema } from "@/lib/validations/character";
import { ZodError } from "zod";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { id } = await params;
  const character = await prisma.character.findUnique({
    where: { id, brandId: session.user.brandId },
    include: { voice: true },
  });

  if (!character) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  return NextResponse.json(character);
}

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { id } = await params;

  let body;
  try {
    body = characterUpdateSchema.parse(await req.json());
  } catch (e) {
    if (e instanceof ZodError) {
      return NextResponse.json({ error: "Validation failed", details: e.errors }, { status: 400 });
    }
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  // Ensure the character belongs to this brand
  const existing = await prisma.character.findUnique({
    where: { id, brandId: session.user.brandId },
  });
  if (!existing) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const { voiceId, ...rest } = body;
  // Strip undefined values, convert null to Prisma's set-null format
  const data: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(rest)) {
    if (value !== undefined) {
      data[key] = value;
    }
  }
  if (voiceId !== undefined) {
    data.voice = voiceId ? { connect: { id: voiceId } } : { disconnect: true };
  }
  const character = await prisma.character.update({
    where: { id },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    data: data as any,
  });
  // Best-effort cache bust. See invalidateCharacterCache docstring for why
  // this is non-fatal: the DB is authoritative, the cache will expire on TTL.
  const cacheCleared = await invalidateCharacterCache(session.user.brandId, id);

  return NextResponse.json({ ...character, _cacheCleared: cacheCleared });
}

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { id } = await params;

  const existing = await prisma.character.findUnique({
    where: { id, brandId: session.user.brandId },
  });
  if (!existing) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  await prisma.character.delete({ where: { id } });
  const cacheCleared = await invalidateCharacterCache(session.user.brandId, id);
  return NextResponse.json({ ok: true, _cacheCleared: cacheCleared });
}
