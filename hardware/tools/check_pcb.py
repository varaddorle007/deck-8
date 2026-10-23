#!/usr/bin/env python3
"""DRC (with schematic parity) on main/deck8.kicad_pcb, then 3D renders and a STEP export.

The board is routed, so every DRC item counts: errors, warnings, unrouted connections and parity issues.
"""
import json
import os
import subprocess
import sys

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PCB = os.path.join(HW, "main", "deck8.kicad_pcb")
BUILD = os.path.join(HW, "build")
CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"


def cli(*args):
    r = subprocess.run([CLI, *args], capture_output=True, text=True)
    if r.returncode not in (0, 5):
        print(r.stdout[-2000:], r.stderr[-2000:])
        raise SystemExit(f"kicad-cli {args[0]} {args[1]} failed ({r.returncode})")
    return r


def main(render=True):
    os.makedirs(BUILD, exist_ok=True)
    out = os.path.join(BUILD, "drc.json")
    cli("pcb", "drc", "--schematic-parity", "--severity-all", "--refill-zones", "--format", "json", "-o", out, PCB)
    d = json.load(open(out))
    groups = {}
    for key in ("violations", "schematic_parity", "unconnected_items"):
        for v in d.get(key, []):
            t = "unconnected_items" if key == "unconnected_items" else v.get("type")
            groups.setdefault((key, v.get("severity"), t), []).append(v)
    bad = 0
    for (key, sev, t), vs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f"{key:18s} {sev:8s} {t:32s} {len(vs)}")
        bad += len(vs)
        for v in vs[:12]:
            items = " | ".join(i.get("description", "") for i in v.get("items", []))
            print(f"      {v.get('description', '')}: {items}")
    print(f"DRC items (errors, warnings, unrouted, parity): {bad}")
    if render:
        for name, args in (("top", ["--side", "top"]), ("bottom", ["--side", "bottom"]),
                           ("iso_top", ["--side", "top", "--rotate", "-45,0,35", "--perspective", "--zoom", "0.9"]),
                           ("iso_bottom", ["--side", "bottom", "--rotate", "-45,0,-35", "--perspective", "--zoom", "0.9"])):
            cli("pcb", "render", *args, "--width", "1800", "--height", "1300", "--quality", "basic",
                "--background", "opaque", "-o", os.path.join(BUILD, f"pcb_{name}.png"), PCB)
        # STEP in plane coordinates plus envelopes for model-less parts, for the Fusion fit check
        kpy = "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3"
        subprocess.run([kpy, os.path.join(HW, "tools", "export_fit.py")], check=True, capture_output=True)
        print("renders, STEP and fit envelopes written to", BUILD)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(render="--no-render" not in sys.argv))
