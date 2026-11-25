"""Draws the Local AI icon (a dam face holding back water, with a speech mark) at 1024 px and writes
local-ai.png (256), local-ai.icns (macOS) and local-ai.ico (Windows) into the folder given."""
import io, struct, sys, os
from PIL import Image, ImageDraw, ImageFilter

def draw(S=1024):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # rounded-square body with a vertical gradient (deep blue to teal)
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    top, bot = (24, 58, 92), (32, 140, 150)
    for y in range(S):
        t = y / (S - 1)
        gd.line([(0, y), (S, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)) + (255,))
    mask = Image.new("L", (S, S), 0)
    m = int(S * 0.09)
    ImageDraw.Draw(mask).rounded_rectangle([m, m, S - m, S - m], radius=int(S * 0.2), fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # water on the left, at the reservoir level
    lvl = int(S * 0.52)
    d.polygon([(m + 2, lvl), (int(S * 0.50), lvl), (int(S * 0.58), S - m - 2), (m + 2, S - m - 2)], fill=(120, 205, 230, 255))
    d.rectangle([m + 2, lvl + int(S*0.16), int(S*0.52), S - m - 2], fill=(120, 205, 230, 255))
    # the dam: a light trapezoid
    d.polygon([(int(S * 0.47), int(S * 0.40)), (int(S * 0.58), int(S * 0.40)), (int(S * 0.80), S - m - 2),
               (int(S * 0.55), S - m - 2)], fill=(236, 233, 222, 255))
    # tailwater on the right
    d.rectangle([int(S * 0.80), int(S * 0.84), S - m - 2, S - m - 2], fill=(120, 205, 230, 200))
    # re-apply the rounded mask so nothing pokes out
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    d = ImageDraw.Draw(out)
    # a speech bubble (the assistant) top left, orange
    bx0, by0, bx1, by1 = int(S * 0.20), int(S * 0.17), int(S * 0.50), int(S * 0.39)
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=int(S * 0.06), fill=(244, 158, 24, 255))
    d.polygon([(int(S * 0.27), by1 - 2), (int(S * 0.36), by1 - 2), (int(S * 0.25), int(S * 0.47))], fill=(244, 158, 24, 255))
    r = int(S * 0.022)
    for cx in (0.28, 0.35, 0.42):
        x, y = int(S * cx), (by0 + by1) // 2
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, 255))
    return out

def png_bytes(im, size):
    b = io.BytesIO(); im.resize((size, size), Image.LANCZOS).save(b, "PNG"); return b.getvalue()

def icns(im):
    entries = [(b"ic07", 128), (b"ic08", 256), (b"ic09", 512), (b"ic10", 1024), (b"ic11", 32), (b"ic12", 64), (b"ic13", 256), (b"ic14", 512)]
    body = b"".join(t + struct.pack(">I", 8 + len(p)) + p for t, p in ((t, png_bytes(im, s)) for t, s in entries))
    return b"icns" + struct.pack(">I", 8 + len(body)) + body

def main(out):
    im = draw()
    os.makedirs(out, exist_ok=True)
    im.resize((256, 256), Image.LANCZOS).save(os.path.join(out, "local-ai.png"), optimize=True)
    with open(os.path.join(out, "local-ai.icns"), "wb") as f:
        f.write(icns(im))
    im.save(os.path.join(out, "local-ai.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    im.resize((512, 512), Image.LANCZOS).save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "preview.png"))

main(sys.argv[1])
