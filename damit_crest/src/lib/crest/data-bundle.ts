/**
 * The committed NID example extract (nid_example = data/nid_ND.json, about 200 KB) on demand. Other states' NID
 * extracts are downloaded by the desktop server (nid-state.ts); no other dam inventory is bundled.
 *
 * Web and desktop builds: a dynamic `import()` of the JSON, which Vite keeps as its own chunk (vite.desktop.config.ts
 * keeps it out of the first parse). The one-file DamIT.html cannot have a separate chunk, so there the
 * build packs the bundle as gzip + base64 into data/packed.ts and leaves the JSON
 * modules out; this inflates one with DecompressionStream the first time it is asked for, or with fflate's gunzip
 * (already a dependency, for the results import) in a browser without that API.
 *
 * Node (the tests, the batch command line) and Vite dev have an empty `packed` table and take the JSON import.
 */

export type BundleName = "nid_example";

/** gzip + base64 of each bundle when the single-file build packed it; empty otherwise (data/packed.ts). */
type Packed = Partial<Record<BundleName, string>>;

let packedTable: Promise<Packed> | null = null;
function packed(): Promise<Packed> {
  packedTable ??= import("./data/packed.ts").then(
    (m) => (m as { default?: Packed }).default ?? {},
    () => ({}),
  );
  return packedTable;
}

/** The bytes of a base64 string. */
export function base64ToBytes(b64: string): Uint8Array<ArrayBuffer> {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

/**
 * Inflate a gzip + base64 string to text: DecompressionStream where the browser has it (every current one; Safari
 * since 16.4), else fflate's gunzip, loaded on demand. Throws on a corrupt payload.
 */
export async function inflateBase64Gzip(b64: string, useStream = true): Promise<string> {
  const bytes = base64ToBytes(b64);
  const DS = (globalThis as { DecompressionStream?: typeof DecompressionStream }).DecompressionStream;
  if (useStream && typeof DS === "function" && typeof Response === "function") {
    try {
      const stream = new Blob([bytes]).stream().pipeThrough(new DS("gzip"));
      return await new Response(stream).text();
    } catch {
      // Fall through to fflate: a stream that fails mid-way (an old implementation) should not lose the bundle.
    }
  }
  const { gunzipSync, strFromU8 } = await import("fflate");
  return strFromU8(gunzipSync(bytes));
}

const loaders: Record<BundleName, () => Promise<unknown>> = {
  // The `with { type: "json" }` import attribute is required by Node's native ESM loader (the unit tests call this)
  // and accepted by Vite's production build, but Vite's dev server serves a dynamic `.json` import as a JS module,
  // which the attribute then rejects with a MIME-type error ("Expected a JSON module script … responded with
  // text/javascript"). So the attribute is dropped under Vite dev only. The `import.meta.env` guard is needed because
  // `import.meta.env` is undefined under `node --test`.
  nid_example: () => (viteDev() ? import("./data/nid_ND.json") : import("./data/nid_ND.json", { with: { type: "json" } })),
};

const viteDev = () => typeof import.meta !== "undefined" && typeof import.meta.env !== "undefined" && import.meta.env.DEV === true;

const cache = new Map<BundleName, Promise<unknown>>();

/** The parsed bundle, from the packed table when the build has one, else from its JSON module. Loaded once. */
export function loadBundle<T>(name: BundleName): Promise<T> {
  let p = cache.get(name);
  if (!p) {
    p = (async () => {
      const table = await packed();
      const b64 = table[name];
      if (b64) return JSON.parse(await inflateBase64Gzip(b64)) as unknown;
      const m = await loaders[name]();
      const data = (m as { default?: unknown }).default ?? m;
      // The single-file build leaves the JSON modules out (vite.desktop.config.ts packedDataPlugin), so a missing
      // packed entry there is a build fault, not a missing file.
      if (data == null) throw new Error(`The ${name} bundle is not in this build.`);
      return data;
    })();
    cache.set(name, p);
  }
  return p as Promise<T>;
}
