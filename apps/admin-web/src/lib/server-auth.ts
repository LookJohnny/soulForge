import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";

/**
 * Get the authenticated user's brandId for server components.
 * Redirects to /login if not authenticated.
 */
export async function requireBrandId(): Promise<string> {
  const session = await auth();
  if (!session?.user?.brandId) {
    redirect("/login");
  }
  return session.user.brandId;
}
