import { useCallback, useEffect, useMemo, useState } from "react";
import type { Call, Triage, TriageMap } from "./types";
import { defaultTriage } from "./types";
import { fetchFeed, sortCalls } from "./lib/feed";
import { filterCounts, selectCalls, type FilterKey } from "./lib/filters";
import { useMediaQuery, MOBILE_QUERY } from "./lib/useMediaQuery";
import { downloadCsv } from "./lib/exportCsv";
import { createLocalTriageStore } from "./storage";
import { DesktopWorkspace } from "./components/DesktopWorkspace";
import { MobileInbox } from "./components/MobileInbox";
import { MobileDetail } from "./components/MobileDetail";
import { FILTERS } from "./lib/filters";
import { initials } from "./lib/format";

// Local triage until the GitHub OAuth flow exists; swapping in
// createGitHubTriageStore is the only change this file needs.
const store = createLocalTriageStore();
const CURRENT_USER = "Ana M.";

export default function App() {
  const [calls, setCalls] = useState<Call[]>([]);
  const [triage, setTriage] = useState<TriageMap>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [filter, setFilter] = useState<FilterKey>("inbox");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);

  const isMobile = useMediaQuery(MOBILE_QUERY);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchFeed(), store.load()])
      .then(([feed, saved]) => {
        if (cancelled) return;
        setCalls(sortCalls(feed.calls));
        setTriage(saved);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const counts = useMemo(() => filterCounts(calls, triage), [calls, triage]);
  const visible = useMemo(
    () => selectCalls(calls, triage, filter, query),
    [calls, triage, filter, query],
  );

  // Desktop keeps a call open; picking a filter that no longer contains it
  // falls back to the top of the new list rather than showing an empty pane.
  useEffect(() => {
    if (isMobile || visible.length === 0) return;
    if (!visible.some((call) => call.call_id === selectedId)) {
      setSelectedId(visible[0]!.call_id);
    }
  }, [isMobile, visible, selectedId]);

  const selected = useMemo(
    () => calls.find((call) => call.call_id === selectedId) ?? null,
    [calls, selectedId],
  );

  const triageFor = useCallback(
    (call: Call): Triage => triage[call.call_id] ?? defaultTriage(call),
    [triage],
  );

  const patch = useCallback(
    (callId: string, changes: Partial<Triage>) => {
      const call = calls.find((candidate) => candidate.call_id === callId);
      if (!call) return;
      const current = triage[callId] ?? defaultTriage(call);
      const next = { ...current, ...changes };
      // Optimistic: the click lands immediately, the write follows.
      setTriage((was) => ({ ...was, [callId]: next }));
      void store.save(callId, changes, current);
    },
    [calls, triage],
  );

  const share = useCallback((call: Call) => {
    void navigator.clipboard?.writeText(call.link);
  }, []);

  if (loading) {
    return <div className="fr-empty">Se încarcă apelurile…</div>;
  }

  if (error) {
    return (
      <div className="fr-empty">
        <strong style={{ fontWeight: 500, fontSize: 17 }}>Nu am putut încărca radarul</strong>
        <span style={{ fontSize: 13 }}>{error}</span>
      </div>
    );
  }

  if (isMobile) {
    if (mobileOpen && selected) {
      return (
        <MobileDetail
          call={selected}
          triage={triageFor(selected)}
          backLabel={FILTERS.find((entry) => entry.key === filter)!.label}
          onBack={() => setMobileOpen(false)}
          onPatch={(changes) => patch(selected.call_id, changes)}
          onShare={() => share(selected)}
        />
      );
    }
    return (
      <MobileInbox
        visible={visible}
        counts={counts}
        filter={filter}
        onFilter={setFilter}
        query={query}
        onQuery={setQuery}
        triage={triage}
        onOpen={(callId) => {
          setSelectedId(callId);
          setMobileOpen(true);
        }}
      />
    );
  }

  return (
    <DesktopWorkspace
      visible={visible}
      counts={counts}
      filter={filter}
      onFilter={setFilter}
      query={query}
      onQuery={setQuery}
      triage={triage}
      selected={selected}
      selectedTriage={selected ? triageFor(selected) : null}
      onSelect={setSelectedId}
      onPatch={patch}
      onShare={share}
      onExport={() => downloadCsv(visible, triage)}
      currentUser={initials(CURRENT_USER)}
    />
  );
}
