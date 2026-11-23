/**
 * Click-to-zoom for the classify receptor tables: the row clicked on the Dashboard or the Report, which the Dashboard
 * map zooms to and marks. A tiny store so the Report can ask for a zoom before the Dashboard map is shown.
 */
import { create } from "zustand";

export type ReceptorFocus = {
  rid: string;
  name: string;
  bounds: { west: number; south: number; east: number; north: number };
  at: [number, number] | null;
  /** Changes on every click, so clicking the same row again zooms back to it. */
  seq: number;
};

type State = { focus: ReceptorFocus | null; zoomTo: (f: Omit<ReceptorFocus, "seq">) => void; clear: () => void };

export const useReceptorFocus = create<State>((set, get) => ({
  focus: null,
  zoomTo: (f) => set({ focus: { ...f, seq: (get().focus?.seq ?? 0) + 1 } }),
  clear: () => set({ focus: null }),
}));
