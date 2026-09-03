import { useState } from "react";
import { ArrowLeft, ArrowSquareOut, Bell, Export, UserCircle } from "@phosphor-icons/react";
import type { Call, Status, Triage } from "../types";
import { STATUS_LABELS } from "./primitives";
import { CallDetail } from "./CallDetail";
import { AssigneePicker } from "./AssigneePicker";

function sheetStatuses(call: Call): Status[] {
  return call.source === "mipe" ? ["review", "relevant", "not_relevant"] : ["new", "relevant", "applied"];
}

interface Props {
  call: Call;
  triage: Triage;
  backLabel: string;
  onBack: () => void;
  onPatch: (patch: Partial<Triage>) => void;
  onShare: () => void;
}

/** Screen 3b — one call opened on mobile; triage collapses into a bottom sheet. */
export function MobileDetail({ call, triage, backLabel, onBack, onPatch, onShare }: Props) {
  const [panel, setPanel] = useState<"none" | "assign">("none");

  return (
    <div className="fr-m">
      <div className="fr-m-subnav">
        <button type="button" className="fr-iconbtn" aria-label="Înapoi" onClick={onBack}>
          <ArrowLeft size={16} />
        </button>
        <span style={{ fontSize: 14, color: "var(--muted-60)" }}>{backLabel}</span>
        <button
          type="button"
          className="fr-iconbtn"
          style={{ marginLeft: "auto" }}
          aria-label="Distribuie"
          onClick={onShare}
        >
          <Export size={16} />
        </button>
      </div>

      <div className="fr-m-scroll">
        <CallDetail call={call} status={triage.status} compact />

        <div className="field" style={{ marginTop: 16 }}>
          <label htmlFor="team-note-m">Note pentru echipă</label>
          <textarea
            id="team-note-m"
            className="input"
            placeholder="Cine coordonează, potrivirea cu programul, pasul următor…"
            style={{ minHeight: 64 }}
            value={triage.note}
            onChange={(event) => onPatch({ note: event.target.value })}
          />
        </div>
      </div>

      <div className="fr-sheet">
        <div className="fr-sheet-grab" />

        {panel === "assign" && (
          <div style={{ marginBottom: 11 }}>
            <div className="fr-kicker" style={{ marginBottom: 7 }}>
              Responsabil
            </div>
            <AssigneePicker
              value={triage.assignee}
              onChange={(assignee) => {
                onPatch({ assignee });
                setPanel("none");
              }}
            />
          </div>
        )}

        <div className="fr-sheet-chips">
          {sheetStatuses(call).map((status) => (
            <button
              type="button"
              key={status}
              className={`fr-chip${triage.status === status ? " on" : ""}`}
              aria-pressed={triage.status === status}
              onClick={() => onPatch({ status })}
            >
              {STATUS_LABELS[status]}
            </button>
          ))}
        </div>

        <div className="fr-sheet-actions">
          <a
            className="btn btn-primary"
            href={call.link}
            target="_blank"
            rel="noreferrer"
            style={{ flex: 1, justifyContent: "center", fontSize: 13 }}
          >
            <ArrowSquareOut size={15} />
            {call.source === "mipe" ? "Deschide pagina" : "Deschide portal"}
          </a>
          <button
            type="button"
            className="btn btn-secondary"
            style={{ justifyContent: "center", fontSize: 13 }}
            aria-label="Alocă"
            aria-pressed={panel === "assign"}
            onClick={() => setPanel((was) => (was === "assign" ? "none" : "assign"))}
          >
            <UserCircle size={16} />
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            style={{
              justifyContent: "center",
              fontSize: 13,
              color: triage.reminder ? "var(--color-accent)" : undefined,
              borderColor: triage.reminder ? "var(--color-accent)" : undefined,
            }}
            aria-label="Memento cu 7 zile înainte de termen"
            aria-pressed={triage.reminder}
            disabled={!call.deadline}
            onClick={() => onPatch({ reminder: !triage.reminder })}
          >
            <Bell size={16} weight={triage.reminder ? "fill" : "regular"} />
          </button>
        </div>
      </div>
    </div>
  );
}
