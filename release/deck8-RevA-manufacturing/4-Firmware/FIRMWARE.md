# Deck-8 firmware (ZMK)

ZMK user config plus the Deck-8 board definition. It covers:
- the 8 keys, L1, L2 and System buttons;
- the two knobs, with their push switches;
- the OLED status screen;
- the key LEDs and light ring, which run as one RGB effect;
- battery level;
- Bluetooth (5 profiles) and USB;
- live remapping in ZMK Studio.

ZMK is pinned in `config/west.yml` to `main` at 4dd95d78 (Zephyr 4.1, hardware model v2).

## Files

| Path | What |
|---|---|
| `config/deck8.keymap` | The keymap: edit this to change what keys do |
| `config/deck8.conf` | Feature switches: RGB limits, sleep, Studio |
| `boards/deck8/` | The board: pins, LED chains, OLED, knobs, battery divider, flash layout |
| `drivers/led_strip/led_strip_chain.c` | Joins the 8 key LEDs and the ring strip (separate data pins) into one strip for ZMK's RGB |
| `src/rgb_battery_guard.c` | Turns the RGB off on battery below 3.7 V, where the SK6812s stop working properly |
| `tools/setup_toolchain.sh`, `tools/build.sh` | Local toolchain in `~/zmk-build` and the build |
| `out/deck8.uf2`, `out/deck8.hex` | Built firmware |

## Keymap

```
         [knob A]   [  OLED  ]   [knob B]
  [L1]   [ 1 ] [ 2 ] [ 3 ] [ 4 ]
  [L2]   [ 5 ] [ 6 ] [ 7 ] [ 8 ]            [SYS]
```

| Layer | How | Keys 1–4 | Keys 5–8 | Knob A (turn / press) | Knob B (turn / press) |
|---|---|---|---|---|---|
| Bank 1 | default | F13 F14 F15 F16 | F17 F18 F19 F20 | volume / mute | ← → / play-pause |
| Media | hold L1 | prev, play/pause, next, mute | undo, redo, copy, paste | as Bank 1 | as Bank 1 |
| Bank 3 | hold L2 | Ctrl+F13–F16 | Ctrl+F17–F20 | as Bank 1 | as Bank 1 |
| System | hold SYS | Bluetooth profile 1–4 | clear profile, USB/BLE, lights on/off, next effect | brightness / saturation | colour / unlock Studio |

On the System layer, L1 jumps to the bootloader and L2 resets.

F13–F24 exist on every OS but no keyboard has them, so apps never clash with them. Bind them in OBS, a Stream Deck-style app or your OS shortcuts, or change them in the keymap or in ZMK Studio.

## Build

```bash
tools/setup_toolchain.sh
```

```bash
tools/build.sh
```

The first command runs once. It downloads about 1.5 GB into `~/zmk-build`, with nothing system-wide. The second builds `out/deck8.uf2`. Run `tools/build.sh pristine` for a clean rebuild.

## First flash (once per board)

A new nRF52840 is empty. Put the UF2 bootloader on it once, through the Tag-Connect footprint J3:
1. Get `nice_nano_bootloader-0.11.0_s140_6.1.1.hex` from the [Adafruit nRF52 bootloader releases](https://github.com/adafruit/Adafruit_nRF52_Bootloader/releases/tag/0.11.0). Its flash layout matches this board: SoftDevice S140 6.1.1, app at 0x26000. Its LED pin (P0.15) is unconnected here, and it leaves DC/DC off.
2. Connect a TC2030-IDC-NL cable and an SWD probe (J-Link EDU Mini, or any CMSIS-DAP), power the board over USB, and flash it:

```bash
nrfjprog --program nice_nano_bootloader-0.11.0_s140_6.1.1.hex --chiperase --verify --reset
```

   Or use J-Flash Lite, or `openocd` with a CMSIS-DAP probe.

3. The board now shows up over USB as a drive named **NICENANO**.

## Updating the firmware

Copy `out/deck8.uf2` onto the NICENANO drive. The board reboots into Deck-8. To get back to the drive later, use either of these:
- Hold SYS and press L1 (System layer → bootloader).
- Double-press the RESET button SW2 on the back of the board (tray off).

## Checks after the first flash

- **Keys and buttons:** the board enumerates as "Deck-8" over USB. Each key sends F13–F20, which you can check in a key-tester web page.
- **OLED:**
  - It should show battery, output and layer.
  - Upside down: add `segment-remap;` and `com-invdir;` to the `oled` node in `boards/deck8/deck8_nrf52840_zmk.dts`.
  - Blank: delete `inversion-on;`.
- **Knobs:**
  - One volume step per detent.
  - Wrong direction: swap the two values in that knob's `sensor-bindings`.
  - Two steps per detent: set `steps = <48>` for that encoder.
- **Lights:**
  - The key LEDs and ring run one swirl effect at up to 40 % brightness.
  - Wrong colours on the ring: change its `color-mapping`; an RGBW strip needs four entries.
  - Wrong length: the ring's LED count is `chain-length` in `ring_leds`, 17 for a 293 mm strip at 60 LEDs/m. Change it there and in `all_leds`.
- **Battery:** the percentage shows on the OLED and in the OS Bluetooth battery level. The RGB switches itself off on battery below 3.7 V (`CONFIG_DECK8_RGB_BATTERY_GUARD_MV`).

## Choices

- **Power:** the chip runs on its LDO. Raytac's material doesn't confirm that the MDBT50Q-1MV2 carries the DC/DC inductor, and switching DC/DC on without it stops the chip. Once a board is in hand, try DC/DC with the line in the board defconfig; it saves about a third of the BLE current.
- **Brightness:** capped at 40 %. 25 LEDs at full white would draw about 1.5 A, and USB gives 500 mA, shared with charging.
- **Idle and sleep:** the lights go off when idle, and the board deep-sleeps after 15 minutes. Any key wakes it; the knobs don't.
