import {
  Broadcast,
  CalendarBlank,
  FlagIcon,
  GlobeHemisphereEast,
  BellRinging,
  WarningCircle,
} from "@phosphor-icons/react";
import type { Call, Source, Status } from "../types";
import { daysUntil, remainingLabel, urgency } from "../lib/deadline";
import { formatShort } from "../lib/format";

const SOURCE_META: Record<Source, { label: string; cls: string; Icon: typeof FlagIcon }> = {
  eu_sedia: { label: "UE", cls: "src-eu", Icon: GlobeHemisphereEast },
  adieuronest: { label: "RO", cls: "src-ro", Icon: FlagIcon },
  mipe: { label: "MIPE", cls: "src-mipe", Icon: BellRinging },
};

export function SourceBadge({ source }: { source: Source }) {
  const { label, cls, Icon } = SOURCE_META[source];
  return (
    <span className={`fr-src ${cls}`}>
      <Icon size={12} /> {label}
    </span>
  );
}

export const STATUS_LABELS: Record<Status, string> = {
  new: "Nou",
  relevant: "Relevant",
  applied: "Depus",
  not_relevant: "Nerelevant",
  review: "De verificat",
};

const STATUS_TAG_CLASS: Record<Status, string> = {
  new: "tag-outline",
  relevant: "tag-accent",
  applied: "tag-success",
  not_relevant: "tag-neutral",
  review: "tag-review",
};

export function StatusTag({ status }: { status: Status }) {
  return <span className={`tag ${STATUS_TAG_CLASS[status]}`}>{STATUS_LABELS[status]}</span>;
}

/**
 * The deadline line. A MIPE alert has no deadline — it shows the amber
 * "verifică" prompt instead, because there is nothing to count down to.
 */
export function DeadlineLabel({ call, now }: { call: Call; now?: Date }) {
  if (!call.deadline) {
    if (call.source === "mipe") {
      return (
        <span style={{ color: "var(--color-soon)", display: "inline-flex", alignItems: "center", gap: 5 }}>
          <WarningCircle size={13} /> verifică
        </span>
      );
    }
    return <span style={{ color: "var(--muted-45)" }}>—</span>;
  }
  const days = daysUntil(call.deadline, now);
  const level = urgency(days);
  return (
    <span className={`fr-dl${level === "normal" ? "" : ` ${level}`}`}>
      <CalendarBlank size={13} />
      {formatShort(call.deadline)}
      {days !== null && days >= 0 ? ` · ${days}d` : ""}
    </span>
  );
}

export function deadlineRemaining(deadline: string, now?: Date): string {
  const days = daysUntil(deadline, now);
  return days === null ? "" : remainingLabel(days);
}

export function BrandMark({ size = 26 }: { size?: number }) {
  return (
    <span className="mk" style={{ width: size, height: size }}>
      <Broadcast weight="fill" size={Math.round(size * 0.58)} />
    </span>
  );
}

export function Avatar({ text, size = 30 }: { text: string; size?: number }) {
  return (
    <div
      className="fr-avatar"
      style={{ width: size, height: size, fontSize: Math.round(size * 0.4) }}
    >
      {text}
    </div>
  );
}

/** Bolds each matched term inside the Romanian match_reason sentence. The
 *  watchers quote terms with Romanian quotation marks, so those delimit. */
export function MatchReason({ reason }: { reason: string }) {
  const parts = reason.split(/(„[^”]*”)/g);
  return (
    <>
      {parts.map((part, index) =>
        part.startsWith("„") && part.endsWith("”") ? (
          <b key={index}>{part}</b>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  );
}
