import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";

import { filterCommands, moveActive, type PaletteCommand } from "@/lib/crest/commands";

export type Command = PaletteCommand & { run: () => void };

/**
 * The command palette (Ctrl+K / Cmd+K): type to filter the desk's real commands, ↑/↓ (or Home/End) to move, Enter to
 * run, Esc to close. A modal dialog with a combobox and a listbox, so a screen reader hears the list and the active
 * command; focus goes back where it was when the palette closes.
 */
export function CommandPalette({ open, onClose, commands }: { open: boolean; onClose: () => void; commands: Command[] }) {
  const [q, setQ] = useState("");
  const [picked, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const back = useRef<HTMLElement | null>(null);
  const list = useRef<HTMLUListElement>(null);
  const ids = useId();
  const shown = useMemo(() => filterCommands(commands, q), [commands, q]);
  // The active row: the one moved to, else the first enabled one (after the list changed under it).
  const active = picked >= 0 && picked < shown.length && !shown[picked].disabled ? picked : moveActive(shown, -1, 1);

  useEffect(() => {
    if (!open) return;
    back.current = document.activeElement as HTMLElement | null;
    setQ("");
    setActive(0);
    const t = window.setTimeout(() => input.current?.focus(), 0);
    return () => {
      window.clearTimeout(t);
      back.current?.focus?.();
    };
  }, [open]);

  useEffect(() => {
    list.current?.querySelector<HTMLElement>(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  if (!open) return null;

  const run = (c: Command | undefined) => {
    if (!c || c.disabled) return;
    onClose();
    // After the palette is gone, so the command's own focus (a field, a step) is not taken back.
    window.setTimeout(() => c.run(), 0);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onClose();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setActive(moveActive(shown, active, e.key === "ArrowDown" ? 1 : -1));
    } else if (e.key === "Home" || e.key === "End") {
      e.preventDefault();
      setActive(e.key === "Home" ? moveActive(shown, -1, 1) : moveActive(shown, shown.length, -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      run(shown[active]);
    } else if (e.key === "Tab") {
      // The input is the dialog's only stop: keep focus inside the modal.
      e.preventDefault();
    }
  };

  const optionId = (i: number) => `${ids}-opt-${i}`;
  let lastGroup = "";
  return (
    <div className="fixed inset-0 z-[2000] flex items-start justify-center bg-black/40 px-4 pt-[12vh]" onMouseDown={onClose} data-testid="palette-backdrop">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${ids}-title`}
        className="w-full max-w-xl overflow-hidden rounded-md border border-line bg-card text-ink shadow-xl"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={onKey}
        data-testid="command-palette"
      >
        <h2 id={`${ids}-title`} className="sr-only">
          Command palette
        </h2>
        <div className="flex items-center gap-2 border-b border-line px-3">
          <Search className="size-4 shrink-0 text-muted" aria-hidden="true" />
          <input
            ref={input}
            role="combobox"
            aria-expanded="true"
            aria-controls={`${ids}-list`}
            aria-activedescendant={active >= 0 ? optionId(active) : undefined}
            aria-autocomplete="list"
            aria-label="Type a command or a step"
            placeholder="Type a command or a step…"
            className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-muted"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setActive(-1);
            }}
            data-testid="palette-input"
          />
          <kbd className="shrink-0 rounded-sm border border-line px-1.5 text-xs text-muted">Esc</kbd>
        </div>
        <ul ref={list} id={`${ids}-list`} role="listbox" aria-label="Commands" className="max-h-[50vh] overflow-y-auto py-1">
          {shown.length === 0 ? (
            <li className="px-3 py-3 text-sm text-muted" role="presentation">
              No command matches &ldquo;{q}&rdquo;.
            </li>
          ) : null}
          {shown.map((c, i) => {
            const header = c.group !== lastGroup ? c.group : null;
            lastGroup = c.group;
            return (
              <li key={c.id} role="presentation">
                {header ? (
                  <p className="px-3 pt-2 pb-1 text-xs font-semibold tracking-wide text-muted uppercase" aria-hidden="true">
                    {header}
                  </p>
                ) : null}
                <div
                  id={optionId(i)}
                  role="option"
                  aria-selected={i === active}
                  aria-disabled={c.disabled || undefined}
                  data-index={i}
                  data-testid={`palette-${c.id}`}
                  onMouseMove={() => !c.disabled && setActive(i)}
                  onClick={() => run(c)}
                  className={
                    "mx-1 flex cursor-pointer items-baseline gap-2 rounded-sm px-2 py-2 text-sm " +
                    (c.disabled ? "cursor-not-allowed text-muted" : i === active ? "bg-water text-card" : "text-ink")
                  }
                >
                  <span className="min-w-0 flex-1 truncate">{c.label}</span>
                  {c.hint ? <span className={"shrink-0 text-xs " + (i === active && !c.disabled ? "text-card" : "text-muted")}>{c.hint}</span> : null}
                </div>
              </li>
            );
          })}
        </ul>
        <p className="border-t border-line px-3 py-1.5 text-xs text-muted">↑ ↓ to move · Enter to run · Esc to close</p>
      </div>
    </div>
  );
}
