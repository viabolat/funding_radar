import type { Call, Status, TriageMap } from "../types";
import { defaultTriage } from "../types";

export type FilterKey = "inbox" | "relevant" | "applied";

export const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "inbox", label: "Primite" },
  { key: "relevant", label: "Relevant" },
  { key: "applied", label: "Depus" },
];

export function statusOf(call: Call, triage: TriageMap): Status {
  return triage[call.call_id]?.status ?? defaultTriage(call).status;
}

function isSnoozed(call: Call, triage: TriageMap): boolean {
  return triage[call.call_id]?.snoozed ?? false;
}

/** "Primite" is the working queue: anything untouched or still needing a look.
 *  Marking a call Nerelevant or snoozing it drops it out of that queue — it
 *  stays reachable under its own filter, it just stops being in the way. */
export function matchesFilter(call: Call, triage: TriageMap, filter: FilterKey): boolean {
  const status = statusOf(call, triage);
  switch (filter) {
    case "inbox":
      return (status === "new" || status === "review") && !isSnoozed(call, triage);
    case "relevant":
      return status === "relevant";
    case "applied":
      return status === "applied";
  }
}

export function matchesQuery(call: Call, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [call.title, call.programme, call.match_reason, ...call.tags]
    .join(" ")
    .toLowerCase()
    .includes(needle);
}

export function selectCalls(
  calls: Call[],
  triage: TriageMap,
  filter: FilterKey,
  query: string,
): Call[] {
  return calls.filter((call) => matchesFilter(call, triage, filter) && matchesQuery(call, query));
}

export function filterCounts(calls: Call[], triage: TriageMap): Record<FilterKey, number> {
  return {
    inbox: calls.filter((c) => matchesFilter(c, triage, "inbox")).length,
    relevant: calls.filter((c) => matchesFilter(c, triage, "relevant")).length,
    applied: calls.filter((c) => matchesFilter(c, triage, "applied")).length,
  };
}
