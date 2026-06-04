import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { getAiCoreServiceHeaders } from "@/lib/ai-core-admin";

const AI_CORE_URL = process.env.AI_CORE_URL || "http://127.0.0.1:8100";

type UserCandidate = {
  id: string;
  label: string | null;
  memoryCount: number;
  lastSeen: Date | null;
};

type MemoryRow = {
  id: string;
  userId: string;
  characterId: string | null;
  tableName: string;
  memoryType: string;
  content: string;
  sensitivityLevel: string;
  permissionLevel: string;
  conflictStatus: string;
  confidenceScore: number;
  retrievalWeight: number;
  canSurfaceDirectly: boolean;
  implicitOnly: boolean;
  requiresConfirmation: boolean;
  usageCount: number;
  lastUsedAt: Date | null;
  createdAt: Date;
  updatedAt: Date | null;
  enabled: boolean;
  relationAxis: string | null;
};

async function requireSession() {
  const session = await auth();
  if (!session?.user?.brandId) {
    return null;
  }
  return session;
}

async function aiCoreRequest(brandId: string, path: string, init: RequestInit = {}) {
  const headers = getAiCoreServiceHeaders(brandId, {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string> | undefined),
  });
  const resp = await fetch(`${AI_CORE_URL}${path}`, { ...init, headers });
  const text = await resp.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { error: text.slice(0, 300) };
  }
  if (!resp.ok) {
    return NextResponse.json(data, { status: resp.status });
  }
  return NextResponse.json(data);
}

async function assertCharacterInBrand(characterId: string | null, brandId: string) {
  if (!characterId) return true;
  const existing = await prisma.character.findUnique({
    where: { id: characterId, brandId },
    select: { id: true },
  });
  return Boolean(existing);
}

async function assertMemoryInBrand(memoryId: string, brandId: string) {
  const rows = await prisma.$queryRaw<{ id: string }[]>`
    WITH target AS (
      SELECT id, character_id FROM profile_memories WHERE id = ${memoryId}::uuid
      UNION ALL
      SELECT id, character_id FROM episodic_memories WHERE id = ${memoryId}::uuid
      UNION ALL
      SELECT id, character_id FROM semantic_memories WHERE id = ${memoryId}::uuid
      UNION ALL
      SELECT id, character_id FROM relational_memories WHERE id = ${memoryId}::uuid
      UNION ALL
      SELECT id, character_id FROM compiled_behavior_rules WHERE id = ${memoryId}::uuid
    )
    SELECT target.id::text AS id
    FROM target
    JOIN characters c ON c.id = target.character_id
    WHERE c.brand_id = ${brandId}::uuid
    LIMIT 1
  `;
  return rows.length > 0;
}

async function requireCharacterInBrand(characterId: string | null, brandId: string) {
  if (!characterId) return false;
  return assertCharacterInBrand(characterId, brandId);
}

export async function GET(req: NextRequest) {
  const session = await requireSession();
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const brandId = session.user.brandId;
  const userId = req.nextUrl.searchParams.get("userId");
  const characterId = req.nextUrl.searchParams.get("characterId");

  if (!(await assertCharacterInBrand(characterId, brandId))) {
    return NextResponse.json({ error: "Character not found" }, { status: 404 });
  }

  const characters = await prisma.character.findMany({
    where: { brandId },
    select: { id: true, name: true, status: true },
    orderBy: { createdAt: "desc" },
  });

  const users = await prisma.$queryRaw<UserCandidate[]>`
    WITH brand_chars AS (
      SELECT id FROM characters WHERE brand_id = ${brandId}::uuid
    ),
    refs AS (
      SELECT user_id, character_id, updated_at AS seen_at FROM profile_memories
      UNION ALL
      SELECT user_id, character_id, created_at AS seen_at FROM episodic_memories
      UNION ALL
      SELECT user_id, character_id, updated_at AS seen_at FROM semantic_memories
      UNION ALL
      SELECT user_id, character_id, updated_at AS seen_at FROM relational_memories
      UNION ALL
      SELECT user_id, character_id, updated_at AS seen_at FROM compiled_behavior_rules
      UNION ALL
      SELECT end_user_id AS user_id, character_id, updated_at AS seen_at FROM relationship_states
      UNION ALL
      SELECT end_user_id AS user_id, character_id, updated_at AS seen_at FROM user_customizations
      UNION ALL
      SELECT end_user_id AS user_id, character_id, updated_at AS seen_at
      FROM devices
      WHERE end_user_id IS NOT NULL AND character_id IS NOT NULL
    )
    SELECT
      eu.id::text AS id,
      COALESCE(eu.nickname, eu.open_id, eu.id::text) AS label,
      COUNT(*)::int AS "memoryCount",
      MAX(refs.seen_at) AS "lastSeen"
    FROM refs
    JOIN brand_chars bc ON bc.id = refs.character_id
    JOIN end_users eu ON eu.id = refs.user_id
    GROUP BY eu.id, eu.nickname, eu.open_id
    ORDER BY MAX(refs.seen_at) DESC NULLS LAST
    LIMIT 100
  `;

  let memories: MemoryRow[] = [];
  if (userId && characterId) {
    memories = await prisma.$queryRaw<MemoryRow[]>`
      WITH selected AS (
        SELECT ${userId}::uuid AS user_id, ${characterId}::uuid AS character_id
      ),
      unioned AS (
        SELECT
          profile_memories.id,
          profile_memories.user_id,
          profile_memories.character_id,
          'profile_memories'::text AS table_name,
          profile_memories.memory_type::text,
          profile_memories.content,
          profile_memories.sensitivity_level::text,
          profile_memories.permission_level::text,
          profile_memories.conflict_status::text,
          profile_memories.confidence_score,
          profile_memories.retrieval_weight,
          profile_memories.can_surface_directly,
          profile_memories.implicit_only,
          profile_memories.requires_confirmation,
          profile_memories.usage_count,
          profile_memories.last_used_at,
          profile_memories.created_at,
          profile_memories.updated_at,
          true AS enabled,
          NULL::text AS relation_axis
        FROM profile_memories, selected
        WHERE profile_memories.user_id = selected.user_id
          AND deleted_at IS NULL
          AND profile_memories.character_id = selected.character_id

        UNION ALL
        SELECT
          episodic_memories.id,
          episodic_memories.user_id,
          episodic_memories.character_id,
          'episodic_memories'::text AS table_name,
          episodic_memories.memory_type::text,
          episodic_memories.content,
          episodic_memories.sensitivity_level::text,
          episodic_memories.permission_level::text,
          episodic_memories.conflict_status::text,
          episodic_memories.confidence_score,
          episodic_memories.retrieval_weight,
          episodic_memories.can_surface_directly,
          episodic_memories.implicit_only,
          episodic_memories.requires_confirmation,
          episodic_memories.usage_count,
          episodic_memories.last_used_at,
          episodic_memories.created_at,
          episodic_memories.created_at AS updated_at,
          true AS enabled,
          NULL::text AS relation_axis
        FROM episodic_memories, selected
        WHERE episodic_memories.user_id = selected.user_id
          AND deleted_at IS NULL
          AND episodic_memories.character_id = selected.character_id

        UNION ALL
        SELECT
          semantic_memories.id,
          semantic_memories.user_id,
          semantic_memories.character_id,
          'semantic_memories'::text AS table_name,
          semantic_memories.memory_type::text,
          semantic_memories.content,
          semantic_memories.sensitivity_level::text,
          semantic_memories.permission_level::text,
          semantic_memories.conflict_status::text,
          semantic_memories.confidence_score,
          semantic_memories.retrieval_weight,
          semantic_memories.can_surface_directly,
          semantic_memories.implicit_only,
          semantic_memories.requires_confirmation,
          semantic_memories.usage_count,
          semantic_memories.last_used_at,
          semantic_memories.created_at,
          semantic_memories.updated_at,
          true AS enabled,
          NULL::text AS relation_axis
        FROM semantic_memories, selected
        WHERE semantic_memories.user_id = selected.user_id
          AND deleted_at IS NULL
          AND semantic_memories.character_id = selected.character_id

        UNION ALL
        SELECT
          relational_memories.id,
          relational_memories.user_id,
          relational_memories.character_id,
          'relational_memories'::text AS table_name,
          relational_memories.memory_type::text,
          relational_memories.content,
          relational_memories.sensitivity_level::text,
          relational_memories.permission_level::text,
          relational_memories.conflict_status::text,
          relational_memories.confidence_score,
          relational_memories.retrieval_weight,
          relational_memories.can_surface_directly,
          relational_memories.implicit_only,
          relational_memories.requires_confirmation,
          relational_memories.usage_count,
          relational_memories.last_used_at,
          relational_memories.created_at,
          relational_memories.updated_at,
          true AS enabled,
          relational_memories.relation_axis
        FROM relational_memories, selected
        WHERE relational_memories.user_id = selected.user_id
          AND deleted_at IS NULL
          AND relational_memories.character_id = selected.character_id

        UNION ALL
        SELECT
          compiled_behavior_rules.id,
          compiled_behavior_rules.user_id,
          compiled_behavior_rules.character_id,
          'compiled_behavior_rules'::text AS table_name,
          compiled_behavior_rules.memory_type::text,
          compiled_behavior_rules.content,
          compiled_behavior_rules.sensitivity_level::text,
          compiled_behavior_rules.permission_level::text,
          compiled_behavior_rules.conflict_status::text,
          compiled_behavior_rules.confidence_score,
          compiled_behavior_rules.retrieval_weight,
          compiled_behavior_rules.can_surface_directly,
          compiled_behavior_rules.implicit_only,
          compiled_behavior_rules.requires_confirmation,
          compiled_behavior_rules.usage_count,
          compiled_behavior_rules.last_used_at,
          compiled_behavior_rules.created_at,
          compiled_behavior_rules.updated_at,
          compiled_behavior_rules.enabled,
          compiled_behavior_rules.rule_type AS relation_axis
        FROM compiled_behavior_rules, selected
        WHERE compiled_behavior_rules.user_id = selected.user_id
          AND enabled = true
          AND compiled_behavior_rules.character_id = selected.character_id
      )
      SELECT
        id::text,
        user_id::text AS "userId",
        character_id::text AS "characterId",
        table_name AS "tableName",
        memory_type AS "memoryType",
        content,
        sensitivity_level AS "sensitivityLevel",
        permission_level AS "permissionLevel",
        conflict_status AS "conflictStatus",
        confidence_score AS "confidenceScore",
        retrieval_weight AS "retrievalWeight",
        can_surface_directly AS "canSurfaceDirectly",
        implicit_only AS "implicitOnly",
        requires_confirmation AS "requiresConfirmation",
        usage_count AS "usageCount",
        last_used_at AS "lastUsedAt",
        created_at AS "createdAt",
        updated_at AS "updatedAt",
        enabled,
        relation_axis AS "relationAxis"
      FROM unioned
      ORDER BY retrieval_weight DESC, confidence_score DESC, updated_at DESC
      LIMIT 200
    `;
  }

  return NextResponse.json({ characters, users, memories });
}

export async function POST(req: NextRequest) {
  const session = await requireSession();
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const body = await req.json();
  const operation = body.operation || "create";
  const characterId = body.character_id || body.characterId || null;

  if (operation === "feedback") {
    if (!body.memory_id || !(await assertMemoryInBrand(body.memory_id, session.user.brandId))) {
      return NextResponse.json({ error: "Memory not found" }, { status: 404 });
    }
  } else if (!(await requireCharacterInBrand(characterId, session.user.brandId))) {
    return NextResponse.json({ error: "Character not found" }, { status: 404 });
  }

  if (operation === "compile") {
    return aiCoreRequest(session.user.brandId, "/memory/compile", {
      method: "POST",
      body: JSON.stringify({
        user_id: body.user_id,
        character_id: body.character_id,
        trigger: "admin_dashboard",
      }),
    });
  }

  if (operation === "feedback") {
    return aiCoreRequest(session.user.brandId, "/memory/feedback", {
      method: "POST",
      body: JSON.stringify({
        memory_id: body.memory_id,
        feedback: body.feedback,
        comment: body.comment,
      }),
    });
  }

  if (operation === "retrieve") {
    return aiCoreRequest(session.user.brandId, "/memory/retrieve", {
      method: "POST",
      body: JSON.stringify({
        user_id: body.user_id,
        character_id: body.character_id,
        query: body.query || "",
        context: body.context || {},
        limit: body.limit || 10,
      }),
    });
  }

  return aiCoreRequest(session.user.brandId, "/memory", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function PATCH(req: NextRequest) {
  const session = await requireSession();
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const memoryId = req.nextUrl.searchParams.get("memoryId");
  if (!memoryId) {
    return NextResponse.json({ error: "memoryId is required" }, { status: 400 });
  }
  if (!(await assertMemoryInBrand(memoryId, session.user.brandId))) {
    return NextResponse.json({ error: "Memory not found" }, { status: 404 });
  }
  return aiCoreRequest(session.user.brandId, `/memory/${memoryId}`, {
    method: "PATCH",
    body: JSON.stringify(await req.json()),
  });
}

export async function DELETE(req: NextRequest) {
  const session = await requireSession();
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const memoryId = req.nextUrl.searchParams.get("memoryId");
  if (!memoryId) {
    return NextResponse.json({ error: "memoryId is required" }, { status: 400 });
  }
  if (!(await assertMemoryInBrand(memoryId, session.user.brandId))) {
    return NextResponse.json({ error: "Memory not found" }, { status: 404 });
  }
  return aiCoreRequest(
    session.user.brandId,
    `/memory/${memoryId}?cascade_compiled_rules=true`,
    { method: "DELETE" }
  );
}
