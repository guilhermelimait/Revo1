#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define WIRELESS_KEY_BYTES 32

/* Called with each complete line that arrives over an authenticated
   wireless session, from that link's own task. */
typedef void (*wireless_line_fn)(char *line, size_t length);

/* Loads the pairing from NVS and, if paired, starts Bluetooth LE and (when a
   network is saved) Wi-Fi. */
void wireless_init(wireless_line_fn on_line);

/* Stores a new key and Wi-Fi network (an empty SSID means Bluetooth only),
   drops any open session and restarts the radios with them. */
bool wireless_pair(const uint8_t key[WIRELESS_KEY_BYTES], const char *ssid,
                   const char *password);

/* Forgets the key and the network and stops listening. */
void wireless_unpair(void);

/* Seals `text` and sends it over every authenticated session. */
void wireless_send(const char *text, size_t length);

/* "NET,<key id|->,<wifi state>,<ip|->,<name>,<links>" for the app:
   wifi state 0 off, 1 connecting, 2 connected, 3 wrong password,
   4 network not found; links has bit 0 for Wi-Fi and bit 1 for Bluetooth. */
void wireless_status(char *out, size_t size);
