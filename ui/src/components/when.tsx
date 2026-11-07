import { useIdentity, useTimezone } from "@/hooks";
import { formatTime, relative } from "@/lib/format";

/** A moment shown as the account's "Time display" setting says: relative with the exact time on hover, or the exact time. */
export function When({ iso, now }: { iso: string; now: number }) {
  const tz = useTimezone();
  const relativeFirst = useIdentity().data?.settings.time_display !== "absolute";
  const exact = formatTime(iso, tz);
  return <span title={relativeFirst ? exact : relative(iso, now)}>{relativeFirst ? relative(iso, now) : exact}</span>;
}
