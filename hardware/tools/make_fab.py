#!/usr/bin/env python3
"""JLCPCB fabrication package for the routed board, written to build/fab/:

  deck8-RevA-gerbers.zip   Gerbers (11 layers) + Excellon drill (PTH, NPTH) + drill maps, one origin
  deck8-RevA-bom-jlc.csv   JLC assembly BOM (Comment, Designator, Footprint, LCSC Part #)
  deck8-RevA-cpl-jlc.csv   JLC pick-and-place (Designator, Val, Package, Mid X, Mid Y, Rotation, Layer)
  deck8-RevA-bom-full.csv  every fitted part, with who fits it (JLC, by hand) and the not-fitted ones
  deck8-RevA-assembly-*.pdf  fab-layer drawings of both sides, for the hand-fitted parts
  README.md                order settings, assembly notes and the check results

Run with KiCad's Python after route_pcb.py:
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 make_fab.py

It refuses to run unless KiCad's DRC (with schematic parity) reports nothing at all, and finishes by handing the
outputs to gerber_check.py, which reads the Gerbers, drill files, BOM and CPL back and compares them with facts
taken from the board here.
"""
import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys
import zipfile

import pcbnew

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PCB = os.path.join(HW, "main", "deck8.kicad_pcb")
BUILD = os.path.join(HW, "build")
FAB = os.path.join(BUILD, "fab")
CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
NAME = "deck8-RevA"
TM = pcbnew.ToMM
LAYERS = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu", "F.Paste", "B.Paste", "F.Silkscreen", "B.Silkscreen",
          "F.Mask", "B.Mask", "Edge.Cuts"]

# JLC's reels hold some packages turned against KiCad's zero orientation. Pattern -> degrees added after the
# bottom-side mirror, from the correction table kicad-jlcpcb-tools fetches (matthewlai/JLCKicadTools
# cpl_rotations_db.csv), first match wins.
ROTATIONS = [(r"^SOT-23", -90), (r"^(.*?_|V)?QFN-(16|20|24|28|40)(-|_|$)", 270),
             (r"^USB_C_Receptacle_HRO_TYPE-C-31-M-12", 180), (r"^JST_PH_S", 180)]
# Parts with no entry in that table whose JLC footprint orientation can't be known in advance: check them in
# JLC's placement preview before confirming the order.
PREVIEW = {"SW_MX_Hotswap": "socket footprint on JLC's side; mounted on the bottom under a top-side switch",
           "LED_SK6812MINI-E": "reverse-mount LED: body sits in the cut-out, pin 1 (VSS) marked",
           "Raytac_MDBT50Q": "module: JLC's origin may be the body centre rather than the pad centre",
           "JST_SH_SM03B": "no rotation entry for this connector",
           "SW_SPDT_PCM12": "no rotation entry; lever must face the board edge",
           "SW_Push_1P1T-MP_NO_Horizontal_Alps_SKRTLAE010": "no rotation entry; actuator must face the board edge",
           "SW_SPST_PTS810": "no rotation entry"}


def cli(*args):
    r = subprocess.run([CLI, *args], capture_output=True, text=True)
    if r.returncode not in (0, 5):
        print(r.stdout[-2000:], r.stderr[-2000:])
        raise SystemExit(f"kicad-cli {' '.join(args[:3])} failed ({r.returncode})")
    return r


def drc_gate():
    out = os.path.join(FAB, "drc.json")
    cli("pcb", "drc", "--schematic-parity", "--severity-all", "--refill-zones", "--format", "json", "-o", out, PCB)
    d = json.load(open(out))
    n = sum(len(d.get(k, [])) for k in ("violations", "unconnected_items", "schematic_parity"))
    if n:
        raise SystemExit(f"DRC reports {n} items: fix the board (check_pcb.py) before making fab files")
    os.remove(out)
    return d.get("kicad_version", "")


def export_gerbers():
    gdir = os.path.join(FAB, "gerbers")
    shutil.rmtree(gdir, ignore_errors=True)
    os.makedirs(gdir)
    # JLC's KiCad settings: Protel extensions, no X2 or netlist attributes, mask subtracted from silk, and the
    # drill/place origin for Gerbers, drill and CPL alike
    cli("pcb", "export", "gerbers", "-o", gdir, "--layers", ",".join(LAYERS), "--subtract-soldermask",
        "--use-drill-file-origin", "--no-x2", "--no-netlist", PCB)
    cli("pcb", "export", "drill", "-o", gdir + os.sep, "--format", "excellon", "--drill-origin", "plot",
        "--excellon-zeros-format", "decimal", "--excellon-oval-format", "alternate", "-u", "mm",
        "--excellon-separate-th", "--generate-map", "--map-format", "gerberx2", PCB)
    zpath = os.path.join(FAB, f"{NAME}-gerbers.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(gdir)):
            z.write(os.path.join(gdir, f), f)
    return gdir, zpath


def assembly_pdfs():
    for side, layers, mirror in (("bottom", "B.Fab,B.Silkscreen,Edge.Cuts", True),
                                 ("top", "F.Fab,F.Silkscreen,Edge.Cuts", False)):
        args = ["pcb", "export", "pdf", "--mode-single", "--layers", layers, "--include-border-title",
                "--black-and-white", "-o", os.path.join(FAB, f"{NAME}-assembly-{side}.pdf")]
        if mirror:
            args.append("--mirror")
        cli(*args, PCB)


def nat(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def field(fp, name):
    return fp.GetFieldText(name) if fp.HasField(name) else ""


class Parts:
    def __init__(self, board):
        self.b = board
        ds = board.GetDesignSettings()
        self.origin = ds.GetAuxOrigin()
        self.fps = sorted(board.GetFootprints(), key=lambda f: nat(f.GetReference()))

    def xy(self, p):
        """Board point -> fab mm: from the drill/place origin, +Y up (Gerber and JLC convention)."""
        return (TM(p.x - self.origin.x), TM(self.origin.y - p.y))

    def fitter(self, fp):
        if fp.IsExcludedFromBOM() or fp.GetAttributes() & pcbnew.FP_EXCLUDE_FROM_BOM:
            return None
        if fp.IsDNP():
            return "not fitted (DNP)"
        if fp.GetAttributes() & pcbnew.FP_THROUGH_HOLE:
            return "hand solder (through-hole)"
        if not field(fp, "LCSC"):
            return "hand solder (not stocked at LCSC)"
        return "JLC SMT"

    def assembly_side(self, fp):
        """Side the part is soldered on: its own side, except a hot-swap socket, which sits on the bottom under a
        footprint placed on top (all its SMD pads are on B.Cu)."""
        if fp.IsFlipped():
            return "bottom"
        layers = {L for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD
                  for L in (pcbnew.F_Cu, pcbnew.B_Cu) if p.IsOnLayer(L)}
        return "bottom" if layers == {pcbnew.B_Cu} else "top"

    def centre(self, fp, side):
        """Centre of the soldered pads on the assembly side (JLC footprints are centred on their pads)."""
        L = pcbnew.B_Cu if side == "bottom" else pcbnew.F_Cu
        pads = [p for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and p.IsOnLayer(L)]
        if not pads:
            return self.xy(fp.GetPosition())
        bb = pads[0].GetBoundingBox()
        for p in pads[1:]:
            bb.Merge(p.GetBoundingBox())
        return self.xy(bb.GetCenter())

    def rotation(self, fp, side):
        name = str(fp.GetFPID().GetUniStringLibItemName())
        rot = fp.GetOrientationDegrees()
        if side == "bottom":
            rot = 180 - rot          # JLC reads bottom angles mirrored about the Y axis
        for pattern, add in ROTATIONS:
            if re.match(pattern, name):
                rot += add
                break
        return int(round(rot)) % 360

    def rows(self):
        out = []
        for fp in self.fps:
            fit = self.fitter(fp)
            if fit is None:
                continue
            side = self.assembly_side(fp)
            out.append(dict(ref=fp.GetReference(), value=fp.GetValue(), mpn=field(fp, "MPN"), lcsc=field(fp, "LCSC"),
                            fp=str(fp.GetFPID().GetUniStringLibItemName()), fit=fit, side=side,
                            at=self.centre(fp, side), rot=self.rotation(fp, side), fpobj=fp))
        return out


def comment(r):
    """Passives: value and part number. Everything else: the part number (their values are function labels such as
    POWER or LED STRIP, which mean nothing to an assembler)."""
    if r["ref"][0] in "RC" and r["ref"][1:].isdigit():
        return f"{r['value']} {r['mpn']}".strip()
    return r["mpn"] or r["value"]


def write_csvs(rows):
    jlc = [r for r in rows if r["fit"] == "JLC SMT"]
    groups = {}
    for r in jlc:
        groups.setdefault((r["lcsc"], r["fp"]), []).append(r)
    bom = os.path.join(FAB, f"{NAME}-bom-jlc.csv")
    with open(bom, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for (lcsc, fpname), rs in sorted(groups.items(), key=lambda kv: nat(kv[1][0]["ref"])):
            # one line per part number; the comment is the first part's value + MPN (keys share one MPN)
            w.writerow([comment(rs[0]), ",".join(r["ref"] for r in rs), fpname, lcsc])
    cpl = os.path.join(FAB, f"{NAME}-cpl-jlc.csv")
    with open(cpl, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Val", "Package", "Mid X", "Mid Y", "Rotation", "Layer"])
        for r in jlc:
            w.writerow([r["ref"], r["value"], r["fp"], f"{r['at'][0]:.4f}", f"{r['at'][1]:.4f}", r["rot"], r["side"]])
    full = os.path.join(FAB, f"{NAME}-bom-full.csv")
    fgroups = {}
    for r in rows:
        key = (r["lcsc"] or r["mpn"] or r["value"], r["fp"], r["fit"])
        fgroups.setdefault(key, []).append(r)
    with open(full, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Item", "Qty", "References", "Value", "Manufacturer part", "LCSC", "Footprint", "Side",
                    "Fitted by"])
        for i, (_, rs) in enumerate(sorted(fgroups.items(), key=lambda kv: nat(kv[1][0]["ref"])), 1):
            r = rs[0]
            values = list(dict.fromkeys(x["value"] for x in rs))
            value = "MX hot-swap socket" if r["ref"].startswith("K") else " / ".join(values)
            w.writerow([i, len(rs), " ".join(x["ref"] for x in rs), value, r["mpn"], r["lcsc"], r["fp"], r["side"],
                        r["fit"]])
    return bom, cpl, full, jlc, groups


def board_facts(board, parts, rows):
    """What the Gerbers and drill files must show, measured on the board itself."""
    origin = parts.origin
    outline = pcbnew.SHAPE_POLY_SET()
    board.GetBoardPolygonOutlines(outline, False)
    bb = outline.BBox()
    vias = [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
    holes = {"PTH": {}, "NPTH": {}}
    pads = {"F.Cu": 0, "In1.Cu": 0, "In2.Cu": 0, "B.Cu": 0}
    paste = {"F.Paste": 0, "B.Paste": 0}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            att = p.GetAttribute()
            if att in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                ds = p.GetDrillSize()
                kind = "PTH" if att == pcbnew.PAD_ATTRIB_PTH else "NPTH"
                d = round(TM(min(ds.x, ds.y)), 3)
                holes[kind][d] = holes[kind].get(d, 0) + 1
            for name, L in (("F.Cu", pcbnew.F_Cu), ("In1.Cu", pcbnew.In1_Cu), ("In2.Cu", pcbnew.In2_Cu),
                            ("B.Cu", pcbnew.B_Cu)):
                if p.IsOnLayer(L) and att != pcbnew.PAD_ATTRIB_NPTH and p.FlashLayer(L):
                    pads[name] += 1
            for name, L in (("F.Paste", pcbnew.F_Paste), ("B.Paste", pcbnew.B_Paste)):
                if p.IsOnLayer(L):
                    paste[name] += 1
    for v in vias:
        d = round(TM(v.GetDrillValue()), 3)
        holes["PTH"][d] = holes["PTH"].get(d, 0) + 1
    return dict(
        outline=[TM(bb.GetLeft() - origin.x), TM(origin.y - bb.GetBottom()),
                 TM(bb.GetRight() - origin.x), TM(origin.y - bb.GetTop())],
        vias=[parts.xy(v.GetPosition()) for v in vias], via_drill=round(TM(vias[0].GetDrillValue()), 3),
        holes={k: {str(d): n for d, n in v.items()} for k, v in holes.items()},
        pads=pads, paste=paste,
        parts=[dict(ref=r["ref"], fit=r["fit"], side=r["side"], lcsc=r["lcsc"], at=r["at"]) for r in rows])


def readme(version, zpath, bom, cpl, full, jlc, groups, rows, facts, smallest):
    hand = [r for r in rows if r["fit"].startswith("hand")]
    dnp = [r for r in rows if r["fit"].startswith("not")]
    w = facts["outline"][2] - facts["outline"][0]
    h = facts["outline"][3] - facts["outline"][1]
    preview = sorted({r["ref"] for r in jlc for k in PREVIEW if r["fp"].startswith(k)}, key=nat)
    hand_lines = "\n".join(f"| {r['ref']} | {r['mpn'] or r['value']} | {r['side']} | {r['fit'].split('(')[1][:-1]} |"
                           for r in hand)
    return f"""# Deck-8 Rev A: JLCPCB fabrication package

Made by `tools/make_fab.py` from `main/deck8.kicad_pcb` (KiCad {version}) after DRC with schematic parity reported
nothing. `tools/gerber_check.py` then read every output back and compared it with the board (results below).

| File | Upload to |
|---|---|
| `{os.path.basename(zpath)}` | PCB order: Gerbers, Excellon drill (PTH + NPTH) and drill maps |
| `{os.path.basename(bom)}` | PCB Assembly: BOM ({len(groups)} lines, {len(jlc)} parts) |
| `{os.path.basename(cpl)}` | PCB Assembly: CPL / pick-and-place ({len(jlc)} placements) |
| `{os.path.basename(full)}` | Your own reference: every fitted part and who fits it |
| `{NAME}-assembly-bottom.pdf`, `-top.pdf` | Your own reference: where the hand-fitted parts go |

## PCB order settings

| Setting | Value |
|---|---|
| Layers | 4 (F.Cu signal, In1 GND, In2 +3V3/VLED, B.Cu parts) |
| Size | {w:.1f} × {h:.1f} mm |
| Thickness | 1.6 mm, JLC's default 4-layer stack-up (no impedance control needed) |
| Material | FR-4 |
| Outer / inner copper | 1 oz / 0.5 oz |
| Min track / space | 0.15 / 0.15 mm (signals are 0.2 mm) |
| Min hole | {smallest:.2f} mm: the charger's thermal vias. Routing vias are 0.3 / 0.6 mm |
| Via covering | Tented (the mask has no openings on vias) |
| Surface finish | ENIG: flat pads for the 0.5 mm-pitch QFN and the module's LGA pads |
| Mask / silkscreen | Any colour; the board is hidden inside the case |
| Order number | "Specify a location": the spot reads JLCJLCJLCJLC on the bottom, beside "Deck-8 Rev A" |
| Remove order number, castellations, edge plating, gold fingers | No |

## Assembly order settings

- PCBA type: Economic or Standard; JLC says at upload if a part needs Standard. The module, the sockets and most
  ICs are Extended parts (a per-part loading fee).
- Assembly side: **bottom only**. Every SMD part is on the bottom; the top side has only through-hole parts.
- Tooling holes: added by JLC. The board has three fiducials on the bottom (FID1–FID3).
- Confirm part placement: **yes**. In JLC's placement preview, check these parts against their pads before confirming:
  {", ".join(preview)}. Their packages have no entry in the rotation table, or JLC's footprint may put the
  origin somewhere else. Rotate or nudge any that are off in the preview; JLC then updates the CPL on its side.
- Bottom-side rotations in the CPL already include the mirror JLC expects, (180° − KiCad angle), and the package
  corrections (SOT-23 −90°, QFN +270°, HRO USB-C +180°, JST-PH +180°).

## Fitted by hand after delivery

| Ref | Part | Side | Why |
|---|---|---|---|
{hand_lines}

Not fitted: {", ".join(r["ref"] for r in dnp)} (DNP by design).

Not on this BOM (enclosure and modules): 8 MX switches, keycaps, the two printed knobs, the LiPo cell (check J2
polarity first), the LED ring strip and the M2 screws and inserts. The 0.96" OLED module is the J5 line above: its own
header is soldered through J5 once the board is screwed into the top shell (`mechanical/README.md`).
"""


def main():
    os.makedirs(FAB, exist_ok=True)
    version = drc_gate()
    board = pcbnew.LoadBoard(PCB)
    parts = Parts(board)
    rows = parts.rows()
    gdir, zpath = export_gerbers()
    assembly_pdfs()
    bom, cpl, full, jlc, groups = write_csvs(rows)
    facts = board_facts(board, parts, rows)
    smallest = min(float(d) for d in facts["holes"]["PTH"])
    with open(os.path.join(FAB, "facts.json"), "w") as f:
        json.dump(facts, f, indent=1)
    with open(os.path.join(FAB, "README.md"), "w") as f:
        f.write(readme(version, zpath, bom, cpl, full, jlc, groups, rows, facts, smallest))
    print(f"wrote {zpath}, {len(groups)} BOM lines / {len(jlc)} placements, "
          f"{sum(1 for r in rows if r['fit'].startswith('hand'))} hand-fitted parts")
    # read everything back with an independent parser (system Python: it renders with PIL)
    r = subprocess.run(["/usr/bin/python3", os.path.join(HW, "tools", "gerber_check.py"), FAB])
    report = json.load(open(os.path.join(FAB, "check_report.json")))
    with open(os.path.join(FAB, "README.md"), "a") as f:
        f.write(f"\n## Read-back checks ({sum(c['ok'] for c in report)}/{len(report)} passed)\n\n"
                "`gerber_check.py` parses the Gerbers, drill files, BOM and CPL without KiCad and compares them with "
                "the board. Its renders of the Gerbers are `check_top.png`, `check_bottom.png` (with the CPL "
                "placements marked), `check_in1.png` and `check_in2.png`.\n\n| Check | Result |\n|---|---|\n")
        for c in report:
            f.write(f"| {'✅' if c['ok'] else '❌'} {c['check']} | {c['detail']} |\n")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
