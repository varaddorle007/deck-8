/*
 * Turn the RGB off on battery when the cell is too low for the SK6812s (CONFIG_DECK8_RGB_BATTERY_GUARD_MV).
 * Off USB, VLED is VSYS = VBAT, and the LEDs need about 3.7 V. Checked on every battery report (once a
 * minute) and whenever USB power comes or goes. It never turns the RGB back on by itself.
 */

#include <zephyr/device.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include <zmk/event_manager.h>
#include <zmk/events/battery_state_changed.h>
#include <zmk/events/usb_conn_state_changed.h>
#include <zmk/rgb_underglow.h>
#include <zmk/usb.h>

LOG_MODULE_REGISTER(deck8_rgb_guard, CONFIG_ZMK_LOG_LEVEL);

static const struct device *const battery = DEVICE_DT_GET(DT_CHOSEN(zmk_battery));

static int guard_listener(const zmk_event_t *eh) {
    struct sensor_value v;
    bool on = false;

    if (zmk_usb_is_powered() || !device_is_ready(battery)) {
        return ZMK_EV_EVENT_BUBBLE;
    }
    if (sensor_channel_get(battery, SENSOR_CHAN_GAUGE_VOLTAGE, &v) != 0) {
        return ZMK_EV_EVENT_BUBBLE;
    }
    int mv = v.val1 * 1000 + v.val2 / 1000;

    if (mv > 0 && mv < CONFIG_DECK8_RGB_BATTERY_GUARD_MV && zmk_rgb_underglow_get_state(&on) == 0 && on) {
        LOG_INF("battery %d mV: RGB off", mv);
        zmk_rgb_underglow_off();
    }
    return ZMK_EV_EVENT_BUBBLE;
}

ZMK_LISTENER(deck8_rgb_guard, guard_listener);
ZMK_SUBSCRIPTION(deck8_rgb_guard, zmk_battery_state_changed);
ZMK_SUBSCRIPTION(deck8_rgb_guard, zmk_usb_conn_state_changed);
