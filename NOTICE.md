# Third-party material

Deck-8 itself is MIT licensed (see `LICENSE`). It builds on:

- **ZMK Firmware** (MIT), fetched at build time from github.com/zmkfirmware/zmk, pinned in `firmware/config/west.yml`.
  `firmware/boards/deck8/` follows ZMK's nice!nano and nice!60 board files.
- **Zephyr RTOS** (Apache-2.0), pulled in through ZMK.
- **KiCad libraries**: the four footprints in `hardware/lib/deck8.pretty` (USB-C, slide switch, MDBT50Q) are local copies of KiCad
  stock footprints with edge silkscreen trimmed. KiCad's libraries are CC-BY-SA 4.0 with an exception for use in designs;
  see https://www.kicad.org/libraries/license/. The MX hot-swap footprint is drawn from the Kailh/HanElectricity datasheets.
- **Part datasheets** (Raytac, TI, Bourns, JST, Würth, Kailh, HanElectricity) were used for footprints and dimensions; none is included.
- **Adafruit nRF52 bootloader** (MIT): not included. You download it, as the README says.
