/* Shared I2S0 clock domain: ES7210 mic ADC (2ch -> mono) + ES8311 speaker codec.
 * D5: 16 kHz / 16-bit, half-duplex (speaker amp GPIO46 LOW while capturing). */
#ifndef AUDIO_CODEC_H
#define AUDIO_CODEC_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "driver/i2c_master.h"
#include "esp_err.h"

#define AUDIO_RATE_HZ 16000
#define AUDIO_CHUNK_SAMPLES 320 /* 20 ms mono */
#define AUDIO_CHUNK_BYTES (AUDIO_CHUNK_SAMPLES * 2)

esp_err_t audio_init(i2c_master_bus_handle_t bus, uint8_t es7210_addr);
bool audio_ok(void);
/* Blocking read of one 20 ms mono chunk (stereo mic pair downmixed in place). */
esp_err_t audio_read_chunk(int16_t mono[AUDIO_CHUNK_SAMPLES]);
/* Map chunk RMS to 0..8 level bars. */
uint8_t audio_level_bars(const int16_t *mono, size_t n);
/* Play a short synthesized chime (1 START .. 6 CONFIRM). Blocks ~0.2-0.6 s. */
void audio_play_chime(uint8_t chime_id, uint8_t volume_pct);
void audio_set_capture(bool on);
/* Render a chime into mono samples, `n` samples starting at sample `pos` of the chime. Returns how many were
 * written (0 = the chime is over). Lets the audio task play an acknowledgement 20 ms at a time between mic reads. */
size_t audio_chime_fill(uint8_t chime_id, uint8_t volume_pct, uint32_t pos, int16_t *mono, size_t n);
/* The one exception to half-duplex: write mono PCM even while capturing (short acknowledgement chimes only;
 * the mic hears them). Turns the amp on; call audio_amp_off() when done. */
esp_err_t audio_write_mono_duplex(const int16_t *mono, size_t n);
/* Play mono 16 kHz PCM16 (host Piper voice) through ES8311; blocks for its real-time duration. */
esp_err_t audio_play_mono(const int16_t *mono, size_t n);
void audio_amp_off(void);

/* pure helper: average L/R into mono, n = stereo frames */
void audio_downmix(const int16_t *stereo, int16_t *mono, size_t n);

#endif
