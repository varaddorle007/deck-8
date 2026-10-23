#!/usr/bin/env python3
"""Copy the stock footprints of the edge-mounted parts into lib/deck8.pretty without the silk that would run past
the board edge (USB-C opening, slide-switch lever, module antenna end).

Run with KiCad's Python on a board placed by gen_pcb.py, from footprints still pointing at the stock libraries:
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 trim_footprints.py

Each part is loaded twice from its stock library: once placed exactly like on the board (to see which silk items
leave it) and once untouched, which is what gets saved, minus those items. gen_schematic.py then names the
Deck8 copies, so DRC's library check compares against footprints that match the board.
"""
import math
import os
import subprocess
import sys

import pcbnew

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FP_DIR = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
LOCAL = os.path.join(HW, "lib", "deck8.pretty")
PARTS = {"J1": ("Connector_USB", "USB_C_Receptacle_HRO_TYPE-C-31-M-12"),
         "SW1": ("Button_Switch_SMD", "SW_SPDT_PCM12"),
         "U5": ("RF_Module", "Raytac_MDBT50Q")}
MARGIN = 0.15     # silk must stay this far inside the board edge


def rings(sps):
    out = []
    for i in range(sps.OutlineCount()):
        for chain in [sps.Outline(i)] + [sps.Hole(i, h) for h in range(sps.HoleCount(i))]:
            out.append([(pcbnew.ToMM(chain.CPoint(j).x), pcbnew.ToMM(chain.CPoint(j).y))
                        for j in range(chain.PointCount())])
    return out


def seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dy * dy
    t = 0 if l2 == 0 else max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2))
    return math.hypot(a[0] + t * dx - p[0], a[1] + t * dy - p[1])


def inside(edges, item):
    """All four bounding-box corners on the board (even-odd over outline and cut-outs) and MARGIN off any edge."""
    b = item.GetBoundingBox()
    for x, y in ((b.GetLeft(), b.GetTop()), (b.GetRight(), b.GetTop()),
                 (b.GetRight(), b.GetBottom()), (b.GetLeft(), b.GetBottom())):
        p = (pcbnew.ToMM(x), pcbnew.ToMM(y))
        hit = False
        for ring in edges:
            for i in range(len(ring)):
                (xi, yi), (xj, yj) = ring[i], ring[i - 1]
                if (yi > p[1]) != (yj > p[1]) and p[0] < (xj - xi) * (p[1] - yi) / (yj - yi) + xi:
                    hit = not hit
                if seg_dist(p, ring[i], ring[i - 1]) < MARGIN:
                    return False
        if not hit:
            return False
    return True


def main(only):
    board = pcbnew.LoadBoard(os.path.join(HW, "main", "deck8.kicad_pcb"))
    outline = pcbnew.SHAPE_POLY_SET()
    board.GetBoardPolygonOutlines(outline, False)
    edges = rings(outline)
    fps = {f.GetReference(): f for f in board.GetFootprints()}
    silk = (pcbnew.F_SilkS, pcbnew.B_SilkS)
    scratch = pcbnew.CreateEmptyBoard()          # a footprint can only be flipped once it sits on a board
    io = pcbnew.PCB_IO_KICAD_SEXPR()            # one plugin for every load and save: pcbnew's per-call helpers
                                                # lose their plugin after a few calls here
    for ref, (lib, name) in PARTS.items():
        if ref != only:
            continue
        on_board = fps[ref]
        placed = io.FootprintLoad(os.path.join(FP_DIR, lib + ".pretty"), name)
        clean = io.FootprintLoad(os.path.join(FP_DIR, lib + ".pretty"), name)
        scratch.Add(placed)
        if on_board.IsFlipped():
            placed.Flip(placed.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
        placed.SetOrientation(on_board.GetOrientation())
        placed.SetPosition(on_board.GetPosition())
        keep = list(clean.GraphicalItems())
        drop = [keep[i] for i, g in enumerate(placed.GraphicalItems())
                if g.GetLayer() in silk and g.GetClass() == "PCB_SHAPE" and not inside(edges, g)]
        for g in drop:
            clean.Remove(g)
        clean.SetFPID(pcbnew.LIB_ID("Deck8", name))
        io.FootprintSave(LOCAL, clean)
        print(f"{ref}: Deck8:{name}, {len(drop)} silk items past the edge removed")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        # one process per part: after a footprint save, this pcbnew build hands back untyped objects
        for ref in PARTS:
            subprocess.run([sys.executable, os.path.abspath(__file__), ref], check=True)
