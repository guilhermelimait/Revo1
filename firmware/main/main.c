#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "driver/ledc.h"
#include "driver/spi_master.h"
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#include "esp_err.h"
#include "esp_heap_caps.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_partition.h"
#include "esp_rom_crc.h"
#include "esp_timer.h"
#include "esp_random.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "lvgl.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "rom/tjpgd.h"
#include "esp_lcd_sh8601.h"
#include "freertos/semphr.h"
#include "wireless.h"
#include "power_save.h"
#include "voltage.h"

#define LCD_WIDTH 360
#define LCD_HEIGHT 360
#define LCD_CS 14
#define LCD_SCLK 13
#define LCD_D0 15
#define LCD_D1 16
#define LCD_D2 17
#define LCD_D3 18
#define LCD_RESET 21
#define LCD_BACKLIGHT 47
#define TOUCH_SDA 11
#define TOUCH_SCL 12
#define TOUCH_RESET 10
#define TOUCH_INT 9
#define TOUCH_ADDRESS 0x15
#define ENCODER_A 8
#define ENCODER_B 7
#define DRAW_BUFFER_ROWS 18
#define ROTATE_BUFFER_PIXELS (LCD_WIDTH * (DRAW_BUFFER_ROWS + 4))
#define SERIAL_LINE_MAX 96
#define LCD_PCLK_HZ (70 * 1000 * 1000)

#define SCREEN_CENTER (LCD_WIDTH / 2)
#define SCREEN_RADIUS (LCD_WIDTH / 2 - 1)

/* Concentric geometry of the dial, as radii from the screen centre: a light
   face covering the whole disc, a raised cap at its middle, and a shallow
   channel just inside the rim carrying the arc. */
#define DIAL_CAP_R 76
/* Screensaver clock: the time big in the middle, the date below. */
#define CLOCK_TIME_Y -8
#define CLOCK_AMPM_Y -76
#define CLOCK_DATE_Y 64
#define DIAL_ARC_R 164
#define DIAL_GROOVE 9
/* Half thickness repainted each frame: wider than the channel so the arc's
   halo tints the face around it and is still cleaned up next frame. */
#define DIAL_ARC_BAND 15

/* A power of two so angular wrap is a mask rather than a modulo. */
#define ARC_SEGMENTS 1024
#define ARC_MASK (ARC_SEGMENTS - 1)
#define BAND_OUTER (DIAL_ARC_R + DIAL_ARC_BAND)
#define BAND_INNER (DIAL_ARC_R - DIAL_ARC_BAND)
/* The band is walked pixel by pixel rather than sampled around the circle, so
   the arc has no gaps at its outer radius and no overdraw at its inner one.
   Distances are kept in quarter pixels to keep the edges smooth. */
#define ARC_SHADE_STEPS (DIAL_ARC_BAND * 4 + 1)
#define BAND_CAPACITY 40000
/* The gauge is the whole ring: it starts at 6 o'clock and runs clockwise all
   the way round, so at 100% the colour meets itself. A back button sits on
   the upper face, between the cap and the ring. */
#define GAUGE_START 768
#define GAUGE_SPAN ARC_SEGMENTS
#define GAUGE_BLEND_FROM (GAUGE_SPAN * 85 / 100)
/* Soft gradient: the tail starts this far up the ramp. Glowing tip: the body's
   ramp position, the tip's length in segments, and where the tip fades out. */
#define SOFT_FLOOR 217
#define GLOW_BODY 170
#define GLOW_TIP 96
#define GLOW_FADE_FROM (GAUGE_SPAN * 95 / 100)
#define FOOTER_Y (-118)
/* Tapping the back button goes back to the menu. */
#define FOOTER_HIT_W 30
#define FOOTER_HIT_H 30
#define BACK_ICON_SIZE 1.0f
#define ARC_TAIL 300
/* Scroll and zoom: each detent moves the comet a fixed number of segments
   (q8), and the head eases a quarter of the way there per frame. The PC app
   applies the same rule to the same ROT stream, so both come to rest on the
   same segment. revo1/dial.py holds the same constants. */
#define COMET_STEP_Q8 (32 << 8)
#define COMET_SNAP_Q8 (2 << 8)

#define MEDIA_MODE 5
#define MEDIA_TEXT_MAX 64
/* Play/pause fills the cap's centre; previous and next sit out on the face
   either side of it, and the track text takes the band below the cap. */
#define MEDIA_BUTTON_SPACING 114
#define MEDIA_PLAY_SIZE 1.9f
#define MEDIA_SKIP_SIZE 1.35f
#define MEDIA_HIT 30
#define MEDIA_TITLE_Y 98
#define MEDIA_ARTIST_Y 120
#define MEDIA_TIME_Y 52

/* The annulus spans about 360 rows; in 32-row strips that is 12 strips and at
   most 20 areas, comfortably inside LVGL's default 32-entry invalidation
   buffer. */
#define ARC_DIRTY_STRIP 32
#define DIRTY_MAX 24
#define ENCODER_PULSES_PER_DETENT 2
#define ENCODER_BOUNCE_REJECT_US 2000
#define ENCODER_DIRECTION_LOCKOUT_US 120000

#define MODE_COUNT 8
#define POMODORO_MODE 6
#define GAMES_MODE 7
#define ALL_SCREENS ((1u << MODE_COUNT) - 1)
/* Lines the app sends, apart from screensaver uploads, fit in this; the
   upload's data lines carry up to 3 KB of base64 and are handled apart. */
#define SERIAL_QUEUE_DEPTH 16
#define RX_LINE_MAX 4200
#define UPLOAD_CHUNK_MAX 3072

static const char *mode_names[MODE_COUNT] = {
    "VOLUME", "SCROLL", "BRIGHTNESS", "MIC", "ZOOM", "MEDIA", "POMODORO", "GAMES"
};
/* What the dial shows; mode_names stay the protocol's words. */
static const char *mode_titles[MODE_COUNT] = {
    "VOLUME", "SCROLL", "BRIGHTNESS", "MICROPHONE", "ZOOM", "MEDIA", "POMODORO", "GAMES"
};

/* Saturated accents; on an AMOLED the unlit pixels stay truly black, so
   additive glow over them reads as emitted light rather than grey haze. */
static const uint8_t mode_accents[MODE_COUNT][3] = {
    {0, 176, 255}, {124, 104, 255}, {255, 168, 40},
    {255, 64, 116}, {0, 226, 158}, {255, 116, 56}, {232, 58, 58},
    {150, 200, 30},
};

/* The screens the menu offers, chosen on the app's dashboard: bit n is
   mode n. The menu ring is split evenly between them. */
static uint8_t screen_mask = ALL_SCREENS;
/* Left/right swipes step between screens unless the app turns them off. */
static bool swipe_enabled = true;

static inline bool screen_enabled(int mode)
{
    return (screen_mask >> mode) & 1u;
}

static int screen_count(void)
{
    return __builtin_popcount(screen_mask);
}

/* The mode in menu slot `slot`, slots running clockwise from the top. */
static int screen_at(int slot)
{
    for (int mode = 0; mode < MODE_COUNT; ++mode) {
        if (screen_enabled(mode) && slot-- == 0) return mode;
    }
    return 0;
}

static int slot_of(int mode)
{
    if (!screen_enabled(mode)) return -1;
    int slot = 0;
    for (int other = 0; other < mode; ++other) {
        if (screen_enabled(other)) ++slot;
    }
    return slot;
}

/* The enabled screen `steps` slots on from `mode`, wrapping round. */
static int step_screen(int mode, int steps)
{
    const int count = screen_count();
    int slot = slot_of(mode);
    if (slot < 0) slot = 0;
    slot = ((slot + steps) % count + count) % count;
    return screen_at(slot);
}

/* Pomodoro: the app keeps the timer (and plays the chime); the knob shows it
   and counts the seconds down between updates, as it does for media. */
static int pomo_phase;
static int pomo_remaining = 25 * 60;
static int pomo_total = 25 * 60;
static bool pomo_running;
/* Mute state of the PC's speakers (Volume) and microphone (Mic), from MUTE. */
static bool volume_muted;
static bool mic_muted;
static int64_t pomo_stamp;
static int pomo_shown = -1;

/* Games run on the knob itself; the app only hears the result. The first is
   Whack-a-Mole: seven holes sit in the eight 45-degree slots round the face
   (the back button has the top one), the knob aims and a touch hits. */
#define WHACK_HOLES 7
#define WHACK_ROUND_US (30 * 1000000LL)
#define WHACK_RING_R 118
#define WHACK_ICON_SIZE 1.75f
/* Half the square repainted for one hole; it stays inside the arc's band. */
#define WHACK_BOX 30
#define GAME_TITLE_Y (-40)
/* The Games screen opens on a round card per game, centred on the dial; a tap
   on the card plays it. */
#define GAME_COUNT 1
#define CARD_R 100
#define CARD_ART_Y (-44)
#define CARD_ART_SIZE 1.8f
#define CARD_NAME_Y 8
#define CARD_BEST_Y 32
#define CARD_PLAY_Y 56
#define CARD_DOTS_Y 124
enum { GAME_LOBBY, GAME_PLAYING, GAME_OVER };
enum { MOLE_NONE, MOLE_PLAIN, MOLE_GOLD, MOLE_BOMB };
enum { FLASH_NONE, FLASH_HIT, FLASH_BOOM };
typedef struct {
    uint8_t kind;
    uint8_t flash;
    int64_t until;
    int64_t flash_until;
} whack_hole_t;
/* GAME_LOBBY is the card view; the other states are inside a game. */
static int game_state = GAME_LOBBY;
static int game_card;
static whack_hole_t whack_holes[WHACK_HOLES];
static int whack_cursor;
static int whack_score;
static int whack_best;
static bool whack_new_best;
static int64_t whack_start_us;
static int64_t whack_end_us;
static int64_t whack_over_us;
static int64_t whack_next_spawn;
static int whack_seconds_shown = -1;
/* The board without moles, so one hole can be repainted on its own. */
static uint16_t *game_backdrop;
static bool game_backdrop_ready;

/* Screen brightness in percent, from the app's settings. */
static int backlight_percent = 100;
/* When the knob is left alone the backlight fades: DIM_STEP_PERCENT less
   after DIM_AFTER_S, and again every DIM_STEP_S, until it is off. Any touch
   or turn brings it straight back. */
static bool dim_enabled = true;
static bool power_save_enabled;
static int backlight_applied = -1;

/* Local wall-clock time from the app (TIME), kept as an offset from the
   timer; unknown until the app has sent it since the knob started. */
static bool clock_valid;
static int64_t clock_offset_s;
static bool clock_24h = true;

/* Screensaver: pictures and clips the app converts to 360x360 JPEG frames
   and stores in the "media" partition. A 4 KB header lists the items; the
   data follows it. The header is written last, so an interrupted upload
   leaves no library rather than a broken one. */
#define MEDIA_MAGIC 0x314D5652u /* "RVM1" */
#define MEDIA_HEADER_BYTES 4096
#define MEDIA_MAX_ITEMS 250
#define MEDIA_FRAME_MAX (256 * 1024)

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t count;
    uint32_t data_bytes;
    uint32_t data_crc;
    uint32_t reserved[3];
} media_header_t;

typedef struct {
    uint32_t offset; /* from the start of the data, after the header */
    uint32_t bytes;
    uint16_t frames;
    uint16_t frame_ms;
    uint32_t reserved;
} media_entry_t;

static const esp_partition_t *media_partition;
static media_header_t media_header;
static media_entry_t *media_entries;
static volatile bool media_valid;
/* Set while the app is writing a new library; playback stays off meanwhile. */
static volatile bool media_busy;
static uint32_t upload_size;
static bool saver_enabled;
/* What the screensaver shows: the stored pictures, or the date and time. */
enum { SAVER_PICTURES, SAVER_CLOCK, SAVER_BOTH };
static int saver_kind = SAVER_PICTURES;
/* How the seconds ring around the screensaver clock is drawn. */
/* The animated styles come after "none" so stored numbers keep their meaning. */
enum { RING_DOTS, RING_BAR, RING_WAVE, RING_TICKS, RING_COMET, RING_NONE,
       RING_WALKER, RING_SNAKE, RING_SPARKLE, RING_ORBIT, RING_PULSE, RING_COUNT };
static int saver_ring = RING_DOTS;
/* The second the ring shows, or -1 before the clock has ticked. */
static int ring_second = -1;
/* The wiggly ring grows smoothly with a rippling tip: the time it was last
   drawn for (its fraction of a second places the tip), and when it is next
   redrawn. */
static int64_t ring_now_us;
static int64_t ring_next_us;
/* Set when the ring style changes, so the next draw clears the old one. */
static bool ring_wipe;
/* Set when the whole canvas under the ring was repainted (a new screensaver,
   a new picture frame or a new look), so the animated styles redraw every
   pixel once rather than just the parts that changed. */
static bool ring_full = true;
/* How many seconds behind the tip still ripple; the body before that is still. */
#define WAVE_HEAD_S 3.0f
/* What the running screensaver shows (one of the SAVER_ kinds). */
static int saver_shown;
static int64_t clock_second_shown = -1;
static lv_obj_t *clock_label;
static lv_obj_t *ampm_label;
/* Montserrat Medium at 96 px, digits and colon only (revo1_clock_96.c). */
LV_FONT_DECLARE(revo1_clock_96);
static lv_obj_t *date_label;
/* The screensaver clock's look (SAVERLOOK): the colour of the time, the face
   behind it when only the clock shows, and whether a picture is darkened
   behind the time. The date, AM/PM and the ring's track are mixed from them. */
static uint8_t clock_ink[3] = {0xF2, 0xF2, 0xF5};
static uint8_t clock_bg[3] = {0, 0, 0};
static uint8_t clock_track[3] = {0x30, 0x30, 0x31};
static bool clock_shade = true;
/* How a level ring is coloured along its length; the order is the number the
   PC sends as the third field of STYLE. */
enum { BAR_GLOW, BAR_FADE, BAR_SOFT, BAR_SOLID, BAR_STYLE_COUNT };
static int bar_style = BAR_GLOW;
static int saver_idle_s = 300;
static int saver_interval_s = 30;
static bool saver_active;
/* The app answers every HELLO with APP. Without any line from it for a few
   seconds the knob shows that it is not connected, in place of every screen.
   It starts out that way, until the app is first heard. */
#define APP_TIMEOUT_MS 3500
static volatile uint32_t last_host_ms;
static volatile bool host_seen;
static bool app_offline = true;
static bool touch_swallowed;
static int64_t last_input_us;
static int saver_item = -1;
static int saver_frame;
static uint32_t saver_offset;
static int64_t saver_item_start;
static int64_t saver_next_frame;
static uint8_t *frame_jpeg;
static uint16_t *frame_pixels;
static void stop_saver(void);
static void open_menu(void);
static void apply_backlight(void);

/* Interface style chosen in the PC app: one colour for every bar instead of
   the per-mode accents, and the size of the big number. */
static bool custom_accent;
static uint8_t custom_rgb[3];
static const lv_font_t *number_font = &lv_font_montserrat_32;

static const uint8_t *accent_of(int mode)
{
    return custom_accent ? custom_rgb : mode_accents[mode];
}

/* Bayer 4x4 thresholds, offset so the mean perturbation is zero and dithering
   neither brightens nor darkens the image. */
static const int8_t bayer4[16] = {
    -8, 0, -6, 2, 4, -4, 6, -2, -5, 3, -7, 1, 7, -1, 5, -3,
};

static const sh8601_lcd_init_cmd_t lcd_init_cmds[] = {
#include "panel_init.inc"
};

static esp_lcd_panel_handle_t panel;
static i2c_master_dev_handle_t touch_device;
static QueueHandle_t serial_queue;
static QueueHandle_t encoder_queue;
static SemaphoreHandle_t lvgl_mutex;
static lv_disp_drv_t display_driver;
static lv_obj_t *canvas;
static lv_obj_t *title_label;
static lv_obj_t *value_label;
static lv_obj_t *artist_label;
static lv_obj_t *time_label;
static lv_obj_t *battery_label;
static int battery_mv = -1;
static int battery_percent = -1;
static lv_color_t *canvas_pixels;
static lv_color_t *draw_buffer_a;
static lv_color_t *draw_buffer_b;
static lv_color_t *rotate_buffer_a;
static lv_color_t *rotate_buffer_b;
static uint16_t touch_x;
static uint16_t touch_y;
static int selected_mode;
/* The option the knob is pointing at while the menu is open; a tap confirms it. */
static int menu_cursor;
static int selected_value = 50;
static int orientation;
static bool show_menu = true;
static bool touch_active;
static uint16_t touch_start_x;
static uint16_t touch_start_y;
static esp_err_t touch_error;
/* Set once the PC has sent a STATE since boot; until then the firmware asks
   for one, so a restarted knob gets its settings back from a connected app. */
static bool state_received;
/* One line at a time reaches the parsers, from USB or a wireless link. */
static SemaphoreHandle_t dispatch_lock;

/* Sends a protocol line to the PC: over USB, and sealed over any open
   wireless session. */
static void host_printf(const char *format, ...)
{
    char text[256];
    va_list arguments;
    va_start(arguments, format);
    int length = vsnprintf(text, sizeof(text), format, arguments);
    va_end(arguments);
    if (length < 0) return;
    if (length >= (int)sizeof(text)) length = sizeof(text) - 1;
    fputs(text, stdout);
    wireless_send(text, (size_t)length);
}

static const lv_font_t *font_for_size(int size)
{
    switch (size) {
    case 24: return &lv_font_montserrat_24;
    case 32: return &lv_font_montserrat_32;
    case 40: return &lv_font_montserrat_40;
    case 48: return &lv_font_montserrat_48;
    default: return NULL;
    }
}

/* The view survives a restart: mode, orientation and style live in NVS, so the
   knob comes back the way it was even before the PC app is running. */
#define SETTINGS_NAMESPACE "revo1"
#define STANDARD_ACCENT 0xFFFFFFFFu

typedef struct {
    uint8_t mode;
    uint8_t orientation;
    uint8_t number_size;
    uint32_t accent;
    uint8_t screens;
    uint8_t backlight;
    uint8_t saver;
    uint16_t idle_s;
    uint16_t interval_s;
    uint8_t swipe;
    uint8_t saver_kind;
    uint8_t dim;
    uint8_t ring;
    uint8_t shade;
    uint32_t ink;
    uint32_t face;
    uint8_t bar;
    uint8_t power_save;
} stored_settings_t;

static uint32_t rgb_word(const uint8_t rgb[3])
{
    return (uint32_t)rgb[0] << 16 | (uint32_t)rgb[1] << 8 | rgb[2];
}

static void set_rgb(uint8_t rgb[3], uint32_t word)
{
    rgb[0] = (uint8_t)(word >> 16);
    rgb[1] = (uint8_t)(word >> 8);
    rgb[2] = (uint8_t)word;
}

static bool settings_ready;
static stored_settings_t saved_settings;

static stored_settings_t current_settings(void)
{
    stored_settings_t settings = {
        .mode = (uint8_t)selected_mode,
        .orientation = (uint8_t)(orientation / 90),
        .number_size = 32,
        .accent = custom_accent ? ((uint32_t)custom_rgb[0] << 16 |
                                   (uint32_t)custom_rgb[1] << 8 | custom_rgb[2])
                                : STANDARD_ACCENT,
        .screens = screen_mask,
        .backlight = (uint8_t)backlight_percent,
        .saver = saver_enabled,
        .idle_s = (uint16_t)saver_idle_s,
        .interval_s = (uint16_t)saver_interval_s,
        .swipe = swipe_enabled,
        .saver_kind = (uint8_t)saver_kind,
        .dim = dim_enabled,
        .ring = (uint8_t)saver_ring,
        .shade = clock_shade,
        .ink = rgb_word(clock_ink),
        .face = rgb_word(clock_bg),
        .bar = (uint8_t)bar_style,
        .power_save = power_save_enabled,
    };
    static const int sizes[] = {24, 32, 40, 48};
    for (size_t index = 0; index < sizeof(sizes) / sizeof(sizes[0]); index++) {
        if (font_for_size(sizes[index]) == number_font) settings.number_size = (uint8_t)sizes[index];
    }
    return settings;
}

static bool same_settings(const stored_settings_t *a, const stored_settings_t *b)
{
    return a->mode == b->mode && a->orientation == b->orientation &&
           a->number_size == b->number_size && a->accent == b->accent &&
           a->screens == b->screens && a->backlight == b->backlight &&
           a->saver == b->saver && a->idle_s == b->idle_s &&
           a->interval_s == b->interval_s && a->swipe == b->swipe &&
           a->saver_kind == b->saver_kind && a->dim == b->dim &&
           a->ring == b->ring && a->shade == b->shade && a->ink == b->ink &&
           a->face == b->face && a->bar == b->bar && a->power_save == b->power_save;
}

static void load_settings(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        err = nvs_flash_init();
    }
    if (err != ESP_OK) return;
    settings_ready = true;
    nvs_handle_t handle;
    if (nvs_open(SETTINGS_NAMESPACE, NVS_READONLY, &handle) == ESP_OK) {
        uint8_t byte;
        uint16_t word;
        uint32_t accent;
        if (nvs_get_u8(handle, "screens", &byte) == ESP_OK && byte && byte <= ALL_SCREENS) {
            screen_mask = byte;
        }
        if (nvs_get_u8(handle, "mode", &byte) == ESP_OK && byte < MODE_COUNT &&
            screen_enabled(byte)) {
            selected_mode = byte;
            show_menu = false;
        } else {
            selected_mode = screen_at(0);
        }
        menu_cursor = selected_mode;
        if (nvs_get_u8(handle, "orient", &byte) == ESP_OK && byte < 4) orientation = byte * 90;
        if (nvs_get_u8(handle, "numsize", &byte) == ESP_OK && font_for_size(byte)) {
            number_font = font_for_size(byte);
        }
        if (nvs_get_u32(handle, "accent", &accent) == ESP_OK && accent <= 0xFFFFFF) {
            custom_accent = true;
            custom_rgb[0] = (uint8_t)(accent >> 16);
            custom_rgb[1] = (uint8_t)(accent >> 8);
            custom_rgb[2] = (uint8_t)accent;
        }
        if (nvs_get_u8(handle, "light", &byte) == ESP_OK && byte >= 5 && byte <= 100) {
            backlight_percent = byte;
        }
        if (nvs_get_u8(handle, "saver", &byte) == ESP_OK) saver_enabled = byte != 0;
        if (nvs_get_u16(handle, "idle", &word) == ESP_OK && word >= 10) saver_idle_s = word;
        if (nvs_get_u16(handle, "every", &word) == ESP_OK && word >= 1) saver_interval_s = word;
        if (nvs_get_u8(handle, "swipe", &byte) == ESP_OK) swipe_enabled = byte != 0;
        if (nvs_get_u8(handle, "show", &byte) == ESP_OK && byte <= SAVER_BOTH) saver_kind = byte;
        if (nvs_get_u8(handle, "dim", &byte) == ESP_OK) dim_enabled = byte != 0;
        if (nvs_get_u8(handle, "power_save", &byte) == ESP_OK) power_save_enabled = byte != 0;
        if (nvs_get_u8(handle, "ring", &byte) == ESP_OK && byte < RING_COUNT) saver_ring = byte;
        if (nvs_get_u8(handle, "shade", &byte) == ESP_OK) clock_shade = byte != 0;
        if (nvs_get_u32(handle, "ink", &accent) == ESP_OK && accent <= 0xFFFFFF) {
            set_rgb(clock_ink, accent);
        }
        if (nvs_get_u32(handle, "face", &accent) == ESP_OK && accent <= 0xFFFFFF) {
            set_rgb(clock_bg, accent);
        }
        if (nvs_get_u16(handle, "whack", &word) == ESP_OK) whack_best = word;
        if (nvs_get_u8(handle, "bar", &byte) == ESP_OK && byte < BAR_STYLE_COUNT) bar_style = byte;
        nvs_close(handle);
    }
    saved_settings = current_settings();
}

/* Called after every change; flash is only written when something differs. */
static void save_settings(void)
{
    if (!settings_ready) return;
    const stored_settings_t settings = current_settings();
    if (same_settings(&settings, &saved_settings)) return;
    nvs_handle_t handle;
    if (nvs_open(SETTINGS_NAMESPACE, NVS_READWRITE, &handle) != ESP_OK) return;
    const bool ok = nvs_set_u8(handle, "mode", settings.mode) == ESP_OK &&
                    nvs_set_u8(handle, "orient", settings.orientation) == ESP_OK &&
                    nvs_set_u8(handle, "numsize", settings.number_size) == ESP_OK &&
                    nvs_set_u32(handle, "accent", settings.accent) == ESP_OK &&
                    nvs_set_u8(handle, "screens", settings.screens) == ESP_OK &&
                    nvs_set_u8(handle, "light", settings.backlight) == ESP_OK &&
                    nvs_set_u8(handle, "saver", settings.saver) == ESP_OK &&
                    nvs_set_u16(handle, "idle", settings.idle_s) == ESP_OK &&
                    nvs_set_u16(handle, "every", settings.interval_s) == ESP_OK &&
                    nvs_set_u8(handle, "swipe", settings.swipe) == ESP_OK &&
                    nvs_set_u8(handle, "show", settings.saver_kind) == ESP_OK &&
                    nvs_set_u8(handle, "dim", settings.dim) == ESP_OK &&
                    nvs_set_u8(handle, "power_save", settings.power_save) == ESP_OK &&
                    nvs_set_u8(handle, "ring", settings.ring) == ESP_OK &&
                    nvs_set_u8(handle, "shade", settings.shade) == ESP_OK &&
                    nvs_set_u32(handle, "ink", settings.ink) == ESP_OK &&
                    nvs_set_u32(handle, "face", settings.face) == ESP_OK &&
                    nvs_set_u8(handle, "bar", settings.bar) == ESP_OK &&
                    nvs_commit(handle) == ESP_OK;
    nvs_close(handle);
    if (ok) saved_settings = settings;
}
static int encoder_lines[2] = {0, 1};
static volatile int64_t encoder_line_edge[2];
static volatile int64_t encoder_last_step;
static volatile int encoder_last_direction;
static int encoder_accumulator;
static uint16_t row_half_width[LCD_HEIGHT];
static uint8_t row_edge_coverage[LCD_HEIGHT];
static int16_t arc_cos[ARC_SEGMENTS];
static int16_t arc_sin[ARC_SEGMENTS];
/* Radial profile of the arc: a solid core inside the groove and a softer
   additive bloom reaching out over the bezel. */
static uint8_t arc_core[ARC_SHADE_STEPS];
static uint8_t arc_glow[ARC_SHADE_STEPS];
static uint8_t arc_level[ARC_SEGMENTS];
static uint8_t arc_ramp[ARC_SEGMENTS];
static uint16_t arc_head_colour;
/* Every pixel of the annulus, with the segment and radial distance it belongs
   to. The bezel beneath never changes, so it is sampled once and composited
   against each frame. */
static uint32_t *band_pixel;
static uint16_t *band_segment;
/* Signed distance of each band pixel from the groove centre, in 1/64 pixel. */
static int16_t *band_offset;
static uint8_t *band_distance;
static uint16_t *band_backdrop;
static int band_count;
static uint8_t ramp_r[256];
static uint8_t ramp_g[256];
static uint8_t ramp_b[256];
static int arc_head = -1;
static int32_t arc_position = GAUGE_START << 8;
static int32_t arc_target = GAUGE_START << 8;
static int arc_direction = 1;
/* The displayed value eases toward the real one, so a knob turn reads as the
   arc sweeping rather than jumping. */
static int32_t dial_value_q8;
static int media_head_shown = -1;
static lv_area_t dirty_areas[DIRTY_MAX];
static int dirty_count;
static bool force_full_redraw = true;
/* Playback mirrored from the PC: the position is interpolated locally between
   the once-a-second updates so the progress ring advances smoothly. */
static int media_status;
static int media_position;
static int media_duration;
static int64_t media_stamp;
static char media_title[MEDIA_TEXT_MAX];
static char media_artist[MEDIA_TEXT_MAX];

static bool panel_color_done(esp_lcd_panel_io_handle_t io,
                             esp_lcd_panel_io_event_data_t *event_data,
                             void *user_context)
{
    lv_disp_flush_ready((lv_disp_drv_t *)user_context);
    return false;
}

static void panel_flush(lv_disp_drv_t *driver, const lv_area_t *area,
                        lv_color_t *pixels)
{
    const int width = area->x2 - area->x1 + 1;
    const int height = area->y2 - area->y1 + 1;
    int x = area->x1;
    int y = area->y1;
    int output_width = width;
    int output_height = height;
    lv_color_t *output = pixels;

    if (orientation != 0) {
        output = pixels == draw_buffer_a ? rotate_buffer_a : rotate_buffer_b;
        if (orientation == 90) {
            x = LCD_WIDTH - 1 - area->y2;
            y = area->x1;
            output_width = height;
            output_height = width;
        } else if (orientation == 180) {
            x = LCD_WIDTH - 1 - area->x2;
            y = LCD_HEIGHT - 1 - area->y2;
        } else {
            x = area->y1;
            y = LCD_HEIGHT - 1 - area->x2;
            output_width = height;
            output_height = width;
        }

        for (int source_y = 0; source_y < height; ++source_y) {
            for (int source_x = 0; source_x < width; ++source_x) {
                int target_x;
                int target_y;
                if (orientation == 90) {
                    target_x = height - 1 - source_y;
                    target_y = source_x;
                } else if (orientation == 180) {
                    target_x = width - 1 - source_x;
                    target_y = height - 1 - source_y;
                } else {
                    target_x = source_y;
                    target_y = width - 1 - source_x;
                }
                output[target_y * output_width + target_x] =
                    pixels[source_y * width + source_x];
            }
        }
    }

    ESP_ERROR_CHECK(esp_lcd_panel_draw_bitmap(
        panel, x, y, x + output_width, y + output_height, output));
}

static void display_rounder(lv_disp_drv_t *driver, lv_area_t *area)
{
    area->x1 = (area->x1 >> 1) << 1;
    area->y1 = (area->y1 >> 1) << 1;
    area->x2 = ((area->x2 >> 1) << 1) + 1;
    area->y2 = ((area->y2 >> 1) << 1) + 1;
    if (area->x2 >= LCD_WIDTH) area->x2 = LCD_WIDTH - 1;
    if (area->y2 >= LCD_HEIGHT) area->y2 = LCD_HEIGHT - 1;
}

static void tick_lvgl(void *argument)
{
    lv_tick_inc(2);
}

static void lvgl_task(void *argument)
{
    for (;;) {
        xSemaphoreTake(lvgl_mutex, portMAX_DELAY);
        lv_timer_handler();
        xSemaphoreGive(lvgl_mutex);
        vTaskDelay(1);
    }
}

/* The panel expects big-endian pixels and LV_COLOR_16_SWAP stores them that
   way, so colours are mixed in native order and byte-swapped once, here. */
static inline uint16_t pack_pixel(int r, int g, int b)
{
    const uint16_t value = (uint16_t)(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
    return (uint16_t)((value >> 8) | (value << 8));
}

static inline int clamp_channel(int value)
{
    if (value < 0) return 0;
    if (value > 255) return 255;
    return value;
}

static void build_screen_tables(void)
{
    for (int y = 0; y < LCD_HEIGHT; ++y) {
        const int dy = y - SCREEN_CENTER;
        const float squared = (float)SCREEN_RADIUS * SCREEN_RADIUS - (float)dy * dy;
        if (squared <= 0.0f) {
            row_half_width[y] = 0;
            row_edge_coverage[y] = 0;
            continue;
        }
        const float exact = sqrtf(squared);
        row_half_width[y] = (uint16_t)exact;
        row_edge_coverage[y] = (uint8_t)((exact - (float)row_half_width[y]) * 255.0f);
    }
    for (int i = 0; i < ARC_SEGMENTS; ++i) {
        const float angle = (float)i * (6.28318531f / (float)ARC_SEGMENTS);
        arc_cos[i] = (int16_t)lroundf(cosf(angle) * 32767.0f);
        arc_sin[i] = (int16_t)lroundf(sinf(angle) * 32767.0f);
    }
    for (int i = 0; i < ARC_SHADE_STEPS; ++i) {
        const float distance = (float)i * 0.25f;
        float core = ((float)DIAL_GROOVE - distance) / 3.0f;
        if (core > 1.0f) core = 1.0f;
        if (core < 0.0f) core = 0.0f;
        arc_core[i] = (uint8_t)(core * 255.0f);
        const float fade = 1.0f - distance / (float)DIAL_ARC_BAND;
        arc_glow[i] = (uint8_t)(fade * fade * 255.0f);
    }
}

/* Walks the annulus once and records, for every pixel in it, which segment of
   the sweep it belongs to and how far it sits from the groove centre. */
static void build_arc_band(void)
{
    band_count = 0;
    for (int y = SCREEN_CENTER - BAND_OUTER; y <= SCREEN_CENTER + BAND_OUTER; ++y) {
        for (int x = SCREEN_CENTER - BAND_OUTER; x <= SCREEN_CENTER + BAND_OUTER; ++x) {
            const float dx = (float)(x - SCREEN_CENTER);
            const float dy = (float)(y - SCREEN_CENTER);
            const float offset = sqrtf(dx * dx + dy * dy) - (float)DIAL_ARC_R;
            if (fabsf(offset) > (float)DIAL_ARC_BAND) continue;
            if (band_count >= BAND_CAPACITY) continue;

            float angle = atan2f(-dy, dx);
            if (angle < 0.0f) angle += 6.28318531f;
            const int segment =
                (int)lroundf(angle * ((float)ARC_SEGMENTS / 6.28318531f)) & ARC_MASK;
            int quarters = (int)lroundf(fabsf(offset) * 4.0f);
            if (quarters > ARC_SHADE_STEPS - 1) quarters = ARC_SHADE_STEPS - 1;

            band_pixel[band_count] = (uint32_t)(y * LCD_WIDTH + x);
            band_segment[band_count] = (uint16_t)segment;
            band_offset[band_count] = (int16_t)lroundf(offset * 64.0f);
            band_distance[band_count] = (uint8_t)quarters;
            ++band_count;
        }
    }
}

static inline bool segment_in_gauge(int segment)
{
    return ((GAUGE_START - segment) & ARC_MASK) <= GAUGE_SPAN;
}

/* The menu ring is one segment per enabled screen, centred on the same
   sectors the touch handler uses, with a short gap between neighbours.
   Returns the slot a segment belongs to, or -1 when it falls in a gap. */
#define MENU_SEGMENT_HALF 456
static int menu_sector_of(int segment)
{
    const int count = screen_count();
    const int whole = count * 1024;
    const int clockwise = (256 - segment) & ARC_MASK;
    const int sector = ((clockwise * count + 512) / 1024) % count;
    int offset = clockwise * count - sector * 1024;
    if (offset > whole / 2) offset -= whole;
    if (offset < -whole / 2) offset += whole;
    return (offset >= -MENU_SEGMENT_HALF && offset <= MENU_SEGMENT_HALF) ? sector : -1;
}

static inline bool segment_on_track(int segment)
{
    return show_menu ? menu_sector_of(segment) >= 0 : segment_in_gauge(segment);
}

static inline bool mode_is_level(int mode)
{
    return mode == 0 || mode == 2 || mode == 3;
}

static inline bool mode_can_mute(int mode)
{
    return mode == 0 || mode == 3;
}

static inline bool mode_muted(int mode)
{
    return (mode == 0 && volume_muted) || (mode == 3 && mic_muted);
}

static void mark_dirty(int x1, int y1, int x2, int y2)
{
    if (dirty_count >= DIRTY_MAX) return;
    if (x1 < 0) x1 = 0;
    if (y1 < 0) y1 = 0;
    if (x2 > LCD_WIDTH - 1) x2 = LCD_WIDTH - 1;
    if (y2 > LCD_HEIGHT - 1) y2 = LCD_HEIGHT - 1;
    if (x1 > x2 || y1 > y2) return;
    dirty_areas[dirty_count].x1 = (lv_coord_t)x1;
    dirty_areas[dirty_count].y1 = (lv_coord_t)y1;
    dirty_areas[dirty_count].x2 = (lv_coord_t)x2;
    dirty_areas[dirty_count].y2 = (lv_coord_t)y2;
    ++dirty_count;
}

/* The arc lives in a thin annulus, so its bounding box would be almost the
   whole screen. It is invalidated as horizontal strips that follow the ring's
   curve: one span per strip across the top and bottom, and a left and right
   span through the middle where the face sits between them. Straight bands
   along the four sides are not enough, because at the diagonals the ring
   curves inside the square they enclose. Strip count stays well under LVGL's
   invalidation buffer so it never falls back to a full-screen refresh. */
static void mark_ring_dirty(int outer, int inner)
{
    for (int top = -outer; top <= outer; top += ARC_DIRTY_STRIP) {
        int bottom = top + ARC_DIRTY_STRIP - 1;
        if (bottom > outer) bottom = outer;

        /* Widest outer extent is at the row nearest the centre line; the
           narrowest inner extent is at the row furthest from it. */
        const int near = (top <= 0 && bottom >= 0) ? 0 : (abs(top) < abs(bottom) ? abs(top) : abs(bottom));
        const int far = abs(top) > abs(bottom) ? abs(top) : abs(bottom);
        const int span = (int)ceilf(sqrtf((float)(outer * outer - near * near)));

        if (far >= inner) {
            mark_dirty(SCREEN_CENTER - span, SCREEN_CENTER + top,
                       SCREEN_CENTER + span, SCREEN_CENTER + bottom);
            continue;
        }
        const int hole = (int)floorf(sqrtf((float)(inner * inner - far * far)));
        mark_dirty(SCREEN_CENTER - span, SCREEN_CENTER + top,
                   SCREEN_CENTER - hole, SCREEN_CENTER + bottom);
        mark_dirty(SCREEN_CENTER + hole, SCREEN_CENTER + top,
                   SCREEN_CENTER + span, SCREEN_CENTER + bottom);
    }
}

static void mark_arc_dirty(void)
{
    mark_ring_dirty(BAND_OUTER + 1, BAND_INNER - 1);
}

/* One light source, high and to the left, so every surface is shaded
   consistently instead of being outlined. */
static inline int dial_light(int dx, int dy)
{
    return 128 - ((dx + dy) * 104) / (2 * SCREEN_RADIUS);
}

/* How much a point faces away from that light, used for drop shadows. */
static inline int dial_shadow_bias(int dx, int dy)
{
    return 128 + ((dx + dy) * 127) / (2 * SCREEN_RADIUS);
}

/* Everything that does not move. The whole disc is the light face; the arc
   runs in a shallow channel cut into it just inside the rim, so no screen area
   is spent on a dark bezel. A raised cap sits at the middle. Rendered only
   when the view changes, which is what makes the per-frame arc repaint
   affordable. */
static void render_dial_chrome(void)
{
    uint16_t *pixels = (uint16_t *)canvas_pixels;

    for (int y = 0; y < LCD_HEIGHT; ++y) {
        uint16_t *row = pixels + (size_t)y * LCD_WIDTH;
        const int dy = y - SCREEN_CENTER;
        const int half = row_half_width[y];
        const int first = SCREEN_CENTER - half;
        const int last = SCREEN_CENTER + half;
        for (int x = 0; x < first; ++x) row[x] = 0;
        for (int x = last + 1; x < LCD_WIDTH; ++x) row[x] = 0;
        if (half == 0) continue;

        const int8_t *dither = &bayer4[(y & 3) << 2];
        const int dy2 = dy * dy;
        for (int x = first; x <= last; ++x) {
            const int dx = x - SCREEN_CENTER;
            const float radius = sqrtf((float)(dx * dx + dy2));
            const int lit = dial_light(dx, dy);
            const float bias = (float)dial_shadow_bias(dx, dy) / 255.0f;

            float face = 212.0f + (float)(lit * 34) / 255.0f +
                         ((float)SCREEN_RADIUS - radius) * 12.0f / (float)SCREEN_RADIUS;

            const float cap = radius - (float)DIAL_CAP_R;
            if (cap < 0.0f) {
                face += 8.0f * (-cap > 1.0f ? 1.0f : -cap);
            } else if (cap < 12.0f) {
                const float fade = 1.0f - cap / 12.0f;
                face -= fade * fade * 16.0f * bias;
            }

            /* The channel: a flat floor with soft walls. Light catches the far
               wall of a recess and the near wall falls into shadow. */
            const float groove = radius - (float)DIAL_ARC_R;
            const float reach = (float)DIAL_GROOVE - fabsf(groove);
            if (reach > 0.0f) {
                const float wall = reach / 2.5f;
                face -= (wall > 1.0f ? 1.0f : wall) * 30.0f;
                if (groove > 0.0f) {
                    const float near = 1.0f - groove / (float)DIAL_GROOVE;
                    face -= near * near * 10.0f * bias;
                }
            }

            /* The rim rolls away from the viewer. */
            const float rim = (radius - ((float)SCREEN_RADIUS - 4.0f)) / 4.0f;
            if (rim > 0.0f) face -= (rim > 1.0f ? 1.0f : rim) * (rim > 1.0f ? 1.0f : rim) * 26.0f;

            const int value = (int)face;
            const int noise = dither[x & 3];
            int r = clamp_channel(value + noise);
            int g = clamp_channel(value - 3 + noise);
            int b = clamp_channel(value - 1 + noise);

            if (x == first || x == last) {
                const int coverage = row_edge_coverage[y];
                r = r * coverage >> 8;
                g = g * coverage >> 8;
                b = b * coverage >> 8;
            }
            row[x] = pack_pixel(r, g, b);
        }
    }
}

/* A faint etched line along the whole sweep, so the unfilled part of the
   gauge still reads as a track rather than an empty channel. */
static void draw_gauge_track(void)
{
    uint16_t *pixels = (uint16_t *)canvas_pixels;

    for (int i = 0; i < band_count; ++i) {
        const int quarters = band_distance[i];
        if (quarters > 8 || !segment_on_track(band_segment[i])) continue;
        uint16_t *target = &pixels[band_pixel[i]];
        const uint16_t native = (uint16_t)((*target >> 8) | (*target << 8));
        const int etch = quarters <= 4 ? 16 : 8;
        const int r = clamp_channel(((native >> 8) & 0xF8) - etch);
        const int g = clamp_channel(((native >> 3) & 0xFC) - etch);
        const int b = clamp_channel(((native << 3) & 0xF8) - etch + 2);
        *target = pack_pixel(r, g, b);
    }
}

static void capture_arc_backdrop(void)
{
    const uint16_t *pixels = (const uint16_t *)canvas_pixels;

    for (int i = 0; i < band_count; ++i) {
        const uint16_t stored = pixels[band_pixel[i]];
        band_backdrop[i] = (uint16_t)((stored >> 8) | (stored << 8));
    }
}

/* Gives the arc direction: a deeper tail that brightens into the full accent
   at the live end, the red-into-amber sweep of a sculpted dial. */
static void build_arc_ramp(const uint8_t *accent)
{
    const int tail_r = accent[0] * 150 / 255;
    const int tail_g = accent[1] * 90 / 255;
    const int tail_b = accent[2] * 70 / 255;

    for (int s = 0; s < 256; ++s) {
        ramp_r[s] = (uint8_t)(tail_r + ((accent[0] - tail_r) * s) / 255);
        ramp_g[s] = (uint8_t)(tail_g + ((accent[1] - tail_g) * s) / 255);
        ramp_b[s] = (uint8_t)(tail_b + ((accent[2] - tail_b) * s) / 255);
    }
    /* A near-white notch reads clearly inside the coloured channel. */
    arc_head_colour = pack_pixel(255, 252, 244);
}

/* One pass over the annulus: the arc, its bloom, and the bright tick at the
   live end that makes the dial look like it is pointing at a value. */
static void draw_arc(void)
{
    uint16_t *pixels = (uint16_t *)canvas_pixels;
    const uint16_t head_colour = arc_head_colour;
    const int head_reach = (DIAL_GROOVE - 1) * 4;

    for (int i = 0; i < band_count; ++i) {
        const int segment = band_segment[i];
        const int level = arc_level[segment];
        const int distance = band_distance[i];
        uint16_t *target = &pixels[band_pixel[i]];

        if (arc_head >= 0 && distance <= head_reach) {
            const int delta = ((segment - arc_head + ARC_SEGMENTS + ARC_SEGMENTS / 2)
                               & ARC_MASK) - ARC_SEGMENTS / 2;
            if (delta >= -1 && delta <= 1) {
                *target = head_colour;
                continue;
            }
        }

        const uint16_t native = band_backdrop[i];
        int r = (native >> 8) & 0xF8;
        int g = (native >> 3) & 0xFC;
        int b = (native << 3) & 0xF8;

        if (level) {
            const int shade = arc_ramp[segment];
            const int cr = ramp_r[shade];
            const int cg = ramp_g[shade];
            const int cb = ramp_b[shade];
            const int core = (arc_core[distance] * level) >> 8;
            if (core) {
                r += ((cr - r) * core) >> 8;
                g += ((cg - g) * core) >> 8;
                b += ((cb - b) * core) >> 8;
            }
            const int glow = (arc_glow[distance] * level) >> 8;
            if (glow) {
                /* On a light face additive bloom would only wash out to white,
                   so the halo is a soft tint of the arc colour instead. */
                const int tint = (glow * 90) >> 8;
                r += ((cr - r) * tint) >> 8;
                g += ((cg - g) * tint) >> 8;
                b += ((cb - b) * tint) >> 8;
            }
        }
        *target = pack_pixel(r, g, b);
    }
}

/* The ramp position (0 deep tail .. 255 full accent) of the segment `d` steps
   into a gauge filled `filled` segments, for the chosen bar style. Every style
   closes on one even colour at 100%, so a full ring shows no seam. */
static int level_shade(int d, int filled)
{
    if (bar_style == BAR_SOLID) return 255;
    if (bar_style == BAR_GLOW) {
        /* An even body; only the last GLOW_TIP segments brighten, and the tip
           fades out over the last few percent so a full ring is plain. */
        int tip = d > filled - GLOW_TIP ? ((d - (filled - GLOW_TIP)) * 255) / GLOW_TIP : 0;
        if (filled > GLOW_FADE_FROM) {
            tip = (tip * (GAUGE_SPAN - filled)) / (GAUGE_SPAN - GLOW_FADE_FROM);
        }
        return GLOW_BODY + ((255 - GLOW_BODY) * tip) / 255;
    }
    int shade = filled > 0 ? (d * 255) / filled : 255;
    if (bar_style == BAR_SOFT) shade = SOFT_FLOOR + (shade * (255 - SOFT_FLOOR)) / 255;
    /* Past GAUGE_BLEND_FROM the tail eases into the full accent. */
    if (filled > GAUGE_BLEND_FROM) {
        const int blend = ((filled - GAUGE_BLEND_FROM) * 255) / (GAUGE_SPAN - GAUGE_BLEND_FROM);
        shade += ((255 - shade) * blend) / 255;
    }
    return shade;
}

static void build_level_arc(int fill_q8)
{
    memset(arc_level, 0, sizeof(arc_level));
    memset(arc_ramp, 0, sizeof(arc_ramp));

    int filled = (GAUGE_SPAN * fill_q8) >> 8;
    if (filled < 0) filled = 0;
    if (filled > GAUGE_SPAN) filled = GAUGE_SPAN;
    for (int d = 0; d <= filled && d <= ARC_MASK; ++d) {
        const int i = (GAUGE_START - d) & ARC_MASK;
        arc_level[i] = 255;
        arc_ramp[i] = (uint8_t)level_shade(d, filled);
    }
    arc_head = filled > 0 && filled < GAUGE_SPAN ? ((GAUGE_START - filled) & ARC_MASK) : -1;
}

/* Scroll and zoom have no absolute value, so their arc is a comet carrying the
   momentum of the turn instead of a gauge reading. */
static void build_comet_arc(void)
{
    memset(arc_level, 0, sizeof(arc_level));
    memset(arc_ramp, 0, sizeof(arc_ramp));

    const int direction = arc_direction;
    const int head = (int)((arc_position >> 8) & ARC_MASK);
    for (int d = 0; d < ARC_TAIL; ++d) {
        const int fade = 255 - (d * 255) / ARC_TAIL;
        const int level = (fade * fade) / 255;
        if (level <= 4) break;
        const int i = (head - direction * d) & ARC_MASK;
        arc_level[i] = (uint8_t)level;
        arc_ramp[i] = (uint8_t)(255 - (d * 255) / ARC_TAIL);
    }
    arc_head = head;
}

/* Lights the segment of the last-used mode at full accent, so the menu opens
   already pointing at where you came from. */
static void build_menu_arc(void)
{
    const int lit_slot = slot_of(menu_cursor);
    for (int i = 0; i < ARC_SEGMENTS; ++i) {
        const bool lit = menu_sector_of(i) == lit_slot;
        arc_level[i] = lit ? 255 : 0;
        arc_ramp[i] = 255;
    }
    arc_head = -1;
}

static void clear_canvas(void)
{
    memset(canvas_pixels, 0, (size_t)LCD_WIDTH * LCD_HEIGHT * sizeof(uint16_t));
}

static inline int mix_channel(int from, int to, int amount)
{
    return from + (((to - from) * amount) >> 8);
}

/* The face behind the screensaver clock, in the chosen colour. */
static void fill_clock_face(void)
{
    const uint16_t face = pack_pixel(clock_bg[0], clock_bg[1], clock_bg[2]);
    uint16_t *pixels = (uint16_t *)canvas_pixels;
    for (size_t i = 0; i < (size_t)LCD_WIDTH * LCD_HEIGHT; ++i) pixels[i] = face;
}

/* Colours the clock labels and mixes the ring's track from the chosen ink
   and face: the date and AM/PM a little softer than the time, the track a
   faint fifth of the way from the face to the ink. Call with lvgl_mutex held. */
static void apply_clock_look(void)
{
    uint8_t soft[3];
    for (int i = 0; i < 3; ++i) {
        soft[i] = (uint8_t)mix_channel(clock_bg[i], clock_ink[i], 210);
        clock_track[i] = (uint8_t)mix_channel(clock_bg[i], clock_ink[i], 52);
    }
    lv_obj_set_style_text_color(clock_label, lv_color_hex(rgb_word(clock_ink)), 0);
    lv_obj_set_style_text_color(ampm_label, lv_color_hex(rgb_word(soft)), 0);
    lv_obj_set_style_text_color(date_label, lv_color_hex(rgb_word(soft)), 0);
}

static void fill_span(int y, int x0, int x1, uint16_t colour)
{
    if (y < 0 || y >= LCD_HEIGHT) return;
    if (x0 < 0) x0 = 0;
    if (x1 > LCD_WIDTH - 1) x1 = LCD_WIDTH - 1;
    uint16_t *row = (uint16_t *)canvas_pixels + (size_t)y * LCD_WIDTH;
    for (int x = x0; x <= x1; ++x) row[x] = colour;
}

/* Menu icons as small vector shapes, rasterised with signed distances so the
   edges are anti-aliased. revo1/icons.py holds the same table; keep the
   two in step. Coordinates are pixels from the icon centre, y pointing down. */
enum { PART_SEG, PART_CAPSULE, PART_ARC, PART_DISC, PART_POLY };

typedef struct {
    uint8_t kind;
    float v[8];
} icon_part_t;

typedef struct {
    const icon_part_t *parts;
    int count;
} menu_icon_t;

static const icon_part_t icon_volume[] = {
    {PART_POLY, {-12, -4.5f, -7, -4.5f, -7, 4.5f, -12, 4.5f}},
    {PART_POLY, {-7, -4.5f, 0, -11, 0, 11, -7, 4.5f}},
    {PART_ARC, {0, 0, 6, 2.4f, -50, 50}},
    {PART_ARC, {0, 0, 11.5f, 2.4f, -50, 50}},
};
static const icon_part_t icon_scroll[] = {
    {PART_CAPSULE, {0, -5, 0, 5, 9, 2.4f}},
    {PART_SEG, {0, -9, 0, -4, 2.8f}},
};
static const icon_part_t icon_brightness[] = {
    {PART_DISC, {0, 0, 5.5f}},
    {PART_SEG, {9, 0, 13, 0, 2.4f}},
    {PART_SEG, {6.364f, 6.364f, 9.192f, 9.192f, 2.4f}},
    {PART_SEG, {0, 9, 0, 13, 2.4f}},
    {PART_SEG, {-6.364f, 6.364f, -9.192f, 9.192f, 2.4f}},
    {PART_SEG, {-9, 0, -13, 0, 2.4f}},
    {PART_SEG, {-6.364f, -6.364f, -9.192f, -9.192f, 2.4f}},
    {PART_SEG, {0, -9, 0, -13, 2.4f}},
    {PART_SEG, {6.364f, -6.364f, 9.192f, -9.192f, 2.4f}},
};
static const icon_part_t icon_mic[] = {
    {PART_SEG, {0, -9, 0, -1, 9}},
    {PART_ARC, {0, -3, 8.5f, 2.4f, 0, 180}},
    {PART_SEG, {0, 5.5f, 0, 11, 2.4f}},
    {PART_SEG, {-5, 11.5f, 5, 11.5f, 2.4f}},
};
static const icon_part_t icon_zoom[] = {
    {PART_ARC, {-3, -3, 8, 2.6f, -180, 180}},
    {PART_SEG, {3.2f, 3.2f, 11, 11, 3.6f}},
    {PART_SEG, {-6.5f, -3, 0.5f, -3, 2}},
    {PART_SEG, {-3, -6.5f, -3, 0.5f, 2}},
};
static const icon_part_t icon_media[] = {
    {PART_POLY, {-12.5f, -9, 0.5f, 0, 0.5f, 0, -12.5f, 9}},
    {PART_SEG, {5.5f, -8, 5.5f, 8, 3.4f}},
    {PART_SEG, {11, -8, 11, 8, 3.4f}},
};
static const icon_part_t icon_pomodoro[] = {
    {PART_ARC, {0, 2, 9.5f, 2.4f, -180, 180}},
    {PART_SEG, {0, 2, 0, -3.5f, 2.4f}},
    {PART_SEG, {0, 2, 3.5f, 4.5f, 2.4f}},
    {PART_SEG, {0, -11, 0, -7.5f, 2.4f}},
    {PART_SEG, {-3.5f, -11.5f, 3.5f, -11.5f, 2.8f}},
};

static const icon_part_t icon_prev[] = {
    {PART_POLY, {15, -13, 15, 13, -7, 0, -7, 0}},
    {PART_POLY, {-14, -13, -12, -13, -12, 13, -14, 13}},
};
static const icon_part_t icon_next[] = {
    {PART_POLY, {-15, -13, 7, 0, 7, 0, -15, 13}},
    {PART_POLY, {12, -13, 14, -13, 14, 13, 12, 13}},
};
static const icon_part_t icon_play[] = {
    {PART_POLY, {-11, -13, 11, 0, 11, 0, -11, 13}},
};
static const icon_part_t icon_pause[] = {
    {PART_POLY, {-9, -13, -3, -13, -3, 13, -9, 13}},
    {PART_POLY, {3, -13, 9, -13, 9, 13, 3, 13}},
};

static const icon_part_t icon_games[] = {
    {PART_CAPSULE, {-6, 1, 6, 1, 7.5f, 2.4f}},
    {PART_SEG, {-9, 1, -4, 1, 2.2f}},
    {PART_SEG, {-6.5f, -1.5f, -6.5f, 3.5f, 2.2f}},
    {PART_DISC, {4.5f, -0.5f, 1.5f}},
    {PART_DISC, {7.5f, 2.5f, 1.5f}},
};

#define ICON_COUNT(parts) ((int)(sizeof(parts) / sizeof(parts[0])))
static const menu_icon_t menu_icons[MODE_COUNT] = {
    {icon_volume, ICON_COUNT(icon_volume)},
    {icon_scroll, ICON_COUNT(icon_scroll)},
    {icon_brightness, ICON_COUNT(icon_brightness)},
    {icon_mic, ICON_COUNT(icon_mic)},
    {icon_zoom, ICON_COUNT(icon_zoom)},
    {icon_media, ICON_COUNT(icon_media)},
    {icon_pomodoro, ICON_COUNT(icon_pomodoro)},
    {icon_games, ICON_COUNT(icon_games)},
};
static const menu_icon_t media_prev = {icon_prev, ICON_COUNT(icon_prev)};
static const menu_icon_t media_next = {icon_next, ICON_COUNT(icon_next)};
static const menu_icon_t media_play = {icon_play, ICON_COUNT(icon_play)};
static const menu_icon_t media_pause = {icon_pause, ICON_COUNT(icon_pause)};
/* A plain chevron: the way back to the menu. */
static const icon_part_t icon_back[] = {
    {PART_SEG, {-3.5f, 0, 2.5f, -7, 2.6f}},
    {PART_SEG, {-3.5f, 0, 2.5f, 7, 2.6f}},
};
static const menu_icon_t back_button = {icon_back, ICON_COUNT(icon_back)};
/* A screen struck through: the app is not there. */
static const icon_part_t icon_offline[] = {
    {PART_SEG, {-12, -10, 12, -10, 2.4f}},
    {PART_SEG, {12, -10, 12, 6, 2.4f}},
    {PART_SEG, {12, 6, -12, 6, 2.4f}},
    {PART_SEG, {-12, 6, -12, -10, 2.4f}},
    {PART_SEG, {0, 6, 0, 11, 2.4f}},
    {PART_SEG, {-6, 11.5f, 6, 11.5f, 2.4f}},
    {PART_SEG, {-14, -13, 14, 13, 2.4f}},
};
static const menu_icon_t offline_icon = {icon_offline, ICON_COUNT(icon_offline)};
/* The icon fills the cap; the heading sits above it and the hint below, mirrored
   in the band between the cap and the ring. */
#define OFFLINE_ICON_SIZE 2.0f
#define OFFLINE_HEAD_Y (-104)
#define OFFLINE_HINT_Y 104
/* Mute, under the level on Volume and Mic: the plain icon while on, crossed
   out while muted. */
static const icon_part_t icon_volume_muted[] = {
    {PART_POLY, {-13, -4.5f, -8, -4.5f, -8, 4.5f, -13, 4.5f}},
    {PART_POLY, {-8, -4.5f, -1, -11, -1, 11, -8, 4.5f}},
    {PART_SEG, {4, -5, 12, 5, 2.4f}},
    {PART_SEG, {12, -5, 4, 5, 2.4f}},
};
static const icon_part_t icon_mic_muted[] = {
    {PART_SEG, {0, -9, 0, -1, 9}},
    {PART_ARC, {0, -3, 8.5f, 2.4f, 0, 180}},
    {PART_SEG, {0, 5.5f, 0, 11, 2.4f}},
    {PART_SEG, {-5, 11.5f, 5, 11.5f, 2.4f}},
    {PART_SEG, {-11, -12, 11, 12, 2.4f}},
};
static const menu_icon_t volume_muted_icon = {icon_volume_muted, ICON_COUNT(icon_volume_muted)};
static const menu_icon_t mic_muted_icon = {icon_mic_muted, ICON_COUNT(icon_mic_muted)};
#define MUTE_ICON_Y 46
#define MUTE_ICON_SIZE 0.8f
#define MUTE_LABEL_Y -46
/* Scroll and Zoom: the screen's icon in the cap, its name below. */
#define MODE_ICON_Y (-10)
#define MODE_ICON_SIZE 1.8f
#define MODE_LABEL_Y 42

#define MENU_ICON_R 120
#define MENU_ICON_SIZE 1.25f
#define MENU_ICON_EXTENT 16

static float segment_distance(float px, float py, float x0, float y0,
                              float x1, float y1)
{
    const float dx = x1 - x0;
    const float dy = y1 - y0;
    const float length = dx * dx + dy * dy;
    float t = length > 0 ? ((px - x0) * dx + (py - y0) * dy) / length : 0;
    if (t < 0) t = 0;
    if (t > 1) t = 1;
    const float ex = px - (x0 + t * dx);
    const float ey = py - (y0 + t * dy);
    return sqrtf(ex * ex + ey * ey);
}

static float part_distance(const icon_part_t *part, float px, float py)
{
    const float *v = part->v;
    switch (part->kind) {
    case PART_SEG:
        return segment_distance(px, py, v[0], v[1], v[2], v[3]) - v[4] * 0.5f;
    case PART_CAPSULE:
        return fabsf(segment_distance(px, py, v[0], v[1], v[2], v[3]) - v[4]) - v[5] * 0.5f;
    case PART_DISC:
        return sqrtf((px - v[0]) * (px - v[0]) + (py - v[1]) * (py - v[1])) - v[2];
    case PART_ARC: {
        const float rx = px - v[0];
        const float ry = py - v[1];
        const float angle = atan2f(ry, rx) * 57.2957795f;
        if (angle >= v[4] && angle <= v[5]) {
            return fabsf(sqrtf(rx * rx + ry * ry) - v[2]) - v[3] * 0.5f;
        }
        float best = 1e9f;
        for (int end = 4; end <= 5; ++end) {
            const float a = v[end] * 0.0174532925f;
            const float ex = px - (v[0] + v[2] * cosf(a));
            const float ey = py - (v[1] + v[2] * sinf(a));
            const float d = sqrtf(ex * ex + ey * ey);
            if (d < best) best = d;
        }
        return best - v[3] * 0.5f;
    }
    case PART_POLY: {
        float area = 0;
        for (int i = 0; i < 4; ++i) {
            const int j = (i + 1) & 3;
            area += v[i * 2] * v[j * 2 + 1] - v[j * 2] * v[i * 2 + 1];
        }
        const float sign = area > 0 ? 1.0f : -1.0f;
        float distance = -1e9f;
        for (int i = 0; i < 4; ++i) {
            const int j = (i + 1) & 3;
            const float ex = v[j * 2] - v[i * 2];
            const float ey = v[j * 2 + 1] - v[i * 2 + 1];
            const float length = sqrtf(ex * ex + ey * ey);
            if (length == 0) continue;
            /* Outward normal of this edge, whichever way the quad winds. */
            const float d = ((px - v[i * 2]) * sign * ey - (py - v[i * 2 + 1]) * sign * ex)
                            / length;
            if (d > distance) distance = d;
        }
        return distance;
    }
    }
    return 1e9f;
}

static void draw_menu_icon(const menu_icon_t *icon, float cx, float cy,
                           float size, int red, int green, int blue)
{
    uint16_t *pixels = (uint16_t *)canvas_pixels;
    const int half = (int)(MENU_ICON_EXTENT * size) + 1;
    const int ox = (int)lroundf(cx);
    const int oy = (int)lroundf(cy);

    for (int y = oy - half; y < oy + half; ++y) {
        if (y < 0 || y >= LCD_HEIGHT) continue;
        for (int x = ox - half; x < ox + half; ++x) {
            if (x < 0 || x >= LCD_WIDTH) continue;
            const float px = (x + 0.5f - cx) / size;
            const float py = (y + 0.5f - cy) / size;
            float distance = 1e9f;
            for (int p = 0; p < icon->count; ++p) {
                const float d = part_distance(&icon->parts[p], px, py);
                if (d < distance) distance = d;
            }
            float cover = 0.5f - distance * size;
            if (cover <= 0) continue;
            if (cover > 1) cover = 1;
            const int weight = (int)(cover * 256);
            uint16_t *target = &pixels[(size_t)y * LCD_WIDTH + x];
            const uint16_t native = (uint16_t)((*target >> 8) | (*target << 8));
            int r = (native >> 8) & 0xF8;
            int g = (native >> 3) & 0xFC;
            int b = (native << 3) & 0xF8;
            r += ((red - r) * weight) >> 8;
            g += ((green - g) * weight) >> 8;
            b += ((blue - b) * weight) >> 8;
            *target = pack_pixel(r, g, b);
        }
    }
}

/* Icons sit on the light face just inside the ring, each opposite its own
   segment. The last-used mode is drawn in its accent, deepened so it stays
   legible on the pale face; the rest are a quiet grey. */
static void draw_menu_icons(void)
{
    const int count = screen_count();
    for (int slot = 0; slot < count; ++slot) {
        const int mode = screen_at(slot);
        const float angle = (90.0f - slot * 360.0f / count) * 0.0174532925f;
        int r = 0x8A, g = 0x8A, b = 0x9A;
        if (mode == menu_cursor) {
            const uint8_t *accent = accent_of(mode);
            r = accent[0] * 3 / 4;
            g = accent[1] * 3 / 4;
            b = accent[2] * 3 / 4;
        }
        draw_menu_icon(&menu_icons[mode],
                       SCREEN_CENTER + MENU_ICON_R * cosf(angle),
                       SCREEN_CENTER - MENU_ICON_R * sinf(angle), MENU_ICON_SIZE, r, g, b);
    }
}

/* Play/pause at the centre of the cap, previous and next outside it. The
   middle one shows the action a tap performs: pause while playing. */
static void draw_media_icons(const uint8_t *accent)
{
    const int dim = 90;
    draw_menu_icon(&media_prev, SCREEN_CENTER - MEDIA_BUTTON_SPACING, SCREEN_CENTER,
                   MEDIA_SKIP_SIZE, dim, dim, dim + 14);
    draw_menu_icon(media_status == 1 ? &media_pause : &media_play,
                   SCREEN_CENTER, SCREEN_CENTER, MEDIA_PLAY_SIZE,
                   accent[0] * 170 >> 8, accent[1] * 170 >> 8, accent[2] * 170 >> 8);
    draw_menu_icon(&media_next, SCREEN_CENTER + MEDIA_BUTTON_SPACING, SCREEN_CENTER,
                   MEDIA_SKIP_SIZE, dim, dim, dim + 14);
}

/* Thin chevrons either side of the game card: more cards to swipe to. */
static void draw_chevrons(void)
{
    const uint16_t colour = pack_pixel(150, 150, 164);
    for (int side = -1; side <= 1; side += 2) {
        const int cx = SCREEN_CENTER + side * 124;
        for (int dy = -8; dy <= 8; ++dy) {
            const int taper = (dy < 0 ? -dy : dy) / 2;
            const int x = cx + side * (2 - taper);
            fill_span(SCREEN_CENTER + dy, x, x + 1, colour);
        }
    }
}

static int media_elapsed(void)
{
    int elapsed = media_position;
    if (media_status == 1) {
        elapsed += (int)((esp_timer_get_time() - media_stamp) / 1000000);
    }
    if (elapsed < 0) elapsed = 0;
    if (media_duration > 0 && elapsed > media_duration) elapsed = media_duration;
    return elapsed;
}

static int pomo_remaining_now(void)
{
    int remaining = pomo_remaining;
    if (pomo_running) {
        remaining -= (int)((esp_timer_get_time() - pomo_stamp) / 1000000);
    }
    return remaining < 0 ? 0 : remaining;
}

/* The pomodoro ring drains as the time runs out. */
static int pomo_fill_q8(void)
{
    return pomo_total > 0 ? (int)(((int64_t)pomo_remaining_now() * 256) / pomo_total) : 0;
}

/* ----- whack-a-mole: drawing ------------------------------------------ */

static const icon_part_t whack_rim_parts[] = {{PART_DISC, {0, 0, 12.5f}}};
static const icon_part_t whack_dirt_parts[] = {{PART_DISC, {0, 0, 10.5f}}};
static const icon_part_t whack_aim_parts[] = {{PART_ARC, {0, 0, 15, 1.6f, -180, 180}}};
static const icon_part_t mole_body_parts[] = {{PART_DISC, {0, 0, 8.5f}}};
static const icon_part_t mole_face_parts[] = {{PART_DISC, {0, 3, 4.8f}}};
static const icon_part_t mole_eye_parts[] = {
    {PART_DISC, {-3.2f, -2.5f, 1.3f}},
    {PART_DISC, {3.2f, -2.5f, 1.3f}},
};
static const icon_part_t mole_nose_parts[] = {{PART_DISC, {0, 1.6f, 1.6f}}};
static const icon_part_t bomb_body_parts[] = {{PART_DISC, {0, 0, 8}}};
static const icon_part_t bomb_shine_parts[] = {{PART_DISC, {-3, -3, 1.8f}}};
static const icon_part_t bomb_fuse_parts[] = {{PART_SEG, {3.5f, -6.5f, 5.5f, -10, 1.8f}}};
static const icon_part_t bomb_spark_parts[] = {{PART_DISC, {6, -11, 1.8f}}};
static const icon_part_t whack_burst_parts[] = {
    {PART_SEG, {-9, 0, 9, 0, 2.4f}},
    {PART_SEG, {0, -9, 0, 9, 2.4f}},
    {PART_SEG, {-6.4f, -6.4f, 6.4f, 6.4f, 2.4f}},
    {PART_SEG, {-6.4f, 6.4f, 6.4f, -6.4f, 2.4f}},
};
#define WHACK_SHAPE(parts) {parts, ICON_COUNT(parts)}
static const menu_icon_t whack_rim = WHACK_SHAPE(whack_rim_parts);
static const menu_icon_t whack_dirt = WHACK_SHAPE(whack_dirt_parts);
static const menu_icon_t whack_aim = WHACK_SHAPE(whack_aim_parts);
static const menu_icon_t mole_body = WHACK_SHAPE(mole_body_parts);
static const menu_icon_t mole_face = WHACK_SHAPE(mole_face_parts);
static const menu_icon_t mole_eyes = WHACK_SHAPE(mole_eye_parts);
static const menu_icon_t mole_nose = WHACK_SHAPE(mole_nose_parts);
static const menu_icon_t bomb_body = WHACK_SHAPE(bomb_body_parts);
static const menu_icon_t bomb_shine = WHACK_SHAPE(bomb_shine_parts);
static const menu_icon_t bomb_fuse = WHACK_SHAPE(bomb_fuse_parts);
static const menu_icon_t bomb_spark = WHACK_SHAPE(bomb_spark_parts);
static const menu_icon_t whack_burst = WHACK_SHAPE(whack_burst_parts);

/* Hole 0 is at half past one, and the rest follow clockwise. */
static void whack_hole_centre(int hole, float *x, float *y)
{
    const float angle = (45.0f - hole * 45.0f) * 0.0174532925f;
    *x = SCREEN_CENTER + WHACK_RING_R * cosf(angle);
    *y = SCREEN_CENTER - WHACK_RING_R * sinf(angle);
}

/* The ring is the round's clock: full while waiting, draining while playing. */
static int whack_fill_q8(void)
{
    if (game_state == GAME_LOBBY) return 256;
    if (game_state == GAME_OVER) return 0;
    const int64_t left = whack_end_us - esp_timer_get_time();
    return left > 0 ? (int)((left * 256) / WHACK_ROUND_US) : 0;
}

static void draw_whack_hole(int hole)
{
    float cx, cy;
    whack_hole_centre(hole, &cx, &cy);
    const float s = WHACK_ICON_SIZE;
    const whack_hole_t *h = &whack_holes[hole];
    const uint8_t *accent = accent_of(GAMES_MODE);

    draw_menu_icon(&whack_rim, cx, cy, s, 0xC4, 0xC4, 0xCE);
    draw_menu_icon(&whack_dirt, cx, cy, s, 0x4A, 0x40, 0x3C);
    if (h->kind == MOLE_PLAIN || h->kind == MOLE_GOLD) {
        const bool gold = h->kind == MOLE_GOLD;
        draw_menu_icon(&mole_body, cx, cy, s, gold ? 0xF2 : 0x8C, gold ? 0xB6 : 0x5E,
                       gold ? 0x1E : 0x3C);
        draw_menu_icon(&mole_face, cx, cy, s, gold ? 0xFF : 0xD2, gold ? 0xE0 : 0xA4,
                       gold ? 0x8A : 0x7C);
        draw_menu_icon(&mole_eyes, cx, cy, s, 0x1E, 0x1A, 0x18);
        draw_menu_icon(&mole_nose, cx, cy, s, 0xE8, 0x6A, 0x82);
    } else if (h->kind == MOLE_BOMB) {
        draw_menu_icon(&bomb_body, cx, cy, s, 0x2A, 0x2A, 0x34);
        draw_menu_icon(&bomb_shine, cx, cy, s, 0x6A, 0x6A, 0x7A);
        draw_menu_icon(&bomb_fuse, cx, cy, s, 0x9A, 0x7A, 0x52);
        draw_menu_icon(&bomb_spark, cx, cy, s, 0xFF, 0x8C, 0x1A);
    }
    if (h->flash == FLASH_HIT) {
        draw_menu_icon(&whack_burst, cx, cy, s, accent[0] * 3 / 4, accent[1] * 3 / 4,
                       accent[2] * 3 / 4);
    } else if (h->flash == FLASH_BOOM) {
        draw_menu_icon(&whack_burst, cx, cy, s, 0xE0, 0x34, 0x34);
    }
    if (hole == whack_cursor && game_state != GAME_OVER) {
        draw_menu_icon(&whack_aim, cx, cy, s, accent[0] * 3 / 4, accent[1] * 3 / 4,
                       accent[2] * 3 / 4);
    }
}

/* Keeps a copy of the empty face so a hole can later be repainted alone. */
static void draw_whack_board(void)
{
    if (game_backdrop) {
        memcpy(game_backdrop, canvas_pixels, (size_t)LCD_WIDTH * LCD_HEIGHT * sizeof(uint16_t));
        game_backdrop_ready = true;
    }
    for (int hole = 0; hole < WHACK_HOLES; ++hole) draw_whack_hole(hole);
}

/* Blends a filled, anti-aliased rounded box into the canvas. */
static void draw_round_box(float cx, float cy, float half_w, float half_h, float radius,
                           int red, int green, int blue, int alpha)
{
    uint16_t *pixels = (uint16_t *)canvas_pixels;
    const int x0 = (int)floorf(cx - half_w) - 1, x1 = (int)ceilf(cx + half_w) + 1;
    const int y0 = (int)floorf(cy - half_h) - 1, y1 = (int)ceilf(cy + half_h) + 1;
    for (int y = y0; y <= y1; ++y) {
        if (y < 0 || y >= LCD_HEIGHT) continue;
        for (int x = x0; x <= x1; ++x) {
            if (x < 0 || x >= LCD_WIDTH) continue;
            const float qx = fabsf(x + 0.5f - cx) - (half_w - radius);
            const float qy = fabsf(y + 0.5f - cy) - (half_h - radius);
            const float ox = qx > 0 ? qx : 0, oy = qy > 0 ? qy : 0;
            const float inside = qx > qy ? qx : qy;
            const float distance = sqrtf(ox * ox + oy * oy) + (inside < 0 ? inside : 0) - radius;
            float cover = 0.5f - distance;
            if (cover <= 0) continue;
            if (cover > 1) cover = 1;
            const int weight = (int)(cover * alpha);
            uint16_t *target = &pixels[(size_t)y * LCD_WIDTH + x];
            const uint16_t native = (uint16_t)((*target >> 8) | (*target << 8));
            int r = (native >> 8) & 0xF8;
            int g = (native >> 3) & 0xFC;
            int b = (native << 3) & 0xF8;
            r += ((red - r) * weight) >> 8;
            g += ((green - g) * weight) >> 8;
            b += ((blue - b) * weight) >> 8;
            *target = pack_pixel(r, g, b);
        }
    }
}

/* The picture on a game's card. */
static void draw_card_art(int game, float cx, float cy)
{
    (void)game;
    const float s = CARD_ART_SIZE;
    draw_menu_icon(&whack_rim, cx, cy, s, 0xC4, 0xC4, 0xCE);
    draw_menu_icon(&whack_dirt, cx, cy, s, 0x4A, 0x40, 0x3C);
    draw_menu_icon(&mole_body, cx, cy, s, 0x8C, 0x5E, 0x3C);
    draw_menu_icon(&mole_face, cx, cy, s, 0xD2, 0xA4, 0x7C);
    draw_menu_icon(&mole_eyes, cx, cy, s, 0x1E, 0x1A, 0x18);
    draw_menu_icon(&mole_nose, cx, cy, s, 0xE8, 0x6A, 0x82);
}

/* One card at a time, with chevrons and page dots once there are several. */
static void draw_game_cards(void)
{
    const float cx = SCREEN_CENTER, cy = SCREEN_CENTER;
    const float r = CARD_R;
    draw_round_box(cx, cy + 4, r + 1, r + 1, r + 1, 0x60, 0x60, 0x70, 40);
    draw_round_box(cx, cy, r, r, r, 0xC8, 0xC8, 0xD2, 256);
    draw_round_box(cx, cy, r - 1, r - 1, r - 1, 0xFA, 0xFA, 0xFC, 256);
    draw_card_art(game_card, cx, SCREEN_CENTER + CARD_ART_Y);
    if (GAME_COUNT > 1) {
        draw_chevrons();
        const uint8_t *accent = accent_of(GAMES_MODE);
        for (int game = 0; game < GAME_COUNT; ++game) {
            const float x = cx + (game - (GAME_COUNT - 1) / 2.0f) * 14;
            const bool on = game == game_card;
            draw_round_box(x, SCREEN_CENTER + CARD_DOTS_Y, 3.5f, 3.5f, 3.5f,
                           on ? accent[0] * 3 / 4 : 0xA8, on ? accent[1] * 3 / 4 : 0xA8,
                           on ? accent[2] * 3 / 4 : 0xB4, 256);
        }
    }
}

/* Puts back the face under one hole, leaving the arc's band alone. */
static void whack_restore_hole(int hole)
{
    float cx, cy;
    whack_hole_centre(hole, &cx, &cy);
    const int ox = (int)lroundf(cx);
    const int oy = (int)lroundf(cy);
    const int limit = (BAND_INNER - 1) * (BAND_INNER - 1);
    uint16_t *pixels = (uint16_t *)canvas_pixels;
    for (int y = oy - WHACK_BOX; y <= oy + WHACK_BOX; ++y) {
        if (y < 0 || y >= LCD_HEIGHT) continue;
        const int dy = y - SCREEN_CENTER;
        for (int x = ox - WHACK_BOX; x <= ox + WHACK_BOX; ++x) {
            if (x < 0 || x >= LCD_WIDTH) continue;
            const int dx = x - SCREEN_CENTER;
            if (dx * dx + dy * dy >= limit) continue;
            const size_t index = (size_t)y * LCD_WIDTH + x;
            pixels[index] = game_backdrop[index];
        }
    }
    mark_dirty(ox - WHACK_BOX, oy - WHACK_BOX, ox + WHACK_BOX, oy + WHACK_BOX);
}

/* Composes a frame: the static chrome only when the view changed, then the
   arc, which is the only thing that moves. */
static void render_canvas(void)
{
    /* The screensaver owns the canvas; the dial is composed afresh when it ends. */
    if (saver_active) return;
    dirty_count = 0;

    if (app_offline) {
        if (force_full_redraw) {
            render_dial_chrome();
            draw_gauge_track();
            draw_menu_icon(&offline_icon, SCREEN_CENTER, SCREEN_CENTER,
                           OFFLINE_ICON_SIZE, 0xE5, 0x48, 0x4D);
            mark_dirty(0, 0, LCD_WIDTH - 1, LCD_HEIGHT - 1);
            force_full_redraw = false;
            for (int index = 0; index < dirty_count; ++index) {
                lv_obj_invalidate_area(canvas, &dirty_areas[index]);
            }
        }
        return;
    }

    if (force_full_redraw) {
        render_dial_chrome();
        draw_gauge_track();
        if (show_menu) {
            draw_menu_icons();
        } else {
            draw_menu_icon(&back_button, SCREEN_CENTER, SCREEN_CENTER + FOOTER_Y,
                           BACK_ICON_SIZE, 0x8A, 0x8A, 0x98);
            if (selected_mode == MEDIA_MODE) {
                draw_media_icons(accent_of(MEDIA_MODE));
            } else if (mode_is_level(selected_mode)) {
                if (mode_can_mute(selected_mode)) {
                    const bool muted = mode_muted(selected_mode);
                    const menu_icon_t *icon =
                        muted ? (selected_mode == 0 ? &volume_muted_icon : &mic_muted_icon)
                              : &menu_icons[selected_mode];
                    if (muted) {
                        draw_menu_icon(icon, SCREEN_CENTER, SCREEN_CENTER + MUTE_ICON_Y,
                                       MUTE_ICON_SIZE, 0xE5, 0x48, 0x4D);
                    } else {
                        draw_menu_icon(icon, SCREEN_CENTER, SCREEN_CENTER + MUTE_ICON_Y,
                                       MUTE_ICON_SIZE, 0x8A, 0x8A, 0x98);
                    }
                } else {
                    /* Brightness: its icon in the same place, as a label. */
                    draw_menu_icon(&menu_icons[selected_mode], SCREEN_CENTER,
                                   SCREEN_CENTER + MUTE_ICON_Y, MUTE_ICON_SIZE,
                                   0x8A, 0x8A, 0x98);
                }
            } else if (selected_mode == POMODORO_MODE) {
                /* The timer icon under the time, where the level screens keep theirs. */
                draw_menu_icon(&menu_icons[POMODORO_MODE], SCREEN_CENTER,
                               SCREEN_CENTER + MUTE_ICON_Y, MUTE_ICON_SIZE,
                               0x8A, 0x8A, 0x98);
            } else if (selected_mode == GAMES_MODE) {
                if (game_state == GAME_LOBBY) {
                    draw_game_cards();
                } else {
                    draw_whack_board();
                }
            } else {
                const uint8_t *accent = accent_of(selected_mode);
                draw_menu_icon(&menu_icons[selected_mode], SCREEN_CENTER,
                               SCREEN_CENTER + MODE_ICON_Y,
                               MODE_ICON_SIZE, accent[0] * 3 / 4, accent[1] * 3 / 4,
                               accent[2] * 3 / 4);
            }
        }
        capture_arc_backdrop();
        mark_dirty(0, 0, LCD_WIDTH - 1, LCD_HEIGHT - 1);
    }

    if (show_menu) {
        /* The menu never animates, so its arc is drawn only with the chrome. */
        if (dirty_count) {
            build_menu_arc();
            build_arc_ramp(accent_of(menu_cursor));
            draw_arc();
        }
    } else {
        if (mode_is_level(selected_mode)) {
            build_level_arc((int)(dial_value_q8 / 100));
        } else if (selected_mode == MEDIA_MODE) {
            int fill = 0;
            if (media_duration > 0) {
                fill = (int)(((int64_t)media_elapsed() * 256) / media_duration);
            }
            build_level_arc(fill);
        } else if (selected_mode == POMODORO_MODE) {
            build_level_arc(pomo_fill_q8());
        } else if (selected_mode == GAMES_MODE) {
            build_level_arc(whack_fill_q8());
        } else {
            build_comet_arc();
        }
        build_arc_ramp(accent_of(selected_mode));
        draw_arc();
        if (!force_full_redraw) mark_arc_dirty();
    }

    force_full_redraw = false;
    for (int index = 0; index < dirty_count; ++index) {
        lv_obj_invalidate_area(canvas, &dirty_areas[index]);
    }
}

/* The menu slot under a touch, or -1 off the ring. */
static int sector_at(int x, int y)
{
    const int dx = x - LCD_WIDTH / 2;
    const int dy = LCD_HEIGHT / 2 - y;
    const int radius_squared = dx * dx + dy * dy;
    if (radius_squared < 50 * 50 || radius_squared > 170 * 170) {
        return -1;
    }
    const int count = screen_count();
    const float step = 360.0f / count;
    float degrees = atan2f((float)dy, (float)dx) * 57.2957795f;
    int sector = (int)floorf((90.0f - degrees + step / 2 + 360.0f) / step);
    return sector % count;
}

/* The animation only changes the canvas. Re-setting the label text every frame
   cost more than drawing the water did, so the label work is kept on the
   state-change path and the tick just redraws the canvas. */
static void draw_frame(void)
{
    if (lvgl_mutex) xSemaphoreTake(lvgl_mutex, portMAX_DELAY);
    render_canvas();
    if (lvgl_mutex) xSemaphoreGive(lvgl_mutex);
}

/* Decides which labels are shown and what they say. Kept off the animation
   path: re-setting label text every frame used to cost more than drawing the
   whole screen did. */
static void apply_battery_label(void)
{
    if (!app_offline && !show_menu && !saver_active &&
        !(selected_mode == GAMES_MODE && game_state == GAME_PLAYING) &&
        wireless_connected() && battery_percent >= 0) {
        char text[16];
        snprintf(text, sizeof(text), "~%d%%", battery_percent);
        lv_label_set_text(battery_label, text);
        lv_obj_set_style_text_color(battery_label,
                                   lv_color_hex(battery_percent <= 20 ? 0xA83232 : 0x5A5A6A), 0);
        lv_obj_clear_flag(battery_label, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(battery_label, LV_OBJ_FLAG_HIDDEN);
    }
}

static void apply_labels(void)
{
    apply_battery_label();
    if (saver_active) return;
    if (app_offline) {
        lv_obj_align(value_label, LV_ALIGN_CENTER, 0, OFFLINE_HEAD_Y);
        lv_obj_set_style_text_font(value_label, &lv_font_montserrat_16, 0);
        lv_obj_set_style_text_color(value_label, lv_color_hex(0x2A2A34), 0);
        lv_label_set_text(value_label, "Not connected");
        lv_obj_align(artist_label, LV_ALIGN_CENTER, 0, OFFLINE_HINT_Y);
        lv_obj_set_style_text_font(artist_label, &lv_font_montserrat_16, 0);
        lv_obj_set_width(artist_label, 220);
        lv_obj_set_style_text_color(artist_label, lv_color_hex(0x5A5A6A), 0);
        lv_label_set_text(artist_label, "Open Revo1 on your PC");
        lv_obj_clear_flag(value_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(artist_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(title_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(time_label, LV_OBJ_FLAG_HIDDEN);
        return;
    }
    lv_obj_align(value_label, LV_ALIGN_CENTER, 0, 0);
    lv_obj_set_style_text_font(artist_label, &lv_font_montserrat_12, 0);
    lv_obj_set_width(artist_label, 160);
    /* Games move the labels: onto the card, or the title into the cap above
       the score. */
    const bool games = !show_menu && selected_mode == GAMES_MODE;
    const bool cards = games && game_state == GAME_LOBBY;
    lv_obj_align(title_label, LV_ALIGN_CENTER, 0,
                 cards ? CARD_NAME_Y : games ? GAME_TITLE_Y : MEDIA_TITLE_Y);
    lv_obj_align(time_label, LV_ALIGN_CENTER, 0, cards ? CARD_BEST_Y : MEDIA_TIME_Y);
    lv_obj_align(artist_label, LV_ALIGN_CENTER, 0, cards ? CARD_PLAY_Y : MEDIA_ARTIST_Y);
    {
        const uint8_t *accent = accent_of(GAMES_MODE);
        lv_obj_set_style_text_color(artist_label,
                                    cards ? lv_color_make(accent[0] * 3 / 5, accent[1] * 3 / 5,
                                                          accent[2] * 3 / 5)
                                          : lv_color_hex(0x76768A), 0);
    }
    if (show_menu) {
        /* The cap names the option the knob points at; a tap confirms it. */
        const uint8_t *accent = accent_of(menu_cursor);
        lv_obj_set_style_text_font(value_label, &lv_font_montserrat_16, 0);
        lv_obj_set_style_text_color(value_label,
                                    lv_color_make(accent[0] * 3 / 4, accent[1] * 3 / 4,
                                                  accent[2] * 3 / 4), 0);
        lv_label_set_text(value_label, mode_titles[menu_cursor]);
        lv_obj_clear_flag(value_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(title_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(artist_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(time_label, LV_OBJ_FLAG_HIDDEN);
        return;
    }

    lv_obj_set_style_text_color(value_label, lv_color_hex(0x2A2A34), 0);
    lv_obj_set_style_text_color(time_label, lv_color_hex(0x3C3C4A), 0);

    if (selected_mode == MEDIA_MODE) {
        lv_label_set_text(title_label,
                          media_title[0] ? media_title : "NOTHING PLAYING");
        lv_label_set_text(artist_label, media_artist);
        const int elapsed = media_elapsed();
        char clock[48];
        if (media_duration > 0) {
            snprintf(clock, sizeof(clock), "%d:%02d / %d:%02d",
                     elapsed / 60, elapsed % 60,
                     media_duration / 60, media_duration % 60);
        } else if (media_status != 0) {
            /* Players without media controls have no length; the app counts
               how long they have played, so show just that. */
            snprintf(clock, sizeof(clock), "%d:%02d", elapsed / 60, elapsed % 60);
        } else {
            clock[0] = '\0';
        }
        lv_label_set_text(time_label, clock);
        lv_obj_clear_flag(title_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(artist_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(time_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(value_label, LV_OBJ_FLAG_HIDDEN);
        return;
    }

    if (selected_mode == POMODORO_MODE) {
        const int remaining = pomo_remaining_now();
        char clock[24];
        snprintf(clock, sizeof(clock), "%d:%02d", remaining / 60, remaining % 60);
        pomo_shown = remaining;
        lv_obj_set_style_text_font(value_label, number_font, 0);
        lv_label_set_text(value_label, clock);
        lv_label_set_text(time_label, pomo_phase ? "BREAK" : "FOCUS");
        /* The phase sits above the time, like MUTED on the level screens. */
        lv_obj_align(time_label, LV_ALIGN_CENTER, 0, MUTE_LABEL_Y);
        lv_label_set_text(title_label, pomo_running ? "Tap to pause" : "Tap to start");
        lv_obj_clear_flag(value_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(time_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(title_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(artist_label, LV_OBJ_FLAG_HIDDEN);
        return;
    }

    if (selected_mode == GAMES_MODE) {
        char line[32];
        if (game_state == GAME_LOBBY) {
            lv_label_set_text(title_label, "WHACK-A-MOLE");
            if (whack_best > 0) {
                snprintf(line, sizeof(line), "BEST %d", whack_best);
            } else {
                snprintf(line, sizeof(line), "NO SCORE YET");
            }
            lv_label_set_text(time_label, line);
            lv_label_set_text(artist_label, "Tap to play");
            lv_obj_clear_flag(title_label, LV_OBJ_FLAG_HIDDEN);
            lv_obj_clear_flag(time_label, LV_OBJ_FLAG_HIDDEN);
            lv_obj_clear_flag(artist_label, LV_OBJ_FLAG_HIDDEN);
            lv_obj_add_flag(value_label, LV_OBJ_FLAG_HIDDEN);
            return;
        } else {
            if (game_state == GAME_PLAYING) {
                const int64_t left = whack_end_us - esp_timer_get_time();
                whack_seconds_shown = left > 0 ? (int)((left + 999999) / 1000000) : 0;
                snprintf(line, sizeof(line), "%d s", whack_seconds_shown);
                lv_label_set_text(title_label, line);
                lv_label_set_text(time_label, "SCORE");
            } else {
                lv_label_set_text(title_label, whack_new_best ? "NEW BEST!" : "TIME UP");
                lv_label_set_text(time_label, "Tap to play again");
            }
            snprintf(line, sizeof(line), "%d", whack_score);
            lv_obj_set_style_text_font(value_label, number_font, 0);
            lv_label_set_text(value_label, line);
        }
        lv_obj_clear_flag(title_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(value_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(time_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(artist_label, LV_OBJ_FLAG_HIDDEN);
        return;
    }

    char value[32];
    if (mode_is_level(selected_mode)) {
        snprintf(value, sizeof(value), "%d", selected_value);
        lv_obj_set_style_text_font(value_label, number_font, 0);
    } else {
        snprintf(value, sizeof(value), "%s", mode_titles[selected_mode]);
        lv_obj_set_style_text_font(value_label, &lv_font_montserrat_16, 0);
        const uint8_t *accent = accent_of(selected_mode);
        lv_obj_set_style_text_color(value_label,
                                    lv_color_make(accent[0] * 3 / 4, accent[1] * 3 / 4,
                                                  accent[2] * 3 / 4), 0);
        lv_obj_align(value_label, LV_ALIGN_CENTER, 0, MODE_LABEL_Y);
    }
    lv_label_set_text(value_label, value);
    lv_obj_clear_flag(value_label, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(title_label, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(artist_label, LV_OBJ_FLAG_HIDDEN);
    if (mode_muted(selected_mode)) {
        /* Muted: the level greys out and the cap says so; a tap unmutes. */
        lv_obj_set_style_text_color(value_label, lv_color_hex(0xA4A4B0), 0);
        lv_obj_set_style_text_color(time_label, lv_color_hex(0xE5484D), 0);
        lv_label_set_text(time_label, "MUTED");
        lv_obj_align(time_label, LV_ALIGN_CENTER, 0, MUTE_LABEL_Y);
        lv_obj_clear_flag(time_label, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(time_label, LV_OBJ_FLAG_HIDDEN);
    }
}

/* Text changed but the dial did not, so the chrome is left alone. */
static void refresh_text(void)
{
    if (lvgl_mutex) xSemaphoreTake(lvgl_mutex, portMAX_DELAY);
    apply_labels();
    if (lvgl_mutex) xSemaphoreGive(lvgl_mutex);
}

/* The view itself changed, so the static chrome has to be composed again. */
static void refresh_screen(void)
{
    if (lvgl_mutex) xSemaphoreTake(lvgl_mutex, portMAX_DELAY);
    force_full_redraw = true;
    render_canvas();
    apply_labels();
    if (lvgl_mutex) xSemaphoreGive(lvgl_mutex);
}

/* ----- whack-a-mole: play --------------------------------------------- */

/* Repaints the holes in `mask` (bit n is hole n) and nothing else. */
static void whack_redraw(unsigned mask)
{
    if (!mask || saver_active || app_offline || show_menu || selected_mode != GAMES_MODE) return;
    if (lvgl_mutex) xSemaphoreTake(lvgl_mutex, portMAX_DELAY);
    if (!game_backdrop_ready) {
        force_full_redraw = true;
        render_canvas();
    } else {
        dirty_count = 0;
        for (int hole = 0; hole < WHACK_HOLES; ++hole) {
            if (!(mask & (1u << hole))) continue;
            whack_restore_hole(hole);
            draw_whack_hole(hole);
        }
        for (int index = 0; index < dirty_count; ++index) {
            lv_obj_invalidate_area(canvas, &dirty_areas[index]);
        }
    }
    if (lvgl_mutex) xSemaphoreGive(lvgl_mutex);
}

static void whack_save_best(void)
{
    if (!settings_ready) return;
    nvs_handle_t handle;
    if (nvs_open(SETTINGS_NAMESPACE, NVS_READWRITE, &handle) != ESP_OK) return;
    if (nvs_set_u16(handle, "whack", (uint16_t)whack_best) == ESP_OK) nvs_commit(handle);
    nvs_close(handle);
}

static void whack_start(int64_t now)
{
    memset(whack_holes, 0, sizeof(whack_holes));
    whack_score = 0;
    whack_new_best = false;
    whack_start_us = now;
    whack_end_us = now + WHACK_ROUND_US;
    whack_next_spawn = now + 700000;
    game_state = GAME_PLAYING;
    refresh_screen();
}

static void whack_finish(int64_t now)
{
    memset(whack_holes, 0, sizeof(whack_holes));
    game_state = GAME_OVER;
    whack_over_us = now;
    if (whack_score > whack_best) {
        whack_best = whack_score > 0xFFFF ? 0xFFFF : whack_score;
        whack_new_best = true;
        whack_save_best();
    }
    host_printf("GAME,WHACK,%d,%d\n", whack_score, whack_best);
    refresh_screen();
}

/* Moles come faster, stay up for less time and crowd in as the round goes
   on; golden ones and bombs join after the first few seconds. */
static unsigned whack_spawn(int64_t now)
{
    const int progress = (int)(((now - whack_start_us) * 100) / WHACK_ROUND_US);
    const int most = progress < 33 ? 1 : progress < 75 ? 2 : 3;
    int up = 0;
    int empty[WHACK_HOLES];
    int empty_count = 0;
    for (int hole = 0; hole < WHACK_HOLES; ++hole) {
        if (whack_holes[hole].kind != MOLE_NONE) {
            ++up;
        } else if (whack_holes[hole].flash == FLASH_NONE) {
            empty[empty_count++] = hole;
        }
    }
    if (up >= most || empty_count == 0) {
        whack_next_spawn = now + 120000;
        return 0;
    }
    const int hole = empty[esp_random() % empty_count];
    const int roll = (int)(esp_random() % 100);
    int kind = MOLE_PLAIN;
    if (progress > 15 && roll < 10) {
        kind = MOLE_GOLD;
    } else if (progress > 25 && roll < 26) {
        kind = MOLE_BOMB;
    }
    int up_ms = 1350 - 7 * progress;
    if (kind == MOLE_GOLD) up_ms = up_ms * 7 / 10;
    whack_holes[hole].kind = (uint8_t)kind;
    whack_holes[hole].until = now + up_ms * 1000LL;
    const int gap_ms = 850 - 4 * progress;
    whack_next_spawn = now + (gap_ms * (70 + (int)(esp_random() % 61)) / 100) * 1000LL;
    return 1u << hole;
}

static unsigned whack_hit(int hole, int64_t now)
{
    whack_hole_t *h = &whack_holes[hole];
    if (h->kind == MOLE_NONE) return 0;
    if (h->kind == MOLE_PLAIN) {
        whack_score += 1;
    } else if (h->kind == MOLE_GOLD) {
        whack_score += 3;
    } else {
        whack_score = whack_score > 3 ? whack_score - 3 : 0;
    }
    h->flash = h->kind == MOLE_BOMB ? FLASH_BOOM : FLASH_HIT;
    h->flash_until = now + 260000;
    h->kind = MOLE_NONE;
    refresh_text();
    return 1u << hole;
}

/* During a round a touch lands as it goes down, not on release, and always
   whacks the hole the knob aims at: aiming is the knob's job, so touching a
   hole directly does not move the aim. The back button still works as usual.
   Returns true when the touch was used. */
static bool whack_press(int x, int y)
{
    if (game_state != GAME_PLAYING || show_menu || selected_mode != GAMES_MODE) return false;
    if (abs(x - SCREEN_CENTER) <= FOOTER_HIT_W &&
        abs(y - SCREEN_CENTER - FOOTER_Y) <= FOOTER_HIT_H) {
        return false;
    }
    whack_redraw(whack_hit(whack_cursor, esp_timer_get_time()));
    return true;
}

/* On the cards a tap on the card plays it; after a round a tap on the cap
   plays again, and the back icon goes back to the cards. */
static bool whack_tap(int dx, int dy)
{
    if (show_menu || selected_mode != GAMES_MODE) return false;
    if (game_state != GAME_LOBBY && abs(dx) <= FOOTER_HIT_W &&
        abs(dy - FOOTER_Y) <= FOOTER_HIT_H) {
        memset(whack_holes, 0, sizeof(whack_holes));
        game_state = GAME_LOBBY;
        refresh_screen();
        return true;
    }
    if (game_state == GAME_PLAYING) return false;
    if (game_state == GAME_LOBBY) {
        if (dx * dx + dy * dy > CARD_R * CARD_R) return false;
    } else if (dx * dx + dy * dy >= DIAL_CAP_R * DIAL_CAP_R) {
        return false;
    }
    const int64_t now = esp_timer_get_time();
    /* A late tap from the round that just ended must not start another. */
    if (game_state == GAME_OVER && now - whack_over_us < 800000) return true;
    whack_start(now);
    return true;
}

static void whack_rotate(int detents)
{
    if (game_state == GAME_LOBBY) {
        const int card = ((game_card + detents) % GAME_COUNT + GAME_COUNT) % GAME_COUNT;
        if (card != game_card) {
            game_card = card;
            refresh_screen();
        }
        return;
    }
    const int old = whack_cursor;
    whack_cursor = ((whack_cursor + detents) % WHACK_HOLES + WHACK_HOLES) % WHACK_HOLES;
    if (whack_cursor != old) whack_redraw((1u << old) | (1u << whack_cursor));
}

static void whack_tick(int64_t now)
{
    if (game_state == GAME_LOBBY) return;
    /* Leaving the screen abandons the round. */
    if (show_menu || selected_mode != GAMES_MODE) {
        memset(whack_holes, 0, sizeof(whack_holes));
        game_state = GAME_LOBBY;
        return;
    }
    if (game_state != GAME_PLAYING) return;
    if (now >= whack_end_us) {
        whack_finish(now);
        return;
    }
    unsigned mask = 0;
    for (int hole = 0; hole < WHACK_HOLES; ++hole) {
        whack_hole_t *h = &whack_holes[hole];
        if (h->kind != MOLE_NONE && now >= h->until) {
            h->kind = MOLE_NONE;
            mask |= 1u << hole;
        }
        if (h->flash != FLASH_NONE && now >= h->flash_until) {
            h->flash = FLASH_NONE;
            mask |= 1u << hole;
        }
    }
    if (now >= whack_next_spawn) mask |= whack_spawn(now);
    whack_redraw(mask);
    const int seconds = (int)((whack_end_us - now + 999999) / 1000000);
    if (seconds != whack_seconds_shown) refresh_text();
}

/* ----- screensaver library ------------------------------------------- */

/* Reads the header and item table, and only trusts them when every item
   lies inside the data the header claims. */
static bool load_media(void)
{
    media_valid = false;
    if (!media_partition || !media_entries) return false;
    media_header_t header;
    if (esp_partition_read(media_partition, 0, &header, sizeof(header)) != ESP_OK) return false;
    const uint32_t capacity = media_partition->size - MEDIA_HEADER_BYTES;
    if (header.magic != MEDIA_MAGIC || header.version != 1 || header.count == 0 ||
        header.count > MEDIA_MAX_ITEMS || header.data_bytes > capacity) {
        return false;
    }
    if (esp_partition_read(media_partition, sizeof(header), media_entries,
                           header.count * sizeof(media_entry_t)) != ESP_OK) {
        return false;
    }
    for (uint32_t index = 0; index < header.count; ++index) {
        const media_entry_t *entry = &media_entries[index];
        if (entry->frames == 0 || entry->bytes < 8 || entry->offset % 4 != 0 ||
            entry->offset > header.data_bytes ||
            entry->bytes > header.data_bytes - entry->offset) {
            return false;
        }
    }
    media_header = header;
    media_valid = true;
    return true;
}

static void report_library(void)
{
    const uint32_t capacity = media_partition ? media_partition->size - MEDIA_HEADER_BYTES : 0;
    host_printf("LIBRARY,%lu,%lu,%lu,%08lX\n", (unsigned long)capacity,
           (unsigned long)(media_valid ? media_header.count : 0),
           (unsigned long)(media_valid ? media_header.data_bytes : 0),
           (unsigned long)(media_valid ? media_header.data_crc : 0));
}

static int base64_value(char character)
{
    if (character >= 'A' && character <= 'Z') return character - 'A';
    if (character >= 'a' && character <= 'z') return character - 'a' + 26;
    if (character >= '0' && character <= '9') return character - '0' + 52;
    if (character == '+') return 62;
    if (character == '/') return 63;
    return -1;
}

/* Returns the decoded length, or -1 on malformed input or overflow. */
static int base64_decode(const char *text, uint8_t *output, int capacity)
{
    int length = 0;
    uint32_t bits = 0;
    int count = 0;
    for (; *text && *text != '='; ++text) {
        const int value = base64_value(*text);
        if (value < 0) return -1;
        bits = (bits << 6) | (uint32_t)value;
        count += 6;
        if (count >= 8) {
            count -= 8;
            if (length >= capacity) return -1;
            output[length++] = (uint8_t)(bits >> count);
        }
    }
    return length;
}

/* CRC-32 (the zlib one) of the data after the header, read back from flash. */
static uint32_t media_data_crc(uint32_t bytes)
{
    uint32_t crc = 0;
    uint32_t offset = 0;
    while (offset < bytes) {
        uint32_t chunk = bytes - offset;
        if (chunk > MEDIA_FRAME_MAX) chunk = MEDIA_FRAME_MAX;
        if (esp_partition_read(media_partition, MEDIA_HEADER_BYTES + offset,
                               frame_jpeg, chunk) != ESP_OK) {
            return ~crc;
        }
        crc = esp_rom_crc32_le(crc, frame_jpeg, chunk);
        offset += chunk;
    }
    return crc;
}

/* Upload, driven by the app one line at a time:
     MEDIA_BEGIN,<bytes>   erase room for the new library   -> MEDIA_READY
     MD,<offset>,<base64>  write a chunk                    -> MD_OK,<offset>
     MEDIA_END             check the header and the CRC     -> MEDIA_OK,<count>
     MEDIA_CLEAR           remove the library               -> MEDIA_OK,0
     LIBRARY               report what is stored            -> LIBRARY,...
   The app sends the header chunk (offset 0) last. Runs on the reader task, so
   the dial keeps working; playback is held off while `media_busy`. */
static void handle_media_line(char *line)
{
    static uint8_t chunk[UPLOAD_CHUNK_MAX];

    if (strcmp(line, "LIBRARY") == 0) {
        report_library();
        return;
    }
    if (!media_partition || !frame_jpeg) {
        host_printf("MEDIA_ERR,NOSTORAGE\n");
        return;
    }
    if (strncmp(line, "MD,", 3) == 0) {
        char *data = strchr(line + 3, ',');
        if (!data || !media_busy) {
            host_printf("MD_ERR,0\n");
            return;
        }
        *data++ = '\0';
        char *end = NULL;
        const unsigned long offset = strtoul(line + 3, &end, 10);
        const int length = base64_decode(data, chunk, sizeof(chunk));
        if (*end != '\0' || length <= 0 || offset > upload_size ||
            (unsigned long)length > upload_size - offset ||
            esp_partition_write(media_partition, offset, chunk, length) != ESP_OK) {
            host_printf("MD_ERR,%lu\n", offset);
            return;
        }
        host_printf("MD_OK,%lu\n", offset);
        return;
    }
    if (strncmp(line, "MEDIA_BEGIN,", 12) == 0) {
        char *end = NULL;
        const unsigned long bytes = strtoul(line + 12, &end, 10);
        if (*end != '\0' || bytes <= MEDIA_HEADER_BYTES || bytes > media_partition->size) {
            host_printf("MEDIA_ERR,SIZE\n");
            return;
        }
        media_busy = true;
        media_valid = false;
        /* Let the main loop leave the screensaver before the flash changes. */
        vTaskDelay(pdMS_TO_TICKS(200));
        upload_size = bytes;
        const uint32_t erase = (bytes + 4095) & ~4095u;
        if (esp_partition_erase_range(media_partition, 0, erase) != ESP_OK) {
            media_busy = false;
            host_printf("MEDIA_ERR,ERASE\n");
            return;
        }
        host_printf("MEDIA_READY\n");
        return;
    }
    if (strcmp(line, "MEDIA_END") == 0) {
        const bool loaded = media_busy && load_media() &&
                            MEDIA_HEADER_BYTES + media_header.data_bytes <= upload_size &&
                            media_data_crc(media_header.data_bytes) == media_header.data_crc;
        if (!loaded) {
            media_valid = false;
            esp_partition_erase_range(media_partition, 0, MEDIA_HEADER_BYTES);
        }
        media_busy = false;
        if (loaded) {
            host_printf("MEDIA_OK,%lu\n", (unsigned long)media_header.count);
        } else {
            host_printf("MEDIA_ERR,CHECK\n");
        }
        report_library();
        return;
    }
    if (strcmp(line, "MEDIA_CLEAR") == 0) {
        media_busy = true;
        media_valid = false;
        vTaskDelay(pdMS_TO_TICKS(200));
        esp_partition_erase_range(media_partition, 0, MEDIA_HEADER_BYTES);
        media_busy = false;
        host_printf("MEDIA_OK,0\n");
        report_library();
        /* With no pictures left the knob goes back to its menu. */
        last_input_us = esp_timer_get_time();
        open_menu();
        if (saver_active) {
            stop_saver();
        } else {
            refresh_screen();
        }
    }
}

static void dispatch_unlocked(char *line, size_t length);

static void begin_saver_item(int item, int64_t now);

static void dispatch_line(char *line, size_t length)
{
    xSemaphoreTake(dispatch_lock, portMAX_DELAY);
    dispatch_unlocked(line, length);
    xSemaphoreGive(dispatch_lock);
}

static int hex_value(char character)
{
    if (character >= '0' && character <= '9') return character - '0';
    if (character >= 'a' && character <= 'f') return character - 'a' + 10;
    if (character >= 'A' && character <= 'F') return character - 'A' + 10;
    return -1;
}

/* Decodes hex up to the next comma (or the end) into `out`; returns the
   byte count, or -1 on bad input. */
static int decode_hex_field(const char **text, uint8_t *out, int capacity)
{
    int count = 0;
    const char *cursor = *text;
    while (*cursor && *cursor != ',') {
        const int high = hex_value(cursor[0]);
        const int low = cursor[1] ? hex_value(cursor[1]) : -1;
        if (high < 0 || low < 0 || count >= capacity) return -1;
        out[count++] = (uint8_t)(high << 4 | low);
        cursor += 2;
    }
    if (*cursor == ',') ++cursor;
    *text = cursor;
    return count;
}

/* PAIR,<key hex> and UNPAIR. Only accepted over USB: pairing needs the
   knob in hand. */
static bool handle_pairing(const char *line)
{
    if (strcmp(line, "UNPAIR") == 0) {
        wireless_unpair();
        host_printf("UNPAIR_OK\n");
        return true;
    }
    if (strncmp(line, "PAIR,", 5) != 0) return false;
    const char *cursor = line + 5;
    uint8_t key[WIRELESS_KEY_BYTES];
    const int key_length = decode_hex_field(&cursor, key, sizeof(key));
    if (key_length != WIRELESS_KEY_BYTES || *cursor != '\0') {
        host_printf("PAIR_ERR,FORMAT\n");
    } else if (!wireless_pair(key)) {
        host_printf("PAIR_ERR,STORE\n");
    } else {
        char status[96];
        wireless_status(status, sizeof(status));
        host_printf("PAIR_OK\n%s\n", status);
    }
    memset(key, 0, sizeof(key));
    return true;
}

static void dispatch_unlocked(char *line, size_t length)
{
    /* The app's heartbeat: hearing it at all is what counts. */
    if (strcmp(line, "APP") == 0) return;
    if (strncmp(line, "MD,", 3) == 0 || strncmp(line, "MEDIA_", 6) == 0 ||
        strcmp(line, "LIBRARY") == 0) {
        handle_media_line(line);
        return;
    }
    /* Anything else is a short command; an over-long track title is cut. */
    if (length >= SERIAL_LINE_MAX) line[SERIAL_LINE_MAX - 1] = '\0';
    xQueueSend(serial_queue, line, pdMS_TO_TICKS(100));
}

/* Any whole line from the app shows it is there. */
static void note_host(void)
{
    last_host_ms = (uint32_t)(esp_timer_get_time() / 1000);
    host_seen = true;
}

/* Reads the USB serial port through its driver, so long upload lines arrive
   whole: the host is held off (USB NAKs) while the buffer is full, and nothing
   is lost or split the way non-blocking stdin could. */
static void serial_reader_task(void *argument)
{
    static char line[RX_LINE_MAX];
    uint8_t buffer[256];
    size_t length = 0;
    bool overflow = false;
    for (;;) {
        const int count = usb_serial_jtag_read_bytes(buffer, sizeof(buffer), portMAX_DELAY);
        for (int index = 0; index < count; ++index) {
            const char character = (char)buffer[index];
            if (character == '\n' || character == '\r') {
                if (length && !overflow) {
                    line[length] = '\0';
                    note_host();
                    if (!handle_pairing(line)) dispatch_line(line, length);
                }
                length = 0;
                overflow = false;
            } else if (length < sizeof(line) - 1) {
                line[length++] = character;
            } else {
                overflow = true;
            }
        }
    }
}

/* Lines from an authenticated wireless session; pairing stays USB-only. */
static void wireless_line(char *line, size_t length)
{
    note_host();
    if (strncmp(line, "PAIR,", 5) == 0 || strcmp(line, "UNPAIR") == 0) {
        host_printf("PAIR_ERR,USB\n");
        return;
    }
    dispatch_line(line, length);
}

static int mode_from_name(const char *name)
{
    for (int index = 0; index < MODE_COUNT; ++index) {
        if (strcmp(name, mode_names[index]) == 0) return index;
    }
    return -1;
}

static bool parse_integer(const char *text, int minimum, int maximum, int *value)
{
    char *end = NULL;
    long parsed = strtol(text, &end, 10);
    if (end == text || *end != '\0' || parsed < minimum || parsed > maximum) {
        return false;
    }
    *value = (int)parsed;
    return true;
}

static void copy_media_text(char *destination, const char *source)
{
    size_t index = 0;
    while (source[index] && index < MEDIA_TEXT_MAX - 1) {
        const char character = source[index];
        /* The bundled fonts only cover printable ASCII. */
        destination[index] = (character >= 0x20 && character < 0x7F) ? character : '?';
        ++index;
    }
    destination[index] = '\0';
}

/* Every new view starts the comet at the head of the gauge; the app resets
   its copy at the same moments. */
static void reset_comet(void)
{
    arc_position = GAUGE_START << 8;
    arc_target = GAUGE_START << 8;
    arc_direction = 1;
}

/* The menu always opens pointing at the control in use. */
static void open_menu(void)
{
    show_menu = true;
    menu_cursor = screen_enabled(selected_mode) ? selected_mode : screen_at(0);
}

static void confirm_menu(int mode)
{
    selected_mode = mode;
    show_menu = false;
    save_settings();
    dial_value_q8 = 0;
    reset_comet();
    host_printf("TAP,%d\n", mode);
    refresh_screen();
}

static void handle_command(char *line)
{
    if (strcmp(line, "VOLTAGE") == 0) {
        int raw, adc_mv;
        const esp_err_t err = voltage_read(&raw, &adc_mv);
        if (err != ESP_OK) {
            host_printf("VOLTAGE_ERR,%s\n", esp_err_to_name(err));
        } else {
            host_printf("VOLTAGE,%d,%d,%d\n", raw, adc_mv, adc_mv * 2);
        }
        return;
    }

    if (strcmp(line, "SHOWMENU") == 0) {
        open_menu();
        refresh_screen();
        host_printf("MENU_OK\n");
        return;
    }

    if (strcmp(line, "COMETRESET") == 0) {
        reset_comet();
        draw_frame();
        return;
    }

    if (strncmp(line, "SCREENS,", 8) == 0) {
        int mask;
        if (!parse_integer(line + 8, 1, ALL_SCREENS, &mask)) return;
        screen_mask = (uint8_t)mask;
        if (!screen_enabled(selected_mode)) selected_mode = screen_at(0);
        if (!screen_enabled(menu_cursor)) menu_cursor = selected_mode;
        save_settings();
        refresh_screen();
        host_printf("SCREENS_OK,%d\n", mask);
        return;
    }

    if (strncmp(line, "SWIPES,", 7) == 0) {
        int enabled;
        if (!parse_integer(line + 7, 0, 1, &enabled)) return;
        swipe_enabled = enabled;
        save_settings();
        host_printf("SWIPES_OK,%d\n", enabled);
        return;
    }

    if (strncmp(line, "BACKLIGHT,", 10) == 0) {
        int percent;
        if (!parse_integer(line + 10, 5, 100, &percent)) return;
        backlight_percent = percent;
        apply_backlight();
        save_settings();
        host_printf("BACKLIGHT_OK,%d\n", percent);
        return;
    }

    if (strncmp(line, "POWERSAVE,", 10) == 0) {
        int enabled;
        if (!parse_integer(line + 10, 0, 1, &enabled)) {
            host_printf("POWERSAVE_ERR,FORMAT\n");
            return;
        }
        power_save_enabled = enabled;
        apply_backlight();
        save_settings();
        host_printf("POWERSAVE_OK,%d\n", enabled);
        return;
    }

    if (strncmp(line, "DIM,", 4) == 0) {
        int enabled;
        if (!parse_integer(line + 4, 0, 1, &enabled)) return;
        dim_enabled = enabled;
        apply_backlight();
        save_settings();
        host_printf("DIM_OK,%d\n", enabled);
        return;
    }

    if (strncmp(line, "TIME,", 5) == 0) {
        char *save = NULL;
        const char *seconds_text = strtok_r(line + 5, ",", &save);
        const char *format_text = strtok_r(NULL, ",", &save);
        char *end = NULL;
        const long long seconds = seconds_text ? strtoll(seconds_text, &end, 10) : 0;
        int h24 = 1;
        /* 2000-01-01 to 2100-01-01, which also keeps the arithmetic small. */
        if (!seconds_text || !end || *end || seconds < 946684800LL || seconds > 4102444800LL ||
            (format_text && !parse_integer(format_text, 0, 1, &h24))) {
            return;
        }
        clock_offset_s = seconds - esp_timer_get_time() / 1000000;
        clock_24h = h24;
        clock_valid = true;
        clock_second_shown = -1;
        host_printf("TIME_OK\n");
        return;
    }

    if (strncmp(line, "SAVERLOOK,", 10) == 0) {
        char *save = NULL;
        const char *shade_text = strtok_r(line + 10, ",", &save);
        const char *ink_text = strtok_r(NULL, ",", &save);
        const char *face_text = strtok_r(NULL, ",", &save);
        int shade;
        char *ink_end = NULL, *face_end = NULL;
        if (!shade_text || !ink_text || !face_text || strlen(ink_text) != 6 ||
            strlen(face_text) != 6 || !parse_integer(shade_text, 0, 1, &shade)) {
            return;
        }
        const uint32_t ink = (uint32_t)strtoul(ink_text, &ink_end, 16);
        const uint32_t face = (uint32_t)strtoul(face_text, &face_end, 16);
        if (*ink_end || *face_end) return;
        const bool changed = shade != clock_shade || ink != rgb_word(clock_ink) ||
                             face != rgb_word(clock_bg);
        clock_shade = shade;
        set_rgb(clock_ink, ink);
        set_rgb(clock_bg, face);
        if (lvgl_mutex) xSemaphoreTake(lvgl_mutex, portMAX_DELAY);
        apply_clock_look();
        /* A running screensaver takes the new look at once. */
        if (changed && saver_active && saver_shown == SAVER_CLOCK) {
            fill_clock_face();
            lv_obj_invalidate(canvas);
        }
        if (lvgl_mutex) xSemaphoreGive(lvgl_mutex);
        if (changed && saver_active) {
            if (saver_shown == SAVER_BOTH && media_valid) {
                begin_saver_item(saver_item, esp_timer_get_time());
            }
            ring_wipe = true;
            clock_second_shown = -1;
            ring_next_us = 0;
        }
        save_settings();
        host_printf("SAVERLOOK_OK\n");
        return;
    }

    if (strncmp(line, "SAVER,", 6) == 0) {
        char *save = NULL;
        const char *enabled_text = strtok_r(line + 6, ",", &save);
        const char *idle_text = strtok_r(NULL, ",", &save);
        const char *interval_text = strtok_r(NULL, ",", &save);
        const char *kind_text = strtok_r(NULL, ",", &save);
        const char *ring_text = strtok_r(NULL, ",", &save);
        int enabled, idle, interval, kind = SAVER_PICTURES, ring = saver_ring;
        if (!enabled_text || !idle_text || !interval_text ||
            !parse_integer(enabled_text, 0, 1, &enabled) ||
            !parse_integer(idle_text, 10, 7200, &idle) ||
            !parse_integer(interval_text, 1, 3600, &interval) ||
            (kind_text && !parse_integer(kind_text, SAVER_PICTURES, SAVER_BOTH, &kind)) ||
            (ring_text && !parse_integer(ring_text, RING_DOTS, RING_COUNT - 1, &ring))) {
            return;
        }
        saver_enabled = enabled;
        saver_idle_s = idle;
        saver_interval_s = interval;
        saver_kind = kind;
        /* A new ring style is drawn in place: the band is wiped once so the
           old style leaves nothing behind, and the clock redraws at once. */
        if (ring != saver_ring && saver_active) {
            ring_wipe = true;
            clock_second_shown = -1;
            ring_next_us = 0;
        }
        saver_ring = ring;
        save_settings();
        host_printf("SAVER_OK\n");
        return;
    }

    if (strncmp(line, "MUTE,", 5) == 0) {
        char *save = NULL;
        const char *volume_text = strtok_r(line + 5, ",", &save);
        const char *mic_text = strtok_r(NULL, ",", &save);
        int volume, mic;
        if (!volume_text || !mic_text || !parse_integer(volume_text, 0, 1, &volume) ||
            !parse_integer(mic_text, 0, 1, &mic)) {
            return;
        }
        if (volume_muted != (bool)volume || mic_muted != (bool)mic) {
            volume_muted = volume;
            mic_muted = mic;
            /* The icon is part of the chrome, so the whole dial is redrawn. */
            if (!show_menu && mode_can_mute(selected_mode)) refresh_screen();
        }
        return;
    }

    if (strncmp(line, "GAMEBEST,", 9) == 0) {
        /* The app keeps a copy of the best score; the higher one wins, so a
           reflashed knob gets its record back. */
        int best;
        if (!parse_integer(line + 9, 0, 0xFFFF, &best)) return;
        if (best > whack_best) {
            whack_best = best;
            whack_save_best();
            if (!show_menu && selected_mode == GAMES_MODE && game_state == GAME_LOBBY) {
                refresh_screen();
            }
        }
        host_printf("GAME,BEST,%d\n", whack_best);
        return;
    }

    if (strncmp(line, "POMO,", 5) == 0) {
        char *save = NULL;
        const char *phase_text = strtok_r(line + 5, ",", &save);
        const char *remaining_text = strtok_r(NULL, ",", &save);
        const char *total_text = strtok_r(NULL, ",", &save);
        const char *running_text = strtok_r(NULL, ",", &save);
        int phase, remaining, total, running;
        if (!phase_text || !remaining_text || !total_text || !running_text ||
            !parse_integer(phase_text, 0, 1, &phase) ||
            !parse_integer(remaining_text, 0, 86400, &remaining) ||
            !parse_integer(total_text, 1, 86400, &total) ||
            !parse_integer(running_text, 0, 1, &running)) {
            return;
        }
        pomo_phase = phase;
        pomo_remaining = remaining;
        pomo_total = total;
        pomo_running = running;
        pomo_stamp = esp_timer_get_time();
        if (!show_menu && selected_mode == POMODORO_MODE) {
            refresh_text();
            draw_frame();
        }
        return;
    }

    if (strncmp(line, "STYLE,", 6) == 0) {
        char *save = NULL;
        const char *accent_text = strtok_r(line + 6, ",", &save);
        const char *size_text = strtok_r(NULL, ",", &save);
        const char *bar_text = strtok_r(NULL, ",", &save);
        int size;
        int bar = bar_style;
        if (!accent_text || !size_text || !parse_integer(size_text, 24, 48, &size)) return;
        if (bar_text && !parse_integer(bar_text, 0, BAR_STYLE_COUNT - 1, &bar)) return;
        bool custom = false;
        uint8_t rgb[3] = {0};
        if (strcmp(accent_text, "STANDARD") != 0) {
            char *end = NULL;
            const unsigned long hex = strtoul(accent_text, &end, 16);
            if (strlen(accent_text) != 6 || *end != '\0') return;
            custom = true;
            rgb[0] = (uint8_t)(hex >> 16);
            rgb[1] = (uint8_t)(hex >> 8);
            rgb[2] = (uint8_t)hex;
        }
        const lv_font_t *font = font_for_size(size);
        if (!font) return;
        custom_accent = custom;
        memcpy(custom_rgb, rgb, sizeof(custom_rgb));
        number_font = font;
        bar_style = bar;
        save_settings();
        refresh_screen();
        host_printf("STYLE_OK\n");
        return;
    }

    if (strncmp(line, "TRACK,", 6) == 0) {
        copy_media_text(media_title, line + 6);
        refresh_text();
        return;
    }

    if (strncmp(line, "ARTIST,", 7) == 0) {
        copy_media_text(media_artist, line + 7);
        refresh_text();
        return;
    }

    if (strncmp(line, "PLAY,", 5) == 0) {
        char *save = NULL;
        const char *status_text = strtok_r(line + 5, ",", &save);
        const char *position_text = strtok_r(NULL, ",", &save);
        const char *duration_text = strtok_r(NULL, ",", &save);
        int status, position, duration;
        if (!status_text || !position_text || !duration_text ||
            !parse_integer(status_text, 0, 2, &status) ||
            !parse_integer(position_text, 0, 86400, &position) ||
            !parse_integer(duration_text, 0, 86400, &duration)) {
            return;
        }
        /* Only the play/pause icon is baked into the chrome, so a plain
           position update must not pay for a full recompose. */
        const bool icon_changed = status != media_status;
        media_status = status;
        media_position = position;
        media_duration = duration;
        media_stamp = esp_timer_get_time();
        if (icon_changed) {
            refresh_screen();
        } else {
            refresh_text();
        }
        return;
    }

    if (strncmp(line, "STATE,", 6) != 0) return;
    char *save = NULL;
    char *mode = strtok_r(line + 6, ",", &save);
    char *value_text = strtok_r(NULL, ",", &save);
    char *orientation_text = strtok_r(NULL, ",", &save);
    char *keep_text = strtok_r(NULL, ",", &save);
    if (!mode || !value_text || !orientation_text || strtok_r(NULL, ",", &save)) {
        return;
    }

    const int parsed_mode = mode_from_name(mode);
    int parsed_value;
    int parsed_orientation;
    if (parsed_mode < 0 ||
        !parse_integer(value_text, 0, 100, &parsed_value) ||
        !parse_integer(orientation_text, 0, 270, &parsed_orientation) ||
        (parsed_orientation != 0 && parsed_orientation != 90 &&
         parsed_orientation != 180 && parsed_orientation != 270)) {
        return;
    }
    int keep = 0;
    if (keep_text && !parse_integer(keep_text, 0, 1, &keep)) return;
    /* With keep set (value updates and a fresh connection) an open menu
       stays open; only picking a screen in the app leaves it. */
    const bool stay_in_menu = keep && show_menu;
    const bool turned = parsed_orientation != orientation;
    /* Only a change of view needs the static chrome composed again; a new
       value just retargets the arc, which the animation tick sweeps to. */
    const bool view_changed = (show_menu && !stay_in_menu) || parsed_mode != selected_mode ||
                              turned;
    selected_mode = parsed_mode;
    selected_value = parsed_value;
    orientation = parsed_orientation;
    if (!stay_in_menu) show_menu = false;
    state_received = true;
    save_settings();
    if (stay_in_menu) {
        if (turned) refresh_screen();
    } else if (view_changed) {
        /* Entering a view sweeps the arc up from nothing. */
        dial_value_q8 = 0;
        reset_comet();
        refresh_screen();
    } else {
        refresh_text();
    }
    host_printf("STATE_OK,%s,%d,%d\n", mode, selected_value, orientation);
}

static void send_touch_event(void)
{
    const int delta_x = (int)touch_x - touch_start_x;
    const int delta_y = (int)touch_y - touch_start_y;
    if (abs(delta_x) > 55 && abs(delta_x) > abs(delta_y)) {
        /* With swipes off a sideways drag does nothing, not even a tap. */
        if (!swipe_enabled) return;
        const char *direction = delta_x < 0 ? "LEFT" : "RIGHT";
        selected_mode = step_screen(selected_mode, delta_x < 0 ? 1 : -1);
        show_menu = false;
        save_settings();
        dial_value_q8 = 0;
        reset_comet();
        host_printf("SWIPE,%s\n", direction);
        refresh_screen();
        return;
    }
    /* The transport buttons share the cap with the menu gesture: they are
       checked first, and the rest of the cap still opens the menu. */
    if (!show_menu && selected_mode == MEDIA_MODE &&
        abs((int)touch_start_y - SCREEN_CENTER) <= MEDIA_HIT) {
        const int offset = (int)touch_start_x - SCREEN_CENTER;
        if (abs(offset) <= MEDIA_HIT) {
            host_printf("MEDIA,PLAYPAUSE\n");
            return;
        }
        if (abs(offset + MEDIA_BUTTON_SPACING) <= MEDIA_HIT) {
            host_printf("MEDIA,PREV\n");
            return;
        }
        if (abs(offset - MEDIA_BUTTON_SPACING) <= MEDIA_HIT) {
            host_printf("MEDIA,NEXT\n");
            return;
        }
    }
    const int dx = (int)touch_start_x - SCREEN_CENTER;
    const int dy = (int)touch_start_y - SCREEN_CENTER;
    if (whack_tap(dx, dy)) return;
    if (!show_menu && selected_mode == POMODORO_MODE &&
        dx * dx + dy * dy < DIAL_CAP_R * DIAL_CAP_R) {
        host_printf("POMO,TOGGLE\n");
        return;
    }
    /* On Volume and Microphone the cap mutes; the name below it still opens the menu. */
    if (!show_menu && mode_can_mute(selected_mode) &&
        dx * dx + dy * dy < DIAL_CAP_R * DIAL_CAP_R) {
        host_printf("MUTE,TOGGLE\n");
        return;
    }
    const int centre_r = show_menu ? 50 : DIAL_CAP_R;
    const bool on_name = !show_menu && abs(dx) <= FOOTER_HIT_W &&
                         abs(dy - FOOTER_Y) <= FOOTER_HIT_H;
    if (on_name || dx * dx + dy * dy < centre_r * centre_r) {
        if (!show_menu) {
            open_menu();
            host_printf("MENU\n");
            refresh_screen();
        } else {
            confirm_menu(menu_cursor);
        }
        return;
    }
    if (show_menu) {
        /* Tapping an icon picks it directly; tapping anywhere else confirms
           whatever the knob is pointing at. */
        const int sector = sector_at(touch_start_x, touch_start_y);
        confirm_menu(sector >= 0 ? screen_at(sector) : menu_cursor);
    }
}

static bool read_touch(uint16_t *x, uint16_t *y)
{
    uint8_t reg = 0x00;
    uint8_t data[7] = {0};
    touch_error = i2c_master_transmit_receive(
        touch_device, &reg, 1, data, sizeof(data), 100);
    if (touch_error != ESP_OK || data[2] == 0) return false;
    *x = ((uint16_t)(data[3] & 0x0f) << 8) | data[4];
    *y = ((uint16_t)(data[5] & 0x0f) << 8) | data[6];
    return *x < LCD_WIDTH && *y < LCD_HEIGHT;
}

static void rotate_touch_coordinates(uint16_t *x, uint16_t *y)
{
    const uint16_t raw_x = *x;
    const uint16_t raw_y = *y;
    if (orientation == 90) {
        *x = raw_y;
        *y = LCD_HEIGHT - 1 - raw_x;
    } else if (orientation == 180) {
        *x = LCD_WIDTH - 1 - raw_x;
        *y = LCD_HEIGHT - 1 - raw_y;
    } else if (orientation == 270) {
        *x = LCD_WIDTH - 1 - raw_y;
        *y = raw_x;
    }
}

static void poll_touch(void)
{
    static esp_err_t reported_error = ESP_OK;
    uint16_t x;
    uint16_t y;
    bool pressed = read_touch(&x, &y);
    if (touch_error != ESP_OK) {
        if (reported_error != touch_error) {
            fprintf(stderr, "Touch I2C error: %s\n", esp_err_to_name(touch_error));
        }
        reported_error = touch_error;
        return;
    }
    reported_error = ESP_OK;
    if (pressed) {
        rotate_touch_coordinates(&x, &y);
        touch_x = x;
        touch_y = y;
        /* A touch on a dark screen only wakes it; nobody can see what it hits. */
        const bool dark = backlight_applied == 0;
        last_input_us = esp_timer_get_time();
        apply_backlight();
        if (!touch_active) {
            touch_active = true;
            touch_start_x = x;
            touch_start_y = y;
            /* With no app a touch only wakes the screen: there is nothing to drive. */
            touch_swallowed = saver_active || dark || app_offline;
            if (saver_active) stop_saver();
            if (!touch_swallowed && whack_press(x, y)) touch_swallowed = true;
        }
    } else if (touch_active) {
        touch_active = false;
        if (!touch_swallowed) send_touch_event();
    }
}

/* The brightness the screen should have now, idle dimming included. */
static int backlight_level(int64_t now)
{
    const int64_t idle_s = (now - last_input_us) / 1000000;
    return screen_power_level(backlight_percent, dim_enabled, power_save_enabled,
                              saver_active, idle_s);
}

/* Percent to PWM on a square law, so equal steps look like equal steps.
   Cheap enough for every loop: the LEDC is only touched on a change. */
static void apply_backlight(void)
{
    const int level = backlight_level(esp_timer_get_time());
    if (level == backlight_applied) return;
    if ((level > 0) != (backlight_applied > 0)) {
        if (lvgl_mutex) xSemaphoreTake(lvgl_mutex, portMAX_DELAY);
        ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(panel, level > 0));
        if (lvgl_mutex) xSemaphoreGive(lvgl_mutex);
    }
    backlight_applied = level;
    int duty = 0;
    if (level > 0) {
        duty = (255 * level * level) / 10000;
        if (duty < 3) duty = 3;
    }
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1, duty);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1);
}

static void initialize_display(void)
{
    const spi_bus_config_t bus = SH8601_PANEL_BUS_QSPI_CONFIG(
        LCD_SCLK, LCD_D0, LCD_D1, LCD_D2, LCD_D3,
        LCD_WIDTH * LCD_HEIGHT * sizeof(lv_color_t));
    ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_CH_AUTO));

    esp_lcd_panel_io_spi_config_t io_config =
        SH8601_PANEL_IO_QSPI_CONFIG(LCD_CS, panel_color_done, &display_driver);
    io_config.pclk_hz = LCD_PCLK_HZ;
    esp_lcd_panel_io_handle_t io;
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi(
        (esp_lcd_spi_bus_handle_t)SPI2_HOST, &io_config, &io));

    sh8601_vendor_config_t vendor = {
        .init_cmds = lcd_init_cmds,
        .init_cmds_size = sizeof(lcd_init_cmds) / sizeof(lcd_init_cmds[0]),
        .flags = {.use_qspi_interface = 1},
    };
    const esp_lcd_panel_dev_config_t config = {
        .reset_gpio_num = LCD_RESET,
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB,
        .bits_per_pixel = 16,
        .vendor_config = &vendor,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_sh8601(io, &config, &panel));
    ESP_ERROR_CHECK(esp_lcd_panel_reset(panel));
    ESP_ERROR_CHECK(esp_lcd_panel_init(panel));
    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(panel, true));

    ledc_timer_config_t timer = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .duty_resolution = LEDC_TIMER_8_BIT,
        .timer_num = LEDC_TIMER_3,
        .freq_hz = 50000,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ledc_channel_config_t backlight = {
        .gpio_num = LCD_BACKLIGHT,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = LEDC_CHANNEL_1,
        .timer_sel = LEDC_TIMER_3,
        .duty = 255,
        .hpoint = 0,
    };
    ESP_ERROR_CHECK(ledc_timer_config(&timer));
    ESP_ERROR_CHECK(ledc_channel_config(&backlight));
    apply_backlight();
}

static void initialize_touch(void)
{
    gpio_config_t reset = {
        .pin_bit_mask = 1ULL << TOUCH_RESET,
        .mode = GPIO_MODE_OUTPUT,
    };
    ESP_ERROR_CHECK(gpio_config(&reset));
    gpio_set_level(TOUCH_RESET, 0);
    vTaskDelay(pdMS_TO_TICKS(10));
    gpio_set_level(TOUCH_RESET, 1);
    vTaskDelay(pdMS_TO_TICKS(80));

    const i2c_master_bus_config_t bus = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = TOUCH_SDA,
        .scl_io_num = TOUCH_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    i2c_master_bus_handle_t bus_handle;
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus, &bus_handle));
    const i2c_device_config_t device = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = TOUCH_ADDRESS,
        .scl_speed_hz = 300000,
    };
    ESP_ERROR_CHECK(i2c_master_bus_add_device(bus_handle, &device, &touch_device));
    const uint8_t normal_mode[] = {0x00, 0x00};
    ESP_ERROR_CHECK(i2c_master_transmit(
        touch_device, normal_mode, sizeof(normal_mode), 100));
}

/* This knob is not a quadrature encoder: it rests with both contacts open at
   (1,1) and pulses them one at a time, never passing through (0,0). Measured
   on this unit, the leading pulse gives the direction, but a counter-clockwise
   click is followed ~70ms later by a trailing pulse on the other line. Netting
   those in hardware cancels the click entirely, so each edge is inspected here
   and the trailing pulse is rejected by direction rather than by time alone. */
static void IRAM_ATTR encoder_interrupt(void *argument)
{
    const int line = *(int *)argument;
    const int64_t now = esp_timer_get_time();

    if (now - encoder_line_edge[line] < ENCODER_BOUNCE_REJECT_US) return;
    encoder_line_edge[line] = now;

    const int direction = line == 0 ? 1 : -1;
    if (direction != encoder_last_direction &&
        now - encoder_last_step < ENCODER_DIRECTION_LOCKOUT_US) {
        return;
    }
    encoder_last_step = now;
    encoder_last_direction = direction;
    xQueueSendFromISR(encoder_queue, &direction, NULL);
}

static void initialize_encoder(void)
{
    const gpio_config_t encoder = {
        .pin_bit_mask = (1ULL << ENCODER_A) | (1ULL << ENCODER_B),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&encoder));
    ESP_ERROR_CHECK(gpio_set_intr_type(ENCODER_A, GPIO_INTR_NEGEDGE));
    ESP_ERROR_CHECK(gpio_set_intr_type(ENCODER_B, GPIO_INTR_NEGEDGE));
    ESP_ERROR_CHECK(gpio_install_isr_service(ESP_INTR_FLAG_IRAM));
    ESP_ERROR_CHECK(gpio_isr_handler_add(ENCODER_A, encoder_interrupt,
                                         &encoder_lines[0]));
    ESP_ERROR_CHECK(gpio_isr_handler_add(ENCODER_B, encoder_interrupt,
                                         &encoder_lines[1]));
}

static void initialize_lvgl(void)
{
    lv_init();
    lvgl_mutex = xSemaphoreCreateMutex();
    assert(lvgl_mutex);
    const size_t canvas_bytes = LCD_WIDTH * LCD_HEIGHT * sizeof(lv_color_t);
    canvas_pixels = heap_caps_malloc(canvas_bytes, MALLOC_CAP_SPIRAM);
    band_pixel = heap_caps_malloc(BAND_CAPACITY * sizeof(uint32_t), MALLOC_CAP_SPIRAM);
    band_segment = heap_caps_malloc(BAND_CAPACITY * sizeof(uint16_t), MALLOC_CAP_SPIRAM);
    band_offset = heap_caps_malloc(BAND_CAPACITY * sizeof(int16_t), MALLOC_CAP_SPIRAM);
    band_distance = heap_caps_malloc(BAND_CAPACITY * sizeof(uint8_t), MALLOC_CAP_SPIRAM);
    band_backdrop = heap_caps_malloc(BAND_CAPACITY * sizeof(uint16_t), MALLOC_CAP_SPIRAM);
    draw_buffer_a = heap_caps_malloc(
        LCD_WIDTH * DRAW_BUFFER_ROWS * sizeof(lv_color_t), MALLOC_CAP_DMA);
    draw_buffer_b = heap_caps_malloc(
        LCD_WIDTH * DRAW_BUFFER_ROWS * sizeof(lv_color_t), MALLOC_CAP_DMA);
    rotate_buffer_a = heap_caps_malloc(
        ROTATE_BUFFER_PIXELS * sizeof(lv_color_t), MALLOC_CAP_DMA);
    rotate_buffer_b = heap_caps_malloc(
        ROTATE_BUFFER_PIXELS * sizeof(lv_color_t), MALLOC_CAP_DMA);
    assert(canvas_pixels && band_pixel && band_segment && band_offset && band_distance &&
           band_backdrop && draw_buffer_a && draw_buffer_b &&
           rotate_buffer_a && rotate_buffer_b);
    build_arc_band();

    static lv_disp_draw_buf_t draw_buffer;
    lv_disp_draw_buf_init(&draw_buffer, draw_buffer_a, draw_buffer_b,
                          LCD_WIDTH * DRAW_BUFFER_ROWS);
    lv_disp_drv_init(&display_driver);
    display_driver.hor_res = LCD_WIDTH;
    display_driver.ver_res = LCD_HEIGHT;
    display_driver.draw_buf = &draw_buffer;
    display_driver.flush_cb = panel_flush;
    display_driver.rounder_cb = display_rounder;
    lv_disp_drv_register(&display_driver);

    canvas = lv_canvas_create(lv_scr_act());
    lv_obj_set_size(canvas, LCD_WIDTH, LCD_HEIGHT);
    lv_obj_center(canvas);
    /* The buffer never moves, so it is bound once here rather than per frame. */
    lv_canvas_set_buffer(canvas, canvas_pixels, LCD_WIDTH, LCD_HEIGHT,
                         LV_IMG_CF_TRUE_COLOR);
    title_label = lv_label_create(lv_scr_act());
    lv_obj_set_style_text_color(title_label, lv_color_hex(0x2A2A34), 0);
    lv_obj_set_style_text_font(title_label, &lv_font_montserrat_16, 0);
    lv_label_set_long_mode(title_label, LV_LABEL_LONG_DOT);
    lv_obj_set_width(title_label, 200);
    lv_obj_set_style_text_align(title_label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(title_label, LV_ALIGN_CENTER, 0, MEDIA_TITLE_Y);
    value_label = lv_label_create(lv_scr_act());
    lv_obj_set_style_text_color(value_label, lv_color_hex(0x2A2A34), 0);
    lv_obj_set_style_text_font(value_label, &lv_font_montserrat_32, 0);
    lv_obj_align(value_label, LV_ALIGN_CENTER, 0, 0);
    artist_label = lv_label_create(lv_scr_act());
    lv_obj_set_style_text_color(artist_label, lv_color_hex(0x76768A), 0);
    lv_obj_set_style_text_font(artist_label, &lv_font_montserrat_12, 0);
    lv_label_set_long_mode(artist_label, LV_LABEL_LONG_DOT);
    lv_obj_set_width(artist_label, 160);
    lv_obj_set_style_text_align(artist_label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(artist_label, LV_ALIGN_CENTER, 0, MEDIA_ARTIST_Y);
    lv_label_set_text(artist_label, "");
    time_label = lv_label_create(lv_scr_act());
    lv_obj_set_style_text_color(time_label, lv_color_hex(0x3C3C4A), 0);
    lv_obj_set_style_text_font(time_label, &lv_font_montserrat_12, 0);
    lv_obj_align(time_label, LV_ALIGN_CENTER, 0, MEDIA_TIME_Y);
    lv_label_set_text(time_label, "");
    battery_label = lv_label_create(lv_scr_act());
    lv_obj_set_style_text_font(battery_label, &lv_font_montserrat_12, 0);
    lv_obj_align(battery_label, LV_ALIGN_CENTER, 0, 132);
    lv_obj_add_flag(battery_label, LV_OBJ_FLAG_HIDDEN);
    clock_label = lv_label_create(lv_scr_act());
    lv_obj_set_style_text_color(clock_label, lv_color_hex(0xF2F2F5), 0);
    lv_obj_set_style_text_font(clock_label, &revo1_clock_96, 0);
    lv_obj_align(clock_label, LV_ALIGN_CENTER, 0, CLOCK_TIME_Y);
    lv_obj_add_flag(clock_label, LV_OBJ_FLAG_HIDDEN);
    ampm_label = lv_label_create(lv_scr_act());
    lv_obj_set_style_text_color(ampm_label, lv_color_hex(0xC8C8D2), 0);
    lv_obj_set_style_text_font(ampm_label, &lv_font_montserrat_24, 0);
    lv_obj_align(ampm_label, LV_ALIGN_CENTER, 0, CLOCK_AMPM_Y);
    lv_obj_add_flag(ampm_label, LV_OBJ_FLAG_HIDDEN);
    date_label = lv_label_create(lv_scr_act());
    lv_obj_set_style_text_color(date_label, lv_color_hex(0xC8C8D2), 0);
    lv_obj_set_style_text_font(date_label, &lv_font_montserrat_24, 0);
    lv_obj_align(date_label, LV_ALIGN_CENTER, 0, CLOCK_DATE_Y);
    lv_obj_add_flag(date_label, LV_OBJ_FLAG_HIDDEN);
    apply_clock_look();
    /* Sits on the upper face, between the cap and the ring. */
    refresh_screen();

    const esp_timer_create_args_t tick = {
        .callback = tick_lvgl,
        .name = "lvgl_tick",
    };
    esp_timer_handle_t timer;
    ESP_ERROR_CHECK(esp_timer_create(&tick, &timer));
    ESP_ERROR_CHECK(esp_timer_start_periodic(timer, 2000));
    xTaskCreate(lvgl_task, "lvgl", 4096, NULL, 2, NULL);
}

/* ----- screensaver playback ------------------------------------------ */

typedef struct {
    const uint8_t *data;
    uint32_t size;
    uint32_t position;
} jpeg_source_t;

static UINT jpeg_input(JDEC *decoder, BYTE *buffer, UINT count)
{
    jpeg_source_t *source = (jpeg_source_t *)decoder->device;
    const uint32_t left = source->size - source->position;
    if (count > left) count = left;
    if (buffer) memcpy(buffer, source->data + source->position, count);
    source->position += count;
    return count;
}

static UINT jpeg_output(JDEC *decoder, void *bitmap, JRECT *rect)
{
    const uint8_t *rgb = (const uint8_t *)bitmap;
    for (int y = rect->top; y <= rect->bottom; ++y) {
        uint16_t *row = frame_pixels + (size_t)y * LCD_WIDTH;
        for (int x = rect->left; x <= rect->right; ++x) {
            row[x] = pack_pixel(rgb[0], rgb[1], rgb[2]);
            rgb += 3;
        }
    }
    return 1;
}

static void draw_seconds_ring(int second, const uint16_t *under);

/* Darkens the middle of a picture so the clock on top of it stays readable:
   about half brightness behind the time, easing back to full towards the rim. */
static void shade_for_clock(uint16_t *pixels)
{
    static uint8_t ramp[1024];
    static bool ready;
    if (!ready) {
        for (int i = 0; i < 1024; ++i) {
            const float r = sqrtf(i * 64.0f);
            float t = (r - 110.0f) / 70.0f;
            if (t < 0) t = 0;
            if (t > 1) t = 1;
            t = t * t * (3 - 2 * t);
            ramp[i] = (uint8_t)(255.0f * (0.45f + 0.55f * t));
        }
        ready = true;
    }
    for (int y = 0; y < LCD_HEIGHT; ++y) {
        const int dy = 2 * y - (LCD_HEIGHT - 1);
        uint16_t *row = pixels + (size_t)y * LCD_WIDTH;
        for (int x = 0; x < LCD_WIDTH; ++x) {
            const int dx = 2 * x - (LCD_WIDTH - 1);
            const int factor = ramp[((dx * dx + dy * dy) >> 2) >> 6];
            if (factor == 255) continue;
            const uint16_t v = (uint16_t)((row[x] >> 8) | (row[x] << 8));
            const int r = ((v >> 11) * factor) >> 8;
            const int g = (((v >> 5) & 63) * factor) >> 8;
            const int b = ((v & 31) * factor) >> 8;
            const uint16_t shaded = (uint16_t)((r << 11) | (g << 5) | b);
            row[x] = (uint16_t)((shaded >> 8) | (shaded << 8));
        }
    }
}

/* Decodes one stored JPEG frame straight onto the screen. */
static bool show_saver_frame(uint32_t offset, uint32_t length)
{
    static uint8_t pool[4096];
    if (length == 0 || length > MEDIA_FRAME_MAX ||
        esp_partition_read(media_partition, MEDIA_HEADER_BYTES + offset,
                           frame_jpeg, length) != ESP_OK) {
        return false;
    }
    jpeg_source_t source = {frame_jpeg, length, 0};
    JDEC decoder;
    if (jd_prepare(&decoder, jpeg_input, pool, sizeof(pool), &source) != JDR_OK ||
        decoder.width != LCD_WIDTH || decoder.height != LCD_HEIGHT ||
        jd_decomp(&decoder, jpeg_output, 0) != JDR_OK) {
        return false;
    }
    if (saver_shown == SAVER_BOTH && clock_valid && clock_shade) shade_for_clock(frame_pixels);
    if (lvgl_mutex) xSemaphoreTake(lvgl_mutex, portMAX_DELAY);
    memcpy(canvas_pixels, frame_pixels, (size_t)LCD_WIDTH * LCD_HEIGHT * sizeof(uint16_t));
    ring_full = true;
    if (saver_shown == SAVER_BOTH && clock_valid && ring_second >= 0) {
        draw_seconds_ring(ring_second, frame_pixels);
    }
    lv_obj_invalidate(canvas);
    if (lvgl_mutex) xSemaphoreGive(lvgl_mutex);
    return true;
}

static void begin_saver_item(int item, int64_t now)
{
    saver_item = item % (int)media_header.count;
    saver_frame = 0;
    saver_offset = media_entries[saver_item].offset;
    saver_item_start = now;
    saver_next_frame = now;
}

static inline float coverage(float value)
{
    return value <= 0.0f ? 0.0f : (value >= 1.0f ? 1.0f : value);
}

/* Every ring style is drawn from a packed list of just the pixels it can
   touch, kept in fast internal memory while the screensaver runs, so any
   style can redraw 25 times a second and move smoothly between seconds.
   Each entry holds the pixel index in the low 17 bits and its segment above,
   with one byte alongside: for bullets, ticks and the bar, whose shapes are
   fixed, the pixel's coverage by the shape out of 255; for the wave and the
   comet, whose shapes move, its distance from the groove centre in 1/16 px. */
#define RING_REACH 11
#define WAVE_REACH 8
#define COMET_REACH 5
/* The animated figures: how far from the groove centre each one reaches. */
#define WALKER_REACH 15
#define SNAKE_REACH 9
#define SPARKLE_REACH 12
#define ORBIT_REACH 8
#define PULSE_REACH 14
/* Internal RAM left free for Bluetooth when a ring list is built. */
#define RING_INTERNAL_RESERVE (64 * 1024)
static uint32_t *ring_pixels;
static uint8_t *ring_bytes;
static int ring_count;
static int ring_list_style = -1;

/* Seconds clockwise from 12 o'clock, 0 to 60, for a segment. */
static inline float segment_seconds(int segment)
{
    return (float)((ARC_SEGMENTS / 4 - segment) & ARC_MASK) * (60.0f / ARC_SEGMENTS);
}

static inline float ease(float t)
{
    return t * t * (3.0f - 2.0f * t);
}

/* How much of a pixel a fixed shape covers, 0 to 1. */
static float ring_shape(int style, float off, int segment)
{
    const float step = 6.28318531f * DIAL_ARC_R / 60.0f;
    const float at = segment_seconds(segment);
    const int mark = (int)lroundf(at) % 60;
    const float along = (at - roundf(at)) * step;
    switch (style) {
    case RING_DOTS: {
        const float radius = mark % 5 == 0 ? 3.2f : 2.0f;
        return coverage(radius + 0.5f - sqrtf(off * off + along * along));
    }
    case RING_TICKS: {
        const float half = mark % 5 == 0 ? 1.4f : 0.9f;
        const float inner = mark % 5 == 0 ? -10.0f : -4.0f;
        return coverage(half + 0.5f - fabsf(along)) *
               coverage(fminf(off - inner, 8.0f - off) + 0.5f);
    }
    case RING_BAR:
        return coverage(3.5f - fabsf(off));
    case RING_WAVE:
        return fabsf(off) < WAVE_REACH ? 1.0f : 0.0f;
    case RING_COMET:
        return fabsf(off) < COMET_REACH ? 1.0f : 0.0f;
    case RING_WALKER:
        return fabsf(off) < WALKER_REACH ? 1.0f : 0.0f;
    case RING_SNAKE:
        return fabsf(off) < SNAKE_REACH ? 1.0f : 0.0f;
    case RING_SPARKLE:
        return fabsf(off) < SPARKLE_REACH ? 1.0f : 0.0f;
    case RING_ORBIT:
        return fabsf(off) < ORBIT_REACH ? 1.0f : 0.0f;
    case RING_PULSE:
        return fabsf(off) < PULSE_REACH ? 1.0f : 0.0f;
    default:
        return 0.0f;
    }
}

static void free_ring_list(void)
{
    free(ring_pixels);
    free(ring_bytes);
    ring_pixels = NULL;
    ring_bytes = NULL;
    ring_count = 0;
    ring_list_style = -1;
}

static bool build_ring_list(int style)
{
    if (ring_pixels && ring_list_style == style) return true;
    free_ring_list();
    int count = 0;
    for (int i = 0; i < band_count; ++i) {
        const float off = (float)band_offset[i] * (1.0f / 64.0f);
        if (fabsf(off) < DIAL_ARC_BAND && ring_shape(style, off, band_segment[i]) > 0.0f) ++count;
    }
    if (count == 0) return false;
    /* Internal memory is used only while enough stays free for the radios. */
    const size_t need = (size_t)count * (sizeof(uint32_t) + 1);
    if (heap_caps_get_free_size(MALLOC_CAP_INTERNAL) >= need + RING_INTERNAL_RESERVE) {
        ring_pixels = heap_caps_malloc(count * sizeof(uint32_t), MALLOC_CAP_INTERNAL);
        ring_bytes = heap_caps_malloc(count, MALLOC_CAP_INTERNAL);
    }
    if (!ring_pixels || !ring_bytes) {
        /* Short of internal memory the list still works from PSRAM, slower. */
        free(ring_pixels);
        free(ring_bytes);
        ring_pixels = heap_caps_malloc(count * sizeof(uint32_t), MALLOC_CAP_SPIRAM);
        ring_bytes = heap_caps_malloc(count, MALLOC_CAP_SPIRAM);
        if (!ring_pixels || !ring_bytes) {
            free_ring_list();
            return false;
        }
    }
    const bool moving = style == RING_WAVE || style == RING_COMET;
    /* The animated figures reach further, so their offsets are kept in 1/8 px. */
    const bool figure = style > RING_NONE;
    for (int i = 0; i < band_count; ++i) {
        const float off = (float)band_offset[i] * (1.0f / 64.0f);
        if (fabsf(off) >= DIAL_ARC_BAND) continue;
        const float shape = ring_shape(style, off, band_segment[i]);
        if (shape <= 0.0f) continue;
        ring_pixels[ring_count] = band_pixel[i] | ((uint32_t)band_segment[i] << 17);
        ring_bytes[ring_count] = figure ? (uint8_t)(int8_t)(band_offset[i] / 8)
                               : moving ? (uint8_t)(int8_t)(band_offset[i] / 4)
                                        : (uint8_t)lroundf(shape * 255.0f);
        ++ring_count;
    }
    ring_list_style = style;
    return true;
}

/* Paints one ring pixel: `lit` of the accent and `dim` of the track, out of
   256, over the picture or the clock face. */
static inline uint16_t ring_pixel(const uint16_t *under, uint32_t index, int lit, int dim,
                                  const uint8_t *accent)
{
    int r, g, b;
    if (under) {
        const uint16_t value = (uint16_t)((under[index] >> 8) | (under[index] << 8));
        /* Over a picture the track is a shadow rather than a grey. */
        const int keep = 256 - ((141 * dim) >> 8);
        r = (((value >> 11) << 3) * keep) >> 8;
        g = ((((value >> 5) & 63) << 2) * keep) >> 8;
        b = (((value & 31) << 3) * keep) >> 8;
    } else {
        r = mix_channel(clock_bg[0], clock_track[0], dim);
        g = mix_channel(clock_bg[1], clock_track[1], dim);
        b = mix_channel(clock_bg[2], clock_track[2], dim);
    }
    r += ((accent[0] - r) * lit) >> 8;
    g += ((accent[1] - g) * lit) >> 8;
    b += ((accent[2] - b) * lit) >> 8;
    return pack_pixel(r, g, b);
}

static inline int clamp_256(int value)
{
    return value < 0 ? 0 : (value > 256 ? 256 : value);
}

/* Only the ring changed, so only its strips are sent to the screen. */
static void invalidate_ring(int reach)
{
    dirty_count = 0;
    mark_ring_dirty(DIAL_ARC_R + reach + 1, DIAL_ARC_R - reach - 1);
    for (int index = 0; index < dirty_count; ++index) {
        lv_obj_invalidate_area(canvas, &dirty_areas[index]);
    }
}

/* Seconds from `from` to `to` going clockwise round, folded into -30..30. */
static inline float ring_gap(float from, float to)
{
    return fmodf(to - from + 90.0f, 60.0f) - 30.0f;
}

/* Where a figure stands on the ring, `seconds` clockwise from 12. */
typedef struct {
    float cos_t, sin_t;
} ring_place_t;

static inline ring_place_t ring_place(float seconds)
{
    const float angle = seconds * (6.28318531f / 60.0f);
    return (ring_place_t){cosf(angle), sinf(angle)};
}

/* A pixel seen from a figure: `u` along the ring (clockwise ahead) and `v`
   away from the groove centre (outwards), both in pixels. */
static inline void ring_local(ring_place_t place, uint32_t index, float *u, float *v)
{
    const float dx = (float)((int)(index % LCD_WIDTH) - SCREEN_CENTER);
    const float dy = (float)((int)(index / LCD_WIDTH) - SCREEN_CENTER);
    *u = dx * place.cos_t + dy * place.sin_t;
    *v = dx * place.sin_t - dy * place.cos_t - (float)DIAL_ARC_R;
}

/* Distance from (x, y) to the line from (ax, ay) to (bx, by). */
static float line_distance(float x, float y, float ax, float ay, float bx, float by)
{
    const float px = x - ax, py = y - ay, ex = bx - ax, ey = by - ay;
    float t = (px * ex + py * ey) / (ex * ex + ey * ey + 1e-6f);
    t = t < 0.0f ? 0.0f : (t > 1.0f ? 1.0f : t);
    const float qx = px - ex * t, qy = py - ey * t;
    return sqrtf(qx * qx + qy * qy);
}

/* One heartbeat on a monitor, 0 to 1 through the beat: a small P wave, the
   sharp QRS spike and a rounded T wave. About 1 at the top of the spike. */
static float heartbeat_trace(float x)
{
#define BEAT_BUMP(height, centre, width) \
    ((height) * expf(-((x - (centre)) * (x - (centre))) / (2.0f * (width) * (width))))
    return BEAT_BUMP(0.14f, 0.16f, 0.045f) + BEAT_BUMP(-0.16f, 0.33f, 0.02f) +
           BEAT_BUMP(1.0f, 0.40f, 0.022f) + BEAT_BUMP(-0.30f, 0.47f, 0.022f) +
           BEAT_BUMP(0.30f, 0.68f, 0.06f);
#undef BEAT_BUMP
}

/* Seconds of ring per heartbeat on the pulse style, and its height in px. */
#define PULSE_PERIOD_S 5.0f
#define PULSE_HEIGHT 12.0f
/* The snake: its length in seconds of ring and the waves along the ring. */
#define SNAKE_LENGTH_S 9.0f
#define SNAKE_WAVES 22
#define SPARKS_PER_SECOND 3

/* The segment at `seconds` clockwise from 12 (the inverse of segment_seconds). */
static inline int seconds_segment(float seconds)
{
    return (ARC_SEGMENTS / 4 - (int)lroundf(seconds * (ARC_SEGMENTS / 60.0f))) & ARC_MASK;
}

/* The animated styles: a little figure travels round once a minute, moving
   on smoothly 25 times a second, over a faint track. `now_s` is the seconds
   into the minute with their fraction. To fit the frame budget only the
   segments that changed are redrawn: those near the figure (now or a frame
   ago) and those whose trail brightness moved on; the figure's exact shape
   is worked out only near it. */
static void draw_figure_ring(int style, int second, float fraction, int fade,
                             const uint16_t *under, uint16_t *pixels, const uint8_t *accent)
{
    const float step = 6.28318531f * DIAL_ARC_R / 60.0f;
    const float now_s = (float)second + fraction;
    static float previous_s = -1.0f;
    static int previous_style = -1;
    /* The trail brightness each segment was last drawn with, out of 255. */
    static uint8_t drawn[ARC_SEGMENTS];
    static uint8_t dirty[ARC_SEGMENTS];
    static float trail[ARC_SEGMENTS];
    /* Paths fixed along the ring, worked out once per style: the snake's
       centre line, slope and scales, and the heartbeat's low and high. */
    static int16_t path_a[ARC_SEGMENTS], path_b[ARC_SEGMENTS];
    static uint8_t path_shade[ARC_SEGMENTS];
    bool full = ring_full;
    ring_full = false;
    if (previous_style != style) {
        full = true;
        for (int segment = 0; segment < ARC_SEGMENTS; ++segment) {
            const float at = segment_seconds(segment);
            if (style == RING_SNAKE) {
                const float phase = at * (6.28318531f * SNAKE_WAVES / 60.0f);
                const float slope =
                    3.5f * (6.28318531f * SNAKE_WAVES / 60.0f) / step * cosf(phase);
                path_a[segment] = (int16_t)lroundf(3.5f * sinf(phase) * 16.0f);
                path_b[segment] = (int16_t)lroundf(256.0f / sqrtf(1.0f + slope * slope));
                /* Darker bands across the back, like scales. */
                path_shade[segment] = (uint8_t)lroundf(
                    255.0f * (0.78f + 0.22f * cosf(at * 6.28318531f * 3.0f)));
            } else if (style == RING_PULSE) {
                /* The lowest and highest the trace reaches within a stroke's
                   width either side, so steep strokes stay as thick as flat
                   ones without overshooting the peaks. */
                const float x = fmodf(at, PULSE_PERIOD_S) / PULSE_PERIOD_S;
                const float side = 1.2f / (step * PULSE_PERIOD_S);
                const float before = heartbeat_trace(x - side), middle = heartbeat_trace(x);
                const float after = heartbeat_trace(x + side);
                path_a[segment] = (int16_t)lroundf(
                    PULSE_HEIGHT * fminf(middle, fminf(before, after)) * 16.0f);
                path_b[segment] = (int16_t)lroundf(
                    PULSE_HEIGHT * fmaxf(middle, fmaxf(before, after)) * 16.0f);
            }
        }
    }
    if (full || previous_s < 0.0f) previous_s = now_s;
    previous_style = style;

    /* How far either side of the figure, in seconds of ring, its shape reaches. */
    float near_s = 0.6f;
    if (style == RING_SNAKE) near_s = 0.7f;
    if (style == RING_ORBIT) near_s = 1.0f;
    for (int segment = 0; segment < ARC_SEGMENTS; ++segment) {
        const float at = segment_seconds(segment);
        /* How long ago the figure passed this point, in seconds. */
        const float behind = fmodf(now_s - at + 60.0f, 60.0f);
        float t;
        int level;
        if (style == RING_WALKER || style == RING_ORBIT) {
            /* What has passed this minute is lit, fading out in second 59. */
            t = coverage((now_s - at) * step + 0.5f);
            if (at >= 1.0f) t = t * (float)fade * (1.0f / 256.0f);
            level = (int)(t * 255.0f + 0.5f);
        } else if (style == RING_SNAKE) {
            t = behind < SNAKE_LENGTH_S ? 1.0f - behind / SNAKE_LENGTH_S : -1.0f;
            level = t < 0.0f ? 255 : (int)(t * 63.0f);
        } else if (style == RING_SPARKLE) {
            t = behind < 20.0f ? 1.0f - behind / 20.0f : 0.0f;
            level = (int)(t * 63.0f + 0.5f);
        } else {
            /* The heartbeat trace fades the way a monitor's does. */
            t = behind < 30.0f ? 1.0f - behind / 30.0f : 0.0f;
            level = (int)(t * 63.0f + 0.5f);
        }
        trail[segment] = t;
        const bool near = fabsf(ring_gap(now_s, at)) < near_s ||
                          fabsf(ring_gap(previous_s, at)) < near_s;
        /* 1: redraw the trail only; 2: also work out the figure here. */
        dirty[segment] = near ? 2 : ((full || level != drawn[segment]) ? 1 : 0);
        drawn[segment] = (uint8_t)level;
    }
    previous_s = now_s;
    const ring_place_t place = ring_place(now_s);

    if (style == RING_WALKER) {
        /* A stick figure walking on the outside of the ring, head outwards,
           leaving the minute lit on the ground behind it. Its stride fits its
           speed, so the feet do not slide. */
        const float swing = 6.28318531f * (64.0f / 60.0f) * now_s;
        const float sp = sinf(swing), cp = cosf(swing);
        const float bob = 0.7f * fabsf(sp);
        const float hip_v = -3.0f - bob, neck_v = 5.5f - bob, shoulder_v = 4.5f - bob;
        const float foot_a = 4.0f * sp, lift_a = 1.8f * fmaxf(0.0f, cp);
        const float foot_b = -4.0f * sp, lift_b = 1.8f * fmaxf(0.0f, -cp);
        const float knee_a = 0.5f * foot_a + 1.5f * fmaxf(0.0f, cp);
        const float knee_b = 0.5f * foot_b + 1.5f * fmaxf(0.0f, -cp);
        const float knee_v_a = 0.5f * (hip_v - 12.0f + lift_a);
        const float knee_v_b = 0.5f * (hip_v - 12.0f + lift_b);
        const float ground = -13.4f;
        for (int i = 0; i < ring_count; ++i) {
            const uint32_t packed = ring_pixels[i];
            const int segment = (int)(packed >> 17);
            if (!dirty[segment]) continue;
            const uint32_t index = packed & 0x1FFFF;
            const float off = (float)(int8_t)ring_bytes[i] * 0.125f;
            const float line = coverage(1.3f - fabsf(off - ground));
            int lit = (int)(256.0f * line * trail[segment]);
            if (dirty[segment] == 2) {
                float u, v;
                ring_local(place, index, &u, &v);
                if (u > -8.0f && u < 8.0f) {
                    float d = line_distance(u, v, 0.0f, hip_v, 0.3f, neck_v);
                    d = fminf(d, line_distance(u, v, 0.0f, hip_v, knee_a, knee_v_a));
                    d = fminf(d, line_distance(u, v, knee_a, knee_v_a, foot_a, -12.0f + lift_a));
                    d = fminf(d, line_distance(u, v, 0.0f, hip_v, knee_b, knee_v_b));
                    d = fminf(d, line_distance(u, v, knee_b, knee_v_b, foot_b, -12.0f + lift_b));
                    d = fminf(d, line_distance(u, v, 0.2f, shoulder_v, 3.6f * sp, -2.0f - bob));
                    d = fminf(d, line_distance(u, v, 0.2f, shoulder_v, -3.6f * sp, -2.0f - bob));
                    const float hu = u - 0.6f, hv = v - (9.8f - bob);
                    const float figure = fmaxf(coverage(1.9f - d),
                                               coverage(3.9f - sqrtf(hu * hu + hv * hv)));
                    const int body = (int)(256.0f * figure);
                    if (body > lit) lit = body;
                }
            }
            const int dim = ((int)(256.0f * line) * (256 - lit)) >> 8;
            pixels[index] = ring_pixel(under, index, lit, dim, accent);
        }
    } else if (style == RING_SNAKE) {
        /* A snake slithering round with its head at the second: the body
           follows a fixed wavy path, so it winds like a real one, tapering to
           the tail. Its tongue flicks out once a second. */
        const float phase = now_s * (6.28318531f * SNAKE_WAVES / 60.0f);
        const float head_v = 3.5f * sinf(phase);
        const float head_slope =
            3.5f * (6.28318531f * SNAKE_WAVES / 60.0f) / step * cosf(phase);
        const float head_len = sqrtf(1.0f + head_slope * head_slope);
        const float dir_u = 1.0f / head_len, dir_v = head_slope / head_len;
        const float flick = fraction < 0.35f ? sinf(fraction * (3.14159265f / 0.35f)) : 0.0f;
        for (int i = 0; i < ring_count; ++i) {
            const uint32_t packed = ring_pixels[i];
            const int segment = (int)(packed >> 17);
            if (!dirty[segment]) continue;
            const uint32_t index = packed & 0x1FFFF;
            const float off = (float)(int8_t)ring_bytes[i] * 0.125f;
            const float t = trail[segment];
            int lit = 0;
            float track = coverage(1.5f - fabsf(off));
            if (t >= 0.0f) {
                const float half = 0.9f + 2.4f * sqrtf(t);
                const float d = fabsf(off - (float)path_a[segment] * (1.0f / 16.0f)) *
                                (float)path_b[segment] * (1.0f / 256.0f);
                lit = (int)(coverage(half + 0.5f - d) * (float)path_shade[segment] + 0.5f);
                track = 0.0f;
            }
            if (dirty[segment] == 2) {
                float u, v;
                ring_local(place, index, &u, &v);
                v -= head_v;
                /* Turned along the path the body follows. */
                const float a = u * dir_u + v * dir_v, b = v * dir_u - u * dir_v;
                const float head = coverage(0.5f + 3.9f * (1.0f - sqrtf((a * a) / 30.0f + (b * b) / 15.0f)));
                if (head > 0.0f && head * 256.0f > (float)lit) {
                    const float eu = a - 1.4f, ev = b - 1.7f;
                    const float eye = coverage(1.6f - sqrtf(eu * eu + ev * ev));
                    lit = (int)(256.0f * head * (1.0f - eye));
                }
                if (flick > 0.0f && a > 4.0f) {
                    const float reach = 5.0f + 3.5f * flick;
                    float d = line_distance(a, b, 5.0f, 0.0f, reach, 0.0f);
                    d = fminf(d, line_distance(a, b, reach, 0.0f, reach + 1.3f, 1.0f));
                    d = fminf(d, line_distance(a, b, reach, 0.0f, reach + 1.3f, -1.0f));
                    const int tongue = (int)(256.0f * coverage(1.1f - d));
                    if (tongue > lit) lit = tongue;
                }
            }
            const int dim = ((int)(256.0f * track) * (256 - lit)) >> 8;
            pixels[index] = ring_pixel(under, index, lit, dim, accent);
        }
    } else if (style == RING_SPARKLE) {
        /* The comet scatters little stars that twinkle and fade behind it.
           Each segment keeps the few stars that can reach it; the segments
           a star covers now or covered a frame ago are redrawn. */
#define SPARKS (60 * SPARKS_PER_SECOND)
#define SPARKS_PER_SEGMENT 3
        static float spark_x[SPARKS], spark_y[SPARKS], spark_size[SPARKS];
        static int16_t nearby[ARC_SEGMENTS][SPARKS_PER_SEGMENT];
        static uint8_t starred[ARC_SEGMENTS];
        for (int segment = 0; segment < ARC_SEGMENTS; ++segment) {
            if (starred[segment]) {
                if (!dirty[segment]) dirty[segment] = 1;
                starred[segment] = 0;
            }
            for (int k = 0; k < SPARKS_PER_SEGMENT; ++k) nearby[segment][k] = -1;
        }
        for (int n = 0; n < SPARKS; ++n) {
            const uint32_t hash = (uint32_t)(n + 1) * 2654435761u;
            const float at = (float)(n / SPARKS_PER_SECOND) + 0.5f +
                             0.9f * ((float)(hash & 255) / 255.0f - 0.5f);
            const float behind = fmodf(now_s - at + 60.0f, 60.0f);
            spark_size[n] = 0.0f;
            if (behind > 18.0f) continue;
            const float lift = 14.0f * ((float)((hash >> 8) & 255) / 255.0f - 0.5f);
            const float twinkle_at = (float)((hash >> 16) & 255) / 255.0f;
            const float life = 1.0f - behind / 18.0f;
            const float twinkle = 0.5f + 0.5f * sinf(6.28318531f * (now_s * 1.7f + twinkle_at));
            const float size = life * (1.4f + 3.2f * twinkle * twinkle);
            spark_size[n] = size;
            const ring_place_t at_place = ring_place(at);
            spark_x[n] = (float)SCREEN_CENTER + ((float)DIAL_ARC_R + lift) * at_place.sin_t;
            spark_y[n] = (float)SCREEN_CENTER - ((float)DIAL_ARC_R + lift) * at_place.cos_t;
            /* The segments the star can touch, with a little to spare. */
            const int centre = seconds_segment(at);
            const int spread = 1 + (int)((size + 1.0f) / step * (ARC_SEGMENTS / 60.0f));
            for (int s = -spread; s <= spread; ++s) {
                const int segment = (centre + s) & ARC_MASK;
                starred[segment] = 1;
                if (!dirty[segment]) dirty[segment] = 1;
                for (int k = 0; k < SPARKS_PER_SEGMENT; ++k) {
                    if (nearby[segment][k] < 0) {
                        nearby[segment][k] = (int16_t)n;
                        break;
                    }
                }
            }
        }
        for (int i = 0; i < ring_count; ++i) {
            const uint32_t packed = ring_pixels[i];
            const int segment = (int)(packed >> 17);
            if (!dirty[segment]) continue;
            const uint32_t index = packed & 0x1FFFF;
            const float off = (float)(int8_t)ring_bytes[i] * 0.125f;
            const float t = trail[segment];
            const float distance = fabsf(off);
            float lit = t > 0.0f ? coverage(0.5f + 3.0f * t - distance) * t : 0.0f;
            if (nearby[segment][0] >= 0) {
                const float x = (float)(index % LCD_WIDTH), y = (float)(index / LCD_WIDTH);
                for (int k = 0; k < SPARKS_PER_SEGMENT; ++k) {
                    const int n = nearby[segment][k];
                    if (n < 0) break;
                    const float size = spark_size[n];
                    const float dx = fabsf(x - spark_x[n]), dy = fabsf(y - spark_y[n]);
                    if (dx > size + 0.5f || dy > size + 0.5f) continue;
                    /* A four-pointed star: a cross with a round middle. */
                    float star = fmaxf(coverage(size + 0.5f - dx) * coverage(0.9f - dy),
                                       coverage(size + 0.5f - dy) * coverage(0.9f - dx));
                    const float core = size * 0.55f + 0.5f;
                    if (dx * dx + dy * dy < core * core) {
                        star = fmaxf(star, coverage(core - sqrtf(dx * dx + dy * dy)));
                    }
                    if (star > lit) lit = star;
                }
            }
            if (dirty[segment] == 2) {
                float u, v;
                ring_local(place, index, &u, &v);
                const float head = coverage(4.5f - sqrtf(u * u + v * v));
                if (head > lit) lit = head;
            }
            const int bright = (int)(256.0f * lit);
            const int dim = (clamp_256((int)((1.5f - distance) * 256.0f)) * (256 - bright)) >> 8;
            pixels[index] = ring_pixel(under, index, bright, dim, accent);
        }
#undef SPARKS
#undef SPARKS_PER_SEGMENT
    } else if (style == RING_ORBIT) {
        /* A planet travels the minute with a moon circling it every two
           seconds, passing behind it on the far side. */
        const float spin = now_s * 3.14159265f;
        const float moon_u = 11.0f * cosf(spin), moon_v = 4.2f * sinf(spin);
        const bool moon_front = sinf(spin) < 0.0f;
        for (int i = 0; i < ring_count; ++i) {
            const uint32_t packed = ring_pixels[i];
            const int segment = (int)(packed >> 17);
            if (!dirty[segment]) continue;
            const uint32_t index = packed & 0x1FFFF;
            const float off = (float)(int8_t)ring_bytes[i] * 0.125f;
            const float line = coverage(1.7f - fabsf(off));
            int lit = (int)(256.0f * line * trail[segment] * 0.75f);
            if (dirty[segment] == 2) {
                float u, v;
                ring_local(place, index, &u, &v);
                const float planet_d = sqrtf(u * u + v * v);
                const float planet = coverage(5.2f - planet_d);
                const float mu = u - moon_u, mv = v - moon_v;
                const float moon_d = sqrtf(mu * mu + mv * mv);
                const float moon = coverage(2.7f - moon_d);
                float shape;
                if (moon_front) {
                    /* A thin dark gap round the moon sets it off the planet. */
                    const float gap = coverage(3.7f - moon_d);
                    shape = fmaxf(moon, planet * (1.0f - gap));
                    lit = (lit * (256 - (int)(256.0f * gap * planet))) >> 8;
                } else {
                    shape = fmaxf(planet, moon * (1.0f - coverage(6.2f - planet_d)));
                }
                const int value = (int)(256.0f * shape);
                if (value > lit) lit = value;
            }
            const int dim = ((int)(256.0f * line) * (256 - lit)) >> 8;
            pixels[index] = ring_pixel(under, index, lit, dim, accent);
        }
    } else {
        /* A heart monitor: the head writes a heartbeat trace that fades
           behind it, and glows with a beat every second. */
        const float beat = fraction < 0.08f ? fraction / 0.08f : expf(-(fraction - 0.08f) * 5.0f);
        const float x = fmodf(now_s, PULSE_PERIOD_S) / PULSE_PERIOD_S;
        const float head_v = PULSE_HEIGHT * heartbeat_trace(x);
        const float glow_r = 3.0f + 4.0f * beat;
        for (int i = 0; i < ring_count; ++i) {
            const uint32_t packed = ring_pixels[i];
            const int segment = (int)(packed >> 17);
            if (!dirty[segment]) continue;
            const uint32_t index = packed & 0x1FFFF;
            const float off = (float)(int8_t)ring_bytes[i] * 0.125f;
            const float t = trail[segment];
            float lit = 0.0f;
            if (t > 0.0f) {
                const float low = (float)path_a[segment] * (1.0f / 16.0f);
                const float high = (float)path_b[segment] * (1.0f / 16.0f);
                const float d = off < low ? low - off : (off > high ? off - high : 0.0f);
                lit = coverage(1.7f - d) * (0.25f + 0.75f * t);
            }
            if (dirty[segment] == 2) {
                float u, v;
                ring_local(place, index, &u, &v);
                v -= head_v;
                const float d2 = u * u + v * v;
                if (d2 < glow_r * glow_r) {
                    const float d = sqrtf(d2);
                    const float glow = 0.55f * beat * (1.0f - d / glow_r);
                    lit = fmaxf(lit, fmaxf(coverage(2.8f - d), glow));
                }
            }
            const int bright = (int)(256.0f * lit);
            /* Ahead of the head the monitor is a flat, faint line. */
            const float track = t > 0.0f ? 0.0f : coverage(1.2f - fabsf(off));
            const int dim = ((int)(256.0f * track) * (256 - bright)) >> 8;
            pixels[index] = ring_pixel(under, index, bright, dim, accent);
        }
    }
}

/* Redraws the seconds ring around the screensaver clock in the chosen style:
   the seconds passed this minute in the accent, the rest as a faint track.
   Everything moves on smoothly through each second: a bullet or tick fades
   in, the bar and the wave grow, and the comet glides. In the last second
   of the minute the filled part fades back to the track, so the new minute
   starts without a jump. It is painted over `under` (the shaded picture) or,
   without one, the clock face, so a new frame simply paints it again.
   Call with lvgl_mutex held. */
static void draw_seconds_ring(int second, const uint16_t *under)
{
    /* Pixels per second along the ring. */
    const float step = 6.28318531f * DIAL_ARC_R / 60.0f;
    /* The ring is drawn in the time's colour, so the clock reads as one piece. */
    const uint8_t *accent = clock_ink;
    uint16_t *pixels = (uint16_t *)canvas_pixels;
    int reach = RING_REACH;
    if (ring_wipe) {
        /* A new style: clear the whole band once so the old one leaves nothing. */
        ring_wipe = false;
        ring_full = true;
        const uint16_t face = pack_pixel(clock_bg[0], clock_bg[1], clock_bg[2]);
        for (int i = 0; i < band_count; ++i) {
            const uint32_t index = band_pixel[i];
            pixels[index] = under ? under[index] : face;
        }
        reach = DIAL_ARC_BAND;
    }
    const int style = saver_ring;
    if (style == RING_NONE || !build_ring_list(style)) {
        if (reach == DIAL_ARC_BAND) invalidate_ring(reach);
        return;
    }
    const float fraction = (float)(ring_now_us % 1000000) * 1e-6f;
    /* In second 59 the filled part fades out towards the new minute. */
    const int fade = second == 59 ? (int)lroundf(256.0f * (1.0f - ease(fraction))) : 256;
    if (style > RING_NONE) {
        draw_figure_ring(style, second, fraction, fade, under, pixels, accent);
        invalidate_ring(DIAL_ARC_BAND);
        return;
    }

    if (style == RING_DOTS || style == RING_TICKS || style == RING_BAR) {
        /* How lit each segment is: whole seconds passed, plus the next one
           fading in (bullets and ticks) or the bar's edge creeping on. */
        static uint16_t weight[ARC_SEGMENTS];
        const int arriving = (int)lroundf(256.0f * ease(fraction));
        const float filled = (float)second + 1.0f + fraction;
        for (int segment = 0; segment < ARC_SEGMENTS; ++segment) {
            const float at = segment_seconds(segment);
            int w;
            if (style == RING_BAR) {
                w = (int)lroundf(256.0f * coverage((filled - at) * step + 0.5f));
            } else {
                const int mark = (int)lroundf(at) % 60;
                w = mark <= second ? 256 : (mark == second + 1 ? arriving : 0);
            }
            /* The first second stays lit through the fade into the new minute. */
            if (at >= 1.0f && !(style != RING_BAR && (int)lroundf(at) % 60 == 0)) {
                w = (w * fade) >> 8;
            }
            weight[segment] = (uint16_t)w;
        }
        for (int i = 0; i < ring_count; ++i) {
            const uint32_t packed = ring_pixels[i];
            const uint32_t index = packed & 0x1FFFF;
            const int shape = ring_bytes[i] + (ring_bytes[i] >> 7);
            const int lit = (shape * weight[packed >> 17]) >> 8;
            pixels[index] = ring_pixel(under, index, lit, shape - lit, accent);
        }
    } else if (style == RING_WAVE) {
        static int16_t height[ARC_SEGMENTS];
        static uint16_t thin[ARC_SEGMENTS], head[ARC_SEGMENTS];
        /* The tip creeps on through each second and only the last few
           seconds behind it ripple, swaying back and forth once a second (a
           sway is periodic, so nothing jumps when the second turns over); the
           ripple eases out along the body, which keeps its shape. */
        const float tip = (float)second + fraction;
        const float sway = 1.4f * sinf(fraction * 6.28318531f);
        /* The still phase falls by the same angle from one segment to the
           next, so its sine and cosine are carried along by rotation. The
           wave repeats every two seconds, so 60 back to 0 needs no fix. */
        const float turn = -3.14159265f * 60.0f / ARC_SEGMENTS;
        const float turn_cos = cosf(turn), turn_sin = sinf(turn);
        const float begin = segment_seconds(0) * 3.14159265f;
        float wave_sin = sinf(begin), wave_cos = cosf(begin);
        const float steep = 4.0f * 3.14159265f / step;
        for (int segment = 0; segment < ARC_SEGMENTS; ++segment) {
            const float at = segment_seconds(segment);
            float sine = wave_sin, cosine = wave_cos;
            const float behind = tip - at;
            if (behind > -1.0f && behind < WAVE_HEAD_S) {
                const float weight = ease(behind <= 0.0f ? 1.0f : 1.0f - behind / WAVE_HEAD_S);
                const float phase = at * 3.14159265f - sway * weight;
                sine = sinf(phase);
                cosine = cosf(phase);
            }
            const float slope = steep * cosine;
            height[segment] = (int16_t)(64.0f * sine + (sine < 0.0f ? -0.5f : 0.5f));
            thin[segment] = (uint16_t)(256.0f / sqrtf(1.0f + slope * slope) + 0.5f);
            int fill = (int)(256.0f * coverage(behind * step + 0.5f) + 0.5f);
            if (at >= 1.0f) fill = (fill * fade) >> 8;
            head[segment] = (uint16_t)fill;
            const float next_sin = wave_sin * turn_cos + wave_cos * turn_sin;
            wave_cos = wave_cos * turn_cos - wave_sin * turn_sin;
            wave_sin = next_sin;
        }
        for (int i = 0; i < ring_count; ++i) {
            const uint32_t packed = ring_pixels[i];
            const uint32_t index = packed & 0x1FFFF;
            const int segment = (int)(packed >> 17);
            const int off = (int8_t)ring_bytes[i];
            const int fill = head[segment];
            /* A squiggle 5 px wide where filled, a 3.5 px line after it. */
            int d = off - height[segment];
            if (d < 0) d = -d;
            const int lit = (clamp_256((40 - ((d * thin[segment]) >> 8)) * 16) * fill) >> 8;
            int dim = 0;
            if (fill < 256) dim = (clamp_256((28 - (off < 0 ? -off : off)) * 16) * (256 - fill)) >> 8;
            pixels[index] = ring_pixel(under, index, lit, dim, accent);
        }
    } else {
        /* The comet: a bright head gliding round with a tail fading behind. */
        static uint16_t tail[ARC_SEGMENTS];
        static int16_t tail_half[ARC_SEGMENTS], head_along[ARC_SEGMENTS];
        const float now_s = (float)second + fraction;
        for (int segment = 0; segment < ARC_SEGMENTS; ++segment) {
            const float at = segment_seconds(segment);
            const float behind = fmodf(now_s - at + 60.0f, 60.0f);
            const float t = behind < 20.0f ? 1.0f - behind / 20.0f : 0.0f;
            tail[segment] = (uint16_t)lroundf(256.0f * t);
            tail_half[segment] = (int16_t)lroundf(16.0f * (0.5f + 3.0f * t));
            const float along = (fmodf(at - now_s + 90.0f, 60.0f) - 30.0f) * step;
            head_along[segment] = fabsf(along) < 5.0f ? (int16_t)lroundf(along * 16.0f)
                                                      : INT16_MAX;
        }
        for (int i = 0; i < ring_count; ++i) {
            const uint32_t packed = ring_pixels[i];
            const uint32_t index = packed & 0x1FFFF;
            const int segment = (int)(packed >> 17);
            const int off = (int8_t)ring_bytes[i];
            const int distance = off < 0 ? -off : off;
            int lit = (clamp_256((tail_half[segment] - distance) * 16) * tail[segment]) >> 8;
            if (head_along[segment] != INT16_MAX) {
                const float along = (float)head_along[segment];
                const float d = sqrtf((float)(off * off) + along * along) * (1.0f / 16.0f);
                const int head = (int)(256.0f * coverage(4.5f - d));
                if (head > lit) lit = head;
            }
            const int dim = (clamp_256((24 - distance) * 16) * (256 - lit)) >> 8;
            pixels[index] = ring_pixel(under, index, lit, dim, accent);
        }
    }
    invalidate_ring(reach);
}

static void clock_tick(int64_t now)
{
    const int64_t local = clock_offset_s + now / 1000000;
    if (local == clock_second_shown) return;
    const bool whole = clock_second_shown < 0 || local / 60 != clock_second_shown / 60;
    clock_second_shown = local;
    const time_t seconds = (time_t)local;
    struct tm fields;
    if (!gmtime_r(&seconds, &fields)) return;
    if (lvgl_mutex) xSemaphoreTake(lvgl_mutex, portMAX_DELAY);
    if (whole) {
        static const char *days[] = {"Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"};
        static const char *months[] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
        char text[24];
        /* The big font has only digits and a colon; AM or PM goes above. */
        if (clock_24h) {
            snprintf(text, sizeof(text), "%d:%02d", fields.tm_hour, fields.tm_min);
            lv_obj_add_flag(ampm_label, LV_OBJ_FLAG_HIDDEN);
        } else {
            const int hour = fields.tm_hour % 12 ? fields.tm_hour % 12 : 12;
            snprintf(text, sizeof(text), "%d:%02d", hour, fields.tm_min);
            lv_label_set_text(ampm_label, fields.tm_hour < 12 ? "AM" : "PM");
            lv_obj_clear_flag(ampm_label, LV_OBJ_FLAG_HIDDEN);
        }
        lv_label_set_text(clock_label, text);
        snprintf(text, sizeof(text), "%s %d %s", days[fields.tm_wday], fields.tm_mday,
                 months[fields.tm_mon]);
        lv_label_set_text(date_label, text);
        lv_obj_clear_flag(clock_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(date_label, LV_OBJ_FLAG_HIDDEN);
    }
    ring_second = fields.tm_sec;
    ring_now_us = now;
    draw_seconds_ring(ring_second, saver_shown == SAVER_BOTH && media_valid ? frame_pixels : NULL);
    if (lvgl_mutex) xSemaphoreGive(lvgl_mutex);
}

static void start_saver(int64_t now)
{
    saver_active = true;
    saver_shown = saver_kind;
    if (lvgl_mutex) xSemaphoreTake(lvgl_mutex, portMAX_DELAY);
    lv_obj_add_flag(battery_label, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(title_label, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(value_label, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(artist_label, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(time_label, LV_OBJ_FLAG_HIDDEN);
    if (saver_shown == SAVER_CLOCK) {
        fill_clock_face();
        lv_obj_invalidate(canvas);
    }
    /* clock_tick shows the time and date on its first pass. */
    clock_second_shown = -1;
    ring_second = -1;
    ring_full = true;
    if (lvgl_mutex) xSemaphoreGive(lvgl_mutex);
    /* Each time the screensaver starts it picks up with the next item. */
    if (saver_shown != SAVER_CLOCK) begin_saver_item(saver_item + 1, now);
    host_printf("SAVER,ON\n");
}

static void stop_saver(void)
{
    if (!saver_active) return;
    saver_active = false;
    if (lvgl_mutex) xSemaphoreTake(lvgl_mutex, portMAX_DELAY);
    free_ring_list();
    lv_obj_add_flag(clock_label, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(ampm_label, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(date_label, LV_OBJ_FLAG_HIDDEN);
    if (lvgl_mutex) xSemaphoreGive(lvgl_mutex);
    refresh_screen();
    host_printf("SAVER,OFF\n");
}

/* Whether the chosen screensaver has something to show. Pictures with the
   time run without the clock until the app has set it. */
static bool saver_ready(void)
{
    if (app_offline) return false;
    if (saver_kind == SAVER_CLOCK) return clock_valid;
    return media_valid && !media_busy;
}

/* Starts, advances and ends the screensaver; called from the main loop. */
static void saver_tick(int64_t now)
{
    if (saver_active && (!saver_enabled || !saver_ready() ||
                         saver_shown != saver_kind)) {
        stop_saver();
        return;
    }
    if (backlight_applied == 0) return;
    if (!saver_active) {
        if (saver_enabled && saver_ready() && !touch_active &&
            now - last_input_us >= (int64_t)saver_idle_s * 1000000) {
            start_saver(now);
        } else {
            return;
        }
    }
    if (saver_shown != SAVER_PICTURES && clock_valid) clock_tick(now);
    if (saver_shown != SAVER_PICTURES && clock_valid && saver_ring != RING_NONE &&
        ring_second >= 0 && now >= ring_next_us) {
        /* About 25 frames a second, so every style moves smoothly between seconds. */
        ring_next_us = now + (int64_t)screensaver_frame_ms(40, power_save_enabled) * 1000;
        ring_now_us = now;
        if (lvgl_mutex) xSemaphoreTake(lvgl_mutex, portMAX_DELAY);
        draw_seconds_ring(ring_second,
                          saver_shown == SAVER_BOTH && media_valid ? frame_pixels : NULL);
        if (lvgl_mutex) xSemaphoreGive(lvgl_mutex);
    }
    if (saver_shown == SAVER_CLOCK) return;
    if (now < saver_next_frame) return;

    const int64_t interval = (int64_t)saver_interval_s * 1000000;
    if (media_header.count > 1 && now - saver_item_start >= interval) {
        begin_saver_item(saver_item + 1, now);
    }
    const media_entry_t *entry = &media_entries[saver_item];
    uint32_t length = 0;
    const uint32_t end = entry->offset + entry->bytes;
    bool shown = false;
    if (saver_offset + 4 <= end &&
        esp_partition_read(media_partition, MEDIA_HEADER_BYTES + saver_offset,
                           &length, sizeof(length)) == ESP_OK &&
        length <= end - saver_offset - 4) {
        shown = show_saver_frame(saver_offset + 4, length);
    }
    if (!shown) {
        /* A damaged item is skipped rather than retried every frame. */
        host_printf("SAVER,BAD,%d\n", saver_item);
        if (media_header.count > 1) {
            begin_saver_item(saver_item + 1, now);
            saver_next_frame = now + 100000;
        } else {
            saver_next_frame = now + interval;
        }
        return;
    }
    if (entry->frames > 1) {
        saver_offset += 4 + ((length + 3) & ~3u);
        if (++saver_frame >= entry->frames) {
            saver_frame = 0;
            saver_offset = entry->offset;
        }
        const int frame_ms = entry->frame_ms ? entry->frame_ms : 100;
        /* Keep to the clip's own pace, time spent decoding included. */
        saver_next_frame += (int64_t)screensaver_frame_ms(frame_ms, power_save_enabled) * 1000;
        if (saver_next_frame < now) saver_next_frame = now;
    } else {
        /* A still stays until it is time for the next item. */
        saver_next_frame = media_header.count > 1 ? saver_item_start + interval
                                                  : INT64_MAX;
    }
}

static void battery_tick(int64_t now)
{
    static int64_t next_read;
    static esp_err_t reported_error = ESP_OK;
    if (!wireless_connected() || app_offline) {
        if (next_read == 0) return;
        next_read = 0;
        battery_mv = battery_percent = -1;
        reported_error = ESP_OK;
    } else if (now >= next_read) {
        next_read = now + 15000000;
        int raw, adc_mv;
        const esp_err_t err = voltage_read(&raw, &adc_mv);
        if (err != ESP_OK) {
            battery_mv = battery_percent = -1;
            if (err != reported_error) host_printf("BATTERY_ERR,%s\n", esp_err_to_name(err));
        } else {
            const int measured_mv = adc_mv * 2;
            if (voltage_estimated_percent(measured_mv) < 0) {
                battery_mv = measured_mv;
                battery_percent = -1;
            } else {
                battery_mv = battery_percent < 0 ? measured_mv :
                             (battery_mv * 3 + measured_mv + 2) / 4;
                battery_percent = voltage_estimated_percent(battery_mv);
            }
        }
        reported_error = err;
        host_printf("BATTERY,%d,%d\n", battery_mv, battery_percent);
    } else {
        return;
    }
    if (lvgl_mutex) xSemaphoreTake(lvgl_mutex, portMAX_DELAY);
    apply_battery_label();
    if (lvgl_mutex) xSemaphoreGive(lvgl_mutex);
}

/* Advances whatever is animating and reports whether the arc moved, so a still
   dial costs nothing at all. */
static bool dial_advance(void)
{
    if (show_menu || saver_active || app_offline) return false;

    if (mode_is_level(selected_mode)) {
        const int32_t target = (int32_t)selected_value << 8;
        if (dial_value_q8 == target) return false;
        const int32_t delta = target - dial_value_q8;
        dial_value_q8 += (delta > -192 && delta < 192) ? delta : delta / 4;
        return true;
    }

    if (selected_mode == MEDIA_MODE) {
        int head = 0;
        if (media_duration > 0) {
            head = (int)(((int64_t)media_elapsed() * GAUGE_SPAN) / media_duration);
        }
        if (head == media_head_shown) return false;
        media_head_shown = head;
        return true;
    }

    if (selected_mode == POMODORO_MODE) {
        const int head = (GAUGE_SPAN * pomo_fill_q8()) >> 8;
        if (head == media_head_shown) return false;
        media_head_shown = head;
        return true;
    }

    if (selected_mode == GAMES_MODE) {
        const int head = (GAUGE_SPAN * whack_fill_q8()) >> 8;
        if (head == media_head_shown) return false;
        media_head_shown = head;
        return true;
    }

    const int32_t delta = arc_target - arc_position;
    if (delta == 0) return false;
    arc_position += (delta > -COMET_SNAP_Q8 && delta < COMET_SNAP_Q8) ? delta : delta / 4;
    return true;
}

void app_main(void)
{
    load_settings();
    game_backdrop = heap_caps_malloc((size_t)LCD_WIDTH * LCD_HEIGHT * sizeof(uint16_t),
                                     MALLOC_CAP_SPIRAM);
    build_screen_tables();
    initialize_display();
    initialize_touch();
    encoder_queue = xQueueCreate(64, sizeof(int));
    assert(encoder_queue);
    initialize_encoder();
    initialize_lvgl();

    /* The driver gives the reader whole, flow-controlled lines, and lets
       printf give up instead of stalling when no one is listening. */
    usb_serial_jtag_driver_config_t usb_config = {
        .rx_buffer_size = 8192,
        .tx_buffer_size = 4096,
    };
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&usb_config));
    usb_serial_jtag_vfs_use_driver();

    media_partition = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, 0x40, "media");
    media_entries = heap_caps_malloc(MEDIA_MAX_ITEMS * sizeof(media_entry_t), MALLOC_CAP_SPIRAM);
    frame_jpeg = heap_caps_malloc(MEDIA_FRAME_MAX, MALLOC_CAP_SPIRAM);
    frame_pixels = heap_caps_malloc((size_t)LCD_WIDTH * LCD_HEIGHT * sizeof(uint16_t),
                                    MALLOC_CAP_SPIRAM);
    if (!frame_jpeg || !frame_pixels) media_partition = NULL;
    load_media();
    last_input_us = esp_timer_get_time();

    serial_queue = xQueueCreate(SERIAL_QUEUE_DEPTH, SERIAL_LINE_MAX);
    assert(serial_queue);
    dispatch_lock = xSemaphoreCreateMutex();
    assert(dispatch_lock);
    wireless_init(wireless_line);
    xTaskCreate(serial_reader_task, "serial_reader", 4096, NULL, 3, NULL);

    char command[SERIAL_LINE_MAX];
    int64_t last_hello = 0;
    int64_t last_frame = 0;
    for (;;) {
        while (xQueueReceive(serial_queue, command, 0) == pdTRUE) {
            handle_command(command);
        }
        int step;
        int pulses = 0;
        while (xQueueReceive(encoder_queue, &step, 0) == pdTRUE) {
            pulses += step;
        }
        /* Each detent on this knob emits two pulses about 70ms apart. Carry the
           undivided remainder, or a slow turn is discarded poll by poll and the
           knob feels dead. */
        encoder_accumulator += pulses;
        /* A half-detent left over from the previous direction would otherwise
           cancel the first pulse of the new one, losing a click on reversal. */
        if (pulses != 0 && (pulses > 0) != (encoder_accumulator > 0)) {
            encoder_accumulator = pulses;
        }
        int detents = encoder_accumulator / ENCODER_PULSES_PER_DETENT;
        encoder_accumulator -= detents * ENCODER_PULSES_PER_DETENT;
        const bool dark = backlight_applied == 0;
        if (pulses != 0) {
            last_input_us = esp_timer_get_time();
            apply_backlight();
        }
        if (pulses != 0 && dark) {
            /* The turn that lights a dark screen does nothing else. */
            encoder_accumulator = 0;
            detents = 0;
            if (saver_active) stop_saver();
        }
        if (app_offline) {
            /* Nothing to drive without the app; the turn only wakes the screen. */
            detents = 0;
        }
        if (detents != 0 && saver_active) {
            /* The turn that wakes the dial does nothing else. */
            stop_saver();
            detents = 0;
        }
        if (detents != 0 && show_menu) {
            /* In the menu the knob walks the highlight around the ring,
               clockwise with a clockwise turn. */
            menu_cursor = step_screen(menu_cursor, detents);
            host_printf("CURSOR,%d\n", menu_cursor);
            refresh_screen();
        } else if (detents != 0 && selected_mode == GAMES_MODE) {
            /* Games keep the knob to themselves; the PC hears nothing. */
            whack_rotate(detents);
        } else if (detents != 0) {
            host_printf("ROT,%d\n", detents);
            /* Scroll and zoom have no value to show, so the turn itself is the
               feedback: the comet follows the knob. Segments run anticlockwise
               and a positive detent is a clockwise turn, hence the minus. */
            if (!mode_is_level(selected_mode) && selected_mode != MEDIA_MODE &&
                selected_mode != POMODORO_MODE && selected_mode != GAMES_MODE) {
                arc_target -= detents * COMET_STEP_Q8;
                arc_direction = detents > 0 ? -1 : 1;
            }
        }
        poll_touch();
        const int64_t now = esp_timer_get_time();
        {
            const bool offline =
                !host_seen || (uint32_t)(now / 1000) - last_host_ms > APP_TIMEOUT_MS;
            if (offline != app_offline) {
                app_offline = offline;
                if (offline) {
                    /* A round or a screensaver must not carry on underneath. */
                    memset(whack_holes, 0, sizeof(whack_holes));
                    game_state = GAME_LOBBY;
                    stop_saver();
                } else {
                    /* The app (re)connected: start from the main menu. */
                    open_menu();
                    host_printf("MENU\n");
                }
                refresh_screen();
            }
        }
        whack_tick(now);
        battery_tick(now);
        apply_backlight();
        if (backlight_applied > 0 && now - last_frame >= 40000) {
            if (dial_advance()) draw_frame();
            if (selected_mode == POMODORO_MODE && pomo_running && !show_menu &&
                !saver_active && pomo_remaining_now() != pomo_shown) {
                refresh_text();
            }
            last_frame = now;
        }
        saver_tick(now);
        apply_backlight();
        if (now - last_hello >= 1000000) {
            host_printf("HELLO,REVO1,1\n");
            host_printf("VERSION,%s\n", REVO1_VERSION);
            host_printf("POWER,%d,%d\n", power_save_enabled, backlight_applied);
            if (!state_received) host_printf("SYNC\n");
            char network[96];
            wireless_status(network, sizeof(network));
            host_printf("%s\n", network);
            last_hello = now;
        }
        vTaskDelay(power_save_enabled ? pdMS_TO_TICKS(10) : 1);
    }
}
