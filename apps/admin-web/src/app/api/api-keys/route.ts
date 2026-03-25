import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import crypto from "node:crypto";

function generateApiKey(): { raw: string; prefix: string; hash: string } {
  const raw = `sk-${crypto.randomBytes(32).toString("hex").slice(0, 37)}`;
  const prefix = raw.slice(0, 10);
  const hash = crypto.createHash("sha256").update(raw).digest("hex");
  return { raw, prefix, hash };
}

export async function GET() {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const keys = await prisma.apiKey.findMany({
    where: { brandId: session.user.brandId },
    orderBy: { createdAt: "desc" },
    select: {
      id: true,
      name: true,
      prefix: true,
      lastUsedAt: true,
      expiresAt: true,
      revoked: true,
      createdAt: true,
    },
  });
  return NextResponse.json(keys);
}

export async function POST(req: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const body = await req.json();
  const name = body.name || "Untitled Key";

  const { raw, prefix, hash } = generateApiKey();

  await prisma.apiKey.create({
    data: {
      brandId: session.user.brandId,
      name,
      prefix,
      hashedKey: hash,
    },
  });

  // Return the raw key ONLY on creation (never stored)
  return NextResponse.json({ key: raw, prefix }, { status: 201 });
}

export async function DELETE(req: NextRequest) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { id } = await req.json();

  const key = await prisma.apiKey.findFirst({
    where: { id, brandId: session.user.brandId },
  });
  if (!key) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  await prisma.apiKey.update({
    where: { id },
    data: { revoked: true },
  });

  return NextResponse.json({ ok: true });
}
