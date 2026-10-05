#include "launcher.h"

#include <stdlib.h>
#include <string.h>
#include "esp_heap_caps.h"
#include "mbedtls/base64.h"

typedef struct {
    uint8_t mask;
    char token[9];
    char names[LAUNCHER_SLOTS][41];
    uint8_t icons[LAUNCHER_SLOTS][LAUNCHER_ICON_BYTES];
    int received[LAUNCHER_SLOTS];
    uint8_t stride[LAUNCHER_SLOTS];
} launcher_snapshot_t;

static launcher_snapshot_t *active;
static launcher_snapshot_t *pending;
static bool receiving;

static bool integer(const char *text, int maximum, int *out)
{
    if (!text || !*text) return false;
    char *end;
    const long value = strtol(text, &end, 10);
    if (*end || value < 0 || value > maximum) return false;
    *out = (int)value;
    return true;
}

static bool valid_token(const char *text)
{
    return text && strlen(text) == 8 && strspn(text, "0123456789abcdef") == 8;
}

static const char *error(void)
{
    receiving = false;
    return "LAUNCHER_ERR,FORMAT";
}

const char *launcher_receive(char *line)
{
    char *save;
    const char *command = strtok_r(line, ",", &save);
    const char *first = strtok_r(NULL, ",", &save);
    const char *second = strtok_r(NULL, ",", &save);
    if (!command || !first || !second) return error();
    if (strcmp(command, "LBEGIN") == 0) {
        int mask;
        if (!valid_token(first) || !integer(second, 127, &mask) ||
            strtok_r(NULL, ",", &save)) return error();
        if (!pending) pending = heap_caps_calloc(1, sizeof(*pending), MALLOC_CAP_SPIRAM);
        if (!pending) {
            receiving = false;
            return "LAUNCHER_ERR,MEMORY";
        }
        memset(pending, 0, sizeof(*pending));
        memcpy(pending->token, first, 9);
        pending->mask = (uint8_t)mask;
        receiving = true;
        return "LAUNCHER_ACK";
    }
    int slot;
    if (!receiving || !integer(first, LAUNCHER_SLOTS - 1, &slot) ||
        !(pending->mask & (1u << slot))) return error();
    if (strcmp(command, "LITEM") == 0) {
        size_t bytes;
        const char *format = strtok_r(NULL, ",", &save);
        if (pending->names[slot][0] || (format && strcmp(format, "RGB565A8")) ||
            strtok_r(NULL, ",", &save) ||
            mbedtls_base64_decode((uint8_t *)pending->names[slot], 40, &bytes,
                                  (const uint8_t *)second, strlen(second)) != 0 ||
            bytes == 0) return error();
        for (size_t i = 0; i < bytes; ++i) {
            if (pending->names[slot][i] < 32 || pending->names[slot][i] > 126) return error();
        }
        pending->names[slot][bytes] = '\0';
        pending->stride[slot] = format ? 3 : 2;
        return "LAUNCHER_ACK";
    }
    if (strcmp(command, "LDATA") == 0) {
        const char *data = strtok_r(NULL, ",", &save);
        int offset;
        size_t bytes;
        const int expected = LAUNCHER_ICON_SIZE * LAUNCHER_ICON_SIZE * pending->stride[slot];
        if (!pending->names[slot][0] || !integer(second, expected - 1, &offset) ||
            offset != pending->received[slot] || !data || strtok_r(NULL, ",", &save) ||
            mbedtls_base64_decode(pending->icons[slot] + offset,
                                  expected - offset, &bytes,
                                  (const uint8_t *)data, strlen(data)) != 0 || bytes == 0) {
            return error();
        }
        pending->received[slot] += (int)bytes;
        return "LAUNCHER_ACK";
    }
    return error();
}

const char *launcher_commit(const char *token)
{
    if (!receiving || !valid_token(token) || strcmp(token, pending->token)) return error();
    for (int slot = 0; slot < LAUNCHER_SLOTS; ++slot) {
        if ((pending->mask & (1u << slot)) &&
            (!pending->names[slot][0] || pending->received[slot] !=
             LAUNCHER_ICON_SIZE * LAUNCHER_ICON_SIZE * pending->stride[slot])) {
            return error();
        }
    }
    launcher_snapshot_t *old = active;
    active = pending;
    pending = old;
    receiving = false;
    return NULL;
}

int launcher_count(void)
{
    return active ? __builtin_popcount(active->mask) : 0;
}

int launcher_slot(int ordinal)
{
    if (!active) return -1;
    for (int slot = 0; slot < LAUNCHER_SLOTS; ++slot) {
        if ((active->mask & (1u << slot)) && ordinal-- == 0) return slot;
    }
    return -1;
}

const char *launcher_name(int slot)
{
    return active && slot >= 0 && slot < LAUNCHER_SLOTS ? active->names[slot] : "";
}

const uint8_t *launcher_icon(int slot)
{
    return active && slot >= 0 && slot < LAUNCHER_SLOTS &&
           (active->mask & (1u << slot)) ? active->icons[slot] : NULL;
}

const char *launcher_token(void)
{
    return active ? active->token : "";
}

int launcher_icon_stride(int slot)
{
    return active && slot >= 0 && slot < LAUNCHER_SLOTS ? active->stride[slot] : 0;
}
