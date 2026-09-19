import { createClient } from "@/lib/supabase/server";
import { NextResponse, type NextRequest } from "next/server";

/**
 * POST/GET /auth/signout - clears the auth session cookies and redirects to
 * the login screen. /auth is public in the middleware, which is fine: an
 * unauthenticated call has no session to clear.
 *
 * returnTo is allowlisted to exactly two safe targets: "/" (header button)
 * and "/login?reason=timeout" (the SessionTimeout component's expire path).
 * Anything else falls back to "/login" - no open-redirect surface.
 */
export async function GET(request: NextRequest) {
  const supabase = createClient();
  await supabase.auth.signOut();

  const returnTo = request.nextUrl.searchParams.get("returnTo") ?? "";
  const target =
    returnTo === "/" || returnTo === "/login?reason=timeout"
      ? returnTo
      : "/login";

  return NextResponse.redirect(new URL(target, request.url));
}

export const POST = GET;
