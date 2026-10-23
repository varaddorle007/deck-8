# Suppresses duplicate unit-address warnings for power, clock, acl and flash-controller (as ZMK's nRF52 boards do)
list(APPEND EXTRA_DTC_FLAGS "-Wno-unique_unit_address_if_enabled")
