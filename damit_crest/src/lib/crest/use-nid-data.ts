/**
 * The NID state the desk panels share, and one state's NID extract (useNidData). Moved out of
 * components/crest/NidDamPicker.tsx so that file exports only components (React Fast Refresh;
 * repo audit 2026-11-23).
 */
import { useEffect, useState, useSyncExternalStore } from "react";
import type { NidData } from "@/lib/crest/nid-dams";
import {
  EXAMPLE_STATE,
  isNidState,
  loadNidState,
  rememberedState,
  rememberState,
  stateName,
} from "@/lib/crest/nid-state";

// ---------------------------------------------------------------- the chosen state (shared by the panels)

const listeners = new Set<() => void>();
let selectedState = EXAMPLE_STATE;
let restored = false;
function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}
export function selectNidState(code: string): void {
  if (!isNidState(code) || code === selectedState) return;
  selectedState = code;
  rememberState(code);
  listeners.forEach((l) => l());
}
/** The state the picker shows; the last choice in this browser profile, else the bundled example (North Dakota). */
export function useSelectedNidState(): string {
  const v = useSyncExternalStore(
    subscribe,
    () => selectedState,
    () => EXAMPLE_STATE,
  );
  useEffect(() => {
    if (restored) return;
    restored = true;
    const r = rememberedState();
    if (r !== selectedState) {
      selectedState = r;
      listeners.forEach((l) => l());
    }
  }, []);
  return v;
}

/**
 * One state's NID extract, loaded on first use: the chosen state, or `state` when given (a record's own state, from
 * its NID ID). `reload()` asks the desktop server for the latest download.
 */
export function useNidData(
  enabled = true,
  state?: string,
): { data: NidData | null; error: string | null; loading: boolean; reload: () => void } {
  const chosen = useSelectedNidState();
  const want = state && isNidState(state) ? state : chosen;
  const [data, setData] = useState<NidData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    setError(null);
    setLoading(true);
    setData((d) => (d && d.state === want ? d : null));
    loadNidState(want, { refresh: refresh > 0 }).then(
      (d) => {
        if (!live) return;
        setData(d);
        setLoading(false);
      },
      (e: unknown) => {
        if (!live) return;
        setError(`Could not load the NID dams for ${stateName(want)}: ${(e as Error).message}`);
        setLoading(false);
      },
    );
    return () => {
      live = false;
    };
  }, [enabled, want, refresh]);
  return { data, error, loading, reload: () => setRefresh((n) => n + 1) };
}
