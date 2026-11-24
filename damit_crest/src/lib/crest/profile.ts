/**
 * The desk's profile: "us" (any state, NID only; the default) or "nd" (North Dakota: the NID plus the ND Department of
 * Water Resources' own dam values, joined on NID ID).
 *
 * One desk serves both (Nick, 2026-11-22: damit-desk is the one desk codebase, with ND and US profiles; the ND-only
 * dwr_crest desk and damit_crest retire into it). The profile only changes what the Record step offers to fill a
 * record from: in "nd", the dam picker is nd-dams.ts / NdDamPicker (NID + DWR height, NAVD 88 elevations after the
 * user confirms, DWR areas, DWR dugouts for reference, DWR-only dams). It never changes the engine, the jurisdiction
 * presets (jurisdiction.ts already starts an ND record on the North Dakota preset in either profile) or a saved record.
 *
 * Where it comes from, first match wins:
 *   1. the page address: `?profile=nd` (or `#...&profile=nd`), so a launcher or bookmark can open the ND desk;
 *   2. the user's last choice in Settings (localStorage), read once at start;
 *   3. "us".
 */
import { create } from "zustand";

export type DeskProfile = "us" | "nd";

export const PROFILE_KEY = "damit-desk-profile";

export const PROFILE_LABEL: Record<DeskProfile, string> = {
  us: "United States (NID)",
  nd: "North Dakota (NID + DWR dam values)",
};

export function isProfile(v: unknown): v is DeskProfile {
  return v === "us" || v === "nd";
}

/** The profile named in a page address (query or fragment), or null. */
export function profileFromAddress(search: string, hash = ""): DeskProfile | null {
  for (const part of [search.replace(/^\?/, ""), hash.replace(/^#/, "")]) {
    for (const kv of part.split("&")) {
      const [k, v] = kv.split("=");
      if (k === "profile") {
        const p = decodeURIComponent(v ?? "").trim().toLowerCase();
        if (isProfile(p)) return p;
      }
    }
  }
  return null;
}

type Storage = Pick<globalThis.Storage, "getItem" | "setItem">;

function storage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** The profile to start with: the address, else the stored choice, else "us". */
export function startProfile(loc?: { search: string; hash: string } | null, store: Storage | null = storage()): DeskProfile {
  const where = loc ?? (typeof window === "undefined" ? null : window.location);
  const fromAddress = where ? profileFromAddress(where.search ?? "", where.hash ?? "") : null;
  if (fromAddress) return fromAddress;
  try {
    const stored = store?.getItem(PROFILE_KEY);
    if (isProfile(stored)) return stored;
  } catch {
    // a blocked storage reads as no choice
  }
  return "us";
}

export const useProfile = create<{ profile: DeskProfile; setProfile: (p: DeskProfile) => void }>((set) => ({
  profile: startProfile(),
  setProfile: (p) => {
    try {
      storage()?.setItem(PROFILE_KEY, p);
    } catch {
      // the choice still holds for this session
    }
    set({ profile: p });
  },
}));
