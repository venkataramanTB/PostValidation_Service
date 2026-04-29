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
    if icon_path.exists():
        print(f"Using existing icon: {icon_path}")
        return
    icon_path.parent.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
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
    images[0].save(
        str(icon_path),
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )
    print(f"Generated icon: {icon_path}")


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
    step1_react()
    step2_pyinstaller()
    step3_electron()
    print("\nDone.")
