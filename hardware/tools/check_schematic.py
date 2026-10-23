#!/usr/bin/env python3
"""Run KiCad ERC and compare KiCad's exported netlist with intended_netlist.json, pin by pin."""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(HW, "main")
CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
ROOT = os.path.join(MAIN, "deck8.kicad_sch")
BUILD = os.path.join(HW, "build")


def run(args):
    r = subprocess.run([CLI] + args, capture_output=True, text=True)
    if r.returncode not in (0, 5):   # erc exits 5 when it finds violations
        print(r.stdout, r.stderr)
        raise SystemExit(f"kicad-cli {' '.join(args[:3])} failed ({r.returncode})")
    return r


def main():
    os.makedirs(BUILD, exist_ok=True)
    erc_path = os.path.join(BUILD, "erc.json")
    run(["sch", "erc", "--format", "json", "--severity-all", "-o", erc_path, ROOT])
    erc = json.load(open(erc_path))
    viol = []
    for sh in erc.get("sheets", []):
        for v in sh.get("violations", []):
            items = "; ".join(i.get("description", "") for i in v.get("items", []))
            viol.append((v.get("severity"), v.get("type"), sh.get("path"), v.get("description"), items))
    by_sev = {}
    for v in viol:
        by_sev.setdefault(v[0], []).append(v)
    print("ERC:", {k: len(v) for k, v in by_sev.items()} or "clean")
    for sev in ("error", "warning"):
        for v in by_sev.get(sev, [])[:60]:
            print(f"  [{sev}] {v[1]} {v[2]}: {v[3]} | {v[4]}")

    net_path = os.path.join(BUILD, "deck8.net.xml")
    run(["sch", "export", "netlist", "--format", "kicadxml", "-o", net_path, ROOT])
    tree = ET.parse(net_path).getroot()
    actual = {}
    nets = {}
    for net in tree.iter("net"):
        name = net.get("name")
        base = name.rsplit("/", 1)[-1] if name.startswith("/") else name
        nodes = [(n.get("ref"), n.get("pin")) for n in net.iter("node")]
        if name.startswith("unconnected-") or len(nodes) < 2:
            base = None
        for ref, pin in nodes:
            actual[(ref, pin)] = base
        if base:
            nets.setdefault(base, set()).update(nodes)
    comps = {c.get("ref"): c for c in tree.iter("comp")}
    intent = json.load(open(os.path.join(MAIN, "intended_netlist.json")))
    problems = []
    for ref, d in intent.items():
        if ref.startswith("#"):
            continue
        if ref not in comps:
            problems.append(f"{ref}: missing from KiCad netlist")
            continue
        fp = comps[ref].findtext("footprint") or ""
        if fp != d["footprint"]:
            problems.append(f"{ref}: footprint {fp!r} != {d['footprint']!r}")
        for pin, net in d["pins"].items():
            got = actual.get((ref, pin), None)
            if got != net:
                problems.append(f"{ref}.{pin}: expected {net}, KiCad has {got}")
    want = {}
    for ref, d in intent.items():
        if ref.startswith("#"):
            continue
        for pin, net in d["pins"].items():
            if net:
                want.setdefault(net, set()).add((ref, pin))
    for net, nodes in nets.items():
        extra = {n for n in nodes if not n[0].startswith("#")} - want.get(net, set())
        if extra:
            problems.append(f"net {net}: unexpected pins {sorted(extra)}")
    print(f"netlist: {len(comps)} components, {len(nets)} nets, {len(problems)} mismatches")
    for p in problems[:80]:
        print("  ", p)
    return 1 if problems or by_sev.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
