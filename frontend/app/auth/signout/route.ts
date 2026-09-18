import { createClient } from "@/lib/supabase/server";
import { NextResponse, type NextRequest } from "next/server";

/**
 * POST/GET /auth/signout - clears the auth session cookies and lands on
 * the login screen. The /auth prefix is public in the middleware, which
 * is fine: an unauthenticated call has no session to clear.
 */
export async function GET(request: NextRequest) {
  const supabase = createClient();
  await supabase.auth.signOut();
  return NextResponse.redirect(new URL("/login", request.url));
}

export const POST = GET;
