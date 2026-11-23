/** WCAG 2.x contrast (relative luminance of sRGB hex colours), for the palette checks in contrast.test.ts. */
function channel(v: number): number {
  const c = v / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  const n = parseInt(full, 16);
  return 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255);
}

export function contrastRatio(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

/** The custom properties set in one CSS block (`selector { --x: #abc; }`), lower-case hex only. */
export function cssVars(css: string, selector: string): Record<string, string> {
  const at = css.indexOf(selector + " {");
  if (at < 0) return {};
  const body = css.slice(at, css.indexOf("}", at));
  const out: Record<string, string> = {};
  for (const m of body.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{3,6})\b/g)) out[m[1]] = m[2].toLowerCase();
  return out;
}
