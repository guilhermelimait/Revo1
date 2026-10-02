#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define WIRELESS_KEY_BYTES 32

/* Called with each complete line that arrives over an authenticated
   wireless session, from that link's own task. */
typedef void (*wireless_line_fn)(char *line, size_t length);

/* Loads the pairing from NVS and, if paired, starts Bluetooth LE. */
void wireless_init(wireless_line_fn on_line);

/* Stores a new key, drops any open session and starts Bluetooth with it. */
bool wireless_pair(const uint8_t key[WIRELESS_KEY_BYTES]);

/* Forgets the key and stops listening. */
void wireless_unpair(void);

/* Seals `text` and sends it over every authenticated session. */
void wireless_send(const char *text, size_t length);

/* "NET,<key id|->,<name>,<1 if the app is linked over Bluetooth, else 0>". */
void wireless_status(char *out, size_t size);
