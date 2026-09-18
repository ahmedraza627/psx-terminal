import { signIn } from "./actions";

/**
 * /login - pure server component, zero client JS. The plain HTML form
 * posts to the signIn server action; on success the middleware sees the
 * session cookies and the console unlocks. No self-signup: operators are
 * created in the Supabase dashboard (Authentication > Users > Add user).
 *
 * The error surface is intentionally generic: any failed attempt renders
 * the same line, never revealing whether the email or password was wrong.
 */
export const metadata = { title: "PSX·DESK — Sign in" };

export default function LoginPage({
  searchParams,
}: {
  searchParams: { e?: string };
}) {
  const failed = searchParams.e != null;

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-sm flex-col items-center justify-center bg-obsidian px-4 text-ink">
      <h1 className="font-mono text-[15px] font-bold tracking-[0.22em]">
        PSX<span className="text-info">·</span>DESK
      </h1>
      <p className="mt-1 mb-6 font-mono text-[9px] uppercase tracking-[0.2em] text-ghost">
        Private institutional terminal · authorized access only
      </p>

      <form action={signIn} className="w-full space-y-3">
        <label className="block">
          <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-ghost">
            Email
          </span>
          <input
            type="email"
            name="email"
            required
            autoComplete="email"
            className="mt-1 w-full border border-hairline bg-panel px-2.5 py-2 font-mono text-[12px] text-ink outline-none focus:border-info"
            placeholder="operator@desk.pk"
          />
        </label>
        <label className="block">
          <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-ghost">
            Password
          </span>
          <input
            type="password"
 name="password"
            required
            autoComplete="current-password"
            className="w-full border border-hairline bg-panel px-2.5 py-2 font-mono text-[12px] text-ink outline-none focus:border-info"
            placeholder="••••••••••••"
          />
        </label>

        {failed && (
          <p className="border border-bear/40 bg-bear/10 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wider text-bear">
            AUTHENTICATION FAILED - CHECK CREDENTIALS
          </p>
        )}

        <button
          type="submit"
          className="w-full border border-info/50 bg-info/15 px-2.5 py-2 font-mono text-[11px] font-bold uppercase tracking-[0.2em] text-info hover:bg-info/25"
        >
          Enter Terminal
        </button>
      </form>
    </main>
  );
}
