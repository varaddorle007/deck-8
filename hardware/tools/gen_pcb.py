#!/usr/bin/env python3
"""Build hardware/main/deck8.kicad_pcb: outline, mounting, fixed placement, clustered passives, nets.

Run with KiCad's Python (it ships pcbnew):
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 gen_pcb.py

Inputs: ../placement.json (positions from the Fusion model) and KiCad's netlist of
../main/deck8.kicad_sch (exported here with kicad-cli). Every footprint is linked to its
schematic symbol by sheet path + UUID, so "Update PCB from Schematic" and DRC parity work.
Coordinates in placement.json are in the PCB plane: origin = key-grid centre, +Y = back.
"""
import json
import math
import os
import subprocess
import xml.etree.ElementTree as ET

import pcbnew

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN, BUILD = os.path.join(HW, "main"), os.path.join(HW, "build")
CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
FP_DIR = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
LOCAL_LIBS = {"Deck8": os.path.join(HW, "lib", "deck8.pretty")}
OX, OY = 150.0, 100.0          # plane origin on the KiCad sheet
USB_OVERHANG = 1.0             # receptacle front past the back edge
SIDE_TIP = 46.1                # side-button actuator tip |X| (cap flange at 46.2)
SLIDE_TAB = 0.8                # board tab under the slide switch (shell inner wall at |X| = 47)
EDGE_COPPER = 0.35             # copper keep-back from the board edge
FRONT_BAND = -24.2             # bottom parts forbidden in front of this: light wall inner face at Y -24.4
BATTERY = (-28.25, 10.1, 12.25, 39.8)   # battery outline (Deck8Model BATTERY, 8 mm left of centre) in the PCB plane
SCREW_KEEPOUT = 2.5            # radius kept clear around H1-H4: boss face on top, M2 wafer head (d 4.5) below
# Mated cable plug in front of a side-entry connector: length out of the housing face, width, height off the board,
# from JST's drawings, plus 0.5 mm. PH: 9.6 mm mated length less the 6.0 mm header, PHR-2 5.8 mm wide, header 5.5 mm
# tall. SH: SHR-03V-S-B is 6.0 mm wide over its tabs; JST draws no mated length, so this assumes only 2.0 of the plug's
# 5.0 mm goes in. Parts on that side stay out of the box, and export_fit.py hands it to the Fusion check.
PLUG = {
    "JST_PH_S2B-PH-SM4-TB_1x02-1MP_P2.00mm_Horizontal": (3.6 + 0.5, 5.8 + 0.5, 5.5),    # J2, PHR-2 on the LiPo
    "JST_SH_SM03B-SRSS-TB_1x03-1MP_P1.00mm_Horizontal": (3.0 + 0.5, 6.0 + 0.5, 2.95),   # J4, SHR-03V-S on the ring
}

FM, TM = pcbnew.FromMM, pcbnew.ToMM


def K(x, y):
    return pcbnew.VECTOR2I(FM(OX + x), FM(OY - y))


def kx(x):
    return OX + x


def ky(y):
    return OY - y


# ----------------------------------------------------------------------------- inputs
def netlist():
    os.makedirs(BUILD, exist_ok=True)
    path = os.path.join(BUILD, "deck8.net.xml")
    subprocess.run([CLI, "sch", "export", "netlist", "--format", "kicadxml", "-o", path,
                    os.path.join(MAIN, "deck8.kicad_sch")], check=True, capture_output=True)
    root = ET.parse(path).getroot()
    comps = {}
    for c in root.iter("comp"):
        props = {p.get("name"): p.get("value") for p in c.iter("property")}
        sp = c.find("sheetpath")
        fields = {f.get("name"): (f.text or "") for f in c.iter("field") if f.get("name") != "Footprint"}
        comps[c.get("ref")] = {
            "value": c.findtext("value"), "fpid": c.findtext("footprint") or "",
            "path": sp.get("tstamps") + c.findtext("tstamps").split()[0],
            "sheetname": props.get("Sheetname", ""), "sheetfile": props.get("Sheetfile", ""),
            "dnp": "dnp" in props, "fields": fields,
            "exclude_from_bom": "exclude_from_bom" in props,
        }
    pins = {}
    nets = []
    for n in root.iter("net"):
        nets.append(n.get("name"))
        for node in n.iter("node"):
            pins[(node.get("ref"), node.get("pin"))] = n.get("name")
    return comps, pins, nets


# ----------------------------------------------------------------------------- geometry helpers
def box(item):
    b = item.GetBoundingBox()
    return [TM(b.GetLeft()), TM(b.GetTop()), TM(b.GetRight()), TM(b.GetBottom())]


def union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def fab_box(fp):
    items = [g for g in fp.GraphicalItems() if g.GetLayerName() in ("F.Fab", "B.Fab")]
    return union([box(g) for g in items]) if items else box(fp)


def pad_centroid(fp, names=None):
    ps = [p for p in fp.Pads() if (names is None and p.GetNumber()) or (names and p.GetNumber() in names)]
    return (sum(TM(p.GetPosition().x) for p in ps) / len(ps), sum(TM(p.GetPosition().y) for p in ps) / len(ps))


def centre(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def courtyard(fp, layer):
    fp.BuildCourtyardCaches()
    poly = fp.GetCourtyard(layer)
    if poly.OutlineCount() == 0:
        return None
    b = poly.BBox()
    return [TM(b.GetLeft()), TM(b.GetTop()), TM(b.GetRight()), TM(b.GetBottom())]


def plug_zone(fp):
    """Box (KiCad mm) a mated plug takes in front of the housing, or None. The plug goes in on the side of the
    mounting tabs (MP), opposite the contact tails, along whichever board axis that is."""
    name = str(fp.GetFPID().GetUniStringLibItemName())
    if name not in PLUG:
        return None
    length, width, _ = PLUG[name]
    tx, ty = pad_centroid(fp, {p.GetNumber() for p in fp.Pads() if p.GetNumber() not in ("", "MP")})
    mx, my = pad_centroid(fp, {"MP"})
    x0, y0, x1, y1 = fab_box(fp)
    if abs(mx - tx) > abs(my - ty):
        xa, xb = (x1, x1 + length) if mx > tx else (x0 - length, x0)
        return [xa, ty - width / 2, xb, ty + width / 2]
    ya, yb = (y1, y1 + length) if my > ty else (y0 - length, y0)
    return [tx - width / 2, ya, tx + width / 2, yb]


def occupancy(fp):
    """Rectangles (KiCad mm) with the side they block: 'F', 'B' or 'both'."""
    out = []
    z = plug_zone(fp)
    if z:
        out.append((z, "B" if fp.IsFlipped() else "F"))
    for layer, side in ((pcbnew.F_CrtYd, "F"), (pcbnew.B_CrtYd, "B")):
        c = courtyard(fp, layer)
        if c:
            out.append((c, side))
    if not out:
        out.append((box(fp), "B" if fp.IsFlipped() else "F"))
    for p in fp.Pads():
        if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
            out.append((box(p), "both"))
    for g in fp.GraphicalItems():
        if g.GetLayerName() == "Edge.Cuts":
            out.append((box(g), "both"))
    if fp.GetReference().startswith("H"):
        # shell boss on top, M2 screw head underneath: nothing else inside either footprint
        p = fp.GetPosition()
        r = SCREW_KEEPOUT
        out.append(([TM(p.x) - r, TM(p.y) - r, TM(p.x) + r, TM(p.y) + r], "both"))
    return out


def overlaps(a, b, gap=0.2):
    return not (a[2] + gap <= b[0] or b[2] + gap <= a[0] or a[3] + gap <= b[1] or b[3] + gap <= a[1])


# ----------------------------------------------------------------------------- the board
class Board:
    def __init__(self, layout):
        self.b = pcbnew.CreateEmptyBoard()
        self.b.SetCopperLayerCount(4)
        self.b.GetDesignSettings().SetBoardThickness(FM(1.6))
        self.layout = layout
        self.fps = {}
        self.occ = []            # (rect, side, ref)
        self.report = {"placed": {}, "clustered": {}, "unplaced": [], "warnings": []}
        bd = layout["board"]
        hw, fr, bk, cb, cf = bd["half_width"], bd["front"], bd["back"], bd["chamfer_back"], bd["chamfer_front"]
        self.convex = [(-hw + cb, bk), (hw - cb, bk), (hw, bk - cb), (hw, fr + cf), (hw - cf, fr),
                       (-hw + cf, fr), (-hw, fr + cf), (-hw, bk - cb)]
        # tab under the power slide switch so its pads stay on the board while the lever reaches the wall slot
        ty, half = layout["parts"]["SW1"]["y"], 4.8      # covers the PCM12 mounting pads (+-4.15)
        self.tab = (-hw - SLIDE_TAB, ty - half, ty + half)
        self.outline = self.convex[:7] + [(-hw, ty - half), (-hw - SLIDE_TAB, ty - half),
                                          (-hw - SLIDE_TAB, ty + half), (-hw, ty + half)] + self.convex[7:]
        self.back, self.front = bk, fr

    # ---- drawing
    def seg(self, a, b, layer, w=0.1):
        s = pcbnew.PCB_SHAPE(self.b)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(K(*a))
        s.SetEnd(K(*b))
        s.SetLayer(layer)
        s.SetWidth(FM(w))
        self.b.Add(s)

    def rect(self, x0, y0, x1, y1, layer, w=0.1):
        for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
            self.seg(a, b, layer, w)

    def circle(self, x, y, r, layer, w=0.1):
        s = pcbnew.PCB_SHAPE(self.b)
        s.SetShape(pcbnew.SHAPE_T_CIRCLE)
        s.SetCenter(K(x, y))
        s.SetEnd(K(x + r, y))
        s.SetLayer(layer)
        s.SetWidth(FM(w))
        self.b.Add(s)

    def text(self, s, x, y, layer, size=1.0):
        t = pcbnew.PCB_TEXT(self.b)
        t.SetText(s)
        t.SetPosition(K(x, y))
        t.SetLayer(layer)
        t.SetTextSize(pcbnew.VECTOR2I(FM(size), FM(size)))
        t.SetTextThickness(FM(size * 0.15))
        if layer in (pcbnew.B_SilkS, pcbnew.B_Fab):
            t.SetMirrored(True)
        self.b.Add(t)

    def zone(self, pts, layer, net=None, rule=False, name=""):
        z = pcbnew.ZONE(self.b)
        z.SetLayer(layer)
        if rule:
            z.SetIsRuleArea(True)
            z.SetDoNotAllowFootprints(True)
            z.SetDoNotAllowTracks(False)
            z.SetDoNotAllowVias(False)
            z.SetDoNotAllowPads(False)
            z.SetDoNotAllowZoneFills(False)
        elif net:
            z.SetNet(self.b.FindNet(net))
            z.SetLocalClearance(FM(0.3))
            z.SetMinThickness(FM(0.2))
        if name:
            z.SetZoneName(name)
        for p in pts:
            z.AppendCorner(K(*p), -1)
        self.b.Add(z)
        return z

    def outline_and_drawings(self):
        pts = self.outline
        for i in range(len(pts)):
            self.seg(pts[i], pts[(i + 1) % len(pts)], pcbnew.Edge_Cuts)
        U = pcbnew.Dwgs_User
        self.rect(-40, -21, 40, 21, U)
        self.text("key well 80 x 42", 0, -22.5, U)
        for knob in (p for r, p in self.layout["parts"].items() if r.startswith("ENC")):
            self.circle(knob["x"], knob["y"], 10, U)
        self.rect(-13, 28, 13, 42, U)
        self.text("OLED window", 0, 43, U, 0.8)
        x0, y0, x1, y1 = BATTERY
        self.rect(x0, y0, x1, y1, pcbnew.B_Fab)
        self.text("BATTERY BELOW: bottom parts max 3 mm here", (x0 + x1) / 2, (y0 + y1) / 2, pcbnew.B_Fab, 0.9)
        self.text("Deck-8 Rev A", 0, -26.5, pcbnew.B_SilkS, 1.2)

    # ---- footprints
    def load(self, ref, comp):
        lib, name = comp["fpid"].split(":", 1)
        path = LOCAL_LIBS.get(lib, os.path.join(FP_DIR, lib + ".pretty"))
        fp = pcbnew.FootprintLoad(path, name)
        if fp is None:
            raise SystemExit(f"{ref}: footprint {comp['fpid']} not found")
        fp.SetFPID(pcbnew.LIB_ID(lib, name))
        fp.SetReference(ref)
        fp.SetValue(comp["value"])
        fp.SetPath(pcbnew.KIID_PATH(comp["path"]))
        for setter, val in (("SetSheetname", comp["sheetname"]), ("SetSheetfile", comp["sheetfile"])):
            try:
                getattr(fp, setter)(val)
            except Exception:
                pass
        for k, v in comp["fields"].items():
            fp.SetField(k, v)
            f = fp.GetField(k)
            if f and k not in ("Reference", "Value"):
                f.SetVisible(False)
        if comp["dnp"]:
            try:
                fp.SetDNP(True)
            except Exception:
                fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_DNP)
        fp.SetExcludedFromBOM(comp["exclude_from_bom"])
        for p in fp.Pads():
            # thermal vias inside an exposed pad join the planes solidly (a relief would starve them)
            if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH and "ThermalVias" in name and p.GetNumber() == "17":
                p.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
        self.b.Add(fp)
        self.fps[ref] = fp
        return fp

    def nets(self, pins, names):
        for n in names:
            if not self.b.FindNet(n):
                self.b.Add(pcbnew.NETINFO_ITEM(self.b, n))
        for ref, fp in self.fps.items():
            for p in fp.Pads():
                n = pins.get((ref, p.GetNumber()))
                if n:
                    p.SetNet(self.b.FindNet(n))

    def side(self, fp, side):
        if side == "B" and not fp.IsFlipped():
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)

    def orient(self, fp, marker, target):
        best = None
        for rot in (0, 90, 180, 270):
            fp.SetOrientationDegrees(rot)
            v = marker(fp)
            n = math.hypot(*v) or 1
            score = (v[0] * target[0] + v[1] * target[1]) / n
            if best is None or score > best[0]:
                best = (score, rot)
        fp.SetOrientationDegrees(best[1])
        return best[1]

    def move_to(self, fp, point, at):
        """Translate fp so that `at` (KiCad mm, measured now) lands on `point` (KiCad mm)."""
        fp.Move(pcbnew.VECTOR2I(FM(point[0] - at[0]), FM(point[1] - at[1])))

    def commit(self, ref):
        for r, s in occupancy(self.fps[ref]):
            self.occ.append((r, s, ref))
        p = self.fps[ref].GetPosition()
        self.report["placed"][ref] = {"x": round(TM(p.x) - OX, 3), "y": round(OY - TM(p.y), 3),
                                      "side": "B" if self.fps[ref].IsFlipped() else "F",
                                      "rot": round(self.fps[ref].GetOrientationDegrees(), 1)}

    def place_fixed(self):
        parts = self.layout["parts"]
        fps = self.fps

        def signal_marker(names):
            return lambda f: tuple(a - b for a, b in zip(centre(fab_box(f)), pad_centroid(f, names)))

        for ref, pl in parts.items():
            if ref not in fps:
                continue
            fp = fps[ref]
            X, Y, side = pl["x"], pl["y"], pl["side"]
            fp.SetPosition(K(X, Y))
            self.side(fp, side)
            if ref.startswith("ENC"):
                # mirror the pair so both A/B/C pin rows face the side walls
                fp.SetOrientationDegrees(0 if X < 0 else 180)
                self.move_to(fp, (kx(X), ky(Y)), pad_centroid(fp, {"MP"}))
            elif ref == "J5":
                fp.SetOrientationDegrees(90)
                self.move_to(fp, (kx(X), ky(Y)), pad_centroid(fp))
                # the OLED module's own header goes through here; Deck8Model.py models it with the module, 4.7 mm up
                fp.Models().clear()
            elif ref == "U5":
                # antenna end: past pads 1 and 55, opposite the 15-33 row (zone boxes go stale on rotation)
                far = {str(n) for n in range(15, 34)}
                ant = lambda f: tuple(a - b for a, b in zip(pad_centroid(f, {"1", "55"}), pad_centroid(f, far)))
                self.orient(fp, ant, (0, -1))
                fb = fab_box(fp)
                self.move_to(fp, (kx(X), ky(self.back)), (centre(fb)[0], fb[1]))
            elif ref == "J1":
                sig = {p.GetNumber() for p in fp.Pads() if p.GetNumber()[:1] in "AB"}
                self.orient(fp, signal_marker(sig), (0, -1))
                fb = fab_box(fp)
                self.move_to(fp, (kx(0), ky(self.back + USB_OVERHANG)), (centre(fb)[0], fb[1]))
            elif ref in ("SW3", "SW4", "SW5"):
                d = -1 if X < 0 else 1
                self.orient(fp, signal_marker({"1", "2"}), (d, 0))
                fb = fab_box(fp)
                edge = fb[0] if d < 0 else fb[2]
                self.move_to(fp, (kx(d * SIDE_TIP), ky(Y)), (edge, centre(fb)[1]))
            elif ref == "SW1":
                self.orient(fp, signal_marker({"1", "2", "3"}), (-1, 0))
                pads = union([box(p) for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD])
                self.move_to(fp, (kx(self.tab[0] + EDGE_COPPER), ky(Y)), (pads[0], centre(fab_box(fp))[1]))
            elif ref in ("J2", "J4"):
                names = {"1", "2", "3"}
                # J2 plug from the battery side; J4 plug from the left so it clears the light wall in front
                target = (-1, 0)
                self.orient(fp, signal_marker(names), target)
                self.move_to(fp, (kx(X), ky(Y)), centre(fab_box(fp)))
            else:
                fp.SetOrientationDegrees(pl.get("rot", 0))
            self.commit(ref)

    def place_led_caps(self):
        """Each key LED's 100 nF goes north of it, else east, west or south: the first free spot."""
        for i in range(8):
            cref, dref = f"C{17 + i}", f"D{i + 1}"
            fp, d = self.fps[cref], self.fps[dref]
            p = d.GetPosition()
            self.side(fp, "B")
            for ddx, ddy, rot in ((0, -3.4, 0), (4.8, 0, 90), (-4.8, 0, 90), (0, 3.4, 0)):
                fp.SetPosition(pcbnew.VECTOR2I(p.x + FM(ddx), p.y + FM(ddy)))
                fp.SetOrientationDegrees(rot)
                if self.free(occupancy(fp), "B"):
                    break
            else:
                self.report["warnings"].append(f"{cref}: no free spot next to {dref}")
            self.commit(cref)

    def place_near(self):
        """Support parts that belong next to one pin: put exactly there, not where a scan finds room."""
        for ref, (x, y, rot) in NEAR.items():
            fp = self.fps[ref]
            fp.SetPosition(K(x, y))
            self.side(fp, "B")
            fp.SetOrientationDegrees(rot)
        placed = set(self.report["placed"]) | set(NEAR)
        for _ in range(2):
            for ref in sorted(NEAR_TURN):
                fp = self.fps[ref]
                best = None
                for rot in (NEAR[ref][2], NEAR[ref][2] + 180):
                    fp.SetOrientationDegrees(rot)
                    score = self.wire_length(fp, placed)
                    if best is None or score < best[0] - 1e-6:
                        best = (score, rot)
                fp.SetOrientationDegrees(best[1])
        for ref in NEAR:
            if not self.free(occupancy(self.fps[ref]), "B"):
                self.report["warnings"].append(f"{ref}: hand position overlaps another part")
            self.commit(ref)

    def wire_length(self, fp, placed):
        """Sum over fp's signal pads of the distance to the nearest same-net pad on another placed part."""
        total = 0.0
        for p in fp.Pads():
            net = p.GetNetname()
            if not net or net == "GND" or net.startswith("unconnected"):
                continue
            a = p.GetPosition()
            best = None
            for ref in placed:
                if ref == fp.GetReference():
                    continue
                for q in self.fps[ref].Pads():
                    if q.GetNetname() == net:
                        d = math.hypot(TM(q.GetPosition().x - a.x), TM(q.GetPosition().y - a.y))
                        best = d if best is None else min(best, d)
            total += best or 0.0
        return total

    # ---- clustered placement
    def inside(self, r, margin=0.6):
        pts = [((x - OX), (OY - y)) for x, y in ((r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3]))]
        poly = self.convex
        for px, py in pts:
            for i in range(len(poly)):
                (ax, ay), (bx, by) = poly[i], poly[(i + 1) % len(poly)]
                cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
                dist = cross / math.hypot(bx - ax, by - ay)
                if dist > -margin:   # outline is clockwise in plane coords: inside = negative
                    return False
        return True

    def on_board(self, r, margin):
        """Like inside(), but against the real outline (with the slide-switch tab) rather than the convex part."""
        pts = [((x - OX), (OY - y)) for x, y in ((r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3]))]
        poly = self.outline
        for px, py in pts:
            hit = False
            for i in range(len(poly)):
                (ax, ay), (bx, by) = poly[i], poly[i - 1]
                if (ay > py) != (by > py) and px < (bx - ax) * (py - ay) / (by - ay) + ax:
                    hit = not hit
                dx, dy = bx - ax, by - ay
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
                if math.hypot(ax + t * dx - px, ay + t * dy - py) < margin:
                    return False
            if not hit:
                return False
        return True

    def free(self, rects, side):
        for r, s in rects:
            for o, os_, _ in self.occ:
                if (os_ == "both" or s == "both" or os_ == s) and overlaps(r, o):
                    return False
            if side == "B" and (OY - r[1]) > FRONT_BAND and (OY - r[3]) < FRONT_BAND:
                return False
            if side == "B" and (OY - r[1]) <= FRONT_BAND:
                return False
            if not self.inside(r):
                return False
        return True

    def cluster(self, name, refs, region, side="B", step=0.5):
        x0, y0, x1, y1 = region
        for ref in refs:
            fp = self.fps[ref]
            done = False
            base_rot = CLUSTER_ROT.get(ref, 0)
            # turned only when no spot fits it as given; a finer grid only when neither orientation fits
            for st, rot in ((step, base_rot), (step, base_rot + 90), (step / 2, base_rot), (step / 2, base_rot + 90)):
                fp.SetPosition(K(0, 0))
                self.side(fp, side)
                fp.SetOrientationDegrees(rot)
                base = occupancy(fp)
                ox, oy = TM(fp.GetPosition().x), TM(fp.GetPosition().y)
                y = y1
                while y >= y0 and not done:
                    x = x0
                    while x <= x1 and not done:
                        dx, dy = kx(x) - ox, ky(y) - oy
                        cand = [([r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy], s) for r, s in base]
                        body = union([r for r, _ in cand])
                        if body[0] >= kx(x0) - 0.01 and body[2] <= kx(x1) + 0.01 and body[1] >= ky(y1) - 0.01 \
                                and body[3] <= ky(y0) + 0.01 and self.free(cand, side):
                            fp.SetPosition(K(x, y))
                            self.commit(ref)
                            self.report["clustered"].setdefault(name, []).append(ref)
                            done = True
                        x += st
                    y -= st
                if done:
                    break
            if not done:
                fp.SetPosition(K(60 + len(self.report["unplaced"]) * 4, 0))
                self.report["unplaced"].append(ref)

    def place_silk(self, size=0.8, thick=0.15):
        """Each reference goes to the first spot around its part that clears pads, holes, cut-outs, other silk and
        the board edge; with no such spot it is hidden on silk (the fab layer still carries it). Silk past the board
        edge should already be gone from the Deck8 copies of the edge parts (trim_footprints.py); anything left is
        trimmed here and reported."""
        silk = {pcbnew.F_SilkS: "F", pcbnew.B_SilkS: "B"}
        for fp in self.fps.values():
            for g in list(fp.GraphicalItems()):
                if g.GetLayer() in silk and g.GetClass() == "PCB_SHAPE" and not self.on_board(box(g), margin=0.15):
                    fp.Remove(g)
                    self.report["warnings"].append(f"{fp.GetReference()}: silk past the board edge trimmed on the "
                                                   "board; re-run trim_footprints.py so the library copy matches")
        obst = {"F": [], "B": []}
        for ref, fp in self.fps.items():
            for p in fp.Pads():
                r = [v + d for v, d in zip(box(p), (-0.15, -0.15, 0.15, 0.15))]
                if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH or p.IsOnLayer(pcbnew.F_Cu) and p.IsOnLayer(pcbnew.B_Cu):
                    obst["F"].append(r)
                    obst["B"].append(r)
                elif p.IsOnLayer(pcbnew.F_Cu):
                    obst["F"].append(r)
                elif p.IsOnLayer(pcbnew.B_Cu):
                    obst["B"].append(r)
            for g in fp.GraphicalItems():
                if g.GetLayer() in silk:
                    obst[silk[g.GetLayer()]].append([v + d for v, d in zip(box(g), (-0.1, -0.1, 0.1, 0.1))])
                elif g.GetLayerName() == "Edge.Cuts":
                    for sd in "FB":
                        obst[sd].append([v + d for v, d in zip(box(g), (-0.3, -0.3, 0.3, 0.3))])
        for d in self.b.Drawings():          # board-level silk (the "Deck-8 Rev A" mark)
            if d.GetLayer() in silk:
                obst[silk[d.GetLayer()]].append([v + g for v, g in zip(box(d), (-0.1, -0.1, 0.1, 0.1))])
        hidden = []
        order = sorted(self.fps.values(), key=lambda f: -(box(f)[2] - box(f)[0]) * (box(f)[3] - box(f)[1]))
        for fp in order:
            ref = fp.Reference()
            if not ref.IsVisible():
                continue
            side = "B" if fp.IsFlipped() else "F"
            ref.SetTextSize(pcbnew.VECTOR2I(FM(size), FM(size)))
            ref.SetTextThickness(FM(thick))
            crt = courtyard(fp, pcbnew.B_CrtYd if side == "B" else pcbnew.F_CrtYd) or box(fp)
            cx, cy = centre(crt)
            spots = [(cx, cy, 0), (cx, cy, 90)]
            for d in (0.15, 0.5, 1.0):        # hug the courtyard first, then step out
                g = d + size / 2
                for t in (0.5, 0.0, 1.0, 0.25, 0.75):
                    x = crt[0] + t * (crt[2] - crt[0])
                    y = crt[1] + t * (crt[3] - crt[1])
                    spots += [(x, crt[1] - g, 0), (x, crt[3] + g, 0), (crt[0] - g, y, 90), (crt[2] + g, y, 90)]
                spots += [(crt[0] - g - 1.2, cy, 0), (crt[2] + g + 1.2, cy, 0)]
            ok = False
            for x, y, ang in spots:
                ref.SetTextAngleDegrees(ang)
                ref.SetPosition(pcbnew.VECTOR2I(FM(x), FM(y)))
                r = box(ref)
                if self.inside(r, margin=0.3) and not any(overlaps(r, o, gap=0.05) for o in obst[side]):
                    obst[side].append(r)
                    ok = True
                    break
            if not ok:
                ref.SetVisible(False)
                hidden.append(fp.GetReference())
        self.report["silk_hidden"] = sorted(hidden)
        self.order_number_spot(obst["B"])

    def order_number_spot(self, obst, size=1.0):
        """JLC prints its order number where it finds "JLCJLCJLCJLC" (otherwise wherever it likes): reserve a
        spot on the hidden bottom side, as near the front edge as there is room."""
        t = pcbnew.PCB_TEXT(self.b)
        t.SetText("JLCJLCJLCJLC")
        t.SetLayer(pcbnew.B_SilkS)
        t.SetMirrored(True)
        t.SetTextSize(pcbnew.VECTOR2I(FM(size), FM(size)))
        t.SetTextThickness(FM(0.15))
        self.b.Add(t)
        y = self.front + 1.5
        while y < self.back - 1.5:
            for x in [v * 0.5 for v in range(0, 80)] + [-v * 0.5 for v in range(1, 80)]:
                t.SetPosition(K(x, y))
                r = box(t)
                if self.inside(r, margin=0.5) and not any(overlaps(r, o, gap=0.2) for o in obst):
                    self.report["order_number_at"] = [x, y]
                    return
            y += 0.5
        self.b.Remove(t)
        self.report["warnings"].append("no free bottom silk spot for the JLC order number")

    def zones(self):
        inset = 0.5
        hw = self.layout["board"]["half_width"] - inset
        pts = []
        for x, y in self.convex:
            pts.append((x - math.copysign(inset, x), y - math.copysign(inset, y - (self.back + self.front) / 2)))
        self.zone(pts, pcbnew.In1_Cu, net="GND", name="GND plane")
        f = self.layout["board"]["front"]
        self.zone([(-hw - 1, f - 1), (hw + 1, f - 1), (hw + 1, FRONT_BAND), (-hw - 1, FRONT_BAND)],
                  pcbnew.B_Cu, rule=True, name="Light wall below: no bottom parts")
        for ref in ("H1", "H2", "H3", "H4"):
            p = self.layout["parts"][ref]
            ring = [(p["x"] + SCREW_KEEPOUT * math.cos(a * math.pi / 12), p["y"] + SCREW_KEEPOUT * math.sin(a * math.pi / 12))
                    for a in range(24)]
            for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
                z = self.zone(ring, layer, rule=True, name=f"{ref} boss and screw head: no tracks or vias")
                z.SetDoNotAllowFootprints(False)
                z.SetDoNotAllowTracks(True)
                z.SetDoNotAllowVias(True)
        filler = pcbnew.ZONE_FILLER(self.b)
        filler.Fill(self.b.Zones())

    def origin(self):
        """Drill/place origin at the board's lower-left corner: Gerbers, drill and the pick-and-place file share it,
        and every fab coordinate comes out positive."""
        xs = [x for x, _ in self.outline]
        ys = [y for _, y in self.outline]
        ds = self.b.GetDesignSettings()
        ds.SetAuxOrigin(K(min(xs), min(ys)))
        ds.SetGridOrigin(K(min(xs), min(ys)))

    def title(self):
        tb = self.b.GetTitleBlock()
        tb.SetTitle("Deck-8 Rev A main PCB")
        tb.SetRevision("A")
        tb.SetDate("2026-10-23")
        tb.SetCompany("Deck-8")
        tb.SetComment(0, "Generated by tools/gen_pcb.py from placement.json + schematic netlist")
        tb.SetComment(1, "4 layers: F.Cu signal, In1 GND, In2 power, B.Cu parts + signal")
        self.b.SetTitleBlock(tb)


CLUSTERS = [

    ("display", ["R18", "R19", "C26", "C27"], (-5.0, 24.6, 4.8, 31.6)),
    ("battery sense", ["R10", "R11", "C4"], (10.0, 16.8, 19.8, 25.0)),      # past the end of J2's plug, under its wires
    ("test points", ["TP1", "TP2", "TP3", "TP4", "TP5", "TP6"], (-21.0, 13.0, -5.5, 23.0)),
    # LED switch with its input cap and links between ST1 and J4's plug; right of J4 the strip bulk cap and the two
    # data buffers, each with its resistor and cap, then the slew cap and the VLED bulk cap (no room beside the switch)
    ("led switch", ["U4", "R20", "R15", "C7"], (-31.0, -24.1, -21.5, -16.8)),
    ("ring buffer", ["C25", "U7", "R17", "C16"], (-14.5, -24.1, -5.0, -16.9)),
    ("key buffer", ["U6", "R16", "C15"], (-5.0, -24.1, 2.5, -16.9)),
    ("led power", ["C8", "R13", "C9"], (2.5, -24.1, 12.0, -16.9)),
]
CLUSTER_ROT = {"U7": 180, "U6": 180}     # buffer outputs face J4 and the first key LED (west)

# Hand positions (plane mm, x, y, rotation; bottom side) for parts that serve one pin.
NEAR = {
    "U1": (3.4, 35.6, 180),          # USB ESD in line between the USB-C pads and the module's D+/D-
    "R1": (-2.6, 38.3, 0), "R2": (5.3, 38.5, 0),     # CC pull-downs either side of the D+/D- pair
    "C12": (5.7, 30.35, 180),        # 4.7 uF VBUS, under pad 32
    "C11": (9.0, 30.35, 180),        # 100 nF VDD, under pads 28/30
    "C10": (9.0, 28.5, 180),         # 10 uF VDD
    "Y1": (12.8, 29.6, 0),           # 32.768 kHz, under pads 17/18 (H2's screw head keeps it west)
    "C13": (14.0, 26.5, 270), "C14": (11.6, 26.5, 270),
    # charger, turned so IN faces the fuse (back), OUT faces the LDO and LED switch (west), BAT faces J2 (east)
    "U2": (-13.0, 38.5, 180),
    "F1": (-8.0, 45.6, 180),
    "C1": (-15.4, 42.5, 90), "R7": (-13.6, 42.5, 90), "R6": (-11.8, 42.5, 90), "R4": (-10.0, 42.5, 90),
    "R3": (-8.9, 39.9, 0), "C3": (-8.9, 37.8, 0),
    "C2": (-17.05, 38.5, 0), "R5": (-18.0, 40.5, 0),
    # LDO with its caps, EN pull-down, 0R link and the two status pull-ups in a row under the charger
    "U3": (-16.4, 34.3, 0), "C5": (-19.55, 33.2, 90), "R12": (-19.6, 37.3, 90),
    "C6": (-13.25, 33.3, 90), "R14": (-11.45, 33.3, 90), "R9": (-9.65, 33.3, 90), "R8": (-7.85, 33.3, 90),
}
# Of these, the two-pad parts may turn 180 deg to face their pin; place_near picks the side with the shorter wire.
NEAR_TURN = {"R1", "R2", "C1", "R7", "R6", "R4", "R3", "C3", "C2", "R5", "C5", "R12", "C6", "R14", "R9", "R8"}


def patch_project():
    path = os.path.join(MAIN, "deck8.kicad_pro")
    with open(path) as f:
        pro = json.load(f)

    def cls(name, track, clearance=0.15, via=(0.6, 0.3), dp=(0.2, 0.15), prio=0):
        return {"name": name, "bus_width": 12, "clearance": clearance, "diff_pair_gap": dp[1],
                "diff_pair_via_gap": 0.25, "diff_pair_width": dp[0], "line_style": 0, "microvia_diameter": 0.3,
                "microvia_drill": 0.1, "pcb_color": "rgba(0, 0, 0, 0.000)", "priority": prio,
                "schematic_color": "rgba(0, 0, 0, 0.000)", "track_width": track, "via_diameter": via[0],
                "via_drill": via[1], "wire_width": 6}
    ns = pro.setdefault("net_settings", {})
    ns["classes"] = [cls("Default", 0.2, prio=2147483647), cls("Power", 0.4, prio=0),
                     cls("USB", 0.2, dp=(0.2, 0.15), prio=1)]
    ns["meta"] = {"version": 4}
    ns["netclass_patterns"] = (
        [{"netclass": "Power", "pattern": p} for p in ("GND", "+3V3", "VBUS*", "VSYS", "VBAT", "VLED*",
                                                         "/Power/3V3_LDO", "/Power/VLED_SW")] +
        [{"netclass": "USB", "pattern": "USB_D*"}])
    ns.setdefault("net_colors", None)
    ns.setdefault("netclass_assignments", None)
    rules = pro.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rules", {})
    rules.update({"min_clearance": 0.15, "min_track_width": 0.15, "min_via_diameter": 0.45,
                  "min_through_hole_diameter": 0.2, "min_copper_edge_clearance": 0.3,
                  "min_hole_clearance": 0.25, "min_hole_to_hole": 0.25})
    with open(path, "w") as f:
        json.dump(pro, f, indent=2)


def main():
    with open(os.path.join(HW, "placement.json")) as f:
        layout = json.load(f)
    comps, pins, net_names = netlist()
    bd = Board(layout)
    for ref, c in sorted(comps.items()):
        if c["fpid"]:
            bd.load(ref, c)
    bd.nets(pins, net_names)
    bd.outline_and_drawings()
    bd.place_fixed()
    bd.place_led_caps()
    bd.place_near()
    for name, refs, region in CLUSTERS:
        bd.cluster(name, [r for r in refs if r in bd.fps], region)
    missing = [r for r in bd.fps if r not in bd.report["placed"] and r not in bd.report["unplaced"]]
    bd.report["not_in_any_rule"] = missing
    bd.place_silk()
    bd.zones()
    bd.origin()
    bd.title()
    out = os.path.join(MAIN, "deck8.kicad_pcb")
    pcbnew.SaveBoard(out, bd.b)
    patch_project()
    with open(os.path.join(BUILD, "pcb_placement_report.json"), "w") as f:
        json.dump(bd.report, f, indent=1)
    print(f"saved {out}: {len(bd.fps)} footprints, {len(net_names)} nets; "
          f"clustered {sum(len(v) for v in bd.report['clustered'].values())}, unplaced {bd.report['unplaced']}, "
          f"no rule {missing}")


if __name__ == "__main__":
    main()
