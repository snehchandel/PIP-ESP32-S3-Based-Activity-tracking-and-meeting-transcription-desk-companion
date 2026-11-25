/* Structured built-in chimes: short soft sine phrases synthesized at 16 kHz. */
#include <math.h>
#include <string.h>

#include "audio_codec.h"
#include "esp_err.h"

esp_err_t audio_write_stereo(const int16_t *stereo, size_t frames);
void audio_amp_off(void);

typedef struct {
    uint16_t hz;
    uint16_t ms;
} note_t;

static const note_t CHIME_START_N[] = {{660, 90}, {880, 140}};
static const note_t CHIME_DONE_N[] = {{660, 90}, {830, 90}, {990, 180}};
static const note_t CHIME_PAUSE_N[] = {{700, 90}, {520, 140}};
static const note_t CHIME_ALARM_N[] = {{880, 140}, {0, 80}, {880, 140}, {0, 80}, {1175, 220}};
static const note_t CHIME_OFFLINE_N[] = {{520, 120}, {390, 160}};
static const note_t CHIME_CONFIRM_N[] = {{780, 80}, {1040, 120}};
static const note_t CHIME_NUDGE_N[] = {{587, 110}, {0, 60}, {587, 160}};          /* soft: "5 minutes left" */
static const note_t CHIME_WRAP_N[] = {{784, 100}, {659, 100}, {523, 220}};        /* falling: "wrap up" */

static void play_note(uint16_t hz, uint16_t ms, float amp)
{
    static int16_t buf[256 * 2];
    const float tau = 6.2831853f;
    uint32_t total = (uint32_t)AUDIO_RATE_HZ * ms / 1000u;
    uint32_t fade = AUDIO_RATE_HZ / 200u; /* 5 ms attack/release: no clicks */
    for (uint32_t done = 0; done < total;) {
        uint32_t n = total - done > 256 ? 256 : total - done;
        for (uint32_t i = 0; i < n; i++) {
            uint32_t k = done + i;
            float env = 1.0f;
            if (k < fade) {
                env = (float)k / (float)fade;
            } else if (total - k < fade) {
                env = (float)(total - k) / (float)fade;
            }
            float s = hz ? sinf(tau * (float)hz * (float)k / (float)AUDIO_RATE_HZ) * amp * env : 0.0f;
            int16_t v = (int16_t)(s * 32767.0f);
            buf[2 * i] = v;
            buf[2 * i + 1] = v;
        }
        if (audio_write_stereo(buf, n) != ESP_OK) {
            return;
        }
        done += n;
    }
}

static size_t chime_notes(uint8_t chime_id, const note_t **seq)
{
#define PICK(arr) do { *seq = arr; return sizeof arr / sizeof arr[0]; } while (0)
    switch (chime_id) {
    case 1: PICK(CHIME_START_N);
    case 2: PICK(CHIME_DONE_N);
    case 3: PICK(CHIME_PAUSE_N);
    case 4: PICK(CHIME_ALARM_N);
    case 5: PICK(CHIME_OFFLINE_N);
    case 6: PICK(CHIME_CONFIRM_N);
    case 7: PICK(CHIME_NUDGE_N);
    case 8: PICK(CHIME_WRAP_N);
    default: *seq = NULL; return 0;
    }
#undef PICK
}

size_t audio_chime_fill(uint8_t chime_id, uint8_t volume_pct, uint32_t pos, int16_t *mono, size_t n)
{
    const note_t *seq = NULL;
    size_t notes = chime_notes(chime_id, &seq);
    const float tau = 6.2831853f;
    const uint32_t fade = AUDIO_RATE_HZ / 200u; /* 5 ms attack/release: no clicks */
    float amp = 0.25f * (float)(volume_pct > 100 ? 100 : volume_pct) / 100.0f;
    size_t out = 0;
    uint32_t start = 0;
    for (size_t i = 0; i < notes && out < n; i++) {
        uint32_t total = (uint32_t)AUDIO_RATE_HZ * seq[i].ms / 1000u;
        while (out < n && pos < start + total) {
            uint32_t k = pos - start;
            float env = 1.0f;
            if (k < fade) {
                env = (float)k / (float)fade;
            } else if (total - k < fade) {
                env = (float)(total - k) / (float)fade;
            }
            float s = seq[i].hz ? sinf(tau * (float)seq[i].hz * (float)k / (float)AUDIO_RATE_HZ) * amp * env : 0.0f;
            mono[out++] = (int16_t)(s * 32767.0f);
            pos++;
        }
        start += total;
    }
    return out;
}

void audio_play_chime(uint8_t chime_id, uint8_t volume_pct)
{
    const note_t *seq = NULL;
    size_t n = chime_notes(chime_id, &seq);
    if (n == 0) {
        return;
    }
    float amp = 0.25f * (float)(volume_pct > 100 ? 100 : volume_pct) / 100.0f;
    for (size_t i = 0; i < n; i++) {
        play_note(seq[i].hz, seq[i].ms, amp);
    }
    play_note(0, 30, 0); /* flush tail silence before the amp turns off */
    audio_amp_off();
}
