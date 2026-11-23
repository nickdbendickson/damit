/**
 * Collapsible map legends (Absaraka desk test 2026-11-21: the Flood map legend covered a third of the map). Open by
 * default; the choice is kept per legend in this browser.
 */
import { useCallback, useState } from "react";

const KEY = "damit-desk-legend-closed";

function closedSet(): Set<string> {
  try {
    const raw = typeof localStorage === "undefined" ? null : localStorage.getItem(KEY);
    const v = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(v) ? v.map(String) : []);
  } catch {
    return new Set();
  }
}

/** [open, toggle] for the legend `id`. */
export function useLegendOpen(id: string): [boolean, () => void] {
  const [open, setOpen] = useState(() => !closedSet().has(id));
  const toggle = useCallback(() => {
    setOpen((o) => {
      const next = !o;
      const s = closedSet();
      if (next) s.delete(id);
      else s.add(id);
      try {
        localStorage.setItem(KEY, JSON.stringify([...s]));
      } catch {
        /* private window: the choice lasts this visit */
      }
      return next;
    });
  }, [id]);
  return [open, toggle];
}
