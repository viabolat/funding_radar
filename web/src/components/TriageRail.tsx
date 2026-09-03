import { Archive, ArrowSquareOut, Export } from "@phosphor-icons/react";
import type { Call, Status, Triage } from "../types";
import { STATUS_LABELS } from "./primitives";
import { AssigneePicker } from "./AssigneePicker";

/** MIPE alerts get "De verificat" instead of "Nou": there is nothing to apply
 *  for, only a page a human has to read and resolve. */
function statusOptions(call: Call): Status[] {
  return call.source === "mipe"
    ? ["review", "relevant", "not_relevant"]
    : ["new", "relevant", "applied", "not_relevant"];
}

interface Props {
  call: Call;
  triage: Triage;
  onPatch: (patch: Partial<Triage>) => void;
  onShare: () => void;
}

export function TriageRail({ call, triage, onPatch, onShare }: Props) {
  return (
    <aside className="fr-rail">
      <div>
        <div className="fr-kicker" style={{ marginBottom: 9 }}>
          Status
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
          {statusOptions(call).map((status) => (
            <label className="radio" key={status}>
              <input
                type="radio"
                name={`status-${call.call_id}`}
                checked={triage.status === status}
                onChange={() => onPatch({ status })}
              />
              <span className="dot" />
              {STATUS_LABELS[status]}
            </label>
          ))}
        </div>
      </div>

      <div>
        <div className="fr-kicker" style={{ marginBottom: 9 }}>
          Responsabil
        </div>
        <AssigneePicker
          value={triage.assignee}
          onChange={(assignee) => onPatch({ assignee })}
        />
      </div>

      {call.deadline && (
        <div>
          <div className="fr-kicker" style={{ marginBottom: 9 }}>
            Memento
          </div>
          <label className="radio" style={{ gap: 9 }}>
            <input
              type="checkbox"
              checked={triage.reminder}
              onChange={(event) => onPatch({ reminder: event.target.checked })}
              style={{ position: "static", opacity: 1, width: 16, height: 16, accentColor: "var(--color-accent)" }}
            />
            <span style={{ fontSize: 13 }}>cu 7 zile înainte de termen</span>
          </label>
        </div>
      )}

      <div className="fr-rail-actions">
        <a
          className="btn btn-primary"
          href={call.link}
          target="_blank"
          rel="noreferrer"
          style={{ fontSize: 13, justifyContent: "center" }}
        >
          <ArrowSquareOut size={15} />
          {call.source === "mipe" ? "Deschide pagina" : "Deschide pe portal"}
        </a>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            className="btn btn-secondary"
            style={{ flex: 1, justifyContent: "center", fontSize: "12.5px" }}
            onClick={onShare}
          >
            <Export size={15} />
            Distribuie
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            style={{ flex: 1, justifyContent: "center", fontSize: "12.5px" }}
            onClick={() => onPatch({ snoozed: !triage.snoozed })}
            aria-pressed={triage.snoozed}
          >
            <Archive size={15} />
            {triage.snoozed ? "Reactivează" : "Arhivează"}
          </button>
        </div>
      </div>
    </aside>
  );
}
