"use server";

import { createClient } from "@/lib/supabase/server";
import { redirect } from "next/navigation";

/**
 * Server-action sign-in: authenticates with the cookie-bound server
 * client, which sets the auth cookies server-side. ZERO client JS for
 * the login screen - the form posts straight to this action.
 */
export async function signIn(formData: FormData) {
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");

  if (email === "" || password === "") {
    redirect("/login?e=empty");
  }

  const supabase = createClient();
  const { error } = await supabase.auth.signInWithPassword({
    email,
    password,
  });

  if (error) {
    // Single generic code - never echo which field was wrong.
    redirect("/login?e=1");
  }

  redirect("/");
}
