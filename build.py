#!/usr/bin/env python3
"""
Build PostValidation Service desktop app.

Outputs (in release/):
  PostValidation-1.0.0-portable.exe
  PostValidation Service Setup 1.0.0.exe

Usage:
  python build.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(cmd, cwd=None):
    cwd = cwd or ROOT
    print(f"\n>>> {cmd if isinstance(cmd, str) else ' '.join(str(c) for c in cmd)}")
    subprocess.run(cmd, cwd=str(cwd), check=True, shell=isinstance(cmd, str))


def ensure_pillow():
    try:
        import PIL  # noqa: F401
    except ImportError:
        print("Installing Pillow...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pillow"], check=True)


def generate_icon():
    from PIL import Image, ImageDraw

    icon_path = ROOT / "assets" / "icon.ico"
    if icon_path.exists() and icon_path.stat().st_size > 0:
        print(f"Using existing icon: {icon_path}")
        return
    icon_path.parent.mkdir(parents=True, exist_ok=True)

    sizes = [256, 128, 64, 48, 32, 24, 16]  # largest first
    images = []
    for sz in sizes:
        img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        m = max(1, sz // 8)
        draw.rounded_rectangle(
            [m, m, sz - m - 1, sz - m - 1],
            radius=max(2, sz // 5),
            fill=(184, 115, 51, 255),
        )
        if sz >= 48:
            lw = max(2, sz // 16)
            cx = sz // 2 - sz // 10
            draw.rectangle(
                [cx, sz // 4, cx + lw, sz * 3 // 4],
                fill=(240, 235, 224),
            )
        images.append(img)

    # Save: primary image is 256x256 (images[0])
    images[0].save(
        str(icon_path),
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )
    print(f"Generated icon: {icon_path} (primary: 256x256)")



def generate_installer_bitmaps():
    """Generate neomorphic/skeuomorphic NSIS installer bitmaps."""
    from PIL import Image, ImageDraw, ImageFont
    import random

    assets = ROOT / "assets"
    sidebar_path = assets / "installer-sidebar.bmp"
    header_path  = assets / "installer-header.bmp"
    if (sidebar_path.exists() and sidebar_path.stat().st_size > 0 and
            header_path.exists() and header_path.stat().st_size > 0):
        print("Using existing installer bitmaps")
        return
    assets.mkdir(parents=True, exist_ok=True)

    BG        = (44,  36,  32)
    CARD      = (54,  44,  39)
    INSET_C   = (36,  29,  25)
    SHADOW    = (20,  15,  12)
    HILIT     = (72,  58,  50)
    COPPER    = (184, 115,  51)
    COPPER_LT = (220, 165,  90)
    COPPER_DK = (128,  76,  26)
    TEXT_W    = (240, 235, 224)
    TEXT_DIM  = ( 88,  74,  62)

    def font(sz):
        for p in [
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibri.ttf",
        ]:
            try:
                return ImageFont.truetype(p, sz)
            except OSError:
                pass
        try:
            return ImageFont.load_default(size=sz)
        except TypeError:
            return ImageFont.load_default()

    def raised_rect(draw, x1, y1, x2, y2, r, depth=6):
        """Neomorphic raised card: dark shadow bottom-right, light highlight top-left."""
        for i in range(depth, 0, -1):
            t = i / depth
            sc = tuple(max(0,   int(BG[j] - 24 * t)) for j in range(3))
            hc = tuple(min(255, int(BG[j] + 26 * t)) for j in range(3))
            draw.rounded_rectangle([x1+i, y1+i, x2+i, y2+i], radius=r, fill=sc)
            draw.rounded_rectangle([x1-i, y1-i, x2-i, y2-i], radius=r, fill=hc)
        draw.rounded_rectangle([x1, y1, x2, y2], radius=r, fill=CARD)

    img  = Image.new("RGB", (164, 314), BG)
    draw = ImageDraw.Draw(img)

    rng = random.Random(42)
    for _ in range(1200):
        x, y = rng.randint(0, 163), rng.randint(0, 313)
        v = rng.choice((-5, -4, -3, 3, 4, 5))
        img.putpixel((x, y), tuple(max(0, min(255, BG[j] + v)) for j in range(3)))

    hatch_col = tuple(max(0, c - 4) for c in BG)
    for i in range(-314, 164, 22):
        draw.line([(i, 0), (i + 314, 314)], fill=hatch_col, width=1)

    sm, sl, sg = 7, 5, 4
    stitch = tuple(max(0, c - 16) for c in BG)
    x = sm
    while x < 164 - sm:
        draw.line([(x, sm),       (min(156, x + sl), sm)],       fill=stitch)
        draw.line([(x, 313 - sm), (min(156, x + sl), 313 - sm)], fill=stitch)
        x += sl + sg
    y = sm
    while y < 314 - sm:
        draw.line([(sm,       y), (sm,       min(306, y + sl))], fill=stitch)
        draw.line([(163 - sm, y), (163 - sm, min(306, y + sl))], fill=stitch)
        y += sl + sg

    draw.rectangle([0, 0,   163, 2],   fill=COPPER_LT)
    draw.rectangle([0, 1,   163, 2],   fill=COPPER)
    draw.rectangle([0, 311, 163, 313], fill=COPPER_DK)

    raised_rect(draw, 12, 42, 152, 272, 18, depth=7)

    bx1, by1, bx2, by2 = 26, 54, 138, 72
    draw.rounded_rectangle([bx1 + 1, by1 + 1, bx2 + 1, by2 + 1], radius=4, fill=COPPER_DK)
    for x in range(bx1, bx2 + 1):
        t  = (x - bx1) / max(bx2 - bx1, 1)
        tt = 1 - abs(t - 0.5) * 2
        rc = int(COPPER_DK[0] + (COPPER_LT[0] - COPPER_DK[0]) * tt)
        gc = int(COPPER_DK[1] + (COPPER_LT[1] - COPPER_DK[1]) * tt)
        bc = int(COPPER_DK[2] + (COPPER_LT[2] - COPPER_DK[2]) * tt)
        draw.line([(x, by1), (x, by2)], fill=(rc, gc, bc))
    draw.rectangle([bx1, by1, bx2, by1 + 2], fill=COPPER_LT)

    f17 = font(17)
    f11 = font(11)
    f9  = font(9)
    ty = 78
    for txt, fnt, col, dy in [
        ("PostValidation", f17, TEXT_W,  0),
        ("S E R V I C E",  f11, COPPER, 22),
    ]:
        bb = draw.textbbox((0, 0), txt, font=fnt)
        tx = (164 - (bb[2] - bb[0])) // 2
        draw.text((tx + 1, ty + dy + 1), txt, fill=SHADOW, font=fnt)
        draw.text((tx,     ty + dy),     txt, fill=col,    font=fnt)

    draw.rectangle([32, 116, 132, 117], fill=COPPER_DK)
    draw.rectangle([32, 115, 132, 115], fill=COPPER_LT)

    ecx, ecy, ER = 82, 190, 36
    for i in range(7, 0, -1):
        t  = i / 7
        dc = tuple(max(0, int(CARD[j] - 22 * t)) for j in range(3))
        draw.ellipse([ecx - ER + i, ecy - ER + i, ecx + ER - i, ecy + ER - i], fill=dc)
    draw.ellipse([ecx - ER + 7, ecy - ER + 7, ecx + ER - 7, ecy + ER - 7], fill=INSET_C)

    for offset, col in [(0, COPPER_DK), (1, COPPER), (2, COPPER_LT)]:
        r2 = ER - 13 - offset
        draw.ellipse([ecx - r2, ecy - r2, ecx + r2, ecy + r2], outline=col, width=1)

    draw.ellipse([ecx - 10, ecy - 10, ecx + 10, ecy + 10], fill=COPPER_DK)
    draw.ellipse([ecx - 9,  ecy - 9,  ecx + 9,  ecy + 9],  fill=COPPER)
    draw.ellipse([ecx - 5,  ecy - 9,  ecx,      ecy - 2],   fill=COPPER_LT)

    for i, dx in enumerate([-18, -9, 0, 9, 18]):
        r2  = 3 if i == 2 else 2
        fc  = COPPER if i == 2 else COPPER_DK
        dot_y = ecy + ER + 10
        draw.ellipse([ecx + dx - r2, dot_y - r2, ecx + dx + r2, dot_y + r2], fill=fc)

    bb = draw.textbbox((0, 0), "v 1.0.0", font=f9)
    draw.text(((164 - (bb[2] - bb[0])) // 2, 256), "v 1.0.0", fill=TEXT_DIM, font=f9)

    bt = "Powered by Mythics"
    bb = draw.textbbox((0, 0), bt, font=f9)
    draw.text(((164 - (bb[2] - bb[0])) // 2, 296), bt, fill=TEXT_DIM, font=f9)

    img.save(str(sidebar_path), format="BMP")
    print(f"Generated installer sidebar: {sidebar_path}")

    hdr  = Image.new("RGB", (150, 57), BG)
    dh   = ImageDraw.Draw(hdr)

    for y in range(57):
        t = 1 - y / 57
        c = tuple(min(255, int(BG[j] + (HILIT[j] - BG[j]) * t * 0.3)) for j in range(3))
        dh.line([(0, y), (149, y)], fill=c)

    dh.rectangle([0,   0,  149, 3],  fill=COPPER)
    dh.rectangle([0,   0,  149, 1],  fill=COPPER_LT)
    dh.rectangle([0,   0,    2, 56], fill=COPPER_DK)
    dh.rectangle([0,  54,  149, 56], fill=COPPER_DK)

    f13 = font(13)
    f9h = font(9)
    for txt, fnt, col, y in [
        ("PostValidation",       f13, TEXT_W,  11),
        ("Service  .  Mythics",  f9h, COPPER,  28),
    ]:
        bb = dh.textbbox((0, 0), txt, font=fnt)
        dh.text((149 - (bb[2] - bb[0]) - 7, y), txt, fill=col, font=fnt)

    hdr.save(str(header_path), format="BMP")
    print(f"Generated installer header: {header_path}")

def step1_react():
    print("\n" + "=" * 60)
    print("STEP 1: Building React frontend")
    print("=" * 60)
    if not (ROOT / "frontend" / "node_modules").exists():
        print("Installing frontend npm dependencies...")
        run("npm install", cwd=ROOT / "frontend")
    run("npm run build", cwd=ROOT / "frontend")
    assert (ROOT / "frontend" / "build" / "index.html").exists(), "React build failed"
    print("React build OK")


def step2_pyinstaller():
    print("\n" + "=" * 60)
    print("STEP 2: Bundling Python backend (PyInstaller)")
    print("=" * 60)
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        run([sys.executable, "-m", "pip", "install", "pyinstaller>=6"])
    run([sys.executable, "-m", "PyInstaller", "backend.spec", "--clean", "--noconfirm"])
    backend_exe = ROOT / "dist" / "backend" / "backend.exe"
    assert backend_exe.exists(), f"backend.exe not found: {backend_exe}"
    print(f"backend.exe  ({backend_exe.stat().st_size / 1024 / 1024:.0f} MB)")


def step3_electron():
    print("\n" + "=" * 60)
    print("STEP 3: Packaging Electron app")
    print("=" * 60)
    if not (ROOT / "node_modules").exists():
        print("Installing npm dependencies...")
        run("npm install", cwd=ROOT)
    run("npx electron-builder --win", cwd=ROOT)
    print("\nOutputs:")
    for f in sorted((ROOT / "release").glob("*.exe")):
        print(f"  {f.name}  ({f.stat().st_size / 1024 / 1024:.0f} MB)")


if __name__ == "__main__":
    print("PostValidation Service — Desktop Build")
    print("=" * 60)
    ensure_pillow()
    generate_icon()
    generate_installer_bitmaps()
    step1_react()
    step2_pyinstaller()
    step3_electron()
    print("\nDone.")
