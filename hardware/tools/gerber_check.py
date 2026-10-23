#!/usr/bin/env python3
"""Read the fab package back without KiCad and compare it with facts measured on the board (facts.json, written by
make_fab.py):

  - every layer file present, and the zip holds exactly the Gerber folder
  - board outline (Edge.Cuts) matches the board's outline
  - drill files: hole count per diameter matches the board's vias, plated and non-plated holes
  - copper: one via flash per via on every copper layer, one pad flash per pad on its layers
  - mask: no opening on any via (tented); paste only on bottom-side SMD pads
  - BOM and CPL: same parts, every part with an LCSC number, every placement on the board and next to its own pads

It also renders the copper layers and the bottom assembly view from the Gerbers to build/fab/check_*.png.
Usage: python3 gerber_check.py build/fab
"""
import csv
import json
import math
import os
import re
import sys
import zipfile

from PIL import Image, ImageDraw

EXT = {"F.Cu": "gtl", "In1.Cu": "g1", "In2.Cu": "g2", "B.Cu": "gbl", "F.Paste": "gtp", "B.Paste": "gbp",
       "F.Silkscreen": "gto", "B.Silkscreen": "gbo", "F.Mask": "gts", "B.Mask": "gbs", "Edge.Cuts": "gm1"}


# ----------------------------------------------------------------------------- Gerber reader
class Gerber:
    """The subset KiCad writes: FS/MO, C/R/O apertures and aperture macros (primitives 1, 4, 20, 21), flashes,
    linear and circular draws, regions and polarity."""

    def __init__(self, path):
        text = open(path).read()
        self.flashes, self.draws, self.regions = [], [], []     # (x, y, ap) / (a, b, ap, dark) / (pts, dark)
        self.apertures, self.functions, self.macros = {}, {}, {}
        self.fmt = (4, 6)
        func = None
        x = y = 0.0
        ap, mode, dark, region, contour = None, "G01", True, False, []
        for block in re.findall(r"%.*?%|[^%]*?\*", text, re.S):
            block = block.strip()
            if not block:
                continue
            if block.startswith("%"):
                body = block.strip("%")
                if body.startswith("FS"):
                    m = re.match(r"FSLAX(\d)(\d)Y(\d)(\d)", body)
                    self.fmt = (int(m.group(1)), int(m.group(2)))
                elif body.startswith("AM"):
                    name, *prims = [p.strip() for p in re.sub(r"\s+", "", body[2:]).split("*") if p.strip()]
                    self.macros[name] = [p for p in prims if not p.startswith("0")]
                elif body.startswith("AD"):
                    m = re.match(r"ADD(\d+)([A-Za-z_][A-Za-z0-9_]*),?([^*]*)", body)
                    params = [float(v) for v in m.group(3).split("X")] if m.group(3) else []
                    self.apertures[int(m.group(1))] = (m.group(2), params)
                    self.functions[int(m.group(1))] = func
                elif body.startswith("LP"):
                    dark = body[2] == "D"
                continue
            cmd = block[:-1]
            if cmd.startswith("G04"):
                m = re.search(r"TA\.AperFunction,([A-Za-z]+)", cmd)
                if m:
                    func = m.group(1)
                continue
            for g in re.findall(r"G(36|37|75|0?[1-3])(?!\d)", cmd.split("X")[0].split("Y")[0].split("D")[0]):
                g = int(g)
                if g in (1, 2, 3):
                    mode = f"G0{g}"
                elif g == 36:
                    region, contour = True, []
                elif g == 37:
                    if len(contour) > 2:
                        self.regions.append((contour, dark))
                    region, contour = False, []
            m = re.fullmatch(r"(?:G\d+)?D(\d+)", cmd)
            if m and int(m.group(1)) >= 10:
                ap = int(m.group(1))
                continue
            m = re.match(r"(?:G\d+)?(?:X(-?\d+))?(?:Y(-?\d+))?(?:I(-?\d+))?(?:J(-?\d+))?D0?([123])$", cmd)
            if not m:
                continue
            nx = self.num(m.group(1)) if m.group(1) else x
            ny = self.num(m.group(2)) if m.group(2) else y
            d = int(m.group(5))
            if d == 3:
                self.flashes.append((nx, ny, ap))
            elif d == 2:
                if region and len(contour) > 2:
                    self.regions.append((contour, dark))
                contour = [(nx, ny)] if region else contour
            elif d == 1:
                pts = [(nx, ny)]
                if mode in ("G02", "G03"):
                    i = self.num(m.group(3)) if m.group(3) else 0.0
                    j = self.num(m.group(4)) if m.group(4) else 0.0
                    pts = arc((x, y), (nx, ny), (x + i, y + j), mode == "G02")
                if region:
                    contour.extend(pts)
                else:
                    prev = (x, y)
                    for p in pts:
                        self.draws.append((prev, p, ap, dark))
                        prev = p
            x, y = nx, ny

    def num(self, s):
        return int(s) / 10 ** self.fmt[1]

    def shapes(self, ap, at):
        """Polygons (dark?, points) and circles (dark?, x, y, r) of aperture ap flashed at `at`."""
        kind, p = self.apertures[ap]
        cx, cy = at
        if kind == "C":
            return [], [(True, cx, cy, p[0] / 2)]
        if kind in ("R", "O"):
            w, h = p[0] / 2, p[1] / 2
            if kind == "O":
                r = min(w, h)
                polys = [(True, [(cx - w + (r if w > h else 0), cy - h + (r if h > w else 0)),
                                 (cx + w - (r if w > h else 0), cy - h + (r if h > w else 0)),
                                 (cx + w - (r if w > h else 0), cy + h - (r if h > w else 0)),
                                 (cx - w + (r if w > h else 0), cy + h - (r if h > w else 0))])]
                ends = [(cx - w + r, cy), (cx + w - r, cy)] if w > h else [(cx, cy - h + r), (cx, cy + h - r)]
                return polys, [(True, ex, ey, r) for ex, ey in ends]
            return [(True, [(cx - w, cy - h), (cx + w, cy - h), (cx + w, cy + h), (cx - w, cy + h)])], []
        return self.macro(kind, p, cx, cy)

    def macro(self, name, params, cx, cy):
        env = {f"${i + 1}": v for i, v in enumerate(params)}
        polys, circles = [], []

        def ev(expr):
            for k in sorted(env, key=len, reverse=True):
                expr = expr.replace(k, repr(env[k]))
            expr = expr.replace("x", "*").replace("X", "*")
            if not re.fullmatch(r"[-+*/().0-9eE ]+", expr):
                raise ValueError(expr)
            return float(eval(expr))

        for prim in self.macros[name]:
            vals = [ev(v) for v in prim.split(",")]
            code, exp = int(vals[0]), vals[1] > 0.5
            if code == 1:
                d, x, y = vals[2:5]
                circles.append((exp, cx + x, cy + y, d / 2))
            elif code == 4:
                n = int(vals[2])
                pts = [(vals[3 + 2 * k], vals[4 + 2 * k]) for k in range(n + 1)]
                rot = math.radians(vals[3 + 2 * (n + 1)])
                polys.append((exp, [(cx + px * math.cos(rot) - py * math.sin(rot),
                                     cy + px * math.sin(rot) + py * math.cos(rot)) for px, py in pts]))
            elif code == 20:
                w, x1, y1, x2, y2, rot = vals[2:8]
                rot = math.radians(rot)
                L = math.hypot(x2 - x1, y2 - y1) or 1e-9
                nx, ny = -(y2 - y1) / L * w / 2, (x2 - x1) / L * w / 2
                pts = [(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)]
                polys.append((exp, [(cx + px * math.cos(rot) - py * math.sin(rot),
                                     cy + px * math.sin(rot) + py * math.cos(rot)) for px, py in pts]))
            elif code == 21:
                w, h, x, y, rot = vals[2:7]
                rot = math.radians(rot)
                pts = [(x - w / 2, y - h / 2), (x + w / 2, y - h / 2), (x + w / 2, y + h / 2), (x - w / 2, y + h / 2)]
                polys.append((exp, [(cx + px * math.cos(rot) - py * math.sin(rot),
                                     cy + px * math.sin(rot) + py * math.cos(rot)) for px, py in pts]))
        return polys, circles

    def extent(self):
        pts = [p for a, b, *_ in self.draws for p in (a, b)] + [(x, y) for x, y, _ in self.flashes] + \
              [p for c, _ in self.regions for p in c]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)


def arc(a, b, c, cw, step=10):
    r = math.hypot(a[0] - c[0], a[1] - c[1])
    t0, t1 = math.atan2(a[1] - c[1], a[0] - c[0]), math.atan2(b[1] - c[1], b[0] - c[0])
    if cw:
        while t1 >= t0:
            t1 -= 2 * math.pi
    else:
        while t1 <= t0:
            t1 += 2 * math.pi
    n = max(2, int(abs(t1 - t0) * 180 / math.pi / step))
    return [(c[0] + r * math.cos(t0 + (t1 - t0) * k / n), c[1] + r * math.sin(t0 + (t1 - t0) * k / n))
            for k in range(1, n + 1)]


# ----------------------------------------------------------------------------- Excellon reader
def excellon(path):
    tools, hits, cur = {}, {}, None
    for line in open(path):
        line = line.strip()
        m = re.fullmatch(r"T(\d+)C([\d.]+)", line)
        if m:
            tools[int(m.group(1))] = float(m.group(2))
            continue
        m = re.fullmatch(r"T(\d+)", line)
        if m:
            cur = int(m.group(1))
            continue
        m = re.match(r"X(-?[\d.]+)Y(-?[\d.]+)", line)
        if m and cur:
            hits.setdefault(round(tools[cur], 3), []).append((float(m.group(1)), float(m.group(2)),
                                                              "G85" in line))
    return hits


# ----------------------------------------------------------------------------- rendering
def render(layers, extent, path, scale=12, marks=()):
    """layers: [(Gerber, rgba)] drawn in order; marks: [(x, y, label)] crosses (CPL placements)."""
    x0, y0, x1, y1 = extent
    pad = 1.0
    W, H = int((x1 - x0 + 2 * pad) * scale), int((y1 - y0 + 2 * pad) * scale)
    img = Image.new("RGB", (W, H), (18, 20, 24))

    def P(p):
        return ((p[0] - x0 + pad) * scale, (y1 - p[1] + pad) * scale)

    for g, col in layers:
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dr = ImageDraw.Draw(lay)
        clear = (0, 0, 0, 0)
        for pts, dark in g.regions:
            dr.polygon([P(p) for p in pts], fill=col if dark else clear)
        for a, b, ap, dark in g.draws:
            kind, prm = g.apertures.get(ap, ("C", [0.1]))
            w = max(1, int(round((prm[0] if prm else 0.1) * scale)))
            dr.line([P(a), P(b)], fill=col if dark else clear, width=w)
            r = w / 2
            for q in (a, b):
                cx, cy = P(q)
                dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col if dark else clear)
        for x, y, ap in g.flashes:
            polys, circles = g.shapes(ap, (x, y))
            for dark, pts in polys:
                dr.polygon([P(p) for p in pts], fill=col if dark else clear)
            for dark, cx, cy, r in circles:
                px, py = P((cx, cy))
                dr.ellipse([px - r * scale, py - r * scale, px + r * scale, py + r * scale], fill=col if dark else clear)
        img.paste(lay, (0, 0), lay)
    dr = ImageDraw.Draw(img)
    for x, y, label in marks:
        px, py = P((x, y))
        dr.line([px - 6, py, px + 6, py], fill=(255, 230, 0), width=2)
        dr.line([px, py - 6, px, py + 6], fill=(255, 230, 0), width=2)
        dr.text((px + 5, py - 14), label, fill=(255, 230, 0))
    img.save(path)


# ----------------------------------------------------------------------------- checks
def main(fab):
    facts = json.load(open(os.path.join(fab, "facts.json")))
    gdir = os.path.join(fab, "gerbers")
    files = os.listdir(gdir)
    results = []

    def check(name, ok, detail):
        results.append((name, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")

    paths = {}
    for layer, ext in EXT.items():
        hit = [f for f in files if f.endswith("." + ext)]
        paths[layer] = os.path.join(gdir, hit[0]) if len(hit) == 1 else None
    drills = {k: next((os.path.join(gdir, f) for f in files if f.endswith(f"-{k}.drl")), None) for k in ("PTH", "NPTH")}
    missing = [k for k, v in list(paths.items()) + list(drills.items()) if not v]
    check("files", not missing, f"{len(EXT)} Gerber layers + PTH/NPTH drill" + (f"; missing {missing}" if missing else ""))
    zips = [f for f in os.listdir(fab) if f.endswith("-gerbers.zip")]
    names = set(zipfile.ZipFile(os.path.join(fab, zips[0])).namelist()) if zips else set()
    check("zip", names == set(files), f"{zips[0] if zips else 'no zip'} holds {len(names)} of {len(files)} files")

    g = {k: Gerber(v) for k, v in paths.items() if v}

    # outline
    ex = g["Edge.Cuts"].extent()
    want = facts["outline"]
    err = max(abs(a - b) for a, b in zip(ex, want))
    check("outline", err < 0.05, f"Edge.Cuts spans {ex[2] - ex[0]:.2f} x {ex[3] - ex[1]:.2f} mm from "
          f"({ex[0]:.2f}, {ex[1]:.2f}); board {want[2] - want[0]:.2f} x {want[3] - want[1]:.2f} mm (max error {err:.3f})")

    # drill
    for kind in ("PTH", "NPTH"):
        hits = excellon(drills[kind])
        got = {f"{d:.3f}": len(v) for d, v in hits.items()}
        exp = {f"{float(d):.3f}": n for d, n in facts["holes"][kind].items()}
        check(f"drill {kind}", got == exp, ", ".join(f"Ø{d} x{n}" for d, n in sorted(got.items())) +
              ("" if got == exp else f"; board has {exp}"))

    # copper flashes
    nvia = len(facts["vias"])
    for layer in ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"):
        fl = g[layer].flashes
        vias = sum(1 for _, _, ap in fl if g[layer].functions.get(ap) == "ViaPad")
        pads = len(fl) - vias
        check(f"copper {layer}", vias == nvia and pads == facts["pads"][layer],
              f"{vias} via flashes (board {nvia}), {pads} pad flashes (board {facts['pads'][layer]}), "
              f"{len(g[layer].draws)} track segments, {len(g[layer].regions)} pour regions")

    # tenting: no mask opening on any via
    for layer in ("F.Mask", "B.Mask"):
        opens = [(x, y) for x, y, _ in g[layer].flashes]
        bad = [v for v in facts["vias"] if any(abs(v[0] - x) < 0.05 and abs(v[1] - y) < 0.05 for x, y in opens)]
        check(f"tenting {layer}", not bad, f"{len(opens)} openings, {len(bad)} on vias")

    for layer in ("F.Paste", "B.Paste"):
        n = len(g[layer].flashes) + len(g[layer].regions)
        check(f"paste {layer}", n == facts["paste"][layer], f"{n} apertures (board {facts['paste'][layer]})")

    # BOM and CPL
    jlc = {p["ref"]: p for p in facts["parts"] if p["fit"] == "JLC SMT"}
    bom_path = next(os.path.join(fab, f) for f in os.listdir(fab) if f.endswith("-bom-jlc.csv"))
    cpl_path = next(os.path.join(fab, f) for f in os.listdir(fab) if f.endswith("-cpl-jlc.csv"))
    bom = list(csv.DictReader(open(bom_path)))
    cpl = list(csv.DictReader(open(cpl_path)))
    bom_refs = [r for line in bom for r in line["Designator"].split(",")]
    cpl_refs = [r["Designator"] for r in cpl]
    check("BOM vs board", sorted(bom_refs) == sorted(jlc) and len(set(bom_refs)) == len(bom_refs),
          f"{len(bom)} lines, {len(bom_refs)} designators; board has {len(jlc)} JLC-fitted parts")
    bad_lcsc = [l["Designator"] for l in bom if not re.fullmatch(r"C\d+", l["LCSC Part #"])]
    check("BOM LCSC numbers", not bad_lcsc, "every line has an LCSC part" if not bad_lcsc else f"missing: {bad_lcsc}")
    check("CPL vs BOM", sorted(cpl_refs) == sorted(bom_refs), f"{len(cpl_refs)} placements")
    x0, y0, x1, y1 = want
    out = [r["Designator"] for r in cpl if not (x0 <= float(r["Mid X"]) <= x1 and y0 <= float(r["Mid Y"]) <= y1)]
    sides = {r["Layer"] for r in cpl}
    check("CPL on board", not out and sides == {"bottom"}, f"all inside the outline, layers {sorted(sides)}" +
          (f"; outside: {out}" if out else ""))
    # every placement sits among its own pads: the nearest bottom paste aperture is within reach of the centre
    paste = [(x, y) for x, y, _ in g["B.Paste"].flashes]
    far = []
    for r in cpl:
        x, y = float(r["Mid X"]), float(r["Mid Y"])
        d = min(math.hypot(x - px, y - py) for px, py in paste)
        if d > 8.0:
            far.append((r["Designator"], round(d, 1)))
    check("CPL frame", not far, "every centre within 8 mm of a bottom paste aperture (mirror or origin errors "
          "would move them off)" + (f"; far: {far}" if far else ""))
    rots = [int(r["Rotation"]) for r in cpl]
    check("CPL rotations", all(0 <= v < 360 for v in rots), f"{len(set(rots))} distinct angles, all 0-359")

    # pictures, from the Gerbers alone
    box = (x0, y0, x1, y1)
    render([(g["In1.Cu"], (60, 140, 60, 255))], box, os.path.join(fab, "check_in1.png"))
    render([(g["In2.Cu"], (200, 120, 40, 255))], box, os.path.join(fab, "check_in2.png"))
    render([(g["F.Cu"], (220, 70, 60, 255)), (g["Edge.Cuts"], (230, 200, 60, 255))], box,
           os.path.join(fab, "check_top.png"))
    render([(g["B.Cu"], (70, 120, 220, 255)), (g["B.Paste"], (200, 200, 200, 255)),
            (g["B.Silkscreen"], (240, 240, 240, 255)), (g["Edge.Cuts"], (230, 200, 60, 255))], box,
           os.path.join(fab, "check_bottom.png"),
           marks=[(float(r["Mid X"]), float(r["Mid Y"]), r["Designator"]) for r in cpl])
    failed = [n for n, ok, _ in results if not ok]
    with open(os.path.join(fab, "check_report.json"), "w") as f:
        json.dump([dict(check=n, ok=ok, detail=d) for n, ok, d in results], f, indent=1)
    print(f"{len(results) - len(failed)}/{len(results)} checks passed" + (f"; FAILED: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "build/fab"))
