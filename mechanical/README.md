# Deck-8 mechanical (Fusion)

`fusion/Deck8Model/Deck8Model.py` builds the whole Rev A assembly in a new Fusion design, then checks the routed KiCad board inside it.

## Run it

1. In Fusion: **Utilities → Add-Ins → Scripts and Add-Ins** (Shift+S).
2. **Deck8Model** is already listed (a copy lives in Fusion's own `API/Scripts` folder). After editing `fusion/Deck8Model/Deck8Model.py` here, copy it over that one, or click **+** and add this `fusion/Deck8Model` folder instead.
3. Click **Run**. A message box reports the build time, errors, interferences and seated contacts. A build takes about 30 s.

Each run closes the previous unsaved Deck-8 build and writes to `exports/`:

| File | What |
|---|---|
| `build_report.json` | Parameters, every body's volume and bounding box, the KiCad fit, interferences and contacts, warnings, timeline errors |
| `deck8_assembly.step` / `.f3d` | Whole assembly |
| `stl/*.stl` | Printable parts: Top Shell, Light Ring, Bottom Tray, Knob, button caps, OLED Lens, Switch Plate |
| `view_*.png` | Hero, front-right, top, side, back, inside and tray views |

## What is parametric

Live user parameters (Modify → Change Parameters): `case_w`, `case_d`, `front_y`, `h_front`, `h_back`, `skin`, `bevel`, `ch_back`, `ch_front`, `tray_t`, `ring_h`, `ring_t`, `mix_gap`, `strip_t`, `lwall_t`, `lwall_h`, the fits, and the knob dimensions. Outline and side-profile sketches are dimensioned with them.

Positions on the sloped top (keys, knobs, OLED, bosses, side buttons, USB-C) come from the layout table at the top of the script, which matches the plan's shared-coordinate table. Change them there and re-run. `hardware/tools/gen_schematic.py` reads the same table, so the board follows.

## Fit check against the routed board

When `hardware/build/deck8_pcb.step` exists (`check_pcb.py` writes it), the build:

1. Imports the KiCad board and seats it on the PCB plane. The height comes from the board's top face, not its bounding box, and the report gives the measured face heights (`kicad_fit.board_faces_v_mm`, top −9.000 mm).
2. Adds boxes from `hardware/build/fit_envelopes.json`:
   - **Bodies** for parts with no KiCad 3D model: the fab outline at the part's datasheet height.
   - **Plugs** in front of the side-entry connectors, taken from JST's drawings. The placer keeps parts out of these boxes too (`gen_pcb.PLUG`). J2's PHR-2 sticks out 3.6 mm (9.6 mm mated length less the 6.0 mm header). J4's SHR-03V-S is taken at 3.0 mm, because JST draws no mated length.
3. Adds the screws and heat-set inserts (`Fasteners (ref)`), each at its chosen length.
4. Drops the simple reference PCB and runs Fusion's interference check on every body. It sorts what it finds into three lists:
   - `interference`: real overlaps, also split into board against enclosure and within the board.
   - `contacts`: overlaps with a mean thickness under 0.05 mm, where faces are meant to touch: a boss on the board, a part seated on it.
   - The report names KiCad bodies by footprint, for example `J4 / JST_SH_… / Body1`.

### Result, 24 Oct 2026

228 timeline features, 0 errors, 0 warnings, **0 interferences**. Nine seated contacts remain, 0.015–0.02 mm thick:
- the two back shell bosses, the two encoders and the two back inserts on the board;
- the four tray screws' threads in their standoffs.

The first run found 9 overlaps. This is what changed:

| Found | Fix |
|---|---|
| J5's 8.5 mm female socket went through the OLED module board and the top shell. A socket plus the module's own header stands the glass 11 mm off the board, and there are 7 mm. | No socket. The module's own 4-pin header, plastic under the module and long pins down, goes straight through J5. The glass rests on the skin underside, past both ends of the lens pocket, and keeps the lens 0.05 mm away. J5 is now a `PinHeader_1x04` footprint with no 3D model, because the module brings the header. The copper didn't change. |
| The LiPo's edge sat under J2's courtyard, and J2's plug would have gone in on top of the cell. A pouch cell shouldn't carry a hard plug. | Cell moved 8 mm left (`BATTERY` centre X −8); the tray fence follows. The plug now sits beside it. |
| The L1, L2 and System caps overlapped SW3–5. | Courtyard artefact: the envelopes now use the fab outline. The actuator tip is at X ±46.05 and the cap flange at ±46.2, which leaves 0.15 mm of pre-travel. |
| Shell bosses and encoders overlapped the board by 0.02 mm. | Measured: the board's top face is exactly on the plane, so these are seated faces. They are now listed as contacts. |

Modelling the screws caught two more problems:
- The front shell screws (H3/H4) sit under the board right over the light wall and the strip, with 1.05 mm to spare. An M2 pan head is 1.6 mm. The shell screws are now 0.8 mm wafer heads, and the wall top drops to the strip's top edge under them, which leaves 0.6 mm.
- The tray counterbores were 1.2 mm deep for 1.6 mm pan heads, so the heads stood 1 mm proud of the rubber-foot seat. They are now Ø5.0 × 2.9 mm, and the bosses are Ø7, so the tilted heads stop 0.18 mm above the seat.

The new plug boxes then caught R15 and C7 standing 2.5 mm in front of J4's mouth, where the SH plug goes in. The placer now keeps both plug boxes clear. J4 and the clusters to its right moved 1.5 mm east, and the battery-sense parts moved past the end of J2's plug, under the wires. Routing is still clean: DRC 0, USB and crystal traces unchanged.

### Fitting the OLED

1. Shell upside down: drop in the lens, then the module glass-down, header pins up.
2. Clip the header's short pins (the display side) to 1 mm or less above the module board. The skin is 1.3 mm above it.
3. Lower the board onto the shell bosses with the four pins through J5, screw it down, and solder J5 from the bottom. Trim the tails.

The shell sets the display height, so the glass ends up against the window whatever the header tolerances are. Removing the board means desoldering four pins.

### Fasteners

The script picks the tray screw lengths and writes them to `build_report.json` (`fasteners`).

| Where | Part | Notes |
|---|---|---|
| H1–H4, shell bosses | 4 × M2 heat-set insert, 3 mm long (Ø3.5–3.6, for a Ø3.2 hole) | Melt in flush with the boss face. They need a thermoplastic shell (MJF/SLS nylon, PETG, ABS); in resin, glue them in with epoxy. |
| H1–H4, board to shell | 4 × M2 × 5 **wafer head**, head Ø4.5–5.0 and ≤ 0.8 mm thick | A pan head will not fit at H3/H4. |
| ST1, ST2, tray front | 2 × M2 × 6 pan head (ISO 7045) | 2.3 mm into the standoff thread |
| ST3, ST4, tray back | 2 × M2 × 12 pan head | 2.0 mm into the standoff thread |
| Feet | 4 × self-adhesive rubber feet, Ø8, 1.5–3 mm thick | In the Ø8.4 recesses, over the tray screws |

## Mounting points for KiCad

Plane coordinates: origin at the key-grid centre on the PCB top, Y along the slope toward the back.

| Feature | X, Y (mm) | PCB feature |
|---|---|---|
| Shell bosses (M2 heat-set inserts) | (±17.6, +28), (±36, −25) | Ø2.2 holes, keep 5 mm pads clear on both sides |
| Tray screws | (±34, −20), (±36, +24) | SMD M2 standoffs, 3 mm, on the bottom side; keep Ø7 clear (the tray bosses are Ø7) |
| PCB outline | X ±46, Y −28.5 … +47.5 | Chamfer the back corners 9 mm and the front corners 3 mm |
| Side switches | left edge Y +24, +10; right edge Y +10; slide switch left edge Y −14 | Actuator axis 1.75 mm below the PCB bottom |
| USB-C | X 0, back edge | Receptacle centre 3.2 mm below the PCB bottom |
| OLED header (J5) | X −3.81 … +3.81, Y +23 (`OLED_HEADER_Y`) | 1×4, 2.54 mm, Ø1.0 holes for the module's own pins |
| Battery | X −28 … +12, under the board | Bottom parts at most 3 mm tall over it |

## Changes from the plan

- 24 Oct (fasteners): wafer-head shell screws, wall notches under H3/H4, deeper tray counterbores and Ø7 tray bosses (above).
- 23 Oct (fit check): OLED soldered on its own header and held by the shell, not socketed; battery 8 mm left of centre (both above).
- 23 Oct (PCB layout): back shell bosses moved to X ±17.6 and back tray screws to Y +24 to clear the encoder pins.
- Shell walls are 2.0 mm (plan said 2.5). One `skin` value for top and walls keeps the shell a single feature, and it leaves 0.5 mm over the encoder bodies.
- Knobs have 40 grooves, not 60, so each rib stays 0.8 mm wide and prints cleanly.
- The tray hangs from the PCB on 4 SMD standoffs; the PCB hangs from the shell on 4 bosses. No screw passes through the light ring, and the tray screw heads sit under the feet.

## Components

- **Top Shell**: wedge 98 × 84 mm, 18 → 30 mm, 3 mm top bevel, 2.0 mm skin and walls, key well, OLED window with lens recess, knob holes, L1/L2 and power-switch slots, System hole, USB-C opening, 4 M2 insert bosses. Aluminum 6061 material, grey anodized appearance.
- **Light Ring**: separate translucent part (Polycarbonate, Clear material; Plastic – Translucent Matte (White) appearance), 4 mm band × 2.5 mm wall.
- **Bottom Tray**: floor, ring locator lip, light wall for the strip (notched under H3/H4), battery fence, 4 tilted Ø7 screw bosses with counterbores under the feet. ABS.
- **Knob** (×2, one component): Ø20 × 16, D-bore 6.10 / flat 4.55, Ø11 × 4.5 counterbore, 40 grooves.
- **Side Buttons**: L1, L2 pills and the round System cap, each with an inner flange.
- **OLED Lens**, **Switch Plate**.
- Reference only: keycaps, encoders, OLED module with its header, battery, LED strip, screws and inserts. The routed KiCad board replaces the simple reference PCB when its STEP exists.
