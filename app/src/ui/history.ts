/**
 * Recently viewed entries.
 *
 * Kept in local storage, newest first, capped so it cannot grow without
 * bound. Reads and writes are wrapped: a page in a sandboxed frame can throw
 * on localStorage rather than return nothing, and a lost history is not worth
 * a blank page.
 */

const KEY = "am-history";
const LIMIT = 40;

export type Visit = {
  id: number;
  headword: string;
  at: number;
};

export function load(): Visit[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((visit): visit is Visit =>
      visit !== null &&
      typeof visit === "object" &&
      typeof visit.id === "number" &&
      typeof visit.headword === "string");
  } catch {
    return [];
  }
}

function store(visits: Visit[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(visits));
  } catch {
    /* Nothing worth failing a page load over. */
  }
}

/** Record a visit, moving a repeat to the front rather than duplicating it. */
export function record(id: number, headword: string): Visit[] {
  const visits = load().filter((visit) => visit.id !== id);
  visits.unshift({ id, headword, at: Date.now() });
  const trimmed = visits.slice(0, LIMIT);
  store(trimmed);
  return trimmed;
}

export function clear(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* As above. */
  }
}

/** "just now", "14 minutes ago", "3 days ago". */
export function when(at: number, now = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - at) / 1000));
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} day${days === 1 ? "" : "s"} ago`;
  const months = Math.round(days / 30);
  return `${months} month${months === 1 ? "" : "s"} ago`;
}
