import type { NextConfig } from "next";
import path from "node:path";
import { fileURLToPath } from "node:url";

const appDir = path.dirname(fileURLToPath(import.meta.url));

function collectAllowedDevOrigins() {
  const hosts = new Set(["localhost", "127.0.0.1"]);

  const nextAuthUrl = process.env.NEXTAUTH_URL;
  if (nextAuthUrl) {
    try {
      const url = new URL(nextAuthUrl);
      if (url.hostname) hosts.add(url.hostname);
    } catch {
      // Ignore malformed env here; auth/runtime code will surface it separately.
    }
  }

  return [...hosts];
}

const nextConfig: NextConfig = {
  output: "standalone",
  allowedDevOrigins: collectAllowedDevOrigins(),
  turbopack: {
    root: path.resolve(appDir, "../.."),
  },
};

export default nextConfig;
