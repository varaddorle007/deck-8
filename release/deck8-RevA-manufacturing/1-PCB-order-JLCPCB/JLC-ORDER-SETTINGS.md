# Deck-8 Rev A: JLCPCB fabrication package

Made by `tools/make_fab.py` from `main/deck8.kicad_pcb` (KiCad 10.0.5) after DRC with schematic parity reported
nothing. `tools/gerber_check.py` then read every output back and compared it with the board (results below).

| File | Upload to |
|---|---|
| `deck8-RevA-gerbers.zip` | PCB order: Gerbers, Excellon drill (PTH + NPTH) and drill maps |
| `deck8-RevA-bom-jlc.csv` | PCB Assembly: BOM (34 lines, 78 parts) |
| `deck8-RevA-cpl-jlc.csv` | PCB Assembly: CPL / pick-and-place (78 placements) |
| `deck8-RevA-bom-full.csv` | Your own reference: every fitted part and who fits it |
| `deck8-RevA-assembly-bottom.pdf`, `-top.pdf` | Your own reference: where the hand-fitted parts go |

## PCB order settings

| Setting | Value |
|---|---|
| Layers | 4 (F.Cu signal, In1 GND, In2 +3V3/VLED, B.Cu parts) |
| Size | 92.8 × 76.0 mm |
| Thickness | 1.6 mm, JLC's default 4-layer stack-up (no impedance control needed) |
| Material | FR-4 |
| Outer / inner copper | 1 oz / 0.5 oz |
| Min track / space | 0.15 / 0.15 mm (signals are 0.2 mm) |
| Min hole | 0.20 mm: the charger's thermal vias. Routing vias are 0.3 / 0.6 mm |
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
  D1, D2, D3, D4, D5, D6, D7, D8, J4, K1, K2, K3, K4, K5, K6, K7, K8, SW1, SW2, SW3, SW4, SW5, U5. Their packages have no entry in the rotation table, or JLC's footprint may put the
  origin somewhere else. Rotate or nudge any that are off in the preview; JLC then updates the CPL on its side.
- Bottom-side rotations in the CPL already include the mirror JLC expects, (180° − KiCad angle), and the package
  corrections (SOT-23 −90°, QFN +270°, HRO USB-C +180°, JST-PH +180°).

## Fitted by hand after delivery

| Ref | Part | Side | Why |
|---|---|---|---|
| ENC1 | Bourns PEC11R-4220F-S0024 | top | through-hole |
| ENC2 | Bourns PEC11R-4220F-S0024 | top | through-hole |
| J5 | 0.96 in 128x64 I2C OLED module (SSD1306), soldered on its own 4-pin header | top | through-hole |
| ST1 | Wurth 9774030243 | bottom | not stocked at LCSC |
| ST2 | Wurth 9774030243 | bottom | not stocked at LCSC |
| ST3 | Wurth 9774030243 | bottom | not stocked at LCSC |
| ST4 | Wurth 9774030243 | bottom | not stocked at LCSC |

Not fitted: R6, R7 (DNP by design).

Not on this BOM (enclosure and modules): 8 MX switches, keycaps, the two printed knobs, the LiPo cell (check J2
polarity first), the LED ring strip and the M2 screws and inserts. The 0.96" OLED module is the J5 line above: its own
header is soldered through J5 once the board is screwed into the top shell (`mechanical/README.md`).

## Read-back checks (19/19 passed)

`gerber_check.py` parses the Gerbers, drill files, BOM and CPL without KiCad and compares them with the board. Its renders of the Gerbers are `check_top.png`, `check_bottom.png` (with the CPL placements marked), `check_in1.png` and `check_in2.png`.

| Check | Result |
|---|---|
| ✅ files | 11 Gerber layers + PTH/NPTH drill |
| ✅ zip | deck8-RevA-gerbers.zip holds 16 of 16 files |
| ✅ outline | Edge.Cuts spans 92.80 x 76.00 mm from (0.00, 0.00); board 92.80 x 76.00 mm (max error 0.000) |
| ✅ drill PTH | Ø0.200 x4, Ø0.300 x585, Ø0.600 x4, Ø1.000 x14, Ø1.500 x4 |
| ✅ drill NPTH | Ø0.650 x2, Ø0.900 x8, Ø0.991 x3, Ø1.750 x16, Ø2.200 x4, Ø3.000 x20, Ø4.000 x8 |
| ✅ copper F.Cu | 585 via flashes (board 585), 27 pad flashes (board 27), 260 track segments, 37 pour regions |
| ✅ copper In1.Cu | 585 via flashes (board 585), 26 pad flashes (board 26), 0 track segments, 1 pour regions |
| ✅ copper In2.Cu | 585 via flashes (board 585), 26 pad flashes (board 26), 0 track segments, 2 pour regions |
| ✅ copper B.Cu | 585 via flashes (board 585), 359 pad flashes (board 359), 777 track segments, 14 pour regions |
| ✅ tenting F.Mask | 83 openings, 0 on vias |
| ✅ tenting B.Mask | 404 openings, 0 on vias |
| ✅ paste F.Paste | 0 apertures (board 0) |
| ✅ paste B.Paste | 321 apertures (board 321) |
| ✅ BOM vs board | 34 lines, 78 designators; board has 78 JLC-fitted parts |
| ✅ BOM LCSC numbers | every line has an LCSC part |
| ✅ CPL vs BOM | 78 placements |
| ✅ CPL on board | all inside the outline, layers ['bottom'] |
| ✅ CPL frame | every centre within 8 mm of a bottom paste aperture (mirror or origin errors would move them off) |
| ✅ CPL rotations | 4 distinct angles, all 0-359 |
