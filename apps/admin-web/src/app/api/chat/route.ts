import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

/**
 * Public API — list all published characters for mobile chat selection.
 * No auth required.
 */
export async function GET() {
  const characters = await prisma.character.findMany({
    where: { status: "PUBLISHED" },
    select: {
      id: true,
      name: true,
      species: true,
      archetype: true,
      backstory: true,
      avatar: true,
    },
    orderBy: { createdAt: "desc" },
  });

  return NextResponse.json(characters);
}
