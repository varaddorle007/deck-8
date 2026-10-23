# Deck-8 hardware (KiCad 10)

`main/deck8.kicad_pro` is the project. Open it in KiCad 10. The files are written in the KiCad 9 format, which KiCad 10 opens and upgrades the first time you save.

## Regenerate and check

The schematic and the board, routing included, are generated, so edit the scripts in `tools/`, not the KiCad files. `KPY` is KiCad's own Python, which ships `pcbnew`:

```bash
KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
```

```bash
cd tools && python3 gen_schematic.py && python3 check_schematic.py
```

```bash
cd tools && $KPY gen_pcb.py && $KPY route_pcb.py && python3 check_pcb.py
```

```bash
cd tools && $KPY make_fab.py
```

The whole chain takes about a minute and gives the same board every time. `route_pcb.py` discards all tracks, vias and its own zones, then routes again from the placement. It depends only on the placement, not on the order KiCad saves footprints in.

`trim_footprints.py` is a one-off: it copies the stock USB-C, slide-switch and MDBT50Q footprints into `lib/deck8.pretty` without the silk that runs past the board edge. Re-run it (before `gen_schematic.py`) only if one of those parts moves; `gen_pcb.py` warns when it has to trim edge silk itself.

## Fabrication package (JLCPCB)

`tools/make_fab.py` writes `build/fab/`. It refuses to run unless DRC with schematic parity reports nothing, and its `README.md` there lists the JLC order settings. The package:

- **`deck8-RevA-gerbers.zip`:** 11 Gerber layers, PTH and NPTH Excellon drill files and drill maps. They use JLC's KiCad settings: Protel extensions, no X2 or netlist attributes, mask subtracted from silk. Gerbers, drill and CPL share the drill/place origin at the board's lower-left corner.
- **`deck8-RevA-bom-jlc.csv` and `deck8-RevA-cpl-jlc.csv`:** 34 BOM lines, 78 bottom-side placements, every one with an LCSC part.
  - Bottom angles are mirrored the way JLC reads them, (180° − KiCad angle).
  - Package corrections come from the JLCKicadTools table that kicad-jlcpcb-tools uses: SOT-23 −90°, QFN +270°, HRO USB-C +180°, JST-PH +180°.
  - Placements sit on the centre of each part's soldered pads. The hot-swap sockets are listed as bottom parts, although their footprint sits on top.
- **`deck8-RevA-bom-full.csv`:** every fitted part with who fits it. JLC fits all bottom SMD parts. You fit by hand the two encoders, the OLED module at J5 (its own header, soldered once the board is in the shell) and the four Würth standoffs (not stocked at LCSC). R6/R7 are not fitted.
- **`deck8-RevA-assembly-top.pdf` and `-bottom.pdf`:** fab-layer drawings for the hand-fitted parts.
- **The order number:** JLC prints it where the bottom silk reads "JLCJLCJLCJLC", beside "Deck-8 Rev A". Pick "Specify a location".

`tools/gerber_check.py` (system Python with PIL) then reads all of it back without KiCad and compares it with facts measured on the board. On 23 Oct 2026 all 19 checks passed:
- the outline;
- hole counts per diameter in both drill files;
- one flash per via and per pad on each copper layer;
- no mask opening on any via;
- paste only on the bottom;
- BOM, CPL and board listing the same parts, each with an LCSC number, every placement on the board beside its own pads.

It also renders the Gerbers to `check_*.png` for a visual check.

The LCSC numbers are an `LCSC` field on each schematic symbol. Passives come from one table in `gen_schematic.py`, so the BOM can't drift from the schematic. Every number was checked on lcsc.com / jlcpcb.com on 23 Oct 2026; stock and prices change, so recheck them at order time.

## PCB (Rev A, routed)

- **Board:** 4 layers, 1.6 mm, 92 × 76 mm with 9 mm back and 3 mm front chamfers. A 0.8 mm tab on the left edge carries the power slider so its lever reaches the wall slot.
- **Stack-up:**
  - F.Cu: signals plus a GND pour.
  - In1: solid GND.
  - In2: +3V3 behind Y +20.3 and VLED in front of Y +19.7 (the keys and LED drivers).
  - B.Cu: parts, signals and a GND pour.
- **Tracks:**
  - 0.2 mm for signals.
  - 0.4 mm for +3V3 and the LDO output.
  - 0.5 mm for VBUS.
  - 0.8 mm for VBUS_IN, VSYS, VBAT and VLED_SW. These neck down only where a pad is narrower: 0.2 mm at the charger's 0.5 mm-pitch pins, 0.45 mm at the USB-C VBUS pins.
  - Pins that only sense a rail get a thin branch: the charger's EN1, the module's VBUS detect, the ESD part's VBUS pin, the power switch and the test points.
- **Vias:** 0.6 / 0.3 mm throughout (JLC standard). Every SMD pad on GND, +3V3 or VLED has its own via into its plane. The charger's GND pins join its exposed pad, which has its own thermal vias. 317 GND stitching vias on a 4 mm grid tie the outer pours to In1, so no pour piece is left floating.
- **USB:** D+ 14.5 mm and D− 15.2 mm, no vias, through the USBLC6 that sits in line between the connector and the module.
- **Crystal:** XL1/XL2 are 6.4 / 8.0 mm, no vias, routed before any other signal.
- **Keep-outs (enforced by DRC):**
  - Antenna: nothing on any layer.
  - Shell bosses and screw heads: no tracks or vias within 2.5 mm of H1–H4 on either side.
  - Tag-Connect: no vias under its pads.
  - Light wall: no bottom parts in front of Y −24.2.
- **Silkscreen:** every reference sits in the first free spot around its part at 0.8 mm. Six on the crowded bottom (C2, C11, C25, R6, R12, R14) have no free spot, so they are only on the fab layer.
- **DRC (23 Oct 2026):** 0 errors, 0 warnings, 0 unrouted, schematic parity clean. 1037 tracks, 585 vias (317 of them stitching).
- `main/deck8.kicad_dru` adds four rules:
  - relaxed clearances inside three stock land patterns (SKRT side buttons, Würth standoff rings, SK6812MINI-E cut-outs);
  - one thermal spoke is enough on the outer GND pours, since every GND pad already reaches In1.
- **Outputs in `build/`:**
  - `drc.json`, `route_report.json`, `pcb_placement_report.json`.
  - `pcb_top/bottom/iso_*.png` and `pcb_views.png` (3D views); `pcb_layers.png` (each copper layer).
  - `deck8_pcb.step` for the Fusion fit check.
- **3D models:** this KiCad install has no 3D models for the MX switch or EC11 encoder, so the renders and STEP show only their pads.

### How the router works

`tools/route_pcb.py` drives a small A* router in C (`tools/router/maze.c`, compiled on the first run). The board is sampled on a 0.1 mm grid, offset half a cell so the 0.05 mm pad rows land on cell centres.

- **Clearance:** for every layer, each cell stores the clearance-adjusted distance to the nearest copper of another net. A track may pass only where that distance covers its half-width, plus the most a step can stray from a checked cell centre. Pad and hole clearances, the 0.3 mm edge clearance, hole-to-hole spacing and the keep-outs are the board's own rules, so every route is legal by construction. KiCad's DRC then confirms it.
- **Shape:** the search tracks heading, so turns cost something and corners sharper than 90° are not allowed. Routes come out as straight runs with 45° bends.
- **Order:**
  1. power and USB;
  2. the plane vias;
  3. the crystal;
  4. the remaining signals, shortest first.
- **Rip-up:** when a pin can't be reached, the router finds the path that crosses the fewest other tracks and rips up only those nets. It then routes the stuck pin and re-routes the ripped nets around it. USB and the crystal are never ripped.
- **Escapes:** three charger pins on a 0.5 mm-pitch corner get a via before anything else is routed, each on its own side (EN1 south-east, PGOOD south, CHG west), so they don't box each other in.

### Choices made while laying out

- **Encoders:** mirrored, so both pin rows face the walls.
- **Tag-Connect:** at (−9, 25.5) under the OLED. Its alignment pins can't go under a switch.
- **J4:** takes its plug from the left, because a front entry would hit the light wall.
- **Plug space:** no bottom part stands where J2's or J4's mated plug goes. The boxes come from JST's drawings (`PLUG` in `gen_pcb.py`), and the Fusion check uses them too. That is why the battery-sense parts sit past the end of J2's plug, under the wires, not where the plug goes.
- **Hand-placed parts:** the parts that serve one pin are placed by hand, not by the scan:
  - the USB ESD part, in line between USB-C and the module's D+/D−, with the CC resistors either side of the pair;
  - the module's VBUS and VDD caps, right under their pins;
  - the crystal and its load caps, as close to their pins as the H2 screw head allows.
- **Charger section:** turned so IN faces the fuse, OUT faces the LDO and the LED switch, and BAT faces the battery connector. Its setup resistors sit in a row above the charger; the LDO, its caps and the status pull-ups in a row below.
- **LED drivers:** the LED switch sits with its input cap between ST1 and J4's plug. Right of J4, each data buffer is grouped with its resistor and cap.
- **Key LED chain:** keys 5-6-7-8-4-3-2-1. Data runs left to right along the front row, up the right side, and back along the back row, whose LEDs are turned 180° so each DOUT faces the next DIN. No data line crosses the board.

## Sheets

| Sheet | Contents |
|---|---|
| Overview | Sheet index, GPIO plan (generated from the pin map), review list |
| Power | USB-C (CC1/CC2 own 5.1 k), PTC, USBLC6, BQ24074 (USB500, 494 mA), battery + divider, TPS7A0533 3.3 V (EN = power switch), TPS22917 LED switch, 0 Ω measurement links, test points |
| MCU | MDBT50Q-1MV2 (normal voltage mode), decoupling, 32.768 kHz crystal, Tag-Connect SWD, reset |
| Inputs | K1–K8, L1/L2/System side buttons, two EC11 encoders with push |
| Lighting | Two SN74LV1T125 shifters on VLED, D1–D8 SK6812MINI-E chain (keys 5-6-7-8-4-3-2-1), ring strip connector + 100 µF |
| Display | OLED header (GND-VCC-SCL-SDA), I²C pull-ups, decoupling |
| Mechanical | H1–H4 shell holes, ST1–ST4 M2×3 SMD standoffs, fiducials |

## GPIO plan (nRF52840)

Each signal leaves the module on the edge that faces where it goes:
- **East:** keys 3, 4 and 8, the right knob and the System button.
- **South:** keys 2, 5, 6 and 7, and the LED lines.
- **West:** key 1, the left knob, L1/L2, I²C and charger status.

The map comes from a minimum-total-length matching of free pads to destinations on this placement, which also keeps the escapes from crossing. Constraints:
- **West edge:** west-going signals use the module's inner and centre pads, which drop a via straight to the free top layer. The outer west pads could only leave into the gap beside the USB ESD part.
- **South edge:** the outer south pads P0.04, P0.06, P0.08 and P1.09 stay free, because the crystal lines run under them.
- **Pin types:** I²C and LED data are on P0 full-speed pins, and BAT_SENSE is on an analog input.

| Function | Pins |
|---|---|
| Keys 1–8 | P0.14, P1.08, P0.28, P0.31, P0.12, P0.07, P0.27, P0.30 |
| L1, L2, System | P1.01, P0.21, P0.29 |
| Knob A (A/B/push) | P1.02, P0.25, P1.00 |
| Knob B (A/B/push) | P1.15, P1.11, P1.13 |
| I²C SDA / SCL | P0.16 / P0.19 |
| LED data: ring / keys | P0.11 / P0.05 (SPI MOSI; the SPI clock goes to a spare unconnected pin) |
| LED_EN, BAT_SENSE (AIN0), CHG_N, PGOOD_N | P0.26, P0.02, P0.23, P1.03 |
| Reset, LFXO | P0.18, P0.00/P0.01 |

All other GPIO are marked no-connect. P0.09/P0.10 (NFC) are left unused. The key LED chain index i drives key 5, 6, 7, 8, 4, 3, 2, 1 in that order.

## Placement from the Fusion model

`gen_schematic.py` reads the layout constants straight out of `../mechanical/fusion/Deck8Model/Deck8Model.py`, so keys, knobs, holes, side switches, USB-C and the board outline can't drift from the enclosure. Every positioned part has a `Deck8_Place` field, and `placement.json` lists all 40 of them. Coordinates are in the PCB plane: origin at the key-grid centre on the PCB top, +Y toward the back.

## Changes from the plan

- 3.3 V regulator: **TPS7A0533** (1 µA Iq) instead of TPS7A02. KiCad's stock library has no TPS7A02; this part draws the same tiny standby current.
- LED switch: **TPS22917** instead of TPS22918. It has the same CT (slew) and QOD (discharge) pins and is in the stock library. QOD goes to VOUT through R20 (0 Ω) so ERC stays clean.
- OLED module: its header row faces the keys (Y ≈ 23 mm). With the header at the back, the pins would land outside the 76 mm board.
- OLED mounting: no socket. A socket plus the module's own header puts the glass 11 mm off the board, and the shell leaves 7 mm. The module's header pins go through J5, now a `PinHeader_1x04` footprint with no 3D model, and are soldered once the board is in the shell (`../mechanical/README.md`). The copper is the same as the socket footprint's.
- GPIO map and key LED chain order changed during layout (above). Firmware isn't written yet, so nothing else depends on them.
- Level shifters: **SN74LV1T125** instead of 74AHCT1G125. AHCT needs a 4.5–5.5 V supply, and VLED is 3.0–4.4 V. The LV1T125 has TTL-level inputs on any supply from 1.6 to 5.5 V and the same pinout and footprint.
- Crystal: Seiko SC-32S, 32.768 kHz, 20 ppm, **9 pF** load (C97605). The two 12 pF caps in series give 6 pF, plus about 3 pF from the pins and traces.

## Checked against the TI BQ24074 datasheet

- ITERM and TMR left open give the default 10 % termination current and the default safety timers, so R6 and R7 stay unfitted. Tying TMR to GND would disable the timers.
- TS: a 10 kΩ fixed resistor to VSS when the cell has no thermistor (R3).
- EN1 high and EN2 low select 450–500 mA input (USB500). The EN pins have internal pull-downs, but the datasheet says not to leave them open.
- K_ISET = 890 AΩ, so the 1.8 kΩ R4 sets 494 mA. OUT (VSYS) regulates at 4.4 V.

## Review before ordering

1. K1–K8 use `Deck8:SW_MX_Hotswap_Kailh_1u_NorthLED` (`lib/deck8.pretty`, registered in `main/fp-lib-table`). Pad and hole positions come from the MX pin pattern; check them against the Kailh CPG151101S11 drawing.
2. Battery J2 polarity must match the cell; JST-PH polarity is not standard.
3. OLED J5: confirm the pin order and header position against the module you buy. Its header needs the usual 6 mm long side, since the pins go through the board.
4. Stock at JLC on 24 Oct: the MDBT50Q-1MV2 (U5, C5118826) had none. Pick JLC Global Sourcing for it when you order, or buy it at Mouser/DigiKey and consign it. Four other lines were short and now use same-footprint parts that JLC has in stock: K1–K8 HanElectricity CPG151101S11-16 (C41430893), U2 BQ24074RGTT (C2861252), SW2 PTS810SJK (C221896), J4 Joint Tech A1001WR-S-03P (C371509). Their drawings match the land patterns.
5. In JLC's placement preview, check the parts whose package has no rotation entry before confirming: the sockets, LEDs, module, JST-SH connector and the switches. The list is in `build/fab/README.md`.
6. SK6812MINI-E needs VDD ≥ 3.7 V, so firmware must turn the RGB off below about 3.7 V on battery.
7. Done 23 Oct: the Fusion fit check of `build/deck8_pcb.step` in the enclosure shows 0 interferences (`../mechanical/README.md`).
