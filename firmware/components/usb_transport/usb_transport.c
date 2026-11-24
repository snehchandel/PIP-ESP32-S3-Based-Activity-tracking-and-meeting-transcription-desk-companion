#include "usb_transport.h"

#include "driver/usb_serial_jtag.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

static const char *TAG = "usb";
static usb_frame_cb_t s_cb;
static void *s_ctx;
static SemaphoreHandle_t s_tx_lock;
static pip_parser_t s_parser;
static uint8_t s_tx[PIP_MAX_FRAME];

static void rx_task(void *arg)
{
    static uint8_t buf[512];
    pip_frame_t f;
    for (;;) {
        int n = usb_serial_jtag_read_bytes(buf, sizeof buf, pdMS_TO_TICKS(20));
        for (int i = 0; i < n; i++) {
            if (pip_parser_feed(&s_parser, buf[i], &f) && s_cb) {
                s_cb(&f, s_ctx);
            }
        }
        if (n <= 0 && s_parser.len > 0) {
            /* 20 ms of silence with a partial frame buffered: it can never complete, resync */
            while (pip_parser_idle(&s_parser, &f)) {
                if (s_cb) {
                    s_cb(&f, s_ctx);
                }
            }
        }
    }
}

esp_err_t usb_transport_init(usb_frame_cb_t cb, void *ctx)
{
    s_cb = cb;
    s_ctx = ctx;
    pip_parser_init(&s_parser);
    s_tx_lock = xSemaphoreCreateMutex();
    usb_serial_jtag_driver_config_t cfg = {
        .rx_buffer_size = 8192,
        .tx_buffer_size = 8192,
    };
    esp_err_t err = usb_serial_jtag_driver_install(&cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "driver install failed: %s", esp_err_to_name(err));
        return err;
    }
    /* Core 0: USB + protocol (spec 3.2 core pinning) */
    xTaskCreatePinnedToCore(rx_task, "usb_rx", 4096, NULL, 6, NULL, 0);
    return ESP_OK;
}

bool usb_transport_host_connected(void) { return usb_serial_jtag_is_connected(); }

uint32_t usb_transport_crc_errors(void) { return s_parser.crc_errors; }

void usb_transport_send(uint8_t type, uint8_t flags, uint16_t seq, const uint8_t *payload, uint16_t len)
{
    if (!s_tx_lock || !usb_serial_jtag_is_connected()) {
        return;
    }
    xSemaphoreTake(s_tx_lock, portMAX_DELAY);
    size_t n = pip_encode(type, flags, seq, payload, len, s_tx, sizeof s_tx);
    if (n) {
        usb_serial_jtag_write_bytes(s_tx, n, pdMS_TO_TICKS(100));
    }
    xSemaphoreGive(s_tx_lock);
}
