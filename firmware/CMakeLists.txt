# Deck-8 module: the LED chain driver (plain Zephyr) and the RGB battery guard (part of the ZMK app).
if(CONFIG_DECK8_LED_STRIP_CHAIN)
  zephyr_library()
  zephyr_library_sources(drivers/led_strip/led_strip_chain.c)
endif()

if(CONFIG_DECK8_RGB_BATTERY_GUARD)
  target_sources(app PRIVATE src/rgb_battery_guard.c)
endif()
