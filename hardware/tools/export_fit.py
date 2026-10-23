#!/usr/bin/env python3
"""The routed board for the Fusion fit check: a STEP in plane coordinates plus envelopes for parts with no 3D model.

  build/deck8_pcb.step        board and every part KiCad has a model for, origin at the key-grid centre (the plane
                              origin shared with the Fusion script), X right, Y toward the back
  build/fit_envelopes.json    boxes Deck8Model.py extrudes on the board:
                              - "body": each part whose model this KiCad install lacks, its fab outline (the body
                                as the library draws it) on the side it sits on, by its datasheet height
                              - "plug": the mated cable plug in front of a side-entry connector (gen_pcb.PLUG,
                                also kept clear by the placer), so the check proves the cells and ring plug in

Run with KiCad's Python (check_pcb.py calls it):
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 export_fit.py
"""
import json
import os
import subprocess

import pcbnew

from gen_pcb import PLUG, plug_zone     # the plug boxes the placer keeps clear

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PCB = os.path.join(HW, "main", "deck8.kicad_pcb")
BUILD = os.path.join(HW, "build")
CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
MODELS = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/3dmodels"
OX, OY = 150.0, 100.0
TM = pcbnew.ToMM

# Body height off the board (mm) for parts whose model is missing here, from their datasheets.
HEIGHT = {
    "USB_C_Receptacle_HRO_TYPE-C-31-M-12": 3.26,               # HRO TYPE-C-31-M-12 shell
    "SW_Push_1P1T-MP_NO_Horizontal_Alps_SKRTLAE010": 3.5,      # Alps SKRT, actuator axis at half height
    "JST_PH_S2B-PH-SM4-TB_1x02-1MP_P2.00mm_Horizontal": 5.5,   # JST PH side entry (JST drawing)
    "SW_MX_Hotswap_Kailh_1u_NorthLED": 1.85,                   # the Kailh socket under the board
    "VQFN-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm_ThermalVias": 1.0,   # BQ24074 RGT package
}
# Modelled in Fusion already (reference encoders with bushing and shaft).
IN_FUSION = {"RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm"}


def has_model(fp):
    for m in fp.Models():
        path = m.m_Filename.replace("${KICAD10_3DMODEL_DIR}", MODELS)
        if os.path.exists(path) or os.path.exists(os.path.splitext(path)[0] + ".step"):
            return True
    return False


def fab_box(fp, layer):
    """Fab outline on one layer, without the line width; None if the footprint draws nothing there."""
    box = None
    for g in fp.GraphicalItems():
        if g.GetLayer() != layer:
            continue
        b = g.GetBoundingBox()
        w = g.GetWidth() // 2 if hasattr(g, "GetWidth") else 0
        b.Inflate(-w, -w)
        if box is None:
            box = b
        else:
            box.Merge(b)
    return box


def plane(b):
    return [round(TM(b.GetLeft()) - OX, 3), round(OY - TM(b.GetBottom()), 3),
            round(TM(b.GetRight()) - OX, 3), round(OY - TM(b.GetTop()), 3)]


def main():
    os.makedirs(BUILD, exist_ok=True)
    step = os.path.join(BUILD, "deck8_pcb.step")
    r = subprocess.run([CLI, "pcb", "export", "step", "--user-origin", f"{OX}x{OY}mm", "--subst-models", "--force",
                        "-o", step, PCB], capture_output=True, text=True)
    if r.returncode not in (0, 5) or not os.path.exists(step):
        raise SystemExit(f"STEP export failed: {r.stderr[-1500:]}")
    board = pcbnew.LoadBoard(PCB)
    envelopes, missing = [], []
    for fp in sorted(board.GetFootprints(), key=lambda f: f.GetReference()):
        name = str(fp.GetFPID().GetUniStringLibItemName())
        ref = fp.GetReference()
        # a hot-swap socket sits on the bottom under a footprint placed on top
        side = "B" if fp.IsFlipped() or name.startswith("SW_MX_Hotswap") else "F"
        body = fab_box(fp, pcbnew.B_Fab if side == "B" else pcbnew.F_Fab)
        if body is None:
            fp.BuildCourtyardCaches()
            body = fp.GetCourtyard(pcbnew.B_CrtYd if side == "B" else pcbnew.F_CrtYd).BBox()
        if name in PLUG:
            x0, y0, x1, y1 = plug_zone(fp)
            envelopes.append(dict(ref=ref, kind="plug", name=f"{ref} plug", footprint=name, side=side,
                                  height=PLUG[name][2], rect=[round(x0 - OX, 3), round(OY - y1, 3),
                                                              round(x1 - OX, 3), round(OY - y0, 3)]))
        if has_model(fp) or not list(fp.Models()) or name in IN_FUSION:
            continue
        if name not in HEIGHT:
            missing.append(f"{ref} ({name})")
            continue
        envelopes.append(dict(ref=ref, kind="body", name=f"{ref} {name[:24]}", footprint=name, side=side,
                              height=HEIGHT[name], rect=plane(body)))
    out = os.path.join(BUILD, "fit_envelopes.json")
    with open(out, "w") as f:
        json.dump(dict(step=step, origin_mm=[OX, OY], envelopes=envelopes, no_height=missing), f, indent=1)
    print(f"wrote {step} and {out}: {len(envelopes)} envelopes" + (f"; no height for {missing}" if missing else ""))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
