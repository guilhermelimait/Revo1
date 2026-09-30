idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES esp_lcd_sh8601 lvgl esp_driver_gpio esp_driver_spi esp_driver_i2c
             esp_driver_ledc esp_timer
)

# The per-pixel renderer is the frame budget; unrolling hides the load-to-use
# stalls this in-order core suffers, and measures far better than -O2 alone.
target_compile_options(${COMPONENT_LIB} PRIVATE -O3 -funroll-loops)

# One version for the app and the firmware: read it from the Python package,
# so the About page can tell whether the device is behind.
set(ROUNDSCREEN_VERSION_FILE "${CMAKE_CURRENT_LIST_DIR}/../../roundscreen/__init__.py")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${ROUNDSCREEN_VERSION_FILE}")
file(STRINGS "${ROUNDSCREEN_VERSION_FILE}" ROUNDSCREEN_VERSION_LINE REGEX "^__version__")
string(REGEX MATCH "[0-9]+\\.[0-9]+\\.[0-9]+" ROUNDSCREEN_VERSION "${ROUNDSCREEN_VERSION_LINE}")
if(NOT ROUNDSCREEN_VERSION)
    message(FATAL_ERROR "No __version__ in ${ROUNDSCREEN_VERSION_FILE}")
endif()
target_compile_definitions(${COMPONENT_LIB} PRIVATE ROUNDSCREEN_VERSION="${ROUNDSCREEN_VERSION}")
