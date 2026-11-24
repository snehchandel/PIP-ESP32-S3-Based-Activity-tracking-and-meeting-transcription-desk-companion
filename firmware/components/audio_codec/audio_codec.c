#include "audio_codec.h"

#include <math.h>
#include <string.h>

#include "board_pins.h"
#include "driver/gpio.h"
#include "driver/i2s_std.h"
#include "esp_codec_dev.h"
#include "esp_codec_dev_defaults.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static const char *TAG = "audio";
static esp_codec_dev_handle_t s_play, s_rec;
static i2s_chan_handle_t s_tx, s_rx;
static bool s_ok, s_capturing;
static SemaphoreHandle_t s_lock;

void audio_downmix(const int16_t *stereo, int16_t *mono, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        mono[i] = (int16_t)(((int32_t)stereo[2 * i] + (int32_t)stereo[2 * i + 1]) / 2);
    }
}

uint8_t audio_level_bars(const int16_t *mono, size_t n)
{
    double acc = 0;
    for (size_t i = 0; i < n; i++) {
        acc += (double)mono[i] * mono[i];
    }
    double rms = n ? sqrt(acc / (double)n) : 0;
    if (rms < 60) {
        return 0;
    }
    double db = 20.0 * log10(rms / 60.0); /* 0..~54 dB above the noise floor */
    int bars = (int)(db / 5.0) + 1;
    return (uint8_t)(bars > 8 ? 8 : bars);
}

static esp_err_t i2s_setup(void)
{
    i2s_chan_config_t ch = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    ch.auto_clear = true;
    esp_err_t err = i2s_new_channel(&ch, &s_tx, &s_rx);
    if (err != ESP_OK) {
        return err;
    }
    i2s_std_config_t std = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(AUDIO_RATE_HZ),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = PIN_I2S_MCLK,
            .bclk = PIN_I2S_BCLK,
            .ws = PIN_I2S_LRCLK,
            .dout = PIN_I2S_DOUT,
            .din = PIN_I2S_DIN,
        },
    };
    std.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_256;
    err = i2s_channel_init_std_mode(s_tx, &std);
    if (err == ESP_OK) {
        err = i2s_channel_init_std_mode(s_rx, &std);
    }
    return err;
}

esp_err_t audio_init(i2c_master_bus_handle_t bus, uint8_t es7210_addr)
{
    s_lock = xSemaphoreCreateMutex();
    gpio_config_t pa = {.pin_bit_mask = 1ULL << PIN_SPK_AMP_EN, .mode = GPIO_MODE_OUTPUT};
    gpio_config(&pa);
    gpio_set_level(PIN_SPK_AMP_EN, 0); /* amp off when idle: no hiss, less current */
    esp_err_t err = i2s_setup();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2s setup: %s", esp_err_to_name(err));
        return err;
    }
    audio_codec_i2s_cfg_t i2s_cfg = {.port = I2S_NUM_0, .rx_handle = s_rx, .tx_handle = s_tx};
    const audio_codec_data_if_t *data_if = audio_codec_new_i2s_data(&i2s_cfg);
    const audio_codec_gpio_if_t *gpio_if = audio_codec_new_gpio();

    audio_codec_i2c_cfg_t out_i2c = {.port = I2C_NUM_0, .addr = ES8311_CODEC_DEFAULT_ADDR, .bus_handle = bus};
    const audio_codec_ctrl_if_t *out_ctrl = audio_codec_new_i2c_ctrl(&out_i2c);
    es8311_codec_cfg_t es8311 = {
        .ctrl_if = out_ctrl,
        .gpio_if = gpio_if,
        .codec_mode = ESP_CODEC_DEV_WORK_MODE_DAC,
        .pa_pin = -1, /* GPIO46 gated by us (half-duplex policy) */
        .use_mclk = true,
    };
    es8311.hw_gain.pa_voltage = 5.0;
    es8311.hw_gain.codec_dac_voltage = 3.3;
    esp_codec_dev_cfg_t out_dev = {
        .dev_type = ESP_CODEC_DEV_TYPE_OUT, .codec_if = es8311_codec_new(&es8311), .data_if = data_if};
    s_play = esp_codec_dev_new(&out_dev);

    uint8_t addr7 = es7210_addr ? es7210_addr : I2C_ADDR_ES7210;
    audio_codec_i2c_cfg_t in_i2c = {.port = I2C_NUM_0, .addr = (uint8_t)(addr7 << 1), .bus_handle = bus};
    es7210_codec_cfg_t es7210 = {
        .ctrl_if = audio_codec_new_i2c_ctrl(&in_i2c),
        .mic_selected = ES7120_SEL_MIC1 | ES7120_SEL_MIC2 /* sic: library spelling */,
    };
    esp_codec_dev_cfg_t in_dev = {
        .dev_type = ESP_CODEC_DEV_TYPE_IN, .codec_if = es7210_codec_new(&es7210), .data_if = data_if};
    s_rec = esp_codec_dev_new(&in_dev);
    if (!s_play || !s_rec) {
        ESP_LOGE(TAG, "codec device creation failed");
        return ESP_FAIL;
    }
    esp_codec_dev_sample_info_t fs = {.sample_rate = AUDIO_RATE_HZ, .channel = 2, .bits_per_sample = 16};
    if (esp_codec_dev_open(s_play, &fs) != ESP_CODEC_DEV_OK || esp_codec_dev_open(s_rec, &fs) != ESP_CODEC_DEV_OK) {
        ESP_LOGE(TAG, "codec open failed");
        return ESP_FAIL;
    }
    esp_codec_dev_set_out_vol(s_play, 70);
    esp_codec_dev_set_in_gain(s_rec, 30.0f);
    s_ok = true;
    ESP_LOGI(TAG, "ES8311 + ES7210(0x%02X) ready", addr7);
    return ESP_OK;
}

bool audio_ok(void) { return s_ok; }

void audio_set_capture(bool on)
{
    s_capturing = on;
    if (on) {
        gpio_set_level(PIN_SPK_AMP_EN, 0);
    }
}

esp_err_t audio_read_chunk(int16_t mono[AUDIO_CHUNK_SAMPLES])
{
    static int16_t stereo[AUDIO_CHUNK_SAMPLES * 2];
    if (!s_ok) {
        return ESP_ERR_INVALID_STATE;
    }
    if (esp_codec_dev_read(s_rec, stereo, sizeof stereo) != ESP_CODEC_DEV_OK) {
        return ESP_FAIL;
    }
    audio_downmix(stereo, mono, AUDIO_CHUNK_SAMPLES);
    return ESP_OK;
}

esp_err_t audio_write_stereo(const int16_t *stereo, size_t frames)
{
    if (!s_ok || s_capturing) {
        return ESP_ERR_INVALID_STATE; /* half-duplex: never play while the mic is live */
    }
    xSemaphoreTake(s_lock, portMAX_DELAY);
    gpio_set_level(PIN_SPK_AMP_EN, 1);
    int r = esp_codec_dev_write(s_play, (void *)stereo, (int)(frames * 4));
    xSemaphoreGive(s_lock);
    return r == ESP_CODEC_DEV_OK ? ESP_OK : ESP_FAIL;
}

void audio_amp_off(void) { gpio_set_level(PIN_SPK_AMP_EN, 0); }
