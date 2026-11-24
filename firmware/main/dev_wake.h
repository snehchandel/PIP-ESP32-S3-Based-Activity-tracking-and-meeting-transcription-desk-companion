/* On-device wake word (Espressif ESP-SR WakeNet9). The audio task feeds idle microphone audio (never while PIP
 * itself is speaking or chiming); a detector task runs the model and calls back on a hit. Mic audio never leaves
 * the device until the wake word is heard. Words are stock Espressif models stored in the "model" partition. */
#ifndef DEV_WAKE_H
#define DEV_WAKE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef void (*dev_wake_cb_t)(int source, void *ctx); /* source 0 = microphone, 1 = test injection */

bool dev_wake_init(dev_wake_cb_t cb, void *ctx); /* false: no models flashed */
void dev_wake_configure(bool enabled, const char *word);
bool dev_wake_active(void);
void dev_wake_feed(const int16_t *pcm, size_t n);      /* from the audio task */
void dev_wake_test_feed(const int16_t *pcm, size_t n); /* PIP_WAKE_TEST frames from the PC */
int dev_wake_status_json(char *out, size_t cap);

#endif
