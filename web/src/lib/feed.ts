import { SUPPORTED_FEED_VERSION, type Call, type Feed } from "../types";

export class FeedVersionError extends Error {
  constructor(public readonly found: number) {
    super(
      `Feed necunoscut (versiunea ${found}, această aplicație citește ${SUPPORTED_FEED_VERSION}).`,
    );
    this.name = "FeedVersionError";
  }
}

/** calls.json sits next to the built app. On GitHub Pages that is the repo
 *  file copied into the deploy directory; in dev it is web/public/calls.json. */
export const FEED_URL = `${import.meta.env.BASE_URL}calls.json`;

export async function fetchFeed(url: string = FEED_URL): Promise<Feed> {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Nu am putut încărca apelurile (HTTP ${response.status}).`);
  }
  const feed = (await response.json()) as Feed;
  // reason: a feed written by a newer calls_store.py may have renamed or
  // dropped fields. Refusing it is better than rendering silent blanks.
  if (feed.version !== SUPPORTED_FEED_VERSION) throw new FeedVersionError(feed.version);
  return feed;
}

/** Newest first, then by deadline, so the freshest work is at the top and
 *  ties break towards whatever closes soonest. */
export function sortCalls(calls: Call[]): Call[] {
  return [...calls].sort((a, b) => {
    if (a.first_seen !== b.first_seen) return a.first_seen < b.first_seen ? 1 : -1;
    if (a.deadline && b.deadline) return a.deadline < b.deadline ? -1 : 1;
    if (a.deadline) return -1;
    if (b.deadline) return 1;
    return a.title.localeCompare(b.title, "ro");
  });
}
