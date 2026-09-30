idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES esp_lcd_sh8601 lvgl esp_driver_gpio esp_driver_spi esp_driver_i2c
             esp_driver_ledc esp_timer
)

# The per-pixel renderer is the frame budget; unrolling hides the load-to-use
# stalls this in-order core suffers, and measures far better than -O2 alone.
target_compile_options(${COMPONENT_LIB} PRIVATE -O3 -funroll-loops)
