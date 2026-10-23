# Deck-8

**An open-source 8-key macro pad with two knobs, a tiny screen and Bluetooth.** Everything is in this repo: the circuit board, the 3D-printable case, the firmware, and every file you need to order the parts.

[![Watch the 30 second promo](docs/images/promo.gif)](media/deck8-promo.mp4)

*Click the preview for the full 30 second video with sound.*

![Deck-8 in its case](docs/images/case-hero.png)

> **Status: Rev A, designed and checked, but not yet built.** The board passes every automatic check (design rules, schematic checks, a fit check of the board in the case). The firmware compiles. But **no one has built one yet**, and the firmware has never run on real hardware. If you build one, you are the first. Please open an issue and tell us what happened, good or bad. See [Known risks](#known-risks).

## What it does

| | |
|---|---|
| **Keys** | 8 mechanical keys (MX-style, hot-swap, so you can change switches without soldering) in 2 rows of 4 |
| **Knobs** | 2 rotary knobs with push buttons (volume, scrolling, anything you map) |
| **Screen** | 0.96 inch OLED showing battery, connection and active layer |
| **Side buttons** | L1 and L2 on the left, System on the right, plus a power slide switch |
| **Lights** | RGB under every key, plus a glowing ring around the base |
| **Connections** | USB-C and Bluetooth (5 profiles) |
| **Battery** | Built-in 1000 mAh LiPo, charges over USB-C |
| **Brain** | Nordic nRF52840 (Raytac MDBT50Q module), running [ZMK](https://zmk.dev) firmware |
| **Remapping** | Change keys live in [ZMK Studio](https://zmk.studio), no rebuild needed |
| **Size** | Case 98 × 84 mm, 18 mm tall at the front rising to 30 mm at the back (the top tilts 8°). Board 92.8 × 76 mm, 4 layers |

### The layers

By default the 8 keys send **F13–F20**. No normal keyboard has those keys, so they never clash with anything. Bind them to anything you like in OBS, in your operating system, or in a Stream Deck-style app.

```
         [knob A]   [  OLED  ]   [knob B]
  [L1]   [ 1 ] [ 2 ] [ 3 ] [ 4 ]
  [L2]   [ 5 ] [ 6 ] [ 7 ] [ 8 ]            [SYS]
```

| Layer | How you get it | Keys 1–4 | Keys 5–8 | Knob A turn / press | Knob B turn / press |
|---|---|---|---|---|---|
| Bank 1 | default | F13 F14 F15 F16 | F17 F18 F19 F20 | volume / mute | ← → / play-pause |
| Media | hold L1 | prev, play/pause, next, mute | undo, redo, copy, paste | same | same |
| Bank 3 | hold L2 | Ctrl+F13–F16 | Ctrl+F17–F20 | same | same |
| System | hold SYS | Bluetooth profile 1–4 | clear profile, USB/Bluetooth, lights on/off, next effect | brightness / saturation | colour / unlock Studio |

On the System layer, L1 jumps to the bootloader (for updates) and L2 resets. Edit [`firmware/config/deck8.keymap`](firmware/config/deck8.keymap) to change any of this.

## Pictures

### The case

| | |
|---|---|
| ![Front right](docs/images/case-front-right.png) | ![Top](docs/images/case-top.png) |
| ![Side](docs/images/case-side.png) | ![Back with USB-C](docs/images/case-back-usb.png) |
| ![Board inside the case](docs/images/case-inside-pcb.png) | ![Tray with battery](docs/images/case-tray-battery.png) |

*Bottom right: the tray, with the battery on the left and the glowing ring's wall around the edge. The 3D renders show the board and its parts as simple boxes where a part has no 3D model.*

### How it stacks together

![Layers from top to bottom](docs/images/stack.svg)

The board is a two-sided sandwich:

- **Underneath** are all the small electronic parts: the main chip, the charger, the USB-C port, the key lights and the 8 key sockets. The factory solders these on.
- **On top** are only the parts you touch: the 2 knobs and the screen.
- **The key switches are not soldered.** They push down from the top through a thin plate and click into the sockets underneath. A broken key is pulled out and replaced.

### The circuit board

| Top | Bottom |
|---|---|
| ![PCB top](docs/images/pcb-top.png) | ![PCB bottom](docs/images/pcb-bottom.png) |

| 3D view, top | 3D view, bottom |
|---|---|
| ![PCB 3D top](docs/images/pcb-3d-top.png) | ![PCB 3D bottom](docs/images/pcb-3d-bottom.png) |

The PCB 3D views show the bare board; most parts have no 3D model in KiCad's library.

Four layers: top (signals), a full ground plane, a split power plane (3.3 V and the LED supply), and the bottom (parts and signals). 1037 tracks, 585 vias, USB data lines 14.5 and 15.2 mm long with no vias.

| Ground layer | Power layer |
|---|---|
| ![Ground plane](docs/images/pcb-layer-in1-gnd.png) | ![Power plane](docs/images/pcb-layer-in2-power.png) |

### The schematic

Seven sheets, all generated from [`hardware/tools/gen_schematic.py`](hardware/tools/gen_schematic.py). The full set is in [`docs/deck8-schematic.pdf`](docs/deck8-schematic.pdf).

| Power: USB-C, charger, regulator, LED switch | MCU: nRF52840 and crystal |
|---|---|
| ![Power](docs/images/schematic-power.png) | ![MCU](docs/images/schematic-mcu.png) |

| Inputs: keys, buttons, knobs | Lighting | Display |
|---|---|---|
| ![Inputs](docs/images/schematic-inputs.png) | ![Lighting](docs/images/schematic-lighting.png) | ![Display](docs/images/schematic-display.png) |

## Build one

This is the plain version. [`release/BUILD-GUIDE.md`](release/BUILD-GUIDE.md) has the same steps in more detail, and [`release/BUY-LIST.csv`](release/BUY-LIST.csv) lists every part.

### What it costs

An honest estimate, from October 2026 prices. **Check every number at the time you order:**

| Item | Rough cost |
|---|---|
| Assembled boards from JLCPCB (3–5 boards, with all the small parts, setup fees and shipping) | about $150–200 total (₹13,000–17,000) |
| Parts you buy yourself: screen, 2 encoders, battery, LED strip, 8 switches, keycaps, screws | about $20–35 per unit |
| Printing the case | about $10–35, depending on where you print |

The big cost is not the board itself. A bare board is cheap (5 boards for about $8 with leaded HASL finish). The cost is assembly: setup fees, "extended part" fees, the parts, and shipping. If you can solder, you can order bare boards and build them, but the main chip's pads are underneath it (see the next section), so you will need a hot-air station.

### Step 1: order the board

The ready-to-upload files are in [`release/deck8-RevA-manufacturing/1-PCB-order-JLCPCB/`](release/deck8-RevA-manufacturing/1-PCB-order-JLCPCB/):

| File | Upload it as |
|---|---|
| `deck8-RevA-gerbers.zip` | The board design |
| `deck8-RevA-bom-jlc.csv` | The parts list |
| `deck8-RevA-cpl-jlc.csv` | Where each part goes |

Settings (all listed in `JLC-ORDER-SETTINGS.md` in the same folder): 4 layers, 1.6 mm thick, ENIG finish (HASL also works but is less flat), tented vias, assembly on the **bottom side only**, and "Confirm parts placement" turned on.

**Watch for these on the JLCPCB parts page:**

- **The nRF52840 module (U5, MDBT50Q-1MV2) was out of stock** on 24 Oct 2026. Pick "Global Sourcing" for it, or buy it from Mouser or DigiKey and send it to JLC. Don't remove it from the order: its pads are under the module, so it can't be soldered by hand without hot air.
- **Four parts were swapped** to alternatives JLC had in stock. Each has the same footprint, checked against its datasheet: the 8 key sockets (HanElectricity CPG151101S11-16), the charger (BQ24074RGTT), the reset button (PTS810SJK) and the ring connector (Joint Tech A1001WR-S-03P).
- **Check the placement preview.** JLC doesn't know some of these parts' rotation. Check D1–D8, K1–K8, J4, SW1–SW5 and U5 sit correctly on their pads, and rotate any that don't.

### Step 2: buy the rest

[`release/BUY-LIST.csv`](release/BUY-LIST.csv) is the full list. Briefly:

- 2 × Bourns PEC11R-4220F-S0024 rotary encoders (through-hole)
- 4 × Würth 9774030243 M2 standoffs (SMD, not at LCSC)
- 0.96 inch SSD1306 I²C OLED module with its 4-pin header (pin order GND-VCC-SCL-SDA)
- 8 × MX-style switches and 8 × keycaps
- 1000 mAh LiPo with protection board and a JST-PH plug (**check the polarity**, see below)
- SK6812 LED strip (5 mm wide, 60 LEDs/m, 293 mm = 17 LEDs) and a 3-pin JST SH lead
- M2 hardware: 4 heat-set inserts (3 mm long), 4 × M2×5 **wafer-head** screws, 2 × M2×6 and 2 × M2×12 pan-head screws
- 4 rubber feet (8 mm), and a 1 mm acrylic lens (laser-cut from the DXF)
- To flash the bootloader once: a Tag-Connect TC2030-IDC-NL cable and an SWD probe

### Step 3: print the case

Files are in [`release/deck8-RevA-manufacturing/3-Enclosure/`](release/deck8-RevA-manufacturing/3-Enclosure/). All STLs are in millimetres, laid flat.

| Part | Qty | Material |
|---|---|---|
| Top shell | 1 | MJF or SLS nylon (best), or FDM PETG/ASA. Nylon takes heat-set inserts. |
| Bottom tray | 1 | MJF nylon or FDM PETG |
| Light ring | 1 | Clear or translucent (clear SLA resin, sanded frosted). It must let light through. |
| Knob | 2 | MJF nylon or SLA (one file, print two) |
| Buttons (L1, L2, System) | 1 each | MJF nylon or SLA |
| Switch plate | 1 | Laser-cut 1.5 mm steel, aluminium or FR-4 from the DXF (best), or printed |
| OLED lens | 1 | 1 mm clear or smoked acrylic, laser-cut from the DXF |

### Step 4: assemble

1. **Solder by hand:** the 4 standoffs on the bottom (ST1–ST4) and the 2 encoders on the top.
2. **Check power.** Plug in USB-C through a USB power meter: it should draw well under 100 mA. With the power switch on, TP2 (VSYS) should read about 4.4 V and TP4 (+3V3) 3.3 V, measured against TP6 (GND).
3. **Flash the bootloader once** (next section).
4. **Melt the 4 heat-set inserts** into the shell bosses.
5. **Fit the OLED.** Shell upside down: drop in the lens, then the screen module glass-down with its header pins pointing up. Clip the header's short pins to 1 mm.
6. **Fit the board.** Lower it onto the bosses with the OLED pins through J5. Screw it down with the four wafer-head screws, then solder the 4 J5 pins from underneath. The shell sets the screen height, so do this *after* screwing the board in.
7. **Switches.** Put the plate in, then push the 8 switches through it into the sockets.
8. **Battery.** **Check the polarity first**: the red wire must land on J2 pin 1 (VBAT). Swap the crimps in the plug if not. Then plug in the cell; it sits in the tray's fence.
9. **Ring.** Stick the LED strip round the light wall, LEDs facing out. Solder the SH lead (VLED, DIN, GND) and plug it into J4.
10. **Close up.** Fit the ring, then close the tray with the M2×6 screws (front) and M2×12 (back). Stick on the feet.
11. **Finish.** Knobs on the shafts, buttons, and keycaps.

### Step 5: firmware

The firmware is ready-built: [`release/deck8-RevA-manufacturing/4-Firmware/deck8.uf2`](release/deck8-RevA-manufacturing/4-Firmware/deck8.uf2).

**Once per board** (a new nRF52840 is empty): put the bootloader on through the Tag-Connect pads J3.

1. Download `nice_nano_bootloader-0.11.0_s140_6.1.1.hex` from the [Adafruit bootloader releases](https://github.com/adafruit/Adafruit_nRF52_Bootloader/releases/tag/0.11.0). Its flash layout matches this board.
2. Connect the Tag-Connect cable and an SWD probe, power the board over USB, then run:

```bash
nrfjprog --program nice_nano_bootloader-0.11.0_s140_6.1.1.hex --chiperase --verify --reset
```

3. A USB drive called **NICENANO** appears. Copy `deck8.uf2` onto it. The board restarts as "Deck-8".

**Updates:** hold SYS and press L1, or double-press the RESET button (SW2), and copy the new `.uf2` onto the drive.

**First-power-up checks** (the firmware has never run on real hardware, so check these):

- **Screen upside down?** Add `segment-remap;` and `com-invdir;` to the `oled` node in `firmware/boards/deck8/deck8_nrf52840_zmk.dts`. **Blank?** Delete `inversion-on;`.
- **A knob turns the wrong way?** Swap its two values in `sensor-bindings` in the keymap. **Two steps per click?** Set `steps = <48>` for that encoder.
- **Ring colours wrong, or the wrong length?** Change `color-mapping` or `chain-length` in the `ring_leds` node, and `chain-length` in `all_leds` (8 key LEDs + ring LEDs).

See [`firmware/README.md`](firmware/README.md) for how the firmware is built and what each file does.

## What's in this repo

```
deck-8/
├── hardware/             the circuit board (KiCad 10)
│   ├── main/             the KiCad project: open deck8.kicad_pro
│   ├── lib/              the 4 custom footprints
│   ├── tools/            Python that generates, routes and checks the board and writes the fab files
│   └── README.md         how the board was designed, routed and checked
├── mechanical/           the case (Autodesk Fusion)
│   ├── fusion/Deck8Model/  script that builds the whole case; change a number and re-run
│   └── exports/          STEP, STL, renders and the clash-check report
├── firmware/             ZMK firmware: keymap, board definition, LED and battery code
├── release/              everything ready to upload, print and flash, plus the build guide and buy list
├── media/                the 30 second promo video
└── docs/                 images and the schematic PDF
```

Nothing is drawn by hand. The schematic, the board layout and the case are all produced by scripts, so a change is a few lines of code and a re-run. That also means **edit the scripts, not the generated files**.

## Rebuild it from source

You need macOS or edit the paths: the scripts point to KiCad at `/Applications/KiCad/KiCad.app`. You'll want KiCad 10, Python 3, Autodesk Fusion (the free personal or education licence works), and a C compiler for the router.

**Board**, from `hardware/tools`. `KPY` is KiCad's own Python, which includes `pcbnew`:

```bash
KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
python3 gen_schematic.py && python3 check_schematic.py
$KPY gen_pcb.py && $KPY route_pcb.py && python3 check_pcb.py
$KPY make_fab.py
```

About a minute in total, with the same result every time. `check_pcb.py` runs KiCad's design-rule check and fails on anything. `make_fab.py` refuses to run unless the check passes, then writes the Gerbers, BOM and pick-and-place files and reads them all back to verify them.

The router is a small A\* autorouter written for this project (`hardware/tools/route_pcb.py` plus a C core in `hardware/tools/router/maze.c`, compiled on first run).

**Case**, in Fusion: open Utilities → Add-Ins → Scripts and Add-Ins, add the folder `mechanical/fusion/Deck8Model`, and run it. It builds the case, loads the PCB from `hardware/build/deck8_pcb.step`, and writes the report and exports. If you copy the script into Fusion's own scripts folder instead, put the path of this repo in a file called `deck8_root.txt` next to it, or set the `DECK8_ROOT` environment variable. A clean build reports 0 errors and 0 clashes.

**Firmware**, from `firmware/`:

```bash
tools/setup_toolchain.sh   # once: about 4 GB into ~/zmk-build, nothing system-wide
tools/build.sh             # builds out/deck8.uf2
```

**Release files**: `python3 release/tools/make_release.py` collects the latest board, case and firmware files into `release/deck8-RevA-manufacturing/`.

## Known risks

Rev A is a first prototype. In order of how likely they are to bite:

1. **Nothing has been powered up.** The design passes every check a computer can run, but first prototypes nearly always have a surprise.
2. **The firmware has never run on a real board.** The screen orientation, knob direction and ring length are the likely first fixes (each is one line).
3. **Part stock.** The nRF52840 module was out of stock at JLC. Stock changes daily; check before you order.
4. **Footprints are checked against datasheets, not against real parts.** The key sockets are HanElectricity parts sold under Kailh's number; the land pattern matches their drawing, but nobody has plugged a switch in.
5. **The LED-ring plug length is assumed** (3.0 mm). JST doesn't draw the mated length for that connector.
6. **The cells' polarity isn't standard.** JST-PH leads from different sellers are wired both ways. Check before plugging in.
7. **The lights need a charged battery.** The SK6812 LEDs need about 3.7 V, so on battery below that the firmware switches the colours off.
8. **Power saving is off.** The chip runs on its LDO. Raytac's material doesn't confirm the DC/DC inductor is fitted, and turning DC/DC on without it stops the chip. Once you have a board, try it (see `firmware/boards/deck8/deck8_nrf52840_zmk_defconfig`).

## Help wanted

- **Build one and report back.** Photos, measurements, what broke.
- **A cheaper variant.** The full board costs a lot to have assembled. A 2-layer, hand-solderable board that takes a ready-made nRF52840 board (nice!nano style) would cost far less. If you design one, send it.
- **Other fabs.** The BOM uses LCSC part numbers for JLCPCB. Ports to PCBWay, or to Indian assembly houses, are welcome.
- **Windows and Linux.** The scripts assume macOS paths.
- **Case ideas.** Different materials, a flat version, a travel lid.

Open an issue or a pull request.

## License

[MIT](LICENSE) for the hardware design files, the case, the code and the docs. Do what you like with them, including selling them; please keep the licence notice. Third-party material is listed in [NOTICE.md](NOTICE.md).
