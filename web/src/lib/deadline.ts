import { parseISODate } from "./format";

export type Urgency = "urgent" | "soon" | "normal";

/** Whole days from today to the deadline. Both ends are normalised to local
 *  midnight so a call due later today reads as 0, not -1. */
export function daysUntil(iso: string, now: Date = new Date()): number | null {
  const target = parseISODate(iso);
  if (!target) return null;
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((target.getTime() - today.getTime()) / 86_400_000);
}

/** Design rule: <=14 days urgent, <=45 days soon, else default text colour. */
export function urgency(days: number | null): Urgency {
  if (days === null) return "normal";
  if (days <= 14) return "urgent";
  if (days <= 45) return "soon";
  return "normal";
}

export function remainingLabel(days: number): string {
  if (days < 0) return "termen depășit";
  if (days === 0) return "azi";
  if (days === 1) return "mâine";
  return `peste ${days} zile`;
}
