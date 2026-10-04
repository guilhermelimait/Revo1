#include "voltage.h"

#include <stdbool.h>

#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_adc/adc_oneshot.h"

static adc_oneshot_unit_handle_t adc;
static adc_cali_handle_t calibration;
static bool initialized;
static esp_err_t initialization_error;

static esp_err_t initialize_voltage(void)
{
    const adc_oneshot_unit_init_cfg_t unit = {.unit_id = ADC_UNIT_1};
    esp_err_t err = adc_oneshot_new_unit(&unit, &adc);
    if (err != ESP_OK) return err;
    const adc_oneshot_chan_cfg_t channel = {
        .atten = ADC_ATTEN_DB_12,
        .bitwidth = ADC_BITWIDTH_12,
    };
    err = adc_oneshot_config_channel(adc, ADC_CHANNEL_0, &channel);
    if (err != ESP_OK) return err;
    const adc_cali_curve_fitting_config_t curve = {
        .unit_id = ADC_UNIT_1,
        .chan = ADC_CHANNEL_0,
        .atten = ADC_ATTEN_DB_12,
        .bitwidth = ADC_BITWIDTH_12,
    };
    return adc_cali_create_scheme_curve_fitting(&curve, &calibration);
}

esp_err_t voltage_read(int *raw, int *adc_mv)
{
    if (!initialized) {
        initialization_error = initialize_voltage();
        initialized = true;
    }
    if (initialization_error != ESP_OK) return initialization_error;
    int total = 0;
    for (int sample = 0; sample < 16; ++sample) {
        int value;
        const esp_err_t err = adc_oneshot_read(adc, ADC_CHANNEL_0, &value);
        if (err != ESP_OK) return err;
        total += value;
    }
    const int average = (total + 8) / 16;
    int millivolts;
    const esp_err_t err = adc_cali_raw_to_voltage(calibration, average, &millivolts);
    if (err != ESP_OK) return err;
    *raw = average;
    *adc_mv = millivolts;
    return ESP_OK;
}

int voltage_estimated_percent(int millivolts)
{
    if (millivolts < 3000 || millivolts > 4250) return -1;
    static const struct { int mv, percent; } curve[] = {
        {3300, 0}, {3500, 10}, {3600, 20}, {3700, 40}, {3800, 60},
        {3900, 75}, {4000, 85}, {4100, 95}, {4200, 100},
    };
    if (millivolts <= curve[0].mv) return 0;
    for (unsigned i = 1; i < sizeof(curve) / sizeof(curve[0]); ++i) {
        if (millivolts <= curve[i].mv) {
            const int span = curve[i].mv - curve[i - 1].mv;
            return curve[i - 1].percent +
                   ((millivolts - curve[i - 1].mv) *
                    (curve[i].percent - curve[i - 1].percent) + span / 2) / span;
        }
    }
    return 100;
}
