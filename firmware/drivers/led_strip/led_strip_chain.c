/*
 * Several LED strips driven as one (binding deck8,led-strip-chain).
 */

#define DT_DRV_COMPAT deck8_led_strip_chain

#include <errno.h>
#include <zephyr/device.h>
#include <zephyr/drivers/led_strip.h>
#include <zephyr/sys/util.h>

struct chain_config {
    const struct device *const *strips;
    const size_t *lengths;
    size_t count;
    size_t total;
};

static int chain_update_rgb(const struct device *dev, struct led_rgb *pixels, size_t num_pixels) {
    const struct chain_config *cfg = dev->config;
    size_t start = 0;
    int ret = 0;

    for (size_t i = 0; i < cfg->count && start < num_pixels; i++) {
        size_t n = MIN(cfg->lengths[i], num_pixels - start);
        int err = led_strip_update_rgb(cfg->strips[i], &pixels[start], n);

        if (err && !ret) {
            ret = err;
        }
        start += n;
    }
    return ret;
}

static size_t chain_length(const struct device *dev) {
    const struct chain_config *cfg = dev->config;

    return cfg->total;
}

static int chain_init(const struct device *dev) {
    const struct chain_config *cfg = dev->config;

    for (size_t i = 0; i < cfg->count; i++) {
        if (!device_is_ready(cfg->strips[i])) {
            return -ENODEV;
        }
    }
    return 0;
}

static const struct led_strip_driver_api chain_api = {
    .update_rgb = chain_update_rgb,
    .length = chain_length,
};

#define CHAIN_STRIP(node_id, prop, idx) DEVICE_DT_GET(DT_PHANDLE_BY_IDX(node_id, prop, idx)),
#define CHAIN_LENGTH(node_id, prop, idx) DT_PROP(DT_PHANDLE_BY_IDX(node_id, prop, idx), chain_length),
#define CHAIN_SUM(node_id, prop, idx) +DT_PROP(DT_PHANDLE_BY_IDX(node_id, prop, idx), chain_length)

#define CHAIN_DEFINE(inst)                                                                         \
    BUILD_ASSERT(DT_INST_PROP(inst, chain_length) ==                                               \
                     (0 DT_INST_FOREACH_PROP_ELEM(inst, strips, CHAIN_SUM)),                      \
                 "chain-length must equal the sum of the strips' chain-length");                  \
    static const struct device *const chain_strips_##inst[] = {                                    \
        DT_INST_FOREACH_PROP_ELEM(inst, strips, CHAIN_STRIP)};                                     \
    static const size_t chain_lengths_##inst[] = {                                                 \
        DT_INST_FOREACH_PROP_ELEM(inst, strips, CHAIN_LENGTH)};                                    \
    static const struct chain_config chain_config_##inst = {                                       \
        .strips = chain_strips_##inst,                                                             \
        .lengths = chain_lengths_##inst,                                                           \
        .count = ARRAY_SIZE(chain_strips_##inst),                                                  \
        .total = DT_INST_PROP(inst, chain_length),                                                 \
    };                                                                                             \
    DEVICE_DT_INST_DEFINE(inst, chain_init, NULL, NULL, &chain_config_##inst, POST_KERNEL,         \
                          CONFIG_LED_STRIP_INIT_PRIORITY, &chain_api);

DT_INST_FOREACH_STATUS_OKAY(CHAIN_DEFINE)
