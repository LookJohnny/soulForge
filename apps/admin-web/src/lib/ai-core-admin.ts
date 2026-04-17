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

/**
 * Invalidate the AI Core character cache. Returns `true` on success.
 *
 * **Non-fatal by design.** Callers invoke this AFTER the authoritative
 * DB write has committed. If the invalidation fails (AI Core down, network
 * blip, service token misconfigured) the DB is still correct; the cache
 * will naturally expire on its TTL. We don't want to surface a 500 to the
 * user when the state they actually care about is already saved — that
 * produces the "retry + duplicate write" failure mode.
 *
 * Failures are logged so ops can still see them. The caller may optionally
 * forward the stale-cache warning to the client.
 */
export async function invalidateCharacterCache(
  brandId: string,
  characterId: string
): Promise<boolean> {
  let lastError: unknown = null;

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
        throw new Error(`HTTP ${resp.status}: ${err.slice(0, 200)}`);
      }
      return true;
    } catch (error) {
      lastError = error;
    }
  }

  console.warn(
    "[ai-core-admin] character cache invalidation failed (DB write already committed, cache will expire on TTL)",
    { brandId, characterId, error: lastError }
  );
  return false;
}
