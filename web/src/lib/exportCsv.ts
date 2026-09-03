import type { Call, TriageMap } from "../types";
import { statusOf } from "./filters";
import { STATUS_LABELS } from "../components/primitives";

const HEADERS = [
  "call_id", "sursa", "titlu", "program", "termen", "buget",
  "status", "responsabil", "note", "link",
];

function cell(value: string): string {
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

export function toCsv(calls: Call[], triage: TriageMap): string {
  const rows = calls.map((call) => {
    const entry = triage[call.call_id];
    return [
      call.call_id,
      call.source,
      call.title,
      call.programme,
      call.deadline ?? "",
      call.budget,
      STATUS_LABELS[statusOf(call, triage)],
      entry?.assignee ?? "",
      entry?.note ?? "",
      call.link,
    ].map(cell).join(",");
  });
  // reason: Excel reads a BOM-less UTF-8 CSV as Latin-1 and mangles every
  // Romanian diacritic — the same BOM problem the CSV source had, inverted.
  return "﻿" + [HEADERS.join(","), ...rows].join("\r\n");
}

export function downloadCsv(calls: Call[], triage: TriageMap): void {
  const blob = new Blob([toCsv(calls, triage)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `apeluri-${new Date().toISOString().slice(0, 10)}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}
