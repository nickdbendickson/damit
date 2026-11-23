/**
 * The desk's file chooser in a browser page: folders and DEM files on this computer, listed by the desk server
 * (server-picker.ts). Mounted once by the desk; DEM choice and the exports folder open it.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { listOnServer, rootLabels, setServerPicker, type Listing, type PickRequest } from "@/lib/crest/server-picker";

export function ServerFilePicker() {
  const [req, setReq] = useState<PickRequest | null>(null);
  const [list, setList] = useState<Listing | null>(null);
  const [typed, setTyped] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const done = useRef<((v: string | null) => void) | null>(null);

  const go = useCallback(async (dir: string | null, mode: PickRequest["mode"]) => {
    setErr(null);
    try {
      const l = await listOnServer(dir, mode);
      setList(l);
      setTyped(l.dir);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);

  useEffect(() => {
    setServerPicker(
      (r) =>
        new Promise<string | null>((resolve) => {
          done.current = resolve;
          setReq(r);
          setList(null);
          void go(r.start ?? null, r.mode);
        }),
    );
    return () => setServerPicker(null);
  }, [go]);

  const finish = (v: string | null) => {
    done.current?.(v);
    done.current = null;
    setReq(null);
  };

  if (!req) return null;
  const btn = "inline-flex h-9 items-center rounded-sm border border-line bg-paper px-3 text-sm text-ink disabled:opacity-50";
  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-label={req.title} data-testid="server-picker">
      <div className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-md border border-line bg-card p-4 shadow-lg">
        <h3 className="text-lg">{req.title}</h3>
        <p className="mt-1 text-xs text-muted">
          {req.mode === "csv"
            ? "Folders and CSV files the DamIT Desk server may show: the work folder, exports, the DamIT data folder and DEM folders."
            : req.mode === "dem"
            ? "Folders and DEM files (.vrt, .tif, .tiff, .img) the DamIT Desk server may show: the work folder, exports, the DamIT data folder and DEM folders. A VRT keeps reading its tiles where they are. For a DEM elsewhere, add its folder to DAMIT_DEM_ROOTS and restart the desk."
            : "Folders inside the DamIT Desk work folder (DAMIT_WORK_ROOTS adds others)."}
        </p>
        <form
          className="mt-2 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void go(typed, req.mode);
          }}
        >
          <input className="h-9 min-w-0 flex-1 rounded-sm border border-line bg-paper px-2 text-sm" value={typed} onChange={(e) => setTyped(e.target.value)} aria-label="Folder" />
          <button type="submit" className={btn}>
            Go
          </button>
          <button type="button" className={btn} disabled={!list?.parent} onClick={() => list?.parent && void go(list.parent, req.mode)}>
            Up
          </button>
          <button type="button" className={btn} onClick={() => void go(list?.home ?? null, req.mode)}>
            Work folder
          </button>
        </form>
        {list?.roots && list.roots.length > 1 ? (
          <div className="mt-2 flex flex-wrap gap-1 text-xs" data-testid="server-picker-roots">
            {list.roots.map((r, i) => (
              <button key={r} type="button" className="rounded-sm border border-line bg-paper px-2 py-0.5 hover:bg-sand" title={r} onClick={() => void go(r, req.mode)}>
                {rootLabels(list.roots ?? [])[i]}
              </button>
            ))}
          </div>
        ) : null}
        {err ? <p className="mt-2 text-sm text-red-700">{err}</p> : null}
        <ul className="mt-2 min-h-40 flex-1 overflow-auto rounded-sm border border-line bg-paper text-sm" data-testid="server-picker-list">
          {list?.entries.length === 0 ? <li className="px-3 py-2 text-muted">{req.mode === "dem" ? "No folders or DEM files here." : req.mode === "csv" ? "No folders or CSV files here." : "No folders here."}</li> : null}
          {list?.entries.map((e) => (
            <li key={e.path}>
              <button
                type="button"
                className="w-full px-3 py-1.5 text-left hover:bg-sand"
                onClick={() => (e.dir ? void go(e.path, req.mode) : finish(e.path))}
                title={e.path}
              >
                {e.dir ? "📁 " : "🗺 "}
                {e.name}
              </button>
            </li>
          ))}
        </ul>
        <div className="mt-3 flex flex-wrap justify-end gap-2">
          {req.mode === "folder" ? (
            <button type="button" className={btn} disabled={!list} onClick={() => list && finish(list.dir)}>
              Use this folder
            </button>
          ) : null}
          <button type="button" className={btn} onClick={() => finish(null)}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
