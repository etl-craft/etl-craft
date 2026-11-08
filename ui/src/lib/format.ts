/** Times always show their zone. */
export function formatTime(iso: string | null, timeZone: string): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone,
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZoneName: "short",
  }).format(new Date(iso));
}

export function formatDuration(start: string | null, end: string | null, now = Date.now()): string {
  if (!start) return "—";
  return formatSeconds(((end ? new Date(end).getTime() : now) - new Date(start).getTime()) / 1000);
}

/** The run id in a run's address or search: the integer itself, or the integer ending a readable label such as SALES-2026-11-07 11:47:50-9. */
export function runIdOf(value: string | null | undefined): number | undefined {
  const text = (value ?? "").trim();
  if (/^\d+$/.test(text)) return Number(text);
  const label = /^.+-\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}-(\d+)$/.exec(text);
  return label ? Number(label[1]) : undefined;
}

/** A length of time the way every duration is written: 45s, 2m 06s, 1h 05m. */
export function formatSeconds(value: number): string {
  const seconds = Math.max(0, Math.round(value));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${String(seconds % 60).padStart(2, "0")}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${String(minutes % 60).padStart(2, "0")}m`;
}

export function formatAgo(iso: string | null, now = Date.now()): string {
  if (!iso) return "—";
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export const seconds = (value: number | null): string => (value === null ? "None" : `${value.toFixed(1)} s`);
export const percent = (value: number | null): string => (value === null ? "No finished runs" : `${Math.round(value * 100)}%`);
export const measured = (value: number | null): string => (value === null ? "Not measured" : value.toLocaleString("en-GB"));

const hours = (field: string): Set<number> | null => {
  const found = new Set<number>();
  for (const part of field.split(",")) {
    const range = /^(\d{1,2})(?:-(\d{1,2}))?$/.exec(part);
    if (!range) return null;
    const from = Number(range[1]);
    const to = range[2] === undefined ? from : Number(range[2]);
    if (from > 23 || to > 23 || to < from) return null;
    for (let h = from; h <= to; h++) found.add(h);
  }
  return found;
};

const two = (n: number) => String(n).padStart(2, "0");

/** A schedule in words for the common cron shapes, or null: the expression itself is then the only honest description. */
export function describeCron(expression: string | null): string | null {
  const parts = expression?.trim().split(/\s+/) ?? [];
  if (parts.length !== 5) return null;
  const [minute, hour, day, month, weekday] = parts as [string, string, string, string, string];
  if (day !== "*" || month !== "*" || weekday !== "*") return null;
  const every = /^\*\/(\d+)$/.exec(minute);
  if (every && hour === "*") return `Every ${every[1]} minutes`;
  if (every) {
    const on = hours(hour);
    if (!on) return null;
    const off = [...Array(24).keys()].filter((h) => !on.has(h));
    if (off.length === 0) return `Every ${every[1]} minutes`;
    return off.length <= 4 ? `Every ${every[1]} minutes, except hour${off.length === 1 ? "" : "s"} ${off.map(two).join(", ")}` : `Every ${every[1]} minutes during hours ${[...on].map(two).join(", ")}`;
  }
  if (/^\d+$/.test(minute)) {
    if (hour === "*") return minute === "0" ? "Every hour" : `Every hour at minute ${minute}`;
    const step = /^\*\/(\d+)$/.exec(hour);
    if (step) return `Every ${step[1]} hours${minute === "0" ? "" : ` at minute ${minute}`}`;
    if (/^\d{1,2}$/.test(hour)) return `Daily at ${two(Number(hour))}:${two(Number(minute))}`;
  }
  return null;
}

/** How far a time is from now, as "in 2 h" or "3 min ago": the exact time stays in a tooltip. */
export function relative(iso: string | null, now: number): string {
  if (!iso) return "—";
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000);
  const abs = Math.abs(seconds);
  const [n, unit] = abs < 60 ? [abs, "s"] : abs < 3600 ? [Math.round(abs / 60), "min"] : abs < 86_400 ? [Math.round(abs / 3600), "h"] : [Math.round(abs / 86_400), "d"];
  return seconds >= 0 ? `in ${n} ${unit}` : `${n} ${unit} ago`;
}
