import { Target } from "@phosphor-icons/react";
import type { Call } from "../types";
import { formatLong, formatShort } from "../lib/format";
import { daysUntil, urgency } from "../lib/deadline";
import { deadlineRemaining, MatchReason, SourceBadge, StatusTag } from "./primitives";
import type { Status } from "../types";

const SOURCE_NAMES: Record<Call["source"], string> = {
  eu_sedia: "Portalul Funding & Tenders",
  adieuronest: "adieuronest.ro",
  mipe: "mfe.gov.ro",
};

interface Props {
  call: Call;
  status: Status;
  compact?: boolean;
  children?: React.ReactNode;
}

/** The centre column of 2a and the scroll body of 3b — identical content, two
 *  type scales. `compact` is the phone one. */
export function CallDetail({ call, status, compact = false, children }: Props) {
  const days = call.deadline ? daysUntil(call.deadline) : null;
  const level = urgency(days);
  const subtitle = [call.programme, SOURCE_NAMES[call.source]].filter(Boolean).join(" · ");

  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: compact ? 8 : 9,
          marginBottom: compact ? 12 : 14,
        }}
      >
        <SourceBadge source={call.source} />
        <StatusTag status={status} />
        {!compact && (
          <span style={{ fontSize: "11.5px", color: "var(--muted-45)", marginLeft: "auto" }}>
            văzut prima dată {formatLong(call.first_seen)}
          </span>
        )}
      </div>

      <h3
        style={{
          fontSize: compact ? 21 : 23,
          margin: `0 0 ${compact ? 5 : 6}px`,
          lineHeight: 1.2,
        }}
      >
        {call.title}
      </h3>
      <div
        style={{
          fontSize: compact ? "12.5px" : "13px",
          color: compact ? "var(--muted-55)" : "var(--muted-58)",
          marginBottom: compact ? 16 : 18,
        }}
      >
        {subtitle}
        {call.announced ? " · anunțat, încă nedeschis" : ""}
      </div>

      <div
        className="fr-stats"
        style={{ gap: compact ? 11 : 14, marginBottom: compact ? 16 : 18 }}
      >
        <div className="fr-statcard" style={{ padding: compact ? "11px 13px" : "12px 14px" }}>
          <div className="fr-kicker" style={{ marginBottom: compact ? 4 : 5 }}>
            Termen
          </div>
          {call.deadline ? (
            <>
              <div
                className={`fr-dl${level === "normal" ? "" : ` ${level}`}`}
                style={{ fontSize: compact ? 15 : 17, fontWeight: 500 }}
              >
                {compact ? formatShort(call.deadline) : formatLong(call.deadline)}
              </div>
              <div
                style={{
                  fontSize: compact ? "11px" : "11.5px",
                  marginTop: compact ? 1 : 2,
                  color: level === "normal" ? "var(--muted-48)" : `var(--color-${level})`,
                }}
              >
                {deadlineRemaining(call.deadline)}
              </div>
            </>
          ) : (
            <>
              <div style={{ fontSize: compact ? 15 : 17, fontWeight: 500 }}>—</div>
              <div
                style={{
                  fontSize: compact ? "11px" : "11.5px",
                  color: "var(--muted-48)",
                  marginTop: compact ? 1 : 2,
                }}
              >
                fără termen
              </div>
            </>
          )}
        </div>

        <div className="fr-statcard" style={{ padding: compact ? "11px 13px" : "12px 14px" }}>
          <div className="fr-kicker" style={{ marginBottom: compact ? 4 : 5 }}>
            Buget
          </div>
          <div
            style={{
              fontFamily: "var(--font-heading)",
              fontSize: compact ? 15 : 17,
              fontWeight: 500,
              lineHeight: 1.25,
            }}
          >
            {call.budget || "—"}
          </div>
          <div
            style={{
              fontSize: compact ? "11px" : "11.5px",
              color: "var(--muted-48)",
              marginTop: compact ? 1 : 2,
            }}
          >
            {call.budget ? "buget total apel" : "nepublicat"}
          </div>
        </div>
      </div>

      {call.match_reason && (
        <div
          className="fr-why"
          style={{ padding: compact ? "12px 14px" : "12px 14px", marginBottom: compact ? 16 : 18 }}
        >
          <div
            className="fr-why-kicker"
            style={{ fontSize: compact ? "10.5px" : "11px", marginBottom: compact ? 5 : 6 }}
          >
            <Target size={13} /> De ce a apărut
          </div>
          <div style={{ fontSize: compact ? "13px" : "13.5px" }}>
            <MatchReason reason={call.match_reason} />
          </div>
        </div>
      )}

      {call.tags.length > 0 && (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 6,
            marginBottom: compact ? 0 : 20,
          }}
        >
          {call.tags.map((tag) => (
            <span className="tag tag-neutral" key={tag}>
              {tag}
            </span>
          ))}
        </div>
      )}

      {children}
    </>
  );
}
