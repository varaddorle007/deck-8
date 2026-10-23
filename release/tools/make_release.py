#!/usr/bin/env python3
"""Assemble release/deck8-RevA-manufacturing/ and its zip from the current build outputs.

  python3 release/tools/make_release.py

PCB files come from hardware/build/fab (make_fab.py), enclosure parts from mechanical/exports (Deck8Model.py).
STLs of the parts exported on the 8.13 deg slope (plate, lens) are turned flat and every part is dropped to z = 0, so they load
print-ready; the lens and switch plate also get DXF outlines for laser cutting.
"""
import ast
import math
import os
import shutil
import struct
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FAB = os.path.join(ROOT, "hardware", "build", "fab")
EXP = os.path.join(ROOT, "mechanical", "exports")
FUSION = os.path.join(ROOT, "mechanical", "fusion", "Deck8Model", "Deck8Model.py")
OUT = os.path.join(ROOT, "release", "deck8-RevA-manufacturing")
GUIDE = os.path.join(ROOT, "release", "BUILD-GUIDE.md")
FW = os.path.join(ROOT, "firmware")
BUY = os.path.join(ROOT, "release", "BUY-LIST.csv")

# part, copies, turn flat (the part lies on the slope)
STL = [("Top_Shell", 1, False), ("Bottom_Tray", 1, False), ("Light_Ring", 1, False), ("Switch_Plate", 1, True),
       ("Knob", 2, False), ("Button_L1", 1, False), ("Button_L2", 1, False), ("Button_System", 1, False),
       ("OLED_Lens", 1, True)]


def layout():
    want = {"KEY_X", "KEY_Y", "LENS", "PARAMS"}
    out = {}
    for node in ast.parse(open(FUSION).read()).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in want:
            out[node.targets[0].id] = ast.literal_eval(node.value)
    p = {n: float(e.split()[0]) for n, e, _ in out["PARAMS"]}
    out["tilt"] = math.atan((p["h_back"] - p["h_front"]) / p["case_d"])
    return out


def read_stl(path):
    d = open(path, "rb").read()
    n = struct.unpack("<I", d[80:84])[0]
    return [struct.unpack("<12f", d[84 + i * 50:84 + i * 50 + 48]) for i in range(n)]


def write_stl(path, tris, name):
    with open(path, "wb") as f:
        f.write(name.encode()[:80].ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        for t in tris:
            f.write(struct.pack("<12fH", *t, 0))


def place(tris, tilt):
    """Turn about X by -tilt when asked, then move the part to sit on z = 0, centred on X/Y."""
    c, s = math.cos(-tilt), math.sin(-tilt)
    rot = lambda x, y, z: (x, y * c - z * s, y * s + z * c)
    out = []
    for t in tris:
        pts = [rot(*t[3 + 3 * k:6 + 3 * k]) for k in range(3)]
        nrm = rot(*t[0:3])
        out.append((nrm, pts))
    xs = [p[0] for _, ps in out for p in ps]
    ys = [p[1] for _, ps in out for p in ps]
    zs = [p[2] for _, ps in out for p in ps]
    dx, dy, dz = -(min(xs) + max(xs)) / 2, -(min(ys) + max(ys)) / 2, -min(zs)
    res = [(*n, *[v for p in ps for v in (p[0] + dx, p[1] + dy, p[2] + dz)]) for n, ps in out]
    return res, (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))


def dxf(path, loops):
    """Minimal R12 DXF: each loop is a list of ('L', x0, y0, x1, y1) or ('A', cx, cy, r, a0, a1) in mm."""
    body = ["0", "SECTION", "2", "HEADER", "9", "$INSUNITS", "70", "4", "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"]
    for loop in loops:
        for e in loop:
            if e[0] == "L":
                body += ["0", "LINE", "8", "0", "10", f"{e[1]:.4f}", "20", f"{e[2]:.4f}", "11", f"{e[3]:.4f}", "21", f"{e[4]:.4f}"]
            else:
                body += ["0", "ARC", "8", "0", "10", f"{e[1]:.4f}", "20", f"{e[2]:.4f}", "40", f"{e[3]:.4f}",
                         "50", f"{e[4]:.4f}", "51", f"{e[5]:.4f}"]
    body += ["0", "ENDSEC", "0", "EOF"]
    open(path, "w").write("\n".join(body) + "\n")


def rounded_rect(cx, cy, w, h, r):
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    if r <= 0:
        return [("L", x0, y0, x1, y0), ("L", x1, y0, x1, y1), ("L", x1, y1, x0, y1), ("L", x0, y1, x0, y0)]
    return [("L", x0 + r, y0, x1 - r, y0), ("A", x1 - r, y0 + r, r, 270, 360), ("L", x1, y0 + r, x1, y1 - r),
            ("A", x1 - r, y1 - r, r, 0, 90), ("L", x1 - r, y1, x0 + r, y1), ("A", x0 + r, y1 - r, r, 90, 180),
            ("L", x0, y1 - r, x0, y0 + r), ("A", x0 + r, y0 + r, r, 180, 270)]


def main():
    L = layout()
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    pcb, ref, enc, fw = (os.path.join(OUT, d) for d in ("1-PCB-order-JLCPCB", "2-PCB-reference", "3-Enclosure",
                                                         "4-Firmware"))
    for d in (pcb, ref, enc, fw, os.path.join(enc, "print-STL"), os.path.join(enc, "laser-cut-DXF")):
        os.makedirs(d)
    for f in ("deck8-RevA-gerbers.zip", "deck8-RevA-bom-jlc.csv", "deck8-RevA-cpl-jlc.csv"):
        shutil.copy(os.path.join(FAB, f), pcb)
    shutil.copy(os.path.join(FAB, "README.md"), os.path.join(pcb, "JLC-ORDER-SETTINGS.md"))
    for f in ("deck8-RevA-bom-full.csv", "deck8-RevA-assembly-top.pdf", "deck8-RevA-assembly-bottom.pdf",
              "check_gerbers.png"):
        shutil.copy(os.path.join(FAB, f), ref)
    sizes = {}
    for name, n, flat in STL:
        tris, size = place(read_stl(os.path.join(EXP, "stl", f"{name}.stl")), L["tilt"] if flat else 0.0)
        suffix = f"_x{n}" if n > 1 else ""
        write_stl(os.path.join(enc, "print-STL", f"Deck8_{name}{suffix}.stl"), tris, f"Deck-8 Rev A {name}")
        sizes[name] = size
    shutil.copy(os.path.join(EXP, "deck8_assembly.step"), os.path.join(enc, "Deck8_assembly_reference.step"))
    lw, lh, _ = L["LENS"]
    dxf(os.path.join(enc, "laser-cut-DXF", "Deck8_OLED_Lens_1mm_acrylic.dxf"), [rounded_rect(0, 0, lw - 0.2, lh - 0.2, 0.9)])
    plate = [rounded_rect(0, 0, 84.0, 41.0, 0.0)]
    for y in L["KEY_Y"]:
        for x in L["KEY_X"]:
            plate.append(rounded_rect(x, y + 1.5, 14.0, 14.0, 0.0))
    dxf(os.path.join(enc, "laser-cut-DXF", "Deck8_Switch_Plate_1.5mm.dxf"), plate)
    for f in ("deck8.uf2", "deck8.hex"):
        shutil.copy(os.path.join(FW, "out", f), fw)
    shutil.copy(os.path.join(FW, "README.md"), os.path.join(fw, "FIRMWARE.md"))
    shutil.copy(os.path.join(FW, "config", "deck8.keymap"), fw)
    shutil.copy(GUIDE, os.path.join(OUT, "BUILD-GUIDE.md"))
    shutil.copy(BUY, os.path.join(OUT, "BUY-LIST.csv"))
    zpath = OUT + ".zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _, files in os.walk(OUT):
            for f in sorted(files):
                p = os.path.join(base, f)
                z.write(p, os.path.relpath(p, os.path.dirname(OUT)))
    for k, v in sizes.items():
        print(f"{k:14s} {v[0]:6.2f} x {v[1]:6.2f} x {v[2]:6.2f} mm")
    print(f"wrote {zpath} ({os.path.getsize(zpath) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
