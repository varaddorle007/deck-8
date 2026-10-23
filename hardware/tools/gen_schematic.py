#!/usr/bin/env python3
"""Generate the Deck-8 Rev A hierarchical schematic (KiCad 9/10 format) from the netlist below.

Every pin gets a short stub ending in a net label, a global label (nets that cross sheets)
or a power symbol, so connectivity comes only from this table. Mechanical positions are
read from the Fusion model script's layout constants and stored on each part as the
`Deck8_Place` field and in placement.json.

Usage: python3 gen_schematic.py   (writes ../main/)
"""
import ast
import json
import math
import os
import shutil
import uuid

import kilib
from sexpr import Str, dump

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HW, "main")
PROJECT = "deck8"
FUSION = os.path.join(os.path.dirname(HW), "mechanical", "fusion", "Deck8Model", "Deck8Model.py")
TEMPLATE_PRO = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/template/kicad.kicad_pro"
NS = uuid.UUID("6f1d2a4e-8d3b-4c7a-9b51-0de8c8a1d0a8")
DATE = "2026-10-23"
GRID = 2.54
STUB = 2.54


def uid(*parts):
    return str(uuid.uuid5(NS, "/".join(str(p) for p in parts)))


def snap(v):
    return round(v / GRID) * GRID


# ----------------------------------------------------------------------------- layout source
def fusion_layout():
    want = {"KEY_X", "KEY_Y", "ROW_Y", "KNOB_X", "SHELL_BOSSES", "TRAY_BOSSES", "L_BUTTONS",
            "SLIDE_Y", "SYS_Y", "PCB_OUTLINE", "USB_AT", "BTN_V", "PCB_TOP_V", "PCB_T", "OLED_HEADER_Y"}
    out = {}
    with open(FUSION) as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in want:
                out[node.targets[0].id] = ast.literal_eval(node.value)
    missing = want - set(out)
    if missing:
        raise SystemExit(f"layout constants missing from {FUSION}: {sorted(missing)}")
    return out


LAY = fusion_layout()

# ----------------------------------------------------------------------------- footprints
FP = {
    "R": "Resistor_SMD:R_0603_1608Metric",
    "C": "Capacitor_SMD:C_0603_1608Metric",
    "C1206": "Capacitor_SMD:C_1206_3216Metric",
    "TP": "TestPoint:TestPoint_Pad_D1.0mm",
}
POWER = {"GND": "power:GND", "+3V3": "power:+3V3", "VBUS": "power:VBUS", "VBAT": "power:+BATT",
         "VSYS": "power:VCC", "VLED": "power:VCC"}


class Part:
    def __init__(self, ref, lib_id, value, fp="", nets=None, by_name=None, mpn="", note="",
                 place=None, dnp=False, desc=None, in_bom=True, lcsc=""):
        self.ref, self.lib_id, self.value, self.fp = ref, lib_id, value, fp
        self.lcsc = lcsc
        self.nets = dict(nets or {})
        self.by_name = dict(by_name or {})
        self.mpn, self.note, self.place, self.dnp, self.desc = mpn, note, place, dnp, desc
        self.in_bom = in_bom
        self.sym = kilib.load(lib_id)
        self.pins = kilib.pins(self.sym)
        self.sheet = None

    def pin_net(self):
        """{pin number: net or None}; every pin must be assigned unless it is a no_connect type."""
        out, missing = {}, []
        for num, name, typ, *_ in self.pins:
            if num in self.nets:
                out[num] = self.nets[num]
            elif name in self.by_name:
                out[num] = self.by_name[name]
            elif typ == "no_connect":
                continue
            else:
                missing.append(f"{num}({name})")
        if missing:
            raise SystemExit(f"{self.ref}: unassigned pins {missing}")
        return out


# Passives (MPN, LCSC part), each checked on lcsc.com. Resistors: UNI-ROYAL 0603 1 % 100 mW thick film.
# Capacitors: Samsung / Yageo 0603 unless noted; voltage ratings at or above the schematic value.
PASSIVES = {
    ("R", "5.1k"): ("0603WAF5101T5E", "C23186"), ("R", "10k"): ("0603WAF1002T5E", "C25804"),
    ("R", "1.8k"): ("0603WAF1801T5E", "C4177"), ("R", "1.5k"): ("0603WAF1501T5E", "C22843"),
    ("R", "100k"): ("0603WAF1003T5E", "C25803"), ("R", "1M"): ("0603WAF1004T5E", "C22935"),
    ("R", "0R"): ("0603WAF0000T5E", "C21189"), ("R", "33"): ("0603WAF330JT5E", "C23140"),
    ("R", "330"): ("0603WAF3300T5E", "C23138"), ("R", "4.7k"): ("0603WAF4701T5E", "C23162"),
    ("C", "100n"): ("CC0603KRX7R9BB104 (50 V X7R)", "C14663"),
    ("C", "1u 25V"): ("CL10A105KB8NNNC (50 V X5R)", "C15849"), ("C", "1u 10V"): ("CL10A105KB8NNNC (50 V X5R)", "C15849"),
    ("C", "2.2u 10V"): ("CL10A225KO8NNNC (16 V X5R)", "C23630"), ("C", "4.7u 10V"): ("CL10A475KO8NNNC (16 V X5R)", "C19666"),
    ("C", "10u 10V"): ("CL10A106KP8NNNC (10 V X5R)", "C19702"), ("C", "1n"): ("CL10B102KB8NNNC (50 V X7R)", "C1588"),
    ("C", "12p"): ("CL10C120JB8NNNC (50 V C0G)", "C38523"),
    ("C", "100u 6.3V"): ("CL31A107MQHNNNE (1206, 6.3 V X5R)", "C15008"),
}


def R(ref, value, a, b, **kw):
    mpn, lcsc = PASSIVES.get(("R", value), ("", ""))
    kw.setdefault("mpn", mpn and "UNI-ROYAL " + mpn)
    kw.setdefault("lcsc", lcsc)
    return Part(ref, "Device:R", value, FP["R"], {"1": a, "2": b}, **kw)


def C(ref, value, a, b="GND", fp=None, **kw):
    mpn, lcsc = PASSIVES.get(("C", value), ("", ""))
    kw.setdefault("mpn", mpn)
    kw.setdefault("lcsc", lcsc)
    return Part(ref, "Device:C", value, fp or FP["C"], {"1": a, "2": b}, **kw)


def flag(ref, net):
    return Part(ref, "power:PWR_FLAG", "PWR_FLAG", "", {"1": net})


def place(x, y, side, note="", rot=0):
    return {"x": round(x, 3), "y": round(y, 3), "side": side, "rot": rot, "note": note}


# ----------------------------------------------------------------------------- netlist
L = LAY
key_xy = [(x, y) for y in L["KEY_Y"] for x in L["KEY_X"]]      # keys 1-4 back row, 5-8 front row
pcb_hw, pcb_front, pcb_back = L["PCB_OUTLINE"][0], L["PCB_OUTLINE"][1], L["PCB_OUTLINE"][2]

# GPIO plan: each signal leaves the module on the edge that faces where it goes (keys south and east, right
# knob and System east; left knob, left buttons, I2C and charger status west). Found by a minimum-total-length
# matching of free pads to destinations on the Rev A placement, which also keeps the escapes from crossing.
# West-going signals use the inner and centre pads, which drop a via straight to the free top layer; the outer
# west pads could only leave into the gap beside the USB ESD part. The outer south pads P0.04/P0.06/P0.08/P1.09
# stay free because the crystal lines run under them. I2C and LED data are on P0 (full-speed) pins, BAT_SENSE
# on AIN0.
MCU_PINS = {
    "P0.14": "KEY1", "P1.08": "KEY2", "P0.28": "KEY3", "P0.31": "KEY4",
    "P0.12": "KEY5", "P0.07": "KEY6", "P0.27": "KEY7", "P0.30": "KEY8",
    "P1.01": "BTN_L1", "P0.21": "BTN_L2", "P0.29": "BTN_SYS",
    "P1.02": "ENCA_A", "P0.25": "ENCA_B", "P1.00": "ENCA_SW",
    "P1.15": "ENCB_A", "P1.11": "ENCB_B", "P1.13": "ENCB_SW",
    "P0.16": "I2C_SDA", "P0.19": "I2C_SCL",
    "P0.11": "LED_RING_3V3", "P0.05": "LED_KEYS_3V3",
    "P0.26": "LED_EN", "P0.02": "BAT_SENSE", "P0.23": "CHG_N", "P1.03": "PGOOD_N",
    "P0.18": "NRESET", "P0.00": "XL1", "P0.01": "XL2",
    "VDD": "+3V3", "VDDH": "+3V3", "VBUS": "VBUS", "GND": "GND", "D+": "USB_DP", "D-": "USB_DM",
    "SWDIO": "SWDIO", "SWDCLK": "SWDCLK", "DCCH": None,
}
for p in ("P0.03", "P0.04", "P0.06", "P0.08", "P0.09", "P0.10", "P0.13", "P0.15", "P0.17", "P0.20",
          "P0.22", "P0.24", "P1.04", "P1.05", "P1.06", "P1.07", "P1.09", "P1.10", "P1.12", "P1.14"):
    MCU_PINS[p] = None

SHEETS = []


def sheet(name, file, title, comment, groups):
    SHEETS.append({"name": name, "file": file, "title": title, "comment": comment, "groups": groups})


sheet("Power", "power.kicad_sch", "Power: USB-C, charger, regulator, LED switch",
      "VSYS ~4.4 V on USB, else battery. Power switch = 3.3 V regulator enable.", [
    ("USB-C input and protection", [
        Part("J1", "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C", "Deck8:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
             by_name={"VBUS": "VBUS_IN", "GND": "GND", "SHIELD": "GND", "CC1": "CC1", "CC2": "CC2",
                      "D+": "USB_DP", "D-": "USB_DM", "SBU1": None, "SBU2": None},
             mpn="HRO TYPE-C-31-M-12", lcsc="C165948", place=place(0, L["USB_AT"][0], "B", "opening faces the back edge")),
        R("R1", "5.1k", "CC1", "GND", note="CC1 own pull-down"),
        R("R2", "5.1k", "CC2", "GND", note="CC2 own pull-down"),
        Part("F1", "Device:Polyfuse", "500mA hold", "Fuse:Fuse_1206_3216Metric", {"1": "VBUS_IN", "2": "VBUS"},
             mpn="Littelfuse 1206L050YR (6 V)", lcsc="C163512"),
        Part("U1", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6",
             {"1": "USB_DP", "6": "USB_DP", "3": "USB_DM", "4": "USB_DM", "5": "VBUS", "2": "GND"}, mpn="ST USBLC6-2SC6", lcsc="C7519"),
        flag("#FLG01", "VBUS"), flag("#FLG02", "GND"),
    ]),
    ("Charger (BQ24074, USB500 mode, 494 mA charge)", [
        Part("U2", "Battery_Management:BQ24074RGT", "BQ24074RGT", "Package_DFN_QFN:VQFN-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm_ThermalVias",
             by_name={"IN": "VBUS", "OUT": "VSYS", "BAT": "VBAT", "VSS": "GND", "TS": "TS", "~{CE}": "GND",
                      "EN2": "GND", "EN1": "VBUS", "ILIM": "ILIM", "ISET": "ISET", "ITERM": "ITERM",
                      "TMR": "TMR", "~{PGOOD}": "PGOOD_N", "~{CHG}": "CHG_N"}, mpn="TI BQ24074RGTT", lcsc="C2861252"),       # RGTR (C54313) had 1 left at JLC on 23 Oct; same die, small reel
        C("C1", "1u 25V", "VBUS"), C("C2", "10u 10V", "VSYS"), C("C3", "4.7u 10V", "VBAT"),
        R("R3", "10k", "TS", "GND", note="stands in for the battery NTC"),
        R("R4", "1.8k", "ISET", "GND", note="K_ISET 890 / 1.8k = 494 mA"),
        R("R5", "1.5k", "ILIM", "GND", note="only used in ILIM mode (~1 A)"),
        R("R6", "DNP", "ITERM", "GND", dnp=True, note="open = default 10% termination (datasheet); 0-15k sets it"),
        R("R7", "DNP", "TMR", "GND", dnp=True, note="open = default safety timers (datasheet); never short to GND"),
        R("R8", "100k", "PGOOD_N", "+3V3"), R("R9", "100k", "CHG_N", "+3V3"),
    ]),
    ("Battery and sense divider", [
        Part("J2", "Connector_Generic:Conn_01x02", "LiPo 1000mAh", "Connector_JST:JST_PH_S2B-PH-SM4-TB_1x02-1MP_P2.00mm_Horizontal",
             {"1": "VBAT", "2": "GND"}, mpn="JST S2B-PH-SM4-TB(LF)(SN)", lcsc="C295747", note="CHECK cell polarity before plugging in",
             place=place(24, 21, "B", "outside the battery footprint; cable entry toward the battery")),
        R("R10", "1M", "VBAT", "BAT_SENSE"), R("R11", "1M", "BAT_SENSE", "GND"), C("C4", "100n", "BAT_SENSE"),
    ]),
    ("3.3 V regulator and power switch", [
        Part("U3", "Regulator_Linear:TPS7A0533PDBV", "TPS7A0533PDBV", "Package_TO_SOT_SMD:SOT-23-5",
             by_name={"IN": "VSYS", "GND": "GND", "EN": "PWR_EN", "OUT": "3V3_LDO"}, mpn="TI TPS7A0533PDBVR", lcsc="C493453"),
        C("C5", "1u 10V", "VSYS"), C("C6", "2.2u 10V", "3V3_LDO"),
        R("R14", "0R", "3V3_LDO", "+3V3", note="lift to measure 3.3 V current"),
        Part("SW1", "Switch:SW_SPDT", "POWER", "Deck8:SW_SPDT_PCM12", {"1": "VSYS", "2": "PWR_EN", "3": "GND"},
             mpn="C&K PCM12SMTR", lcsc="C221841", place=place(-pcb_hw, L["SLIDE_Y"], "B", "lever through the left wall")),
        R("R12", "1M", "PWR_EN", "GND", note="holds EN low while the switch moves"),
        flag("#FLG03", "+3V3"),
    ]),
    ("LED power switch (all RGB off when dark)", [
        Part("U4", "Power_Management:TPS22917DBV", "TPS22917DBV", "Package_TO_SOT_SMD:SOT-23-6",
             by_name={"VIN": "VSYS", "GND": "GND", "ON": "LED_EN", "CT": "LED_CT", "QOD": "LED_QOD", "VOUT": "VLED_SW"},
             mpn="TI TPS22917DBVR", lcsc="C2681320"),
        R("R20", "0R", "LED_QOD", "VLED_SW", note="quick output discharge; a resistor here slows it"),
        C("C7", "1u 10V", "VSYS"), C("C8", "1n", "LED_CT", note="slew rate, keeps VSYS from dipping"),
        R("R13", "100k", "LED_EN", "GND", note="LEDs off while the MCU is off"),
        R("R15", "0R", "VLED_SW", "VLED", note="lift to measure LED current"),
        C("C9", "10u 10V", "VLED"), flag("#FLG04", "VLED"),
    ]),
    ("Test points", [
        Part(f"TP{i + 1}", "Connector:TestPoint", net, FP["TP"], {"1": net}, in_bom=False)
        for i, net in enumerate(["VBUS", "VSYS", "VBAT", "+3V3", "VLED", "GND"])
    ]),
])

sheet("MCU", "mcu.kicad_sch", "MCU: Raytac MDBT50Q-1MV2 (nRF52840)",
      "Normal voltage mode: VDD + VDDH on +3V3, DCCH unused. GPIO plan: root sheet.", [
    ("nRF52840 module", [
        Part("U5", "RF_Module:MDBT50Q-1MV2", "MDBT50Q-1MV2", "Deck8:Raytac_MDBT50Q", by_name=MCU_PINS,
             mpn="Raytac MDBT50Q-1MV2", lcsc="C5118826", place=place(13.0, 39.75, "B", "antenna end at the back edge; keep-out per Raytac")),
        C("C10", "10u 10V", "+3V3"), C("C11", "100n", "+3V3"), C("C12", "4.7u 10V", "VBUS", note="nRF VBUS decoupling"),
    ]),
    ("32.768 kHz crystal (LFXO)", [
        Part("Y1", "Device:Crystal", "32.768kHz 9pF", "Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm", {"1": "XL1", "2": "XL2"},
             mpn="Seiko SC-32S 32.768kHz 20ppm 9pF", lcsc="C97605",
             note="9 pF load: two 12 pF caps in series (6 pF) plus ~3 pF of pins and traces"),
        C("C13", "12p", "XL1"), C("C14", "12p", "XL2"),
    ]),
    ("Programming and reset", [
        Part("J3", "Connector:Conn_ARM_SWD_TagConnect_TC2030-NL", "SWD", "Connector:Tag-Connect_TC2030-IDC-NL_2x03_P1.27mm_Vertical",
             by_name={"VCC": "+3V3", "SWDIO": "SWDIO", "SWCLK": "SWDCLK", "~{RESET}": "NRESET", "GND": "GND", "SWO": None},
             place=place(-9.0, 25.5, "B", "under the OLED module, clear of the keys; flash the UF2 bootloader once"), in_bom=False),
        Part("SW2", "Switch:SW_Push", "RESET", "Button_Switch_SMD:SW_SPST_PTS810", {"1": "NRESET", "2": "GND"},
             mpn="C&K PTS810SJK250SMTRLFS", lcsc="C221896",       # 2.6 N; the 1.6 N SJM (C116501) was out at JLC on 23 Oct
             place=place(0, 19.8, "B", "double-press for the bootloader")),
    ]),
])

sheet("Inputs", "inputs.kicad_sch", "Inputs: 8 keys, 3 side buttons, 2 encoders",
      "Each input on its own GPIO, internal pull-up; any input wakes the MCU.", [
    ("Keys (MX hot-swap)", [
        Part(f"K{i + 1}", "Switch:SW_Push", f"KEY{i + 1}", "Deck8:SW_MX_Hotswap_Kailh_1u_NorthLED",
             # Kailh-pattern MX socket by HanElectricity: its drawing gives the same land pattern (3.0 holes 6.35 x 2.54 apart,
             # 2.55 x 2.5 pads, 1.85 tall). The Kailh-branded C2803348 was out at JLC on 23 Oct.
             {"1": f"KEY{i + 1}", "2": "GND"}, mpn="HanElectricity CPG151101S11-16 (MX hot-swap socket)", lcsc="C41430893",
             note="hot-swap socket on the back; LED window faces north",
             place=place(x, y, "F", "switch centre"))
        for i, (x, y) in enumerate(key_xy)
    ]),
    ("Side buttons", [
        Part("SW3", "Switch:SW_Push", "L1", "Button_Switch_SMD:SW_Push_1P1T-MP_NO_Horizontal_Alps_SKRTLAE010",
             {"1": "BTN_L1", "2": "GND"}, mpn="Alps SKRTLAE010", lcsc="C110293", place=place(-pcb_hw, L["L_BUTTONS"][0], "B", "actuator faces the left wall")),
        Part("SW4", "Switch:SW_Push", "L2", "Button_Switch_SMD:SW_Push_1P1T-MP_NO_Horizontal_Alps_SKRTLAE010",
             {"1": "BTN_L2", "2": "GND"}, mpn="Alps SKRTLAE010", lcsc="C110293", place=place(-pcb_hw, L["L_BUTTONS"][1], "B", "actuator faces the left wall")),
        Part("SW5", "Switch:SW_Push", "SYSTEM", "Button_Switch_SMD:SW_Push_1P1T-MP_NO_Horizontal_Alps_SKRTLAE010",
             {"1": "BTN_SYS", "2": "GND"}, mpn="Alps SKRTLAE010", lcsc="C110293", place=place(pcb_hw, L["SYS_Y"], "B", "actuator faces the right wall")),
    ]),
    ("Encoders (knob A, knob B)", [
        Part(f"ENC{i + 1}", "Device:RotaryEncoder_Switch", "PEC11R-4220F-S0024",
             "Rotary_Encoder:RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm",
             {"A": f"ENC{ab}_A", "B": f"ENC{ab}_B", "C": "GND", "S1": f"ENC{ab}_SW", "S2": "GND"},
             mpn="Bourns PEC11R-4220F-S0024", place=place(x, L["ROW_Y"], "F", f"knob {ab}"))
        for i, (ab, x) in enumerate(zip("AB", L["KNOB_X"]))
    ]),
])

# Data snakes through the keys: front row left to right, up the right side, back row right to left.
# The back-row LEDs are turned 180 deg so each DOUT faces the next DIN; firmware index i = key LED_CHAIN[i].
LED_CHAIN = (5, 6, 7, 8, 4, 3, 2, 1)
key_leds = []
for i in range(8):
    n = LED_CHAIN[i]
    din = f"KEYLED_D{n}"
    dout = f"KEYLED_D{LED_CHAIN[i + 1]}" if i < 7 else None
    x, y = key_xy[n - 1]
    key_leds.append(Part(f"D{n}", "LED:SK6812MINI-E", "SK6812MINI-E", "LED_SMD:LED_SK6812MINI-E_3.2x2.8mm_P1.5mm_ReverseMount",
                         by_name={"VDD": "VLED", "VSS": "GND", "DIN": din, "DOUT": dout}, mpn="OPSCO SK6812MINI-E",
                         lcsc="C5149201",
                         place=place(x, y + 5.08, "B", f"under key {n}, chain position {i + 1}", rot=180 if n <= 4 else 0)))
key_leds.sort(key=lambda p: int(p.ref[1:]))
sheet("Lighting", "lighting.kicad_sch", "Lighting: level shifters, 8 key LEDs, ring strip",
      "Both chains on VLED (switched VSYS). Data held low while VLED is off.", [
    # SN74LV1T125: TTL-level inputs at any supply from 1.6 to 5.5 V, so it runs from VLED (3.0-4.4 V). An AHCT part
    # needs 4.5 V. Same pinout as the generic 1G125 symbol.
    ("Level shifters (3.3 V data to VLED logic)", [
        Part("U6", "74xGxx:74LVC1G125", "SN74LV1T125", "Package_TO_SOT_SMD:SOT-23-5",
             {"1": "GND", "2": "LED_KEYS_3V3", "3": "GND", "4": "LED_KEYS_BUF", "5": "VLED"},
             mpn="TI SN74LV1T125DBVR", lcsc="C473338"),
        C("C15", "100n", "VLED"), R("R16", "33", "LED_KEYS_BUF", f"KEYLED_D{LED_CHAIN[0]}"),
        Part("U7", "74xGxx:74LVC1G125", "SN74LV1T125", "Package_TO_SOT_SMD:SOT-23-5",
             {"1": "GND", "2": "LED_RING_3V3", "3": "GND", "4": "LED_RING_BUF", "5": "VLED"},
             mpn="TI SN74LV1T125DBVR", lcsc="C473338"),
        C("C16", "100n", "VLED"), R("R17", "330", "LED_RING_BUF", "RING_DIN", note="near J4"),
    ]),
    ("Key LEDs (chain: keys 5-6-7-8-4-3-2-1)", key_leds + [C(f"C{17 + i}", "100n", "VLED") for i in range(8)]),
    ("Ring strip connector", [
        Part("J4", "Connector_Generic:Conn_01x03", "LED STRIP", "Connector_JST:JST_SH_SM03B-SRSS-TB_1x03-1MP_P1.00mm_Horizontal",
             {"1": "VLED", "2": "RING_DIN", "3": "GND"}, mpn="Joint Tech A1001WR-S-03P (JST SH compatible)", lcsc="C371509",
             # same land pattern and body as JST SM03B-SRSS-TB (C160403), which had 2 left at JLC on 23 Oct
             place=place(-18.5, -20.3, "B", "inside the light wall loop; plug enters from the left (clears the light wall)")),
        C("C25", "100u 6.3V", "VLED", fp=FP["C1206"], note="strip bulk capacitor"),
    ]),
])

sheet("Display", "display.kicad_sch", "Display: 0.96 in 128x64 OLED (I2C)",
      "Header order GND, VCC, SCL, SDA. Buy modules with that order.", [
    ("OLED module header", [
        # No socket: a socket plus the module's own header stands the glass 11 mm off the board and there is 7 mm
        # under the shell. The module's header pins go straight through J5 and are soldered from below once the
        # board is screwed into the shell, which holds the glass against its underside (mechanical/README.md).
        Part("J5", "Connector_Generic:Conn_01x04", "OLED GND-VCC-SCL-SDA", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
             {"1": "GND", "2": "+3V3", "3": "I2C_SCL", "4": "I2C_SDA"},
             mpn="0.96 in 128x64 I2C OLED module (SSD1306), soldered on its own 4-pin header",
             note="module header row toward the keys; verify against the module drawing",
             place=place(0, L["OLED_HEADER_Y"], "F", "header row; module board spans Y 21-49")),
        R("R18", "4.7k", "I2C_SCL", "+3V3"), R("R19", "4.7k", "I2C_SDA", "+3V3"),
        C("C26", "10u 10V", "+3V3"), C("C27", "100n", "+3V3"),
    ]),
])

mech = []
for i, (x, y) in enumerate(L["SHELL_BOSSES"]):
    mech.append(Part(f"H{i + 1}", "Mechanical:MountingHole", "M2 boss", "MountingHole:MountingHole_2.2mm_M2",
                     place=place(x, y, "F", "shell boss with heat-set insert"), in_bom=False))
for i, (x, y) in enumerate(L["TRAY_BOSSES"]):
    mech.append(Part(f"ST{i + 1}", "Mechanical:MountingHole_Pad", "M2x3 standoff",
                     "Mounting_Wuerth:Mounting_Wuerth_WA-SMSI-M2_H3mm_9774030243", {"1": "GND"},
                     mpn="Wurth 9774030243", place=place(x, y, "B", "tray screw")))
FIDS = [(-41.0, -21.0), (41.0, -21.0), (-40.0, 39.0)]
for i in range(3):
    mech.append(Part(f"FID{i + 1}", "Mechanical:Fiducial", "Fiducial", "Fiducial:Fiducial_1mm_Mask2mm",
                     place=place(*FIDS[i], "B", "assembly side"), in_bom=False))
sheet("Mechanical", "mechanical.kicad_sch", "Mechanical: mounting, standoffs, fiducials",
      "Positions from the Fusion model (Deck8_Place field on each part).", [("Mounting and fiducials", mech)])

# ----------------------------------------------------------------------------- geometry helpers
DIRS = {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}   # lib pin angle -> outward on screen


def outward(angle):
    return DIRS[int(round(angle)) % 360]


def label_angle(d):
    return {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[d]


def power_rot(net, d):
    supply = net != "GND"
    if supply:   # arrow up at rot 0
        return {(0, -1): 0, (0, 1): 180, (1, 0): 270, (-1, 0): 90}[d]
    return {(0, 1): 0, (0, -1): 180, (1, 0): 90, (-1, 0): 270}[d]


def text_w(s):
    return 1.05 * len(s) + 1.0


def part_extent(part, pnet, glob):
    """Extent including stubs, labels and power symbols, relative to the symbol origin."""
    x0, y0, x1, y1 = kilib.body_extent(part.sym)
    for num, name, typ, px, py, ang, ln in part.pins:
        if num not in pnet:
            continue
        net = pnet[num]
        dx, dy = outward(ang)
        ex, ey = px + dx * STUB, -py + dy * STUB
        reach = 0 if net is None else (5.5 if net in POWER else text_w(net) + (3 if net in glob else 0))
        ex += dx * reach
        ey += dy * reach
        x0, x1, y0, y1 = min(x0, ex), max(x1, ex), min(y0, ey), max(y1, ey)
    # reference and value text (placed by SheetWriter.part) must not run into the neighbour
    bx0 = kilib.body_extent(part.sym)[0]
    small = len(part.pins) == 2 and all(int(p[5]) in (90, 270) for p in part.pins)
    longest = max(text_w(part.value), 0 if part.ref.startswith("#") else text_w(part.ref))
    x1 = max(x1, (2.54 if small else bx0) + longest)
    return x0 - 1, y0 - 2.5, x1 + 1, y1 + 3.5


# ----------------------------------------------------------------------------- writers
def effects(size=1.27, justify=None, hide=False, bold=False):
    font = ["font", ["size", size, size]]
    if bold:
        font.append(["bold", "yes"])
    e = ["effects", font]
    if justify:
        e.append(["justify"] + justify.split())
    if hide:
        e.append(["hide", "yes"])
    return e


def prop(name, value, x, y, ang=0, hide=False, justify=None):
    return ["property", Str(name), Str(value), ["at", x, y, ang], effects(justify=justify, hide=hide)]


def wire(a, b, u):
    return ["wire", ["pts", ["xy", a[0], a[1]], ["xy", b[0], b[1]]], ["stroke", ["width", 0], ["type", "default"]], ["uuid", Str(u)]]


def label(net, p, d, u, glob):
    ang = label_angle(d)
    just = "left" if ang in (0, 90) else "right"
    if glob:
        return ["global_label", Str(net), ["shape", "bidirectional"], ["at", p[0], p[1], ang], ["fields_autoplaced", "yes"],
                effects(justify=just), ["uuid", Str(u)],
                ["property", Str("Intersheetrefs"), Str("${INTERSHEET_REFS}"), ["at", p[0], p[1], ang], effects(justify=just, hide=True)]]
    return ["label", Str(net), ["at", p[0], p[1], ang], effects(justify=just + " bottom"), ["uuid", Str(u)]]


class SheetWriter:
    def __init__(self, sheet, path, root_uuid, glob_nets):
        self.s, self.path, self.root_uuid, self.glob = sheet, path, root_uuid, glob_nets
        self.items, self.libs, self.pwr_n = [], {}, 0
        self.placed = []

    def lib(self, lib_id, sym=None):
        if lib_id not in self.libs:
            self.libs[lib_id] = sym if sym is not None else kilib.load(lib_id)

    def instance(self, lib_id, ref, value, at, rot, sym, fields, in_bom=True, dnp=False, ref_at=None, val_at=None,
                 hide_ref=False, val_angle=None):
        self.lib(lib_id, sym)
        u = uid(self.s["name"], ref, "sym")
        node = ["symbol", ["lib_id", Str(lib_id)], ["at", at[0], at[1], rot], ["unit", 1],
                ["exclude_from_sim", "no"], ["in_bom", "yes" if in_bom else "no"], ["on_board", "yes"],
                ["dnp", "yes" if dnp else "no"], ["uuid", Str(u)]]
        rx, ry = ref_at or (at[0], at[1] - 3)
        vx, vy = val_at or (at[0], at[1] + 3)
        node.append(prop("Reference", ref, rx, ry, hide=hide_ref, justify="left"))
        if val_angle is None:
            node.append(prop("Value", value, vx, vy, justify="left"))
        else:
            node.append(prop("Value", value, round(vx, 3), round(vy, 3), ang=val_angle))
        for k, v in fields:
            node.append(prop(k, v, at[0], at[1], hide=True))
        for num, *_ in kilib.pins(sym):
            node.append(["pin", Str(num), ["uuid", Str(uid(self.s["name"], ref, "pin", num))]])
        node.append(["instances", ["project", Str(PROJECT), ["path", Str(self.path), ["reference", Str(ref)], ["unit", 1]]]])
        self.items.append(node)

    def power(self, net, at, rot, key):
        """Power symbol whose value reads cleanly: vertical on supply arrows (as KiCad's own
        +3V3), horizontal on GND and on sideways symbols. Field angles are relative to the
        symbol's rotation, so sideways symbols get 90 to come out horizontal."""
        self.pwr_n += 1
        lib_id = POWER[net]
        sym = kilib.load(lib_id)
        ref = f"#PWR{self.s['page']:01d}{self.pwr_n:03d}"
        supply = net != "GND"
        half = 0.55 * len(net) * 1.27 / 1.27 + 0.6
        if rot in (90, 270):
            d = 1 if (rot == 270) == supply else -1        # which way the symbol points
            val_at, ang = (at[0] + d * (3.3 + half), at[1]), 90
        elif supply:
            s = -1 if rot == 0 else 1
            val_at, ang = (at[0], at[1] + s * (3.3 + half)), 90
        else:
            s = 1 if rot == 0 else -1
            val_at, ang = (at[0], at[1] + s * 4.2), 0
        self.instance(lib_id, ref, net, at, rot, sym,
                      [("Footprint", ""), ("Datasheet", ""), ("Description", f"Power symbol for net {net}")],
                      in_bom=False, ref_at=(at[0], at[1]), val_at=val_at, hide_ref=True, val_angle=ang)

    def part(self, part, origin):
        pnet = part.pin_net()
        ox, oy = origin
        x0, y0, x1, y1 = kilib.body_extent(part.sym)
        small = len(part.pins) == 2 and all(int(p[5]) in (90, 270) for p in part.pins)
        if small:
            ref_at, val_at = (ox + 2.54, oy - 1.0), (ox + 2.54, oy + 1.6)
        else:
            ref_at, val_at = (ox + x0, oy + y0 - 1.3), (ox + x0, oy + y1 + 2.6)
        fields = [("Footprint", part.fp), ("Datasheet", kilib.props(part.sym).get("Datasheet", "~")),
                  ("Description", part.desc or kilib.props(part.sym).get("Description", ""))]
        if part.mpn:
            fields.append(("MPN", part.mpn))
        if part.lcsc:
            fields.append(("LCSC", part.lcsc))
        if part.note:
            fields.append(("Note", part.note))
        if part.place:
            pl = part.place
            fields.append(("Deck8_Place", f"X={pl['x']};Y={pl['y']};side={pl['side']};rot={pl['rot']}"))
        in_bom = part.in_bom and not part.ref.startswith("#")
        self.instance(part.lib_id, part.ref, part.value, (ox, oy), 0, part.sym, fields, in_bom=in_bom,
                      dnp=part.dnp, ref_at=ref_at, val_at=val_at, hide_ref=part.ref.startswith("#"))
        done = set()
        for num, name, typ, px, py, ang, ln in part.pins:
            if num not in pnet:
                continue
            net = pnet[num]
            p = (round(ox + px, 4), round(oy - py, 4))
            key = (p, net)
            if key in done:
                continue
            done.add(key)
            k = f"{part.ref}/{num}"
            if net is None:
                self.items.append(["no_connect", ["at", p[0], p[1]], ["uuid", Str(uid(self.s["name"], k, "nc"))]])
                continue
            d = outward(ang)
            e = (round(p[0] + d[0] * STUB, 4), round(p[1] + d[1] * STUB, 4))
            self.items.append(wire(p, e, uid(self.s["name"], k, "stub")))
            if net in POWER:
                self.power(net, e, power_rot(net, d), k)
            else:
                self.items.append(label(net, e, d, uid(self.s["name"], k, "label"), net in self.glob))
        self.placed.append(part)

    def text(self, s, x, y, size=1.27, bold=False):
        self.items.append(["text", Str(s), ["exclude_from_sim", "no"], ["at", x, y, 0],
                           effects(size=size, justify="left top", bold=bold), ["uuid", Str(uid(self.s["name"], "text", s[:40], x, y))]])

    def frame(self, x0, y0, x1, y1, key):
        self.items.append(["rectangle", ["start", x0, y0], ["end", x1, y1],
                           ["stroke", ["width", 0.2], ["type", "dash"]], ["fill", ["type", "none"]],
                           ["uuid", Str(uid(self.s["name"], "frame", key))]])

    def layout(self, page_w, page_h, glob):
        margin_x, top = 18.0, 22.0
        gx, gy, shelf_h = margin_x, top, 0.0
        max_group_w = page_w - 2 * margin_x
        for gi, (title, parts) in enumerate(self.s["groups"]):
            # lay parts out in rows inside the group
            rows, row, rw = [], [], 0.0
            ext = {}
            for prt in parts:
                ext[prt.ref] = part_extent(prt, prt.pin_net(), glob)
                w = ext[prt.ref][2] - ext[prt.ref][0]
                if row and rw + w > min(max_group_w, 230.0):
                    rows.append(row)
                    row, rw = [], 0.0
                row.append(prt)
                rw += w + 4.0
            rows.append(row)
            gw = max(sum(ext[p.ref][2] - ext[p.ref][0] + 4.0 for p in r) for r in rows)
            gh = sum(max(ext[p.ref][3] - ext[p.ref][1] for p in r) + 4.0 for r in rows)
            if gx + gw > page_w - margin_x:
                gx, gy, shelf_h = margin_x, gy + shelf_h + 16.0, 0.0
            y = gy
            for r in rows:
                x = gx
                rh = max(ext[p.ref][3] - ext[p.ref][1] for p in r)
                for prt in r:
                    e = ext[prt.ref]
                    self.part(prt, (snap(x - e[0]), snap(y - e[1])))
                    x += e[2] - e[0] + 4.0
                y += rh + 4.0
            self.frame(round(gx - 4, 2), round(gy - 9, 2), round(gx + gw + 1, 2), round(gy + gh + 1, 2), gi)
            self.text(title, round(gx - 2, 2), round(gy - 7.5, 2), size=1.8, bold=True)
            gx += gw + 16.0
            shelf_h = max(shelf_h, gh)
        return gy + shelf_h

    def write(self, fname, page_w, paper):
        body = ["kicad_sch", ["version", 20250114], ["generator", Str("eeschema")], ["generator_version", Str("9.0")],
                ["uuid", Str(uid("file", self.s["name"]))], ["paper", Str(paper)],
                title_block(self.s["title"], self.s["comment"]),
                ["lib_symbols"] + list(self.libs.values())]
        body += self.items
        body.append(["embedded_fonts", "no"])
        with open(fname, "w") as f:
            f.write(dump(body) + "\n")


def title_block(title, comment):
    return ["title_block", ["title", Str(f"Deck-8 Rev A — {title}")], ["date", Str(DATE)], ["rev", Str("A")],
            ["company", Str("Deck-8")], ["comment", 1, Str(comment)],
            ["comment", 2, Str("Generated by tools/gen_schematic.py; edit the script")]]


PAPERS = [("A4", 297, 210), ("A3", 420, 297), ("A2", 594, 420)]


def main():
    os.makedirs(OUT, exist_ok=True)
    root_uuid = uid("root")
    # which nets cross sheets
    net_sheets = {}
    all_parts = []
    for si, s in enumerate(SHEETS):
        for _, parts in s["groups"]:
            for p in parts:
                p.sheet = s["name"]
                all_parts.append(p)
                for net in p.pin_net().values():
                    if net and net not in POWER:
                        net_sheets.setdefault(net, set()).add(s["name"])
    refs = [p.ref for p in all_parts]
    dup = {r for r in refs if refs.count(r) > 1}
    if dup:
        raise SystemExit(f"duplicate references {dup}")
    glob = {n for n, sh in net_sheets.items() if len(sh) > 1}
    single_pin = [n for n in net_sheets if sum(1 for p in all_parts for v in p.pin_net().values() if v == n) < 2]
    if single_pin:
        raise SystemExit(f"nets with only one pin: {single_pin}")

    sheet_syms = []
    for si, s in enumerate(SHEETS):
        s["page"] = si + 2
        sheet_uuid = uid("sheet", s["name"])
        for paper, pw, ph in PAPERS:
            w = SheetWriter(s, f"/{root_uuid}/{sheet_uuid}", root_uuid, glob)
            bottom = w.layout(pw, ph, glob)
            if bottom < ph - 45:
                break
        w.write(os.path.join(OUT, s["file"]), pw, paper)
        sheet_syms.append((s, sheet_uuid))

    # root sheet: sheet symbols + design notes
    items = []
    x, y = 25.4, 35.56
    for i, (s, su) in enumerate(sheet_syms):
        sx, sy = x + (i % 3) * 63.5, y + (i // 3) * 40.64
        items.append(["sheet", ["at", sx, sy], ["size", 50.8, 25.4], ["exclude_from_sim", "no"], ["in_bom", "yes"],
                      ["on_board", "yes"], ["dnp", "no"], ["fields_autoplaced", "yes"],
                      ["stroke", ["width", 0.1524], ["type", "solid"]], ["fill", ["color", 0, 0, 0, 0.0]],
                      ["uuid", Str(su)],
                      ["property", Str("Sheetname"), Str(s["name"]), ["at", sx, sy - 0.7, 0], effects(justify="left bottom")],
                      ["property", Str("Sheetfile"), Str(s["file"]), ["at", sx, sy + 26.0, 0], effects(justify="left top")],
                      ["instances", ["project", Str(PROJECT), ["path", Str(f"/{root_uuid}"), ["page", Str(str(s["page"]))]]]]])
        items.append(["text", Str(s["title"]), ["exclude_from_sim", "no"], ["at", sx + 2, sy + 8, 0],
                      effects(justify="left top"), ["uuid", Str(uid("root", "label", s["name"]))]])
    notes = NOTES.strip()
    items.append(["text", Str(notes), ["exclude_from_sim", "no"], ["at", 25.4, 128, 0], effects(justify="left top"),
                  ["uuid", Str(uid("root", "notes"))]])
    root = ["kicad_sch", ["version", 20250114], ["generator", Str("eeschema")], ["generator_version", Str("9.0")],
            ["uuid", Str(root_uuid)], ["paper", Str("A3")],
            title_block("Overview", "8-key wired + Bluetooth macro controller (see the plan page)."),
            ["lib_symbols"]] + items + [["sheet_instances", ["path", Str("/"), ["page", Str("1")]]], ["embedded_fonts", "no"]]
    with open(os.path.join(OUT, f"{PROJECT}.kicad_sch"), "w") as f:
        f.write(dump(root) + "\n")

    # project file: start from KiCad's template once, then keep it (gen_pcb.py and KiCad add rules to it)
    pro_path = os.path.join(OUT, f"{PROJECT}.kicad_pro")
    if not os.path.exists(pro_path):
        with open(TEMPLATE_PRO) as f:
            pro = json.load(f)
        pro.setdefault("meta", {})["filename"] = f"{PROJECT}.kicad_pro"
        with open(pro_path, "w") as f:
            json.dump(pro, f, indent=2)

    # intended netlist and placement, for the checker and the layout step
    intent = {p.ref: {"lib": p.lib_id, "value": p.value, "footprint": p.fp, "sheet": p.sheet,
                      "pins": p.pin_net()} for p in all_parts}
    with open(os.path.join(OUT, "intended_netlist.json"), "w") as f:
        json.dump(intent, f, indent=1, sort_keys=True)
    placement = {"units": "mm, PCB plane: origin = key-grid centre on the PCB top, +Y toward the back",
                 "source": os.path.relpath(FUSION, HW),
                 "board": {"half_width": pcb_hw, "front": pcb_front, "back": pcb_back,
                           "chamfer_back": L["PCB_OUTLINE"][3], "chamfer_front": L["PCB_OUTLINE"][4]},
                 "parts": {p.ref: p.place for p in all_parts if p.place}}
    with open(os.path.join(HW, "placement.json"), "w") as f:
        json.dump(placement, f, indent=1)
    print(f"wrote {len(SHEETS) + 1} sheets, {len([p for p in all_parts if not p.ref.startswith('#')])} parts, "
          f"{len(glob)} global nets, {len(placement['parts'])} placed parts")


def gpio_notes():
    pin = {v: k for k, v in MCU_PINS.items() if v}
    ain = {"P0.02": 0, "P0.03": 1, "P0.04": 2, "P0.05": 3, "P0.28": 4, "P0.29": 5, "P0.30": 6, "P0.31": 7}
    keys = " ".join(pin[f"KEY{i}"] for i in range(1, 9))
    unused = " ".join(sorted(k for k, v in MCU_PINS.items() if v is None and k.startswith("P")))
    return (f"MCU GPIO: keys 1-8 {keys} | L1 {pin['BTN_L1']} L2 {pin['BTN_L2']} SYS {pin['BTN_SYS']} | "
            f"knob A {pin['ENCA_A']}/{pin['ENCA_B']} sw {pin['ENCA_SW']} | knob B {pin['ENCB_A']}/{pin['ENCB_B']} "
            f"sw {pin['ENCB_SW']}\n"
            f"          I2C SDA {pin['I2C_SDA']} SCL {pin['I2C_SCL']} | LED ring {pin['LED_RING_3V3']}, keys "
            f"{pin['LED_KEYS_3V3']} (SPI MOSI; spare SCK pins are unconnected) | LED_EN {pin['LED_EN']} | "
            f"BAT_SENSE {pin['BAT_SENSE']} (AIN{ain[pin['BAT_SENSE']]}) | CHG_N {pin['CHG_N']} PGOOD_N {pin['PGOOD_N']} | "
            f"reset P0.18 | LFXO P0.00/P0.01\n"
            f"Unused, no-connect: {unused} (P0.09/P0.10 are NFC).\n"
            f"Key LED chain: keys {'-'.join(str(n) for n in LED_CHAIN)}; the back-row LEDs are turned 180 deg.")


NOTES = f"""
DESIGN NOTES (Rev A)
Power: USB-C -> PTC + USBLC6 -> BQ24074 (USB500: EN1=VBUS, EN2=GND) -> VSYS. TPS7A0533 (EN = power switch) -> +3V3. TPS22917 (ON = LED_EN) -> VLED.
{gpio_notes()}

Checked against the TI BQ24074 datasheet: ITERM and TMR open = default 10% termination and default timers (R6, R7 not fitted);
TS 10k to VSS when the cell has no NTC; EN1 high + EN2 low = 450-500 mA input; K_ISET 890 A-ohm; OUT regulates at 4.4 V.

REVIEW BEFORE ORDERING
1  Battery J2 polarity must match the cell (JST-PH polarity is not standard).
2  OLED J5 pin order GND-VCC-SCL-SDA; header row position depends on the module drawing.
3  MDBT50Q-1MV2 (C5118826) was out at JLC on 23 Oct: use JLC Global Sourcing or consign it.
4  ST1-ST4 (Wurth 9774030243) are not stocked at LCSC: solder them by hand after assembly.
5  SK6812MINI-E needs VDD >= 3.7 V: firmware turns RGB off below about 3.7 V on battery.
"""

if __name__ == "__main__":
    main()
