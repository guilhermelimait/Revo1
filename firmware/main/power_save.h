#pragma once

#include <stdbool.h>
#include <stdint.h>

#define DIM_AFTER_S 600
#define DIM_STEP_S 300
#define DIM_STEP_PERCENT 10
#define POWER_ACTIVE_PERCENT 40
#define POWER_SAVER_PERCENT 20
#define POWER_IDLE_PERCENT 10
#define POWER_DIM_AFTER_S 30
#define POWER_OFF_AFTER_S 300
#define POWER_FRAME_MS 200

static inline int screen_power_level(int brightness, bool dim, bool power_save,
                                     bool screensaver, int64_t idle_s)
{
    if (power_save) {
        if (idle_s >= POWER_OFF_AFTER_S) return 0;
        int cap = screensaver ? POWER_SAVER_PERCENT : POWER_ACTIVE_PERCENT;
        if (idle_s >= POWER_DIM_AFTER_S) cap = POWER_IDLE_PERCENT;
        return brightness < cap ? brightness : cap;
    }
    if (!dim || idle_s < DIM_AFTER_S) return brightness;
    const int64_t steps = 1 + (idle_s - DIM_AFTER_S) / DIM_STEP_S;
    const int64_t level = brightness - steps * DIM_STEP_PERCENT;
    return level > 0 ? (int)level : 0;
}

static inline int screensaver_frame_ms(int frame_ms, bool power_save)
{
    return power_save && frame_ms < POWER_FRAME_MS ? POWER_FRAME_MS : frame_ms;
}
