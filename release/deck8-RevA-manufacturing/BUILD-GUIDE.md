# Deck-8 Rev A: order and build guide

This folder has everything needed to order the board and print the case. Read section 1 before paying for anything.

## 1. Where it stands (24 Oct 2026)

**Checked:**
- **Board:** DRC with schematic parity shows 0 errors, 0 warnings, 0 unrouted. ERC is clean. A read-back of every Gerber, drill, BOM and CPL file passes 19/19 checks.
- **Fit:** the routed board, every part, the cable plugs, and the screws and inserts sit in the case with 0 interferences in Fusion.
- **Footprints:** checked against the makers' drawings for the hot-swap sockets, the LED-ring connector, the JST plugs and the encoders.
- **Stock:** every JLC BOM line was checked against JLC's live stock on 24 Oct; see 2.

- **Firmware:** written and compiled. `4-Firmware/deck8.uf2` covers the keys, side buttons, knobs, OLED, key and ring LEDs, battery, Bluetooth and USB, with ZMK Studio remapping.

**Not done yet:**
- **Firmware on hardware:** it hasn't run on a board yet. `4-Firmware/FIRMWARE.md` lists what to check on first power-up: OLED orientation, knob direction, ring LED count.
- **Hardware:** nothing has been built. This is a first prototype, so plan for small fixes (a part orientation, a tight fit) before calling it final.

## 2. Order the board (JLCPCB)

Upload from `1-PCB-order-JLCPCB/`:

| File | Where |
|---|---|
| `deck8-RevA-gerbers.zip` | PCB order |
| `deck8-RevA-bom-jlc.csv` | PCB Assembly → BOM |
| `deck8-RevA-cpl-jlc.csv` | PCB Assembly → CPL |

Settings, all listed in `JLC-ORDER-SETTINGS.md`:
- **Board:** 4 layers, 1.6 mm, ENIG, tented vias. Order number at "Specify a location".
- **Assembly:** bottom side only. Turn on "Confirm part placement".

On the parts page:
- **U5 (MDBT50Q-1MV2) shows out of stock.** Choose **Global Sourcing** for it. If JLC can't source it, buy one at Mouser or DigiKey and send it as a consigned part. Don't remove it from the order: its pads are under the module, so it can't be soldered by hand.
- **Changed parts.** Four lines were changed on 24 Oct to parts JLC had in stock, with the same footprint and checked against their drawings:
  - K1–K8 hot-swap sockets: HanElectricity CPG151101S11-16.
  - U2 charger: BQ24074RGTT, the same chip on a smaller reel.
  - SW2 reset button: PTS810SJK.
  - J4 LED-ring connector: Joint Tech A1001WR-S-03P, JST SH compatible.
- **Anything else out of stock** on the day: tell me the part and I'll find a same-footprint swap.
- **Placement preview:** check D1–D8, K1–K8, J4, SW1–SW5 and U5 against their pads before confirming. Rotate any that are off.

You get the assembled boards with every bottom part on. The top side is empty, and you fit the through-hole parts yourself (section 5).

## 3. Print the case

Files are in `3-Enclosure/print-STL/`. All are in millimetres, laid flat and sitting on z = 0.

| Part | Qty | Best material | Notes |
|---|---|---|---|
| Top Shell | 1 | MJF or SLS nylon (PA12) | Open side down. Nylon takes the heat-set inserts. FDM PETG/ASA works with supports inside. With resin, glue the inserts in with epoxy. |
| Bottom Tray | 1 | MJF PA12, or FDM PETG | Floor down |
| Light Ring | 1 | Translucent: clear SLA resin (sand it frosted) or natural PETG at 100 % infill | It must let light through. Grey MJF won't. |
| Switch Plate | 1 | Laser-cut 1.5 mm steel, aluminium or FR-4 from the DXF (best), or print it | MX switches clip into a 1.5 mm plate |
| Knob | 2 | MJF PA12 or SLA | One file, print two. Test the D-bore on the encoder shaft; it's sized for a 6.0 mm shaft with a 4.5 mm flat. |
| Button L1, L2, System | 1 each | MJF PA12 or SLA | Small; any orientation |
| OLED Lens | 1 | **1.0 mm acrylic, laser cut** from `laser-cut-DXF/` | Clear or smoked. The STL is only for reference. |

`Deck8_assembly_reference.step` is the whole assembly, to check anything in a CAD viewer.

## 4. Buy

`BUY-LIST.csv` lists everything that isn't on the JLC order:
- the encoders, standoffs, OLED, switches, keycaps, battery and LED strip;
- the screws, inserts and feet;
- the one-time programmer.

**Get the screw types right:**
- **Shell screws:** **M2 × 5 wafer head**, head ≤ 0.8 mm thick, for all four. A normal pan head at the two front screws hits the LED wall.
- **Tray screws:** **M2 × 6** pan head at the front, **M2 × 12** pan head at the back.

## 5. Build order

1. **Solder by hand on the board:**
   - Four Würth standoffs (bottom, ST1–ST4).
   - Two encoders (top, ENC1/ENC2).
2. **Check the board.** Plug USB-C in through a USB power meter: it should draw well under 100 mA. Then measure against TP6 (GND):
   - TP2 (VSYS) should read about 4.4 V.
   - TP4 (+3V3) should read 3.3 V.

   The power switch must be on.
3. **Flash the bootloader once.** Use the Tag-Connect cable on J3; `4-Firmware/FIRMWARE.md` has the exact file and command. The board then appears as a USB drive named NICENANO. Copy `4-Firmware/deck8.uf2` onto it.
4. **Prepare the shell.** Melt the 4 heat-set inserts into the shell bosses, flush with the boss face.
5. **Fit the OLED.** Shell upside down:
   - Drop the lens into its pocket.
   - Put the OLED module in glass-down, its header pins pointing up. First clip the header's short pins, on the display side, to 1 mm.
6. **Fit the board.** Lower it onto the bosses with the OLED pins through J5. Screw it down with the four wafer-head screws, then solder the four J5 pins from the bottom and trim them. The shell sets the display height, so don't solder J5 before this step.
7. **Fit the switches.** Put the switch plate in, then push the 8 switches through it into the hot-swap sockets.
8. **Battery:**
   - **Check polarity first:** the battery plug's red wire must land on J2 pin 1 (VBAT).
   - Plug the cell into J2. It sits in the tray's fence, left of centre.
9. **Light ring:**
   - Stick the LED strip round the light wall, LEDs facing out.
   - Solder the SH lead to the strip (VLED, DIN, GND) and plug it into J4.
10. **Close up:**
    - Fit the light ring.
    - Close the tray with the M2 × 6 screws (front) and the M2 × 12 screws (back).
    - Stick the feet on.
11. **Finish:** press the knobs onto the encoder shafts, then fit the side buttons and the keycaps.

## 6. Files in this folder

| Folder | What |
|---|---|
| `1-PCB-order-JLCPCB/` | The three upload files and the order settings |
| `2-PCB-reference/` | Full BOM with who fits what, top/bottom assembly drawings, Gerber check image |
| `3-Enclosure/print-STL/` | Print-ready parts |
| `3-Enclosure/laser-cut-DXF/` | Lens (1.0 mm) and switch plate (1.5 mm) outlines |
| `4-Firmware/` | `deck8.uf2` (drag onto the board), `deck8.hex` (SWD), the keymap and the firmware notes |
| `BUY-LIST.csv` | Everything to buy that isn't on the JLC order |
