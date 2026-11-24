#include "rlcd_display.h"

#include <string.h>

#include "board_pins.h"
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_heap_caps.h"
#include "esp_lcd_panel_io.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "rlcd";
static esp_lcd_panel_io_handle_t s_io;
static uint8_t *s_panel; /* DMA-capable panel RAM image */

#define RLCD_SPI_HOST SPI2_HOST
#define RLCD_PCLK_HZ (10 * 1000 * 1000) /* start 10 MHz (spec: 20 MHz max) */

static void cmd(uint8_t c, const uint8_t *data, size_t n)
{
    ESP_ERROR_CHECK(esp_lcd_panel_io_tx_param(s_io, c, data, n));
}

#define CMD(c, ...)                                         \
    do {                                                    \
        static const uint8_t d_[] = {__VA_ARGS__};          \
        cmd((c), d_, sizeof d_);                            \
    } while (0)

void rlcd_display_convert(const rlcd_fb_t *fb, uint8_t *panel)
{
    /* Landscape mapping (verified against vendor LUT): logical (x, y) ->
     * inv_y = 299 - y; index = (x / 2) * 75 + inv_y / 4; bit = 7 - ((inv_y % 4) * 2 + x % 2) */
    for (int bx = 0; bx < RLCD_W / 2; bx++) {
        for (int by = 0; by < RLCD_H / 4; by++) {
            uint8_t out = 0;
            for (int ly = 0; ly < 4; ly++) {
                int y = RLCD_H - 1 - (by * 4 + ly);
                const uint8_t *row = &fb->px[y * RLCD_STRIDE];
                for (int lx = 0; lx < 2; lx++) {
                    int x = bx * 2 + lx;
                    int black = (row[x >> 3] >> (7 - (x & 7))) & 1;
                    if (!black) { /* panel: 1 = white */
                        out = (uint8_t)(out | (1u << (7 - (ly * 2 + lx))));
                    }
                }
            }
            panel[bx * (RLCD_H / 4) + by] = out;
        }
    }
}

static void panel_reset(void)
{
    gpio_set_level(PIN_RLCD_RST, 1);
    vTaskDelay(pdMS_TO_TICKS(50));
    gpio_set_level(PIN_RLCD_RST, 0);
    vTaskDelay(pdMS_TO_TICKS(20));
    gpio_set_level(PIN_RLCD_RST, 1);
    vTaskDelay(pdMS_TO_TICKS(50));
}

static void panel_init_sequence(void)
{
    CMD(0xD6, 0x17, 0x02);                  /* NVM load control */
    CMD(0xD1, 0x01);                        /* booster enable */
    CMD(0xC0, 0x11, 0x04);                  /* gate voltage */
    CMD(0xC1, 0x69, 0x69, 0x69, 0x69);      /* VSHP */
    CMD(0xC2, 0x19, 0x19, 0x19, 0x19);      /* VSLP */
    CMD(0xC4, 0x4B, 0x4B, 0x4B, 0x4B);      /* VSHN */
    CMD(0xC5, 0x19, 0x19, 0x19, 0x19);      /* VSLN */
    CMD(0xD8, 0x80, 0xE9);                  /* OSC */
    CMD(0xB2, 0x02);                        /* frame rate */
    CMD(0xB3, 0xE5, 0xF6, 0x05, 0x46, 0x77, 0x77, 0x77, 0x77, 0x76, 0x45);
    CMD(0xB4, 0x05, 0x46, 0x77, 0x77, 0x77, 0x77, 0x76, 0x45);
    CMD(0x62, 0x32, 0x03, 0x1F);
    CMD(0xB7, 0x13);
    CMD(0xB0, 0x64);
    cmd(0x11, NULL, 0); /* sleep out */
    vTaskDelay(pdMS_TO_TICKS(200));
    CMD(0xC9, 0x00);
    CMD(0x36, 0x48); /* MADCTL */
    CMD(0x3A, 0x11); /* pixel format */
    CMD(0xB9, 0x20);
    CMD(0xB8, 0x29);
    cmd(0x21, NULL, 0); /* inversion on */
    CMD(0x2A, 0x12, 0x2A);
    CMD(0x2B, 0x00, 0xC7);
    CMD(0x35, 0x00); /* TE on */
    CMD(0xD0, 0xFF);
    cmd(0x38, NULL, 0); /* high power mode off */
    cmd(0x29, NULL, 0); /* display on */
}

esp_err_t rlcd_display_init(void)
{
    spi_bus_config_t bus = {
        .mosi_io_num = PIN_RLCD_MOSI,
        .miso_io_num = -1,
        .sclk_io_num = PIN_RLCD_SCLK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = RLCD_FB_BYTES,
    };
    esp_err_t err = spi_bus_initialize(RLCD_SPI_HOST, &bus, SPI_DMA_CH_AUTO);
    if (err != ESP_OK) {
        return err;
    }
    esp_lcd_panel_io_spi_config_t io = {
        .dc_gpio_num = PIN_RLCD_DC,
        .cs_gpio_num = PIN_RLCD_CS,
        .pclk_hz = RLCD_PCLK_HZ,
        .lcd_cmd_bits = 8,
        .lcd_param_bits = 8,
        .spi_mode = 0,
        .trans_queue_depth = 4,
    };
    err = esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)RLCD_SPI_HOST, &io, &s_io);
    if (err != ESP_OK) {
        return err;
    }
    gpio_config_t rst = {.pin_bit_mask = 1ULL << PIN_RLCD_RST, .mode = GPIO_MODE_OUTPUT};
    gpio_config(&rst);
    s_panel = heap_caps_malloc(RLCD_FB_BYTES, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    if (!s_panel) {
        return ESP_ERR_NO_MEM;
    }
    panel_reset();
    panel_init_sequence();
    ESP_LOGI(TAG, "ST7305 ready (%d Hz SPI)", RLCD_PCLK_HZ);
    return ESP_OK;
}

esp_err_t rlcd_display_flush(const rlcd_fb_t *fb)
{
    if (!s_io || !s_panel) {
        return ESP_ERR_INVALID_STATE;
    }
    rlcd_display_convert(fb, s_panel);
    CMD(0x2A, 0x12, 0x2A); /* column address window */
    CMD(0x2B, 0x00, 0xC7); /* page address window */
    return esp_lcd_panel_io_tx_color(s_io, 0x2C, s_panel, RLCD_FB_BYTES);
}
