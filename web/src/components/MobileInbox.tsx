import { MagnifyingGlass, X } from "@phosphor-icons/react";
import { useState } from "react";
import type { Call, TriageMap } from "../types";
import { FILTERS, type FilterKey } from "../lib/filters";
import { BrandMark } from "./primitives";
import { CallRow } from "./CallRow";

interface Props {
  visible: Call[];
  counts: Record<FilterKey, number>;
  filter: FilterKey;
  onFilter: (filter: FilterKey) => void;
  query: string;
  onQuery: (query: string) => void;
  triage: TriageMap;
  onOpen: (callId: string) => void;
}

/** Screen 3a — the list, standalone, at phone width. */
export function MobileInbox(props: Props) {
  const [searching, setSearching] = useState(props.query !== "");

  const closeSearch = () => {
    setSearching(false);
    props.onQuery("");
  };

  return (
    <div className="fr-m">
      <div className="fr-m-head">
        <BrandMark size={28} />
        <span className="fr-m-title">Radar Finanțări</span>
        <button
          type="button"
          className="fr-iconbtn"
          style={{ marginLeft: "auto", width: 34, height: 34 }}
          aria-label={searching ? "Închide căutarea" : "Caută"}
          onClick={() => (searching ? closeSearch() : setSearching(true))}
        >
          {searching ? <X size={16} /> : <MagnifyingGlass size={16} />}
        </button>
      </div>

      {searching && (
        <div style={{ padding: "0 18px 12px", display: "flex", gap: 8, alignItems: "center" }}>
          <input
            className="input"
            autoFocus
            placeholder="Caută apeluri"
            aria-label="Caută apeluri"
            value={props.query}
            onChange={(event) => props.onQuery(event.target.value)}
          />
          <button type="button" className="fr-iconbtn" aria-label="Golește" onClick={closeSearch}>
            <X size={15} />
          </button>
        </div>
      )}

      <div className="fr-m-chips">
        {FILTERS.map(({ key, label }) => (
          <button
            type="button"
            key={key}
            className={`fr-chip${props.filter === key ? " on" : ""}`}
            aria-pressed={props.filter === key}
            onClick={() => props.onFilter(key)}
          >
            {label}
            {props.counts[key] > 0 ? ` · ${props.counts[key]}` : ""}
          </button>
        ))}
      </div>

      <div className="fr-m-rows">
        {props.visible.length === 0 ? (
          <div className="fr-empty">
            <strong style={{ fontWeight: 500 }}>Niciun apel aici</strong>
            <span style={{ fontSize: 13 }}>Schimbă filtrul sau golește căutarea.</span>
          </div>
        ) : (
          props.visible.map((call) => (
            <CallRow
              key={call.call_id}
              call={call}
              triage={props.triage}
              selected={false}
              onSelect={props.onOpen}
              variant="mobile"
            />
          ))
        )}
      </div>
    </div>
  );
}
