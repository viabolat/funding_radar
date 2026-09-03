import { Export, Funnel, MagnifyingGlass } from "@phosphor-icons/react";
import type { Call, Triage, TriageMap } from "../types";
import { FILTERS, type FilterKey } from "../lib/filters";
import { Avatar, BrandMark } from "./primitives";
import { CallRow } from "./CallRow";
import { CallDetail } from "./CallDetail";
import { TriageRail } from "./TriageRail";

interface Props {
  visible: Call[];
  counts: Record<FilterKey, number>;
  filter: FilterKey;
  onFilter: (filter: FilterKey) => void;
  query: string;
  onQuery: (query: string) => void;
  triage: TriageMap;
  selected: Call | null;
  selectedTriage: Triage | null;
  onSelect: (callId: string) => void;
  onPatch: (callId: string, patch: Partial<Triage>) => void;
  onShare: (call: Call) => void;
  onExport: () => void;
  currentUser: string;
}

/** Screen 2a — the split inbox: list (390px) · detail (flex) · triage rail (230px). */
export function DesktopWorkspace(props: Props) {
  const { visible, counts, filter, query, triage, selected, selectedTriage } = props;

  return (
    <div className="fr-app">
      <header className="fr-nav">
        <div className="fr-brand">
          <BrandMark />
          Radar Finanțări
        </div>
        <a className="fr-navlink" href="#apeluri" aria-current="page">
          Apeluri
        </a>
        <a className="fr-navlink" href="#rezumat">
          Rezumat
        </a>
        <a className="fr-navlink" href="#surse">
          Surse
        </a>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
          <div className="fr-search">
            <MagnifyingGlass size={14} />
            <input
              className="input"
              placeholder="Caută apeluri"
              value={query}
              onChange={(event) => props.onQuery(event.target.value)}
              aria-label="Caută apeluri"
            />
          </div>
          <button type="button" className="fr-iconbtn" title="Exportă" onClick={props.onExport}>
            <Export size={15} />
          </button>
          <Avatar text={props.currentUser} />
        </div>
      </header>

      <div className="fr-body">
        <div className="fr-list">
          <div className="fr-filters">
            {FILTERS.map(({ key, label }) => (
              <button
                type="button"
                key={key}
                className={`fr-chip${filter === key ? " on" : ""}`}
                aria-pressed={filter === key}
                onClick={() => props.onFilter(key)}
              >
                {label}
                {counts[key] > 0 ? ` · ${counts[key]}` : ""}
              </button>
            ))}
            <button type="button" className="fr-chip" style={{ marginLeft: "auto" }} title="Filtre">
              <Funnel size={11} />
            </button>
          </div>

          <div className="fr-rows">
            {visible.length === 0 ? (
              <div className="fr-empty" style={{ height: "auto", paddingTop: 60 }}>
                <strong style={{ fontWeight: 500 }}>Niciun apel aici</strong>
                <span style={{ fontSize: 13 }}>Schimbă filtrul sau golește căutarea.</span>
              </div>
            ) : (
              visible.map((call) => (
                <CallRow
                  key={call.call_id}
                  call={call}
                  triage={triage}
                  selected={selected?.call_id === call.call_id}
                  onSelect={props.onSelect}
                  variant="desktop"
                />
              ))
            )}
          </div>
        </div>

        {selected && selectedTriage ? (
          <>
            <main className="fr-detail">
              <CallDetail call={selected} status={selectedTriage.status}>
                <div className="field" style={{ marginBottom: 8 }}>
                  <label htmlFor="team-note">Note pentru echipă</label>
                  <textarea
                    id="team-note"
                    className="input"
                    placeholder="Cine coordonează, potrivirea cu programul, pasul următor…"
                    style={{ minHeight: 64 }}
                    value={selectedTriage.note}
                    onChange={(event) =>
                      props.onPatch(selected.call_id, { note: event.target.value })
                    }
                  />
                </div>
              </CallDetail>
            </main>
            <TriageRail
              call={selected}
              triage={selectedTriage}
              onPatch={(patch) => props.onPatch(selected.call_id, patch)}
              onShare={() => props.onShare(selected)}
            />
          </>
        ) : (
          <main className="fr-detail">
            <div className="fr-empty">
              <strong style={{ fontWeight: 500, fontSize: 17 }}>Niciun apel selectat</strong>
              <span style={{ fontSize: 13 }}>Alege un apel din listă pentru a-l deschide.</span>
            </div>
          </main>
        )}
      </div>
    </div>
  );
}
