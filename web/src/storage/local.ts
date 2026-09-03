import type { Triage, TriageMap } from "../types";
import type { TriageStore } from "./types";

const KEY = "radar-finantari.triage.v1";

/** Per-browser triage. This is the default until GitHub auth exists: it needs
 *  no token and no network, and it is the same shape the GitHub adapter will
 *  commit as triage.json. */
export function createLocalTriageStore(
  storage: Storage | null = globalThis.localStorage ?? null,
): TriageStore {
  return {
    name: "local",
    writable: storage !== null,

    async load(): Promise<TriageMap> {
      if (!storage) return {};
      try {
        const raw = storage.getItem(KEY);
        if (!raw) return {};
        const parsed = JSON.parse(raw) as unknown;
        // reason: a hand-edited or half-written localStorage value must not
        // take the whole dashboard down — an unusable value is no value.
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
        return parsed as TriageMap;
      } catch {
        return {};
      }
    },

    async save(callId: string, patch: Partial<Triage>, current: Triage): Promise<Triage> {
      const next = { ...current, ...patch };
      if (!storage) return next;
      const all = await this.load();
      all[callId] = next;
      try {
        storage.setItem(KEY, JSON.stringify(all));
      } catch {
        // Quota or a private-mode block: the UI keeps its optimistic state for
        // this session rather than reverting the click.
      }
      return next;
    },
  };
}
