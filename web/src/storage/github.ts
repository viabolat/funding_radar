import type { Triage, TriageMap } from "../types";
import type { TriageStore } from "./types";

export interface GitHubStoreOptions {
  owner: string;
  repo: string;
  branch?: string;
  path?: string;
  /** A user token from the OAuth flow. Without one the store is read-only. */
  token?: string;
}

/**
 * STUB — not wired up yet.
 *
 * The intended shape, per the handoff: triage.json lives in the repo, so the
 * repo stays the single source of truth and no database or new secret is
 * introduced. Reads are a raw file fetch (works unauthenticated on a public
 * repo). Writes are a contents-API PUT with the user's OAuth token, which is
 * why `writable` is false until auth lands — see README.
 *
 * Whoever finishes this: the contents API needs the blob `sha` of the file
 * being replaced, so `load()` must keep it, and a 409 means someone else
 * committed in between — refetch and re-apply the patch rather than force it.
 */
export function createGitHubTriageStore(options: GitHubStoreOptions): TriageStore {
  const { owner, repo, branch = "main", path = "triage.json", token } = options;
  const rawUrl = `https://raw.githubusercontent.com/${owner}/${repo}/${branch}/${path}`;

  return {
    name: "github",
    writable: false, // flip once the OAuth token flow exists

    async load(): Promise<TriageMap> {
      const response = await fetch(rawUrl, { cache: "no-store" });
      if (response.status === 404) return {}; // no triage committed yet
      if (!response.ok) throw new Error(`Nu am putut citi ${path} (HTTP ${response.status}).`);
      return (await response.json()) as TriageMap;
    },

    async save(_callId: string, _patch: Partial<Triage>, _current: Triage): Promise<Triage> {
      void token;
      throw new Error(
        "Scrierea în triage.json nu este încă disponibilă — autentificarea GitHub lipsește.",
      );
    },
  };
}
