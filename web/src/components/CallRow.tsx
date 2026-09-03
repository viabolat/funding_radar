import type { Call, TriageMap } from "../types";
import { statusOf } from "../lib/filters";
import { initials } from "../lib/format";
import { DeadlineLabel, SourceBadge, StatusTag } from "./primitives";

interface Props {
  call: Call;
  triage: TriageMap;
  selected: boolean;
  onSelect: (callId: string) => void;
  variant: "desktop" | "mobile";
}

/** One row in the list. Same content on both screens; only the type scale and
 *  the selected-state border width differ, so the variants share this file. */
export function CallRow({ call, triage, selected, onSelect, variant }: Props) {
  const prefix = variant === "mobile" ? "fr-m-row" : "fr-row";
  const assignee = triage[call.call_id]?.assignee;

  return (
    <button
      type="button"
      className={`${prefix}${selected ? " on" : ""}`}
      aria-current={selected ? "true" : undefined}
      onClick={() => onSelect(call.call_id)}
    >
      <div className={`${prefix}-head`}>
        <SourceBadge source={call.source} />
        <DeadlineLabel call={call} />
      </div>
      <div className={`${prefix}-title`}>{call.title}</div>
      <div className={`${prefix}-tags`}>
        {call.programme && <span className="tag tag-neutral">{call.programme}</span>}
        {call.budget && <span className="tag tag-neutral">{call.budget}</span>}
        <StatusTag status={statusOf(call, triage)} />
        {assignee && (
          <span style={{ fontSize: "10.5px", color: "var(--muted-42)", alignSelf: "center" }}>
            {initials(assignee)}
          </span>
        )}
      </div>
    </button>
  );
}
