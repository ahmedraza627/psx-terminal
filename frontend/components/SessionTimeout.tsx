"use client";

import { useEffect } from "react";

// ---------------------------------------------------------------------------
// SESSION TIMEOUT - 30-minute inactivity auto-logout.
//
// Mounted ONCE in the root layout, so it guards every route (console and
// login). It listens for real user activity, keeps the session epoch in
// sessionStorage (so each browser tab owns its own timer), and on expiry:
//
//   1. POSTs to /auth/signout - the route handler clears the Supabase auth
//      cookies server-side (supabase.auth.signOut()),
//   2. redirects to /login?reason=timeout.
//
// Why not call supabase.auth.signOut() directly from here? That would need
// the @supabase/ssr browser bundle (~70 kB) loaded for every visitor just
// for this feature. The route handler already does exactly that on the
// server - so the timeout costs ZERO bytes of vendor code.
//
// Hard boundaries (deliberate): document.visibilitychange, focus/blur and
// programmatic re-renders do NOT count as activity - a background tab or a
// sleeping laptop must still time out. The interval re-arms the idle timer
// at most once a minute; anything still inside the grace window re-extends.
// ---------------------------------------------------------------------------

const TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes
const EVENTS: (keyof DocumentEventMap)[] = [
  "mousemove",
  "mousedown",
  "keydown",
  "scroll",
  "touchstart",
  "wheel",
];

const EPOCH_KEY = "psx-desk:last-activity";

export default function SessionTimeout() {
  useEffect(() => {
    if (typeof window === "undefined") return;

    const now = () => Date.now();
    const epoch = () => {
      const stored = window.sessionStorage.getItem(EPOCH_KEY);
      return stored != null ? Number(stored) : null;
    };
    const mark = () => {
      window.sessionStorage.setItem(EPOCH_KEY, String(now()));
    };

    // A fresh page load counts as activity - but only when there is no
    // stored epoch yet (a reload inside an idle period must NOT reset it).
    if (epoch() == null) mark();

    let timer: number | null = null;

    const arm = () => {
      if (timer != null) window.clearTimeout(timer);
      const start = epoch() ?? now();
      const remaining = Math.max(0, TIMEOUT_MS - (now() - start));
      timer = window.setTimeout(onExpire, remaining);
    };

    const onExpire = () => {
      const start = epoch() ?? 0;
      // Real expiry only when the full window actually elapsed. Any activity
      // inside the window re-armed us; late-fired timers just re-arm.
      if (now() - start >= TIMEOUT_MS) {
        window.sessionStorage.removeItem(EPOCH_KEY);
        void fetch("/auth/signout", {
          method: "POST",
          keepalive: true,
          headers: { "psx-timeout": "1" },
        })
          .catch(() => undefined)
          .finally(() => {
            window.location.assign("/login?reason=timeout");
          });
        return;
      }
      arm();
    };

    // Throttled activity stamp: sessionStorage writes are synchronous, so
    // mousemove is capped at ~1 write/second instead of hundreds.
    let lastWrite = 0;
    const onActivity = () => {
      const t = now();
      if (t - lastWrite >= 1000) {
        lastWrite = t;
        mark();
        arm();
      }
    };
    EVENTS.forEach((e) =>
      document.addEventListener(e, onActivity, { passive: true }),
    );

    arm();
    return () => {
      if (timer != null) window.clearTimeout(timer);
      EVENTS.forEach((e) => document.removeEventListener(e, onActivity));
    };
  }, []);

  return null; // renders nothing - pure behavioral guard
}
