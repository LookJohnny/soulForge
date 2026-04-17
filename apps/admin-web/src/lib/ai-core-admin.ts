const AI_CORE_URL = process.env.AI_CORE_URL || "http://127.0.0.1:8100";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

function buildAiCoreServiceHeaders(brandId: string, extra?: Record<string, string>) {
  if (!SERVICE_TOKEN) {
    throw new Error("SERVICE_TOKEN is not configured");
  }

  return {
    "X-Service-Token": SERVICE_TOKEN,
    "X-Brand-Id": brandId,
    ...extra,
  };
}

export function getAiCoreServiceHeaders(brandId: string, extra?: Record<string, string>) {
  return buildAiCoreServiceHeaders(brandId, extra);
}

export async function invalidateCharacterCache(brandId: string, characterId: string) {
  let lastError: Error | null = null;

  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const resp = await fetch(`${AI_CORE_URL}/internal/cache/character/invalidate`, {
        method: "POST",
        headers: buildAiCoreServiceHeaders(brandId, {
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({ character_id: characterId }),
      });

      if (!resp.ok) {
        const err = await resp.text();
        throw new Error(`AI Core cache invalidation failed (${resp.status}): ${err.slice(0, 200)}`);
      }
      return;
    } catch (error) {
      lastError = error instanceof Error ? error : new Error("Unknown AI Core cache invalidation error");
    }
  }

  throw lastError ?? new Error("AI Core cache invalidation failed");
}
