const MONTHS_SHORT = [
  "ian.", "feb.", "mar.", "apr.", "mai", "iun.",
  "iul.", "aug.", "sep.", "oct.", "nov.", "dec.",
];
const MONTHS_LONG = [
  "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
  "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie",
];

/** Parses an ISO date as local midnight. `new Date("2026-04-16")` parses as
 *  UTC, which shifts the day backwards west of Greenwich and would show a
 *  deadline as one day nearer than it is. */
export function parseISODate(iso: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return null;
  const [, y, m, d] = match;
  return new Date(Number(y), Number(m) - 1, Number(d));
}

export function formatShort(iso: string): string {
  const date = parseISODate(iso);
  if (!date) return iso;
  return `${date.getDate()} ${MONTHS_SHORT[date.getMonth()]}`;
}

export function formatLong(iso: string): string {
  const date = parseISODate(iso);
  if (!date) return iso;
  return `${date.getDate()} ${MONTHS_LONG[date.getMonth()]} ${date.getFullYear()}`;
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join("");
}
