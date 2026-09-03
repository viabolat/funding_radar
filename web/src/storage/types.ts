import type { Triage, TriageMap } from "../types";

/**
 * Triage state is user-authored and does NOT belong in calls.json — the
 * watchers rewrite that file and would erase it. It is stored separately,
 * keyed by call_id, behind this interface so the local adapter can be swapped
 * for the GitHub one without touching a component.
 */
export interface TriageStore {
  readonly name: string;
  /** True when writes actually persist. A read-only adapter still loads. */
  readonly writable: boolean;
  load(): Promise<TriageMap>;
  /** Merges a partial change into one call's triage and returns the result. */
  save(callId: string, patch: Partial<Triage>, current: Triage): Promise<Triage>;
}
