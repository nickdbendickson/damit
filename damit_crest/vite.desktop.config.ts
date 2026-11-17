/**
 * Static build of the DamIT Crest desk for the desktop app (desktop/). DamIT Crest is local only: there is no web
 * deploy, server, sign-in or hosted build (Crest's TanStack Start / Vercel app was left out). Output:
 * desktop/damit_desktop/web/ — plain files, relative paths,
 * Leaflet / leaflet-draw / marker icons bundled, no CDN, no Google Fonts. Basemap tiles need the network, and so do the
 * on-request lookups (3DEP terrain, 911 points, PLSS sections), each one request that is then saved with the dam.
 *
 * `--mode singlefile` (`npm run build:html`) builds the same desk into ONE self-contained file, DamIT.html in this
 * folder (JS, CSS, Leaflet images and the favicon inlined). It is not committed (.gitignore); build it when you want a
 * one-file copy to open without Python. The Report-step plugin buttons need the desktop app.
 *
 * Build with `npm run build:desktop`. The bundle is committed so `python desktop/run.py` needs no Node. build-info.json lists
 * every repo source file that went into it with its SHA-256; the desktop tests recompute those hashes and fail when the
 * committed bundle is older than the sources (rebuild and commit it).
 *
 * Build after `npm ci`, so node_modules matches package-lock.json. The build is reproducible from the lockfile (two
 * builds give identical files); a bundle built after a plain `npm install` picked up React 19.3.1 instead of the
 * locked 19.3.0, and a later lockfile build then rewrote the assets with small diffs.
 */
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import type { Plugin } from "vite";
import { defineConfig, loadEnv } from "vite";
import viteReact from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { crestVersion } from "./scripts/crest-version.mjs";
import { contentSecurityPolicy, SECURITY_HEADERS } from "./src/lib/crest/csp.ts";

const r = (p: string) => fileURLToPath(new URL(p, import.meta.url));
const ROOT = r("./");

/** SHA-256 of a text file with CRLF folded to LF, so a Windows checkout hashes the same as Linux. */
function sha256(file: string): string {
  return createHash("sha256").update(readFileSync(file, "utf8").replace(/\r\n/g, "\n")).digest("hex");
}

/** Writes build-info.json. */
function buildInfoPlugin(): Plugin {
  return {
    name: "damit-desktop:build-info",
    apply: "build",
    generateBundle() {
      this.emitFile({ type: "asset", fileName: "build-info.json", source: buildInfo(this.getModuleIds()) });
    },
  };
}

/** build-info JSON: the repo files (not node_modules) that went into the bundle, with their hashes. */
function buildInfo(moduleIds: Iterable<string>, builtBy = "npm run build:desktop"): string {
  const sources: Record<string, string> = {};
  for (const id of moduleIds) {
    const file = id.split("?")[0];
    if (!file.startsWith(ROOT) || file.includes("/node_modules/") || file.includes("\0")) continue;
    const rel = relative(ROOT, file).split("\\").join("/");
    sources[rel] = sha256(file);
  }
  const sorted = Object.fromEntries(Object.entries(sources).sort(([a], [b]) => a.localeCompare(b)));
  const pkg = JSON.parse(readFileSync(r("./package.json"), "utf8")) as { name?: string };
  return JSON.stringify({ app: pkg.name ?? "damit-crest", builtBy, sources: sorted }, null, 2) + "\n";
}

/** The build's VITE_CREST_TILE_URL (basemap.ts), read the way Vite reads it for the bundle, so the policy allows it. */
function configuredTileUrl(mode: string): string | undefined {
  return loadEnv(mode, r("./src/desktop"), "VITE_").VITE_CREST_TILE_URL || undefined;
}

/** `sha384-…` / `sha256-…` of a string or bytes, as Subresource Integrity and CSP hash sources write it. */
function integrity(algo: "sha256" | "sha384", data: string | Uint8Array): string {
  return `${algo}-${createHash(algo).update(data).digest("base64")}`;
}

/**
 * Desktop bundle security files (2026-11-13):
 *  - security-headers.json: the Content-Security-Policy (src/lib/crest/csp.ts) and the other security headers; the
 *    Python server (desktop/damit_desktop/__main__.py) sends them with every response, so the policy has one source.
 *  - `integrity="sha384-…"` on index.html's entry script, its preloads and its stylesheet (Subresource Integrity): the
 *    window refuses a bundle file that does not match the index.html it shipped with. The repo's .gitattributes keeps
 *    git from rewriting line endings in the bundle, which would change the hashes on a Windows checkout.
 */
function desktopSecurityPlugin(mode: string): Plugin {
  return {
    name: "damit-desktop:security",
    apply: "build",
    enforce: "post",
    // After the files are written: Vite still rewrites the entry chunk (its preload list) after generateBundle, so the
    // hashes are taken from the bytes on disk, the bytes the window will load.
    writeBundle(options) {
      const out = options.dir ?? r("./desktop/damit_desktop/web");
      const index = join(out, "index.html");
      let n = 0;
      const text = readFileSync(index, "utf8").replace(
        /<(?:script|link)\b[^>]*?\s(?:src|href)="\.\/(assets\/[^"]+\.(?:js|css))"[^>]*>/g,
        (tag, name: string) => {
          n++;
          return tag.replace(/\s*\/?>$/, (end: string) => ` integrity="${integrity("sha384", readFileSync(join(out, name)))}"${end}`);
        },
      );
      if (!n) throw new Error("security: index.html has no script or stylesheet to put an integrity hash on");
      writeFileSync(index, text);
      const headers = { "Content-Security-Policy": contentSecurityPolicy({ tileUrl: configuredTileUrl(mode) }), ...SECURITY_HEADERS };
      writeFileSync(join(out, "security-headers.json"), JSON.stringify(headers, null, 2) + "\n");
    },
  };
}

/**
 * The committed NID example extract inside the one-file DamIT.html: gzip + base64 instead of the JSON flattened into
 * the page's one script. src/lib/crest/data/packed.ts is the empty stand-in every other build sees; here it is
 * replaced by a module whose default export carries the bundle packed, and the JSON module data-bundle.ts would
 * otherwise import is replaced by an empty stub so it is not inlined as well. data-bundle.ts inflates it on first use
 * with DecompressionStream, or fflate's gunzip (already a dependency) where a browser lacks it.
 */
const PACKED_BUNDLES = { nid_example: "nid_ND" } as const;
const OMITTED_JSON = "\0damit:json-omitted";
function packedDataPlugin(): Plugin {
  const stub = r("./src/lib/crest/data/packed.ts");
  const loader = r("./src/lib/crest/data-bundle.ts");
  return {
    name: "damit-desktop:packed-data",
    apply: "build",
    enforce: "pre",
    resolveId(source, importer) {
      // Only data-bundle.ts's own fallback imports are stubbed; a test or script importing a bundle is left alone.
      if (importer && importer.split("?")[0] === loader && /^\.\/data\/nid_[A-Za-z_]+\.json$/.test(source)) return OMITTED_JSON;
      return null;
    },
    load(id) {
      if (id === OMITTED_JSON) return "export default null;\n";
      if (id.split("?")[0] !== stub) return null;
      const entries = Object.entries(PACKED_BUNDLES).map(([name, file]) => {
        const json = readFileSync(r(`./src/lib/crest/data/${file}.json`), "utf8");
        return `  ${name}: ${JSON.stringify(gzipSync(Buffer.from(json, "utf8"), { level: 9 }).toString("base64"))},`;
      });
      return `const packed = {\n${entries.join("\n")}\n};\nexport default packed;\n`;
    },
  };
}

/** Inline the one JS chunk and the CSS into the HTML and emit it as DamIT.html (what vite-plugin-singlefile does). */
function singleFilePlugin(mode: string): Plugin {
  return {
    name: "damit-desktop:single-file",
    apply: "build",
    enforce: "post",
    generateBundle(_options, bundle) {
      const html = Object.values(bundle).find((f) => f.type === "asset" && f.fileName.endsWith(".html"));
      if (!html || html.type !== "asset") throw new Error("single-file: no HTML in the bundle");
      let text = String(html.source);
      for (const [name, file] of Object.entries(bundle)) {
        if (file === html) continue;
        const ref = new RegExp(`<script[^>]*src="\\./${name.replace(/[.]/g, "\\.")}"[^>]*></script>|<link[^>]*href="\\./${name.replace(/[.]/g, "\\.")}"[^>]*>`);
        if (file.type === "chunk") {
          // With code splitting off Vite leaves its preload-deps placeholder unreplaced; there is nothing to preload.
          const code = file.code.replace(/__VITE_PRELOAD__/g, "void 0").replace(/<\/(script)/gi, "<\\/$1");
          text = text.replace(ref, () => `<script type="module">\n${code}</script>`);
        } else if (name.endsWith(".css")) {
          text = text.replace(ref, () => `<style>\n${String(file.source)}</style>`);
        } else {
          // An asset the HTML links directly (the favicon): Vite does not inline those, so use a data: URL.
          const type = name.endsWith(".svg") ? "image/svg+xml" : name.endsWith(".png") ? "image/png" : "";
          if (!type || !text.includes(`"./${name}"`)) throw new Error(`single-file: ${name} was not inlined`);
          const data = Buffer.from(file.source).toString("base64");
          text = text.split(`"./${name}"`).join(`"data:${type};base64,${data}"`);
        }
        delete bundle[name];
      }
      if (/(src|href)="\.\/assets\//.test(text)) throw new Error("single-file: a reference to ./assets/ is left");
      // Content-Security-Policy for the one file (src/lib/crest/csp.ts): only the script inlined above may run, by
      // its SHA-256, and the page may reach only the tile and lookup services the desk names. Opened from disk the
      // file has no origin of its own to trust, so 'self' is left out.
      const scripts = [...text.matchAll(/<script type="module">([\s\S]*?)<\/script>/g)].map((m) => m[1]);
      if (scripts.length !== 1) throw new Error(`single-file: expected one inline script, found ${scripts.length}`);
      const csp = contentSecurityPolicy({ delivery: "meta", self: false, tileUrl: configuredTileUrl(mode), scriptHashes: [integrity("sha256", scripts[0])] });
      text = text.replace("<head>", `<head>\n    <meta http-equiv="Content-Security-Policy" content="${csp}" />`);
      if (!text.includes("Content-Security-Policy")) throw new Error("single-file: no <head> to carry the policy");
      const info = buildInfo(this.getModuleIds(), "npm run build:html").replace(/--/g, "- -");
      delete bundle[html.fileName];
      writeFileSync(
        r("./DamIT.html"),
        `<!-- Generated by \`npm run build:html\` from src/ (the same desk and engine as the DamIT Crest desktop app). Do not edit.\ndamit-build-info ${info}-->\n${text}`,
      );
    },
  };
}

export default defineConfig(({ mode }) => (mode === "singlefile" ? singleFile(mode) : desktop(mode)));

/** Chunks the groups below name; kept at their own names (a group chunk is not a dynamic entry). */
const LAZY_CHUNKS = ["nid_dams", "geotiff"];

const desktop = (mode: string) => defineConfig({
  root: r("./src/desktop"),
  base: "./",
  publicDir: false,
  // Build version for the exports (src/lib/crest/version.ts): package.json version + git SHA of HEAD, never a
  // timestamp, so the committed bundle stays reproducible from the same tree.
  define: { __CREST_VERSION__: JSON.stringify(crestVersion()) },
  resolve: { alias: { "@": r("./src") } },
  plugins: [tailwindcss(), viteReact(), buildInfoPlugin(), desktopSecurityPlugin(mode)],
  build: {
    outDir: r("./desktop/damit_desktop/web"),
    emptyOutDir: true,
    sourcemap: false,
    modulePreload: { polyfill: false },
    rollupOptions: {
      input: { index: r("./src/desktop/index.html"), engine: r("./src/desktop/engine-entry.ts") },
      preserveEntrySignatures: "exports-only",
      output: {
        // Stable names keep the committed bundle's diffs readable. Rollup names a shared chunk after one of its
        // modules, and which one moves with small source edits (samples.js became export.js), so the one chunk
        // index and engine share always keeps the name it was first committed under.
        entryFileNames: "assets/[name].js",
        chunkFileNames: (chunk) => (chunk.isDynamicEntry || LAZY_CHUNKS.includes(chunk.name) ? "assets/[name].js" : "assets/samples.js"),
        assetFileNames: "assets/[name][extname]",
        // The NID example extract and geotiff stay their own chunks, loaded only when the picker, the Batch view or
        // a results import asks for them, whatever else shares a module with
        // them. Rolldown's `codeSplitting.groups` is the manualChunks of Vite 8 (Rollup's manualChunks is deprecated
        // there); the test is on the module id. `priority` puts a data module in its group before the default
        // sharing rules could fold it into the desk chunk.
        codeSplitting: {
          groups: [
            { name: "nid_dams", test: /[\\/]src[\\/]lib[\\/]crest[\\/]data[\\/]nid_[A-Za-z_]+\.json/, priority: 30 },
            { name: "geotiff", test: /[\\/]node_modules[\\/]geotiff[\\/]/, priority: 20 },
          ],
        },
      },
    },
  },
});

/** DamIT.html: the desk alone (no engine facade), everything in one file. */
const singleFile = (mode: string) => defineConfig({
  ...desktop(mode),
  plugins: [packedDataPlugin(), tailwindcss(), viteReact(), singleFilePlugin(mode)],
  build: {
    outDir: r("./node_modules/.cache/damit-html"), // stays empty: the plugin writes DamIT.html in this folder
    emptyOutDir: true,
    copyPublicDir: false,
    sourcemap: false,
    cssCodeSplit: false,
    assetsInlineLimit: () => true,
    modulePreload: { polyfill: false },
    rollupOptions: {
      input: { index: r("./src/desktop/index.html") },
      output: { codeSplitting: false, entryFileNames: "assets/[name].js", assetFileNames: "assets/[name][extname]" },
    },
  },
});
