/**
 * The desk's own file chooser for a browser page (Linux, or wherever the native window does not start). A browser
 * cannot give a page the path of a file on this computer, so the desk server lists folders
 * (desktop/damit_desktop/browser_io.py, GET /api/fs/list) and ServerFilePicker.tsx shows them. In the native window
 * (pywebview) the system's Open and Save dialogs are used instead and none of this runs.
 */
import { crestApiHeaders, desktopToken } from "./desktop-server.ts";

export type PickMode = "dem" | "folder" | "csv";
export type PickRequest = { mode: PickMode; title: string; start?: string | null };
type Opener = (req: PickRequest) => Promise<string | null>;

let opener: Opener | null = null;

/** ServerFilePicker registers itself here when it mounts. */
export function setServerPicker(f: Opener | null): void {
  opener = f;
}

/** True when the page came from the desk server: it was opened with the per-launch token (in the address fragment,
 * then sessionStorage; see desktop-server.ts). The served page itself never carries the token. */
export function hasDeskServer(): boolean {
  if (typeof document === "undefined") return false;
  return !!desktopToken();
}

/** Ask for a DEM file or a folder on this computer; null when cancelled or when there is no chooser. */
export function pickOnServer(req: PickRequest): Promise<string | null> {
  return opener ? opener(req) : Promise.resolve(null);
}

/** One folder as the desk server lists it. `roots` are the only folders it shows (the work folder, exports, the data
 * folder, DEM folders: browser_io.py read_roots); `home` is the first of them. */
export type Listing = { dir: string; parent: string | null; home: string; roots?: string[]; entries: { name: string; path: string; dir: boolean }[] };

export async function listOnServer(dir: string | null, mode: PickMode): Promise<Listing> {
  const q = new URLSearchParams({ mode, ...(dir ? { dir } : {}) });
  const r = await fetch(`/api/fs/list?${q.toString()}`, { headers: crestApiHeaders() });
  const body = (await r.json()) as Listing & { error?: string };
  if (!r.ok) throw new Error(body.error ?? `HTTP ${r.status}`);
  return body;
}

export async function postServer<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, { method: "POST", headers: crestApiHeaders(true), body: JSON.stringify(body) });
  const out = (await r.json()) as T & { error?: string };
  if (!r.ok) throw new Error(out.error ?? `HTTP ${r.status}`);
  return out;
}

export async function getServer<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: crestApiHeaders() });
  const out = (await r.json()) as T & { error?: string };
  if (!r.ok) throw new Error(out.error ?? `HTTP ${r.status}`);
  return out;
}

/** Short names for the picker's root shortcuts: the folder name, with its parent when two roots share a name. */
export function rootLabels(roots: string[]): string[] {
  const parts = roots.map((r) => r.split(/[\\/]/).filter(Boolean));
  const last = parts.map((p, i) => p[p.length - 1] || roots[i]!);
  return parts.map((p, i) =>
    last.filter((l) => l === last[i]).length > 1 && p.length > 1 ? `${p[p.length - 2]}/${last[i]}` : last[i]!,
  );
}
