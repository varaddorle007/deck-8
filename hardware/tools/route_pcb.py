#!/usr/bin/env python3
"""Route main/deck8.kicad_pcb after gen_pcb.py has placed it. Run with KiCad's Python (it ships pcbnew):
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 route_pcb.py

Stages, in order:
  1. power and USB   VBUS_IN, VBUS, VSYS, VBAT, VLED_SW and 3V3_LDO as wide tracks; USB D+/D- and CC
  2. planes          In1 GND (from gen_pcb), In2 split into +3V3 (back) and VLED (keys and front), GND pours on
                     both outer layers; every SMD pad on a plane net gets its own via (or joins plane copper next to it)
  3. signals         crystal, MCU support, keys, buttons, encoders, LED data chain, then GND stitching vias

The board is rasterised on a 0.1 mm grid and each connection is found by A* (tools/router/maze.c, built on demand).
Every check the search makes is the board's own DRC rule, so a route it finds is legal by construction; check_pcb.py
then runs KiCad's DRC to prove it. Re-running this script discards all tracks, vias and its own zones and routes
again from the placement, so the result is reproducible.
"""
import ctypes
import json
import math
import os
import re
import subprocess
import sys
import time

import pcbnew

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(HW, "tools")
MAIN, BUILD = os.path.join(HW, "main"), os.path.join(HW, "build")
PCB = os.path.join(MAIN, "deck8.kicad_pcb")
OX, OY = 150.0, 100.0
FM, TM = pcbnew.FromMM, pcbnew.ToMM

# ----------------------------------------------------------------------------- grid and rules
RES = 0.1
X0, Y0 = -48.45, -29.95                     # plane mm of cell (0, 0): half-cell offset puts the 0.05 mm pad
NX, NY = 970, 790                           # centres (USB-C, MDBT50Q, QFN rows) on cell centres
LAYERS = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]
F, IN1, IN2, B = 0, 1, 2, 3
OUTER = (1 << F) | (1 << B)
ALL = 0b1111
SLACK = RES / 2                             # a straight step strays res/2 from a checked cell centre (maze.c adds
                                            # the extra for diagonal steps)
CLEAR, HOLE_CLEAR, EDGE_CLEAR, HOLE_TO_HOLE = 0.15, 0.25, 0.3, 0.25
VIA_D, VIA_DRILL = 0.6, 0.3
REACH = 1.6                                 # distances beyond this are never asked for
NET_BLOCK = 65535

# track widths (mm) by net; everything else is a 0.2 mm signal
WIDTH = {"/Power/VBUS_IN": 0.8, "VSYS": 0.8, "VBAT": 0.8, "/Power/VLED_SW": 0.8, "VLED": 0.8,
         "VBUS": 0.5, "/Power/3V3_LDO": 0.4, "+3V3": 0.4, "GND": 0.4}
NARROW = 0.2                                # neck-down width next to fine-pitch pads
# Pins on a power net that only sense it get a thin branch: the charger's EN1, the module's VBUS detect, the ESD
# part's VBUS reference, the power switch (it only drives the LDO's EN) and the test points.
BRANCH = {("U2", "6"): 0.2, ("U5", "32"): 0.25, ("U1", "5"): 0.3, ("SW1", "1"): 0.3,
          ("TP1", "1"): 0.3, ("TP2", "1"): 0.3, ("TP3", "1"): 0.3}
# In2 split: +3V3 behind the line, VLED in front of it (keys, LED drivers)
SPLIT_Y, SPLIT_GAP = 20.0, 0.6
PLANES = {"GND": (IN1, None), "+3V3": (IN2, (SPLIT_Y + SPLIT_GAP + 0.6, 99.0)),
          "VLED": (IN2, (-99.0, SPLIT_Y - SPLIT_GAP - 0.6))}
# Pins given a via before routing, each on its own side, so neighbours on a fine-pitch row don't box each other in:
# the charger's EN1 (VBUS) goes south-east, PGOOD beside it south, CHG on the next side west.
PRE_ESCAPE = {("U2", "6"): (1, -1), ("U2", "7"): (0, -1), ("U2", "9"): (-1, 0)}
FEEDS = {("R14", "2"): 2, ("R15", "2"): 3, ("J4", "1"): 2, ("C25", "1"): 2}   # plane feed points: vias per pad


def ref_key(s):
    """Natural sort key: R2 before R10, pad 9 before pad 10."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def plane_xy(p):
    return (TM(p.x) - OX, OY - TM(p.y))


def kicad_xy(x, y):
    return pcbnew.VECTOR2I(FM(OX + x), FM(OY - y))


def poly_rings(sps):
    """SHAPE_POLY_SET -> list of outlines, each a list of rings [outline, hole, ...] in plane mm."""
    out = []
    for i in range(sps.OutlineCount()):
        rings = []
        for chain in [sps.Outline(i)] + [sps.Hole(i, h) for h in range(sps.HoleCount(i))]:
            rings.append([plane_xy(chain.CPoint(j)) for j in range(chain.PointCount())])
        out.append(rings)
    return out


# ----------------------------------------------------------------------------- shape records (see maze.c)
def capsule(mask, a, b, r):
    return [0.0, float(mask), a[0], a[1], b[0], b[1], r]


def polygon(mask, pts):
    rec = [1.0, float(mask), float(len(pts))]
    for x, y in pts:
        rec += [x, y]
    return rec


def ringset(mask, rings):
    rec = [2.0, float(mask), float(len(rings))]
    for r in rings:
        rec.append(float(len(r)))
        for x, y in r:
            rec += [x, y]
    return rec


def dbuf(recs):
    flat = [v for r in recs for v in r]
    return (ctypes.c_double * max(1, len(flat)))(*flat), len(recs)


# ----------------------------------------------------------------------------- C core
class GridS(ctypes.Structure):
    _fields_ = [("nx", ctypes.c_int), ("ny", ctypes.c_int), ("nl", ctypes.c_int),
                ("x0", ctypes.c_double), ("y0", ctypes.c_double), ("res", ctypes.c_double),
                ("d1", ctypes.POINTER(ctypes.c_float)), ("d2", ctypes.POINTER(ctypes.c_float)),
                ("n1", ctypes.POINTER(ctypes.c_uint16)), ("hole", ctypes.POINTER(ctypes.c_float)),
                ("smd", ctypes.POINTER(ctypes.c_float)), ("viablock", ctypes.POINTER(ctypes.c_uint8)),
                ("cost", ctypes.POINTER(ctypes.c_uint8))]


F4 = ctypes.c_float * 4


class Params(ctypes.Structure):
    _fields_ = [("net", ctypes.c_int), ("layers", ctypes.c_int), ("hw", F4), ("hwn", F4),
                ("via_r", ctypes.c_float), ("via_hole", ctypes.c_float), ("via_smd", ctypes.c_float),
                ("via_cost", ctypes.c_float), ("allow_via", ctypes.c_int), ("layer_cost", F4),
                ("turn45", ctypes.c_float), ("turn90", ctypes.c_float), ("narrow_pen", ctypes.c_float),
                ("cost_scale", ctypes.c_float),
                ("wx0", ctypes.c_int), ("wy0", ctypes.c_int), ("wx1", ctypes.c_int), ("wy1", ctypes.c_int),
                ("target_via", ctypes.c_int),
                ("vx0", ctypes.c_int), ("vy0", ctypes.c_int), ("vx1", ctypes.c_int), ("vy1", ctypes.c_int),
                ("max_expand", ctypes.c_long), ("conflict_cost", ctypes.c_float)]


def load_core():
    src = os.path.join(TOOLS, "router", "maze.c")
    lib = os.path.join(BUILD, "maze.dylib")
    if not os.path.exists(lib) or os.path.getmtime(lib) < os.path.getmtime(src):
        os.makedirs(BUILD, exist_ok=True)
        subprocess.run(["clang", "-O3", "-shared", "-fPIC", "-o", lib, src], check=True)
    core = ctypes.CDLL(lib)
    core.stamp.argtypes = [ctypes.POINTER(GridS), ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.c_double,
                           ctypes.c_int, ctypes.c_double, ctypes.c_int, ctypes.c_int]
    core.reset.argtypes = [ctypes.POINTER(GridS)]
    core.astar.argtypes = [ctypes.POINTER(GridS), ctypes.POINTER(Params), ctypes.POINTER(ctypes.c_double), ctypes.c_int,
                           ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.POINTER(ctypes.c_double), ctypes.c_int,
                           ctypes.POINTER(ctypes.c_int32), ctypes.c_int, ctypes.POINTER(GridS)]
    core.astar.restype = ctypes.c_int
    core.via_fits.argtypes = [ctypes.POINTER(GridS), ctypes.POINTER(Params), ctypes.c_int, ctypes.c_int]
    core.cell_free.argtypes = [ctypes.POINTER(GridS), ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    core.cell_free.restype = ctypes.c_float
    return core


def cell(x, y):
    return int(round((x - X0) / RES)), int(round((y - Y0) / RES))


def cxy(ix, iy):
    return (round(X0 + ix * RES, 4), round(Y0 + iy * RES, 4))


# ----------------------------------------------------------------------------- the router
class Pad:
    def __init__(self, ref, kp, netid, net):
        self.ref, self.num, self.net, self.netid, self.k = ref, kp.GetNumber(), net, netid, kp
        self.mask = sum(1 << i for i, L in enumerate(LAYERS) if kp.IsOnLayer(L))
        self.smd = kp.GetAttribute() in (pcbnew.PAD_ATTRIB_SMD, pcbnew.PAD_ATTRIB_CONN)
        self.at = plane_xy(kp.GetPosition())
        layer = pcbnew.B_Cu if self.mask & (1 << B) and not self.mask & (1 << F) else pcbnew.F_Cu
        sps = pcbnew.SHAPE_POLY_SET()
        kp.TransformShapeToPolygon(sps, layer, 0, FM(0.002), pcbnew.ERROR_OUTSIDE)
        # every outline and hole of the pad copper, read even-odd (ring pads keep their hole)
        self.rings = [ring for outline in poly_rings(sps) for ring in outline] if sps.OutlineCount() else None
        xs = [p[0] for p in self.rings[0]] if self.rings else [self.at[0]]
        ys = [p[1] for p in self.rings[0]] if self.rings else [self.at[1]]
        self.box = (min(xs), min(ys), max(xs), max(ys))
        self.minw = min(self.box[2] - self.box[0], self.box[3] - self.box[1])
        # own clearance and an enlarged mask opening (fiducials) both keep other copper further away
        local = kp.GetLocalClearance()
        mask = kp.GetSolderMaskExpansion(pcbnew.B_Cu if self.mask & (1 << B) else pcbnew.F_Cu)
        self.clr = max(CLEAR, TM(local) if local else 0.0, TM(mask) + 0.05 if mask > 0 else 0.0)
        self.hole = None
        if kp.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
            hs = kp.GetEffectiveHoleShape()
            seg = hs.GetSeg()
            self.hole = (plane_xy(seg.A), plane_xy(seg.B), TM(hs.GetWidth()) / 2)

    def shape(self, mask=None):
        mask = self.mask if mask is None else mask
        return polygon(mask, self.rings[0]) if len(self.rings) == 1 else ringset(mask, self.rings)

    def contains(self, x, y, tol=0.01):
        """Inside the pad copper (outline minus any hole, even-odd), or on its edge (maze.c counts edge cells in)."""
        inside = False
        for pts in self.rings:
            j = len(pts) - 1
            for i in range(len(pts)):
                xi, yi = pts[i]
                xj, yj = pts[j]
                if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                    inside = not inside
                if seg_dist((x, y), pts[i], pts[j]) < tol:
                    return True
                j = i
        return inside

    def holds(self, a, b):
        """The straight stub a-b stays on this pad's copper (so a stub to the anchor never crosses a hole)."""
        n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.05))
        return all(self.contains(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n, tol=0)
                   for i in range(n + 1))


class Router:
    def __init__(self, board):
        self.b = board
        self.core = load_core()
        n = NX * NY
        types = dict(d1=(ctypes.c_float, 4 * n), d2=(ctypes.c_float, 4 * n), n1=(ctypes.c_uint16, 4 * n),
                     hole=(ctypes.c_float, n), smd=(ctypes.c_float, n), viablock=(ctypes.c_uint8, n),
                     cost=(ctypes.c_uint8, 4 * n))
        self.arr = {k: (t * m)() for k, (t, m) in types.items()}
        self.snap = {k: (t * m)() for k, (t, m) in types.items()}
        self.arr2 = {k: (t * m)() for k, (t, m) in types.items()}       # one net's view, for rip-up searches

        def grid(a):
            return GridS(NX, NY, 4, X0, Y0, RES, *[ctypes.cast(a[k], ctypes.POINTER(types[k][0])) for k in (
                "d1", "d2", "n1", "hole", "smd", "viablock", "cost")])
        self.g, self.g_own = grid(self.arr), grid(self.arr2)
        self.conflict = None          # set while searching for the least-disturbing path
        self.netid = {}
        for name, item in board.GetNetsByName().items():
            name = str(name)
            if name:
                self.netid[name] = item.GetNetCode()
        assert max(self.netid.values()) < NET_BLOCK
        self.pads, self.by_net = [], {}
        # by reference and pad number: KiCad saves footprints in an order tied to their random UUIDs, and the
        # result must depend on the placement only
        for fp in sorted(board.GetFootprints(), key=lambda f: ref_key(f.GetReference())):
            for kp in sorted(fp.Pads(), key=lambda q: (ref_key(q.GetNumber()), plane_xy(q.GetPosition()))):
                if not kp.GetLayerSet().Contains(pcbnew.F_Cu) and not kp.GetLayerSet().Contains(pcbnew.B_Cu) \
                        and kp.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH:
                    continue
                net = kp.GetNetname()
                p = Pad(fp.GetReference(), kp, self.netid.get(net, 0) or NET_BLOCK, net)
                self.pads.append(p)
                if net and not net.startswith("unconnected-"):
                    self.by_net.setdefault(net, []).append(p)
        self.static = []          # (record, kind, clearance, net, invert, value)
        self.tracks = []          # dict(net, layer, a, b, w, conn)
        self.vias = []            # dict(net, at, conn)
        self.conns = {}           # conn id -> dict(net, kind 'tree' | 'fan', pad)
        self.tree = {}            # net -> pads joined so far
        self.orders = {}          # net -> preferred pad order (root first)
        self.failed = []          # (net, pad, kind)
        self.ripped = {}          # net -> times ripped up
        self.log = []
        self.static_obstacles()
        self.core.reset(ctypes.byref(self.g))
        for rec, kind, clr, net, inv, val in self.static:
            self.stamp(rec, kind, clr, net, inv, val)
        for k, a in self.arr.items():
            ctypes.memmove(self.snap[k], a, ctypes.sizeof(a))

    # ---- fields
    def stamp(self, rec, kind=0, clearance=CLEAR, net=NET_BLOCK, invert=0, value=0, grid=None):
        buf, _ = dbuf([rec])
        self.core.stamp(ctypes.byref(grid or self.g), buf, kind, clearance, net, REACH, invert, value)

    def static_obstacles(self):
        S = self.static.append
        for p in self.pads:
            if p.k.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                a, b_, r = p.hole
                S((capsule(ALL, a, b_, r), 0, HOLE_CLEAR, NET_BLOCK, 0, 0))
                S((capsule(ALL, a, b_, r), 1, 0, 0, 0, 0))
                continue
            S((p.shape(), 0, p.clr, p.netid, 0, 0))
            if p.hole:
                a, b_, r = p.hole
                S((capsule(ALL, a, b_, r), 0, HOLE_CLEAR, p.netid, 0, 0))
                S((capsule(ALL, a, b_, r), 1, 0, 0, 0, 0))
            if p.smd:
                S((p.shape(), 2, 0, 0, 0, 0))
        outline = pcbnew.SHAPE_POLY_SET()
        self.b.GetBoardPolygonOutlines(outline, False)
        self.outline = poly_rings(outline)[0]
        S((ringset(ALL, self.outline), 0, EDGE_CLEAR, NET_BLOCK, 1, 0))
        fps = sorted(self.b.GetFootprints(), key=lambda f: ref_key(f.GetReference()))
        zones = sorted(self.b.Zones(), key=lambda z: (z.GetZoneName(), plane_xy(z.GetPosition()))) + \
            [z for fp in fps for z in fp.Zones()]
        for z in zones:
            if not z.GetIsRuleArea():
                continue
            mask = sum(1 << i for i, L in enumerate(LAYERS) if z.GetLayerSet().Contains(L))
            for rings in poly_rings(z.Outline()):
                if z.GetDoNotAllowTracks():
                    S((polygon(mask, rings[0]), 0, 0.0, NET_BLOCK, 0, 0))
                elif z.GetDoNotAllowVias():
                    S((polygon(mask, rings[0]), 3, VIA_D / 2 + 0.01, 0, 0, 0))
        # soft costs: stay out from under bottom-side bodies unless it saves a lot
        for fp in fps:
            fp.BuildCourtyardCaches()
            c = fp.GetCourtyard(pcbnew.B_CrtYd)
            if not c.OutlineCount():
                continue
            ref = fp.GetReference()
            # fine-pitch ICs: wrapping a track round them blocks their pins' escapes
            value = 48 if ref in ("U5", "U2") else 20 if ref.startswith(("K", "J1", "J2", "SW")) else 8
            for rings in poly_rings(c):
                S((polygon(1 << B, rings[0]), 4, 0.0, 0, 0, value))

    def load_field(self, only_net=None):
        """Static obstacles plus all routed copper into the main grid; with only_net, static obstacles plus that
        net's copper into the second grid instead (the main one keeps the full board for conflict costs)."""
        arr, g = (self.arr, self.g) if only_net is None else (self.arr2, self.g_own)
        for k, a in self.snap.items():
            ctypes.memmove(arr[k], a, ctypes.sizeof(a))
        for t in self.tracks:
            if only_net is None or t["net"] == only_net:
                self.stamp(capsule(1 << t["layer"], t["a"], t["b"], t["w"] / 2), 0, CLEAR, self.netid[t["net"]],
                           grid=g)
        for v in self.vias:
            if only_net is None or v["net"] == only_net:
                self.stamp(capsule(ALL, v["at"], v["at"], VIA_D / 2), 0, CLEAR, self.netid[v["net"]], grid=g)
                self.stamp(capsule(ALL, v["at"], v["at"], VIA_DRILL / 2), 1, grid=g)

    def stamp_track(self, t):
        self.stamp(capsule(1 << t["layer"], t["a"], t["b"], t["w"] / 2), 0, CLEAR, self.netid[t["net"]])

    def stamp_via(self, v):
        self.stamp(capsule(ALL, v["at"], v["at"], VIA_D / 2), 0, CLEAR, self.netid[v["net"]])
        self.stamp(capsule(ALL, v["at"], v["at"], VIA_DRILL / 2), 1)

    # ---- one search
    def neck(self, net, w, pads=None):
        """Width a wide track narrows to next to its pads: no narrower than the smallest SMD pad needs."""
        m = min((p.minw for p in (pads or self.by_net.get(net, [])) if p.smd), default=w)
        return max(NARROW, min(w, math.floor((m - 0.1) * 20) / 20))

    def params(self, net, w, layers=OUTER, allow_via=True, layer_cost=(1.0, 3.0, 3.0, 1.15), via_cost=12.0,
               window=None, target_via=None, nw=None):
        p = Params()
        p.net = self.netid[net]
        p.layers = layers
        nw = min(w, NARROW) if nw is None else nw
        for i in range(4):
            p.hw[i] = w / 2 + SLACK
            p.hwn[i] = nw / 2 + SLACK
            p.layer_cost[i] = layer_cost[i]
        p.via_r = VIA_D / 2
        p.via_hole = VIA_DRILL / 2 + HOLE_TO_HOLE
        p.via_smd = VIA_D / 2 + 0.05
        p.via_cost = via_cost
        p.allow_via = 1 if allow_via else 0
        p.turn45, p.turn90, p.narrow_pen, p.cost_scale = 0.6, 4.0, 1.5, 1.0
        x0, y0, x1, y1 = window
        p.wx0, p.wy0 = [max(0, v) for v in cell(x0, y0)]
        p.wx1, p.wy1 = min(NX - 1, cell(x1, y1)[0]), min(NY - 1, cell(x1, y1)[1])
        p.target_via = 0
        if target_via:
            p.target_via = 1
            vx0, vy0, vx1, vy1 = target_via
            p.vx0, p.vy0 = [max(0, v) for v in cell(vx0, vy0)]
            p.vx1, p.vy1 = min(NX - 1, cell(vx1, vy1)[0]), min(NY - 1, cell(vx1, vy1)[1])
        p.max_expand = 40_000_000
        p.conflict_cost = 40.0
        return p

    def search(self, p, src, tgt, narrow):
        sb, ns = dbuf(src)
        tb, nt = dbuf(tgt)
        nb, nn = dbuf(narrow)
        cap = 200_000
        out = (ctypes.c_int32 * (4 * cap))()
        if self.conflict:
            n = self.core.astar(ctypes.byref(self.g_own), ctypes.byref(p), sb, ns, tb, nt, nb, nn, out, cap,
                                ctypes.byref(self.g))
        else:
            n = self.core.astar(ctypes.byref(self.g), ctypes.byref(p), sb, ns, tb, nt, nb, nn, out, cap, None)
        if n < 0:
            return None
        path = [(out[4 * i], out[4 * i + 1], out[4 * i + 2], out[4 * i + 3]) for i in range(n)]
        return path[::-1]

    # ---- path -> copper
    def path_copper(self, net, path, w, nw=None):
        """Cell path -> (tracks, via points): straight runs merged, a via wherever the layer changes."""
        pts = [(l, cxy(ix, iy), fl) for l, ix, iy, fl in path]
        tracks, vias = [], []
        runs, cur = [], [pts[0]]
        for prev, nxt in zip(pts, pts[1:]):
            if nxt[0] != prev[0]:
                vias.append(prev[1])
                runs.append(cur)
                cur = [nxt]
            else:
                cur.append(nxt)
        runs.append(cur)
        nw = min(w, NARROW) if nw is None else nw
        for run in runs:
            layer = run[0][0]
            if len(run) < 2:
                continue
            seg_start = run[0][1]
            seg_w = nw if run[1][2] & 1 else w          # each cell carries the width of the step into it
            seg_dir = (round((run[1][1][0] - run[0][1][0]) / RES), round((run[1][1][1] - run[0][1][1]) / RES))
            for i in range(1, len(run) - 1):
                a, b_ = run[i], run[i + 1]
                d = (round((b_[1][0] - a[1][0]) / RES), round((b_[1][1] - a[1][1]) / RES))
                sw = nw if b_[2] & 1 else w
                if d != seg_dir or sw != seg_w:
                    tracks.append(dict(net=net, layer=layer, a=seg_start, b=a[1], w=seg_w))
                    seg_start, seg_dir, seg_w = a[1], d, sw
            tracks.append(dict(net=net, layer=layer, a=seg_start, b=run[-1][1], w=seg_w))
        return pts, tracks, vias

    def commit_path(self, net, path, w, start, end, kind, pad, nw=None):
        """Turn a cell path into tracks and vias. start/end: ('pad', Pad) | ('track', t) | ('via', v), and end may
        also be ('newvia', None). pad is the pad this connection was made for (rip-up re-routes it)."""
        nw = min(w, NARROW) if nw is None else nw
        pts, tracks, vias = self.path_copper(net, path, w, nw)
        first_w = tracks[0]["w"] if tracks else nw
        last_w = tracks[-1]["w"] if tracks else nw
        # stubs into the exact pad / via / track the path started and ended on (a pad stub only when it stays on
        # the pad: a ring pad's anchor can sit across its hole, and the path already ends on its copper)
        skind, sobj = start
        first_l, first_xy = pts[0][0], pts[0][1]
        if skind == "pad" and first_xy != sobj.at and sobj.holds(sobj.at, first_xy) and \
                self.stub_ok(net, first_l, sobj.at, first_xy, min(first_w, max(sobj.minw, 0.15))):
            sw = min(first_w, max(sobj.minw, 0.15))
            tracks.insert(0, dict(net=net, layer=first_l, a=sobj.at, b=first_xy, w=sw))
        elif skind == "via" and first_xy != sobj["at"]:
            tracks.insert(0, dict(net=net, layer=first_l, a=sobj["at"], b=first_xy, w=first_w))
        elif skind == "track":
            q = project(first_xy, sobj["a"], sobj["b"])
            if q != first_xy:
                tracks.insert(0, dict(net=net, layer=first_l, a=q, b=first_xy, w=min(first_w, sobj["w"])))
            self.split_track(sobj, q)
        ekind, obj = end
        last_l, last_xy = pts[-1][0], pts[-1][1]
        if ekind == "pad" and last_xy != obj.at and obj.holds(last_xy, obj.at) and \
                self.stub_ok(net, last_l, last_xy, obj.at, min(last_w, max(obj.minw, 0.15))):
            tracks.append(dict(net=net, layer=last_l, a=last_xy, b=obj.at, w=min(last_w, max(obj.minw, 0.15))))
        elif ekind == "via" and last_xy != obj["at"]:
            tracks.append(dict(net=net, layer=last_l, a=last_xy, b=obj["at"], w=last_w))
        elif ekind == "track":
            q = project(last_xy, obj["a"], obj["b"])
            if q != last_xy:
                tracks.append(dict(net=net, layer=last_l, a=last_xy, b=q, w=min(last_w, obj["w"])))
            self.split_track(obj, q)
        elif ekind == "newvia":
            vias.append(last_xy)
        cid = len(self.conns) + 1
        while cid in self.conns:
            cid += 1
        self.conns[cid] = dict(net=net, kind=kind, pad=pad)
        for t in tracks:
            if t["a"] != t["b"]:
                t["conn"] = cid
                self.tracks.append(t)
                self.stamp_track(t)
        for at in vias:
            v = dict(net=net, at=at, conn=cid)
            self.vias.append(v)
            self.stamp_via(v)
        return cid

    def stub_ok(self, net, layer, a, b, w):
        """A stub drawn off the grid still clears everything: every point's nearest cell has room for it."""
        nid = self.netid[net]
        n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.05))
        for i in range(n + 1):
            ix, iy = cell(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)
            if self.core.cell_free(ctypes.byref(self.g), layer, ix, iy, nid) < w / 2 + RES * 0.7072:
                return False
        return True

    def split_track(self, t, q):
        if q in (t["a"], t["b"]):
            return
        self.tracks.remove(t)
        self.tracks.append(dict(t, b=q))
        self.tracks.append(dict(t, a=q))

    def remove(self, nets=(), conns=()):
        nets, conns = set(nets), set(conns)
        self.tracks = [t for t in self.tracks if t["net"] not in nets and t["conn"] not in conns]
        self.vias = [v for v in self.vias if v["net"] not in nets and v["conn"] not in conns]
        for c in list(self.conns):
            if self.conns[c]["net"] in nets or c in conns:
                del self.conns[c]
        for n in nets:
            self.tree.pop(n, None)

    # ---- nets
    def target_shapes(self, net, pads):
        shapes, items = [], []
        for p in pads:
            shapes.append(p.shape(p.mask & OUTER))
            items.append(("pad", p))
        for t in self.tracks:
            if t["net"] == net and self.conns[t["conn"]]["kind"] != "escape":
                shapes.append(capsule(1 << t["layer"], t["a"], t["b"], RES * 0.75))
                items.append(("track", t))
        for v in self.vias:
            if v["net"] == net and self.conns[v["conn"]]["kind"] != "escape":
                shapes.append(capsule(OUTER, v["at"], v["at"], RES * 0.75))
                items.append(("via", v))
        return shapes, items

    def source_shapes(self, p):
        """A pad plus its escape (the short stub and via it was given before routing)."""
        shapes, items = [p.shape(p.mask & OUTER)], [("pad", p)]
        own = {c for c, k in self.conns.items() if k["kind"] == "escape" and k["pad"] is p}
        for t in self.tracks:
            if t["conn"] in own:
                shapes.append(capsule(1 << t["layer"], t["a"], t["b"], RES * 0.75))
                items.append(("track", t))
        for v in self.vias:
            if v["conn"] in own:
                shapes.append(capsule(OUTER, v["at"], v["at"], RES * 0.75))
                items.append(("via", v))
        return shapes, items, own

    def hit(self, items, layer, xy):
        x, y = xy
        for kind, it in items:
            if kind == "pad" and it.mask & (1 << layer) and it.contains(x, y):
                return kind, it
        for kind, it in items:
            if kind == "via" and math.hypot(x - it["at"][0], y - it["at"][1]) <= RES * 0.8:
                return kind, it
            if kind == "track" and it["layer"] == layer and seg_dist(xy, it["a"], it["b"]) <= RES * 0.8:
                return kind, it
        return None

    def narrow_zones(self, pads):
        return [capsule(ALL, p.at, p.at, math.hypot(p.box[2] - p.box[0], p.box[3] - p.box[1]) / 2 + 0.8)
                for p in pads]

    def find_tree(self, net, p, margins=(6.0, 25.0, 200.0)):
        """Search from pad p (and its escape) to the net's tree. Returns (path, start item, end item) or None."""
        done = self.tree[net]
        w = BRANCH.get((p.ref, p.num), WIDTH.get(net, 0.2))
        tgt, items = self.target_shapes(net, done)
        src, src_items, _ = self.source_shapes(p)
        pts = [q.at for q in done] + [t[k] for t in self.tracks if t["net"] == net for k in ("a", "b")]
        narrow = self.narrow_zones(self.by_net[net])
        for m in margins:
            xs = [p.box[0], p.box[2]] + [a[0] for a in pts]
            ys = [p.box[1], p.box[3]] + [a[1] for a in pts]
            win = (min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m)
            path = self.search(self.params(net, w, window=win, nw=self.neck(net, w)), src, tgt, narrow)
            if path:
                start = self.hit(src_items, path[0][0], cxy(path[0][1], path[0][2]))
                end = self.hit(items, path[-1][0], cxy(path[-1][1], path[-1][2]))
                assert start and end, f"{net}: path ends match no item"
                return path, start, end
        return None

    def join(self, net, p):
        """Connect pad p to its net's tree; False when no legal path exists right now."""
        found = self.find_tree(net, p)
        if not found:
            return False
        path, start, end = found
        if len(path) > 1 or end[0] != "pad" or start[0] != "pad":
            w = BRANCH.get((p.ref, p.num), WIDTH.get(net, 0.2))
            self.commit_path(net, path, w, start, end, "tree", p, nw=self.neck(net, w))
        self.adopt_escape(p)
        self.tree[net].append(p)
        return True

    def adopt_escape(self, p):
        for c in self.source_shapes(p)[2]:
            self.conns[c]["kind"] = "tree"

    def escape(self, net, p, direction):
        """Pre-route pad p to a via on one side of it, so a neighbour can leave the other way."""
        dx, dy = direction
        x0, y0, x1, y1 = p.box
        cx, cy = p.at
        reach, side, gap = 2.5, 0.8, 0.4
        win = (x0 - (reach if dx < 0 else side), y0 - (reach if dy < 0 else side),
               x1 + (reach if dx > 0 else side), y1 + (reach if dy > 0 else side))
        via = (cx + gap if dx > 0 else -99, cy + gap if dy > 0 else -99,
               cx - gap if dx < 0 else 99, cy - gap if dy < 0 else 99)
        w = min(WIDTH.get(net, 0.2), NARROW)       # a short stub off a fine-pitch pin: keep it signal width
        par = self.params(net, w, allow_via=False, window=win, target_via=via, layer_cost=(1.0, 9, 9, 1.0))
        par.layers = p.mask & OUTER
        path = self.search(par, [p.shape(p.mask & OUTER)], [], self.narrow_zones([p]))
        if path:
            self.commit_path(net, path, w, ("pad", p), ("newvia", None), "escape", p)

    def route_net(self, net, order=None):
        if order:
            self.orders[net] = order
        order = self.orders.get(net)
        pads = list(self.by_net[net])
        if order:
            pads.sort(key=lambda p: order.index(p.ref) if p.ref in order else len(order))
        for q in pads:
            if (q.ref, q.num) in PRE_ESCAPE and not self.source_shapes(q)[2]:
                self.escape(net, q, PRE_ESCAPE[(q.ref, q.num)])
        self.tree[net] = [pads[0]]
        self.adopt_escape(pads[0])
        todo = pads[1:]
        while todo:
            tree_pts = [p.at for p in self.tree[net]] + \
                       [t[k] for t in self.tracks if t["net"] == net for k in ("a", "b")]
            p = min(todo, key=lambda q: min(math.hypot(q.at[0] - a[0], q.at[1] - a[1]) for a in tree_pts))
            todo.remove(p)
            if not self.join(net, p):
                self.failed.append((net, p, "tree"))

    def plane_copper(self, net, pad):
        """Same-net copper already tied to the plane: vias, fan-out tracks, through-hole pads, and exposed pads
        that carry their own thermal vias."""
        shapes, items = [], []
        thermal = {(q.ref, q.num) for q in self.by_net[net] if q.hole}
        for q in self.by_net[net]:
            if q is not pad and (q.hole or (q.ref, q.num) in thermal):
                shapes.append(q.shape(q.mask & OUTER))
                items.append(("pad", q))
        for t in self.tracks:
            if t["net"] == net and self.conns[t["conn"]]["kind"] == "fan":
                shapes.append(capsule(1 << t["layer"], t["a"], t["b"], RES * 0.75))
                items.append(("track", t))
        for v in self.vias:
            if v["net"] == net:
                shapes.append(capsule(OUTER, v["at"], v["at"], RES * 0.75))
                items.append(("via", v))
        return shapes, items

    def find_fan(self, pad, net, w, join=True):
        """Path from an SMD pad to a cell that takes a new via, or (join) to plane copper next to it."""
        x0, y0, x1, y1 = pad.box
        win = (x0 - 3.5, y0 - 3.5, x1 + 3.5, y1 + 3.5)
        vy0, vy1 = PLANES[net][1] or (-99, 99)
        par = self.params(net, w, allow_via=False, window=win, target_via=(-99, vy0, 99, vy1), nw=self.neck(net, w, [pad]),
                          layer_cost=(1.0, 9, 9, 1.0))
        par.layers = pad.mask & OUTER
        shapes, items = self.plane_copper(net, pad) if join else ([], [])
        path = self.search(par, [pad.shape(pad.mask & OUTER)], shapes, self.narrow_zones([pad]))
        if not path:
            return None
        end = self.hit(items, path[-1][0], cxy(path[-1][1], path[-1][2])) if items else None
        return path, end or ("newvia", None)

    def fanout(self, pad, net, count=1):
        """Short track from an SMD pad to a new via in its plane (count vias for plane feed points), or to plane
        copper right next to it (a GND pin beside its exposed pad)."""
        for i in range(count):
            found = self.find_fan(pad, net, WIDTH[net], join=count == 1)
            if not found:
                self.failed.append((net, pad, "fan"))
                return
            path, end = found
            if len(path) > 1 or end[0] != "pad":
                self.commit_path(net, path, WIDTH[net], ("pad", pad), end, "fan", pad,
                                 nw=self.neck(net, WIDTH[net], [pad]))

    # ---- rip-up and reroute
    def blockers(self, net, path, w):
        """Connections whose copper sits on the given path (found with only this net's copper present)."""
        _, tracks, vias = self.path_copper(net, path, w)
        hits = set()
        for t in self.tracks:
            if t["net"] == net:
                continue
            for u in tracks:
                if u["layer"] == t["layer"] and \
                        seg_seg(u["a"], u["b"], t["a"], t["b"]) < (u["w"] + t["w"]) / 2 + CLEAR + RES:
                    hits.add(t["conn"])
            for at in vias:
                if seg_dist(at, t["a"], t["b"]) < VIA_D / 2 + t["w"] / 2 + CLEAR + RES:
                    hits.add(t["conn"])
        for v in self.vias:
            if v["net"] == net:
                continue
            for u in tracks:
                if seg_dist(v["at"], u["a"], u["b"]) < VIA_D / 2 + u["w"] / 2 + CLEAR + RES:
                    hits.add(v["conn"])
            for at in vias:
                if math.hypot(at[0] - v["at"][0], at[1] - v["at"][1]) < VIA_D + CLEAR + RES:
                    hits.add(v["conn"])
        return hits

    def retry(self, item):
        net, pad, kind = item
        if kind == "tree":
            return self.join(net, pad)
        found = self.find_fan(pad, net, WIDTH[net])
        if found:
            path, end = found
            if len(path) > 1 or end[0] != "pad":
                self.commit_path(net, path, WIDTH[net], ("pad", pad), end, "fan", pad,
                                 nw=self.neck(net, WIDTH[net], [pad]))
            return True
        return False

    def repair(self, rounds=60, max_rips=4):
        hard = []
        while self.failed and rounds > 0:
            rounds -= 1
            item = self.failed.pop(0)
            net, pad, kind = item
            if self.retry(item):
                continue
            # the path that crosses the least routed copper (other nets passable at a cost), then rip up what
            # sits on it
            self.load_field(only_net=net)
            self.conflict = True
            found = self.find_tree(net, pad, margins=(10.0, 200.0)) if kind == "tree" else \
                self.find_fan(pad, net, WIDTH[net])
            self.conflict = None
            path = found[0] if found else None
            if not path:
                hard.append(item)
                continue
            hits = self.blockers(net, path, WIDTH.get(net, 0.2))
            nets = {self.conns[c]["net"] for c in hits if self.conns[c]["kind"] in ("tree", "escape")}
            fans = [c for c in hits if self.conns[c]["kind"] == "fan"]
            nets = {n for n in nets if self.ripped.get(n, 0) < max_rips and n not in NO_RIP}
            if not nets and not fans:
                hard.append(item)
                continue
            fan_pads = [(self.conns[c]["net"], self.conns[c]["pad"]) for c in fans]
            for n in nets:
                self.ripped[n] = self.ripped.get(n, 0) + 1
            self.remove(nets=nets, conns=fans)
            self.failed = [f for f in self.failed if f[0] not in nets]
            self.load_field()
            if not self.retry(item):
                hard.append(item)
            for n in sorted(nets):
                self.route_net(n)
            for n, p in fan_pads:
                if not self.retry((n, p, "fan")):
                    self.failed.append((n, p, "fan"))
            self.log.append(("ripped", net, pad.ref, pad.num, sorted(nets), len(fans)))
        self.failed = hard + self.failed

    # ---- clean-up
    def touches(self, net, layer, pt, skip):
        """KiCad joins a track end to another track only at that track's end (T-junctions are split for this)."""
        for t in self.tracks:
            if t is not skip and t["net"] == net and t["layer"] == layer and \
                    min(math.hypot(pt[0] - t["a"][0], pt[1] - t["a"][1]),
                        math.hypot(pt[0] - t["b"][0], pt[1] - t["b"][1])) < 1e-3:
                return True
        for v in self.vias:
            if v["net"] == net and math.hypot(pt[0] - v["at"][0], pt[1] - v["at"][1]) <= VIA_D / 2:
                return True
        return any(p.mask & (1 << layer) and p.contains(*pt) for p in self.by_net.get(net, []))

    def cleanup(self):
        """Drop vias that join fewer than two layers (a plane counts) and track stubs that end on nothing."""
        removed = 0
        while True:
            gone = []
            for v in self.vias:
                if v["net"] in PLANES:
                    continue
                layers = {t["layer"] for t in self.tracks if t["net"] == v["net"] and
                          seg_dist(v["at"], t["a"], t["b"]) <= t["w"] / 2 + 1e-6}
                for p in self.by_net[v["net"]]:
                    if p.contains(*v["at"], tol=VIA_D / 2):
                        layers |= {i for i in (F, B) if p.mask & (1 << i)}
                if len(layers) < 2:
                    gone.append(("via", v))
            for t in self.tracks:
                if not (self.touches(t["net"], t["layer"], t["a"], t) and self.touches(t["net"], t["layer"], t["b"], t)):
                    gone.append(("track", t))
            if not gone:
                break
            for kind, it in gone:
                (self.vias if kind == "via" else self.tracks).remove(it)
            removed += len(gone)
        self.log.append(("cleanup removed", removed))

    def stitch(self, pitch=4.0, spacing=2.0):
        """GND vias on a grid wherever one fits, so every piece of the outer GND pours reaches the In1 plane."""
        par = self.params("GND", 0.4, window=(X0, Y0, X0 + NX * RES, Y0 + NY * RES))
        made = []
        ring = self.outline[0]
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        y = min(ys) + pitch / 2
        while y < max(ys):
            x = min(xs) + pitch / 2
            while x < max(xs):
                best = None
                # look a little around each grid point for a spot that takes a via
                for ox, oy in ((0, 0), (0.5, 0), (-0.5, 0), (0, 0.5), (0, -0.5), (0.5, 0.5), (-0.5, -0.5),
                               (0.5, -0.5), (-0.5, 0.5), (1.0, 0), (-1.0, 0), (0, 1.0), (0, -1.0)):
                    ix, iy = cell(x + ox, y + oy)
                    if self.core.via_fits(ctypes.byref(self.g), ctypes.byref(par), ix, iy):
                        best = cxy(ix, iy)
                        break
                if best and all(math.hypot(best[0] - v["at"][0], best[1] - v["at"][1]) >= spacing
                                for v in self.vias if v["net"] == "GND"):
                    cid = max(self.conns, default=0) + 1
                    self.conns[cid] = dict(net="GND", kind="stitch", pad=None)
                    v = dict(net="GND", at=best, conn=cid)
                    self.vias.append(v)
                    self.stamp_via(v)
                    made.append(v)
                x += pitch
            y += pitch
        self.log.append(("stitching vias", len(made)))

    # ---- stages
    def stage_power_usb(self):
        t0 = time.time()
        for (ref, num), d in PRE_ESCAPE.items():
            p = next(q for q in self.pads if q.ref == ref and q.num == num)
            self.escape(p.net, p, d)
        plan = [("USB_DP", ["J1", "U1", "U5"]), ("USB_DM", ["J1", "U1", "U5"]),
                ("/Power/CC1", None), ("/Power/CC2", None),
                ("/Power/VBUS_IN", ["J1", "F1"]),
                ("VBUS", ["F1", "U1", "U2", "C1", "C12", "U5", "TP1"]),
                ("VSYS", ["U2", "C2", "U3", "C5", "TP2", "U4", "C7", "SW1"]),
                ("VBAT", ["J2", "C3", "U2", "R10", "TP3"]),
                ("/Power/VLED_SW", ["U4", "R20", "R15"]),
                ("/Power/3V3_LDO", ["U3", "C6", "R14"])]
        for net, order in plan:
            self.route_net(net, order)
        self.repair()
        self.log.append(("power+usb", round(time.time() - t0, 1)))

    def ep_join(self, p):
        """Straight stub from an IC's GND pin into the exposed pad beside it (which has its own thermal vias).
        Checked exactly against the other pins rather than on the grid: the gap is right at the clearance."""
        eps = [q for q in self.by_net[p.net] if q.ref == p.ref and q is not p and q.smd and
               any(h.ref == q.ref and h.num == q.num and h.hole for h in self.by_net[p.net])]
        for ep in eps:
            ex0, ey0, ex1, ey1 = ep.box
            (cx, cy), horizontal = p.at, (p.box[2] - p.box[0]) > (p.box[3] - p.box[1])
            if horizontal and ey0 < cy < ey1:
                end = ((ex1 - 0.15) if cx > ex1 else (ex0 + 0.15), cy)
            elif not horizontal and ex0 < cx < ex1:
                end = (cx, (ey1 - 0.15) if cy > ey1 else (ey0 + 0.15))
            else:
                continue
            layer = B if p.mask & (1 << B) else F
            for w in (0.2, 0.15):
                if self.clear_of_others(p.net, layer, p.at, end, w):
                    t = dict(net=p.net, layer=layer, a=p.at, b=end, w=w)
                    cid = max(self.conns, default=0) + 1
                    self.conns[cid] = dict(net=p.net, kind="fan", pad=p)
                    t["conn"] = cid
                    self.tracks.append(t)
                    self.stamp_track(t)
                    return True
        return False

    def clear_of_others(self, net, layer, a, b, w):
        need = w / 2 + CLEAR + 0.005
        for q in self.pads:
            if q.net == net or not q.mask & (1 << layer):
                continue
            if q.box[0] - need > max(a[0], b[0]) or q.box[2] + need < min(a[0], b[0]) or \
                    q.box[1] - need > max(a[1], b[1]) or q.box[3] + need < min(a[1], b[1]):
                continue
            ring = q.rings[0]
            if q.contains(a[0], a[1], 0) or any(seg_seg(a, b, ring[i], ring[i - 1]) < need for i in range(len(ring))):
                return False
        for t in self.tracks:
            if t["net"] != net and t["layer"] == layer and seg_seg(a, b, t["a"], t["b"]) < (w + t["w"]) / 2 + CLEAR:
                return False
        for v in self.vias:
            if v["net"] != net and seg_dist(v["at"], a, b) < w / 2 + VIA_D / 2 + CLEAR:
                return False
        return True

    def stage_planes(self):
        t0 = time.time()
        for net in PLANES:
            for p in self.by_net[net]:
                if p.smd and not self.ep_join(p):   # through-hole pads join the inner planes directly
                    self.fanout(p, net, FEEDS.get((p.ref, p.num), 1))
        self.repair()
        self.log.append(("planes", round(time.time() - t0, 1)))

    def stage_signals(self, nets):
        t0 = time.time()
        for net in nets:
            self.route_net(net)
        self.repair()
        self.log.append(("signals", round(time.time() - t0, 1)))


def seg_seg(a, b, c, d):
    """Distance between segments ab and cd."""
    def cross(o, p, q):
        return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
    d1, d2, d3, d4 = cross(c, d, a), cross(c, d, b), cross(a, b, c), cross(a, b, d)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 and d2 and d3 and d4:
        return 0.0
    return min(seg_dist(a, c, d), seg_dist(b, c, d), seg_dist(c, a, b), seg_dist(d, a, b))


def seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dy * dy
    t = 0 if l2 == 0 else max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2))
    return math.hypot(a[0] + t * dx - p[0], a[1] + t * dy - p[1])


def project(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dy * dy
    t = 0 if l2 == 0 else max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2))
    return (round(a[0] + t * dx, 4), round(a[1] + t * dy, 4))


# ----------------------------------------------------------------------------- board output
def clear_routing(board):
    zones = [z for z in board.Zones() if z.GetZoneName().startswith("route:")]
    tracks = list(board.GetTracks())
    for item in zones + tracks:
        board.Delete(item)


def write_copper(board, r):
    for t in r.tracks:
        k = pcbnew.PCB_TRACK(board)
        k.SetStart(kicad_xy(*t["a"]))
        k.SetEnd(kicad_xy(*t["b"]))
        k.SetWidth(FM(t["w"]))
        k.SetLayer(LAYERS[t["layer"]])
        k.SetNet(board.FindNet(t["net"]))
        board.Add(k)
    stitches = []
    for v in r.vias:
        k = pcbnew.PCB_VIA(board)
        k.SetPosition(kicad_xy(*v["at"]))
        k.SetViaType(pcbnew.VIATYPE_THROUGH)
        k.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        k.SetWidth(FM(VIA_D))
        k.SetDrill(FM(VIA_DRILL))
        k.SetNet(board.FindNet(v["net"]))
        board.Add(k)
        if r.conns[v["conn"]]["kind"] == "stitch":
            stitches.append(k)
    return stitches


def prune_stitches(board, stitches):
    """After the fill: a stitching via must land in GND pour on at least two layers (In1 and an outer pour)."""
    gnd = [z for z in board.Zones() if not z.GetIsRuleArea() and z.GetNetname() == "GND"]
    dead = []
    for k in stitches:
        pos = k.GetPosition()
        layers = {L for z in gnd for L in z.GetLayerSet().Seq() if z.HitTestFilledArea(L, pos)}
        if len(layers) < 2:
            dead.append(k)
    for k in dead:
        board.Delete(k)
    return len(dead)


def add_zone(board, name, layer, net, pts, priority=0, clearance=0.3):
    z = pcbnew.ZONE(board)
    z.SetZoneName("route:" + name)
    z.SetLayer(layer)
    z.SetNet(board.FindNet(net))
    z.SetLocalClearance(FM(clearance))
    z.SetMinThickness(FM(0.2))
    z.SetAssignedPriority(priority)
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THT_THERMAL)
    z.SetThermalReliefGap(FM(0.3))
    z.SetThermalReliefSpokeWidth(FM(0.4))
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    for x, y in pts:
        z.AppendCorner(kicad_xy(x, y), -1)
    board.Add(z)
    return z


def planes(board, r):
    ring = r.outline[0]
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    x0, x1, y0, y1 = min(xs) - 1, max(xs) + 1, min(ys) - 1, max(ys) + 1
    s0, s1 = SPLIT_Y - SPLIT_GAP / 2, SPLIT_Y + SPLIT_GAP / 2
    add_zone(board, "In2 +3V3", pcbnew.In2_Cu, "+3V3", [(x0, s1), (x1, s1), (x1, y1), (x0, y1)])
    add_zone(board, "In2 VLED", pcbnew.In2_Cu, "VLED", [(x0, y0), (x1, y0), (x1, s0), (x0, s0)])
    for layer, name in ((pcbnew.F_Cu, "F GND"), (pcbnew.B_Cu, "B GND")):
        add_zone(board, name, layer, "GND", [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


NO_RIP = {"USB_DP", "USB_DM", "/MCU/XL1", "/MCU/XL2"}   # routed first and kept: the rest go around them
STAGE1 = {"USB_DP", "USB_DM", "/Power/CC1", "/Power/CC2", "/Power/VBUS_IN", "VBUS", "VSYS", "VBAT",
          "/Power/VLED_SW", "/Power/3V3_LDO"}
FIRST = ["/MCU/XL1", "/MCU/XL2"]          # crystal first: shortest, most sensitive


def signal_order(r):
    rest = [n for n in r.by_net if n not in STAGE1 and n not in PLANES and n not in FIRST]

    def span(n):
        xs = [p.at[0] for p in r.by_net[n]]
        ys = [p.at[1] for p in r.by_net[n]]
        return (max(xs) - min(xs)) + (max(ys) - min(ys))
    return FIRST + sorted(rest, key=span)


def main():
    t0 = time.time()
    board = pcbnew.LoadBoard(PCB)
    clear_routing(board)
    r = Router(board)
    print(f"grid ready in {time.time() - t0:.1f} s: {len(r.pads)} pads, {len(r.by_net)} nets")
    r.stage_power_usb()
    print(f"power+usb: {len(r.tracks)} tracks, {len(r.vias)} vias, failed {[(n, p.ref, p.num) for n, p, _ in r.failed]}")
    r.stage_planes()
    print(f"planes: {len(r.tracks)} tracks, {len(r.vias)} vias, failed {[(n, p.ref, p.num) for n, p, _ in r.failed]}")
    r.stage_signals(signal_order(r))
    print(f"signals: {len(r.tracks)} tracks, {len(r.vias)} vias, failed {[(n, p.ref, p.num) for n, p, _ in r.failed]}")
    r.cleanup()
    r.stitch()
    for entry in r.log:
        print("  ", entry)
    stitches = write_copper(board, r)
    planes(board, r)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pruned = prune_stitches(board, stitches)
    if pruned:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    print(f"   stitching vias kept {len(stitches) - pruned}, dropped {pruned} (not in two GND pours)")
    pcbnew.SaveBoard(PCB, board)
    report = dict(tracks=len(r.tracks), vias=len(r.vias) - pruned, stitching=len(stitches) - pruned,
                  failed=[(n, p.ref, p.num, k) for n, p, k in r.failed],
                  log=[list(e) for e in r.log], seconds=round(time.time() - t0, 1))
    with open(os.path.join(BUILD, "route_report.json"), "w") as f:
        json.dump(report, f, indent=1)
    print(f"saved {PCB} in {time.time() - t0:.1f} s")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
