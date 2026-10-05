#pragma once

#include <stdbool.h>
#include <stdint.h>

#define LAUNCHER_SLOTS 7
#define LAUNCHER_ICON_SIZE 64
#define LAUNCHER_ICON_BYTES (LAUNCHER_ICON_SIZE * LAUNCHER_ICON_SIZE * 3)

/* Incoming staging lines do not touch the displayed snapshot. Commit runs
   on the UI task, so a partially transferred icon can never be displayed. */
const char *launcher_receive(char *line);
const char *launcher_commit(const char *token);
int launcher_count(void);
int launcher_slot(int ordinal);
const char *launcher_name(int slot);
const uint8_t *launcher_icon(int slot);
int launcher_icon_stride(int slot);
const char *launcher_token(void);
