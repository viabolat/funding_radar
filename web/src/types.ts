/** Mirrors the record shape written by calls_store.py. Keep in sync with
 *  FEED_VERSION: if the Python side bumps it, this file changed too. */
export const SUPPORTED_FEED_VERSION = 1;

export type Source = "eu_sedia" | "adieuronest" | "mipe";

export interface Call {
  call_id: string;
  source: Source;
  title: string;
  programme: string;
  deadline: string | null; // ISO YYYY-MM-DD; MIPE change-alerts have none
  announced: boolean;
  budget: string;
  tags: string[];
  match_reason: string;
  link: string;
  first_seen: string;
}

export interface Feed {
  version: number;
  generated_at: string;
  calls: Call[];
}

/** Writable, user-authored. Lives in triage.json, never in calls.json. */
export type Status = "new" | "relevant" | "applied" | "not_relevant" | "review";

export interface Triage {
  status: Status;
  assignee: string | null;
  note: string;
  reminder: boolean;
  snoozed: boolean;
}

export type TriageMap = Record<string, Triage>;

export const EMPTY_TRIAGE: Triage = {
  status: "new",
  assignee: null,
  note: "",
  reminder: false,
  snoozed: false,
};

/** MIPE alerts are not "new calls" — they are a page a human has to look at,
 *  and they stay in that state until someone resolves them. */
export function defaultTriage(call: Call): Triage {
  return call.source === "mipe" ? { ...EMPTY_TRIAGE, status: "review" } : EMPTY_TRIAGE;
}
