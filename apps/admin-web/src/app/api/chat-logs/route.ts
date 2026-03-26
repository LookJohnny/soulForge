import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

/**
 * Chat logs API — protected by middleware (dashboard auth).
 * Lists all conversations grouped by visitor.
 */
export async function GET(req: NextRequest) {
  const characterId = req.nextUrl.searchParams.get("character");
  const visitorId = req.nextUrl.searchParams.get("visitor");

  // Single conversation detail
  if (visitorId && characterId) {
    const messages = await prisma.chatMessage.findMany({
      where: { characterId, visitorId },
      orderBy: { createdAt: "asc" },
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
    return NextResponse.json({ messages });
  }

  // List all visitors with stats, optionally filtered by character
  const where = characterId ? { characterId } : {};

  const visitors = await prisma.$queryRawUnsafe<
    { visitor_id: string; character_id: string; character_name: string; msg_count: number; first_at: Date; last_at: Date }[]
  >(`
    SELECT
      cm.visitor_id,
      cm.character_id,
      c.name as character_name,
      COUNT(*)::int as msg_count,
      MIN(cm.created_at) as first_at,
      MAX(cm.created_at) as last_at
    FROM chat_messages cm
    JOIN characters c ON c.id = cm.character_id
    ${characterId ? `WHERE cm.character_id = '${characterId}'` : ""}
    GROUP BY cm.visitor_id, cm.character_id, c.name
    ORDER BY last_at DESC
    LIMIT 200
  `);

  return NextResponse.json({
    conversations: visitors.map((v) => ({
      visitorId: v.visitor_id,
      characterId: v.character_id,
      characterName: v.character_name,
      messageCount: v.msg_count,
      firstAt: v.first_at,
      lastAt: v.last_at,
    })),
  });
}
