import { useEffect, useRef, useState } from "react";
import { CaretDown, UserCircle } from "@phosphor-icons/react";
import { STAFF } from "../staff";
import { initials } from "../lib/format";
import { Avatar } from "./primitives";

interface Props {
  value: string | null;
  onChange: (assignee: string | null) => void;
}

export function AssigneePicker({ value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (!boxRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const pick = (person: string | null) => {
    onChange(person);
    setOpen(false);
  };

  return (
    <div ref={boxRef} style={{ position: "relative" }}>
      <button
        type="button"
        className="fr-select"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((was) => !was)}
      >
        {value ? (
          <Avatar text={initials(value)} size={24} />
        ) : (
          <UserCircle size={24} color="var(--muted-45)" />
        )}
        <span style={{ color: value ? undefined : "var(--muted-55)" }}>
          {value ?? "Nealocat"}
        </span>
        <CaretDown size={12} color="var(--muted-45)" style={{ marginLeft: "auto" }} />
      </button>

      {open && (
        <div
          role="listbox"
          style={{
            position: "absolute", top: "calc(100% + 4px)", left: 0, right: 0, zIndex: 20,
            background: "var(--color-surface)", border: "1px solid var(--color-divider)",
            borderRadius: 8, padding: 4, boxShadow: "var(--shadow-md)",
          }}
        >
          {[null, ...STAFF].map((person) => (
            <button
              key={person ?? "__none"}
              type="button"
              role="option"
              aria-selected={person === value}
              className="fr-navlink"
              onClick={() => pick(person)}
              style={{
                display: "flex", alignItems: "center", gap: 8, width: "100%",
                padding: "6px 7px", borderRadius: 6, fontSize: 13,
                color: person === value ? "var(--color-accent-200)" : "var(--color-text)",
              }}
            >
              {person ? (
                <Avatar text={initials(person)} size={20} />
              ) : (
                <UserCircle size={20} color="var(--muted-45)" />
              )}
              {person ?? "Nealocat"}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
