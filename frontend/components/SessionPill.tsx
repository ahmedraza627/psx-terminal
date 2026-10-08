/**
 * Session date pill - the latest certified pipeline session, or an honest
 * "no session" state. Pure server component.
 */
export default function SessionPill({ session }: { session: string | null }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1 text-[12px] font-medium text-slate-700 shadow-sm">
      <span className="h-1.5 w-1.5 rounded-full bg-blue-600" />
      {session != null ? `Session ${session}` : "No certified session"}
    </span>
  );
}
