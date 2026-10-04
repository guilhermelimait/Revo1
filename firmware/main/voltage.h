#pragma once

#include "esp_err.h"

esp_err_t voltage_read(int *raw, int *adc_mv);

int voltage_estimated_percent(int millivolts);
