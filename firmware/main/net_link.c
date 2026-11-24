#include "net_link.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "lwip/sockets.h"
#include "mbedtls/md.h"
#include "mdns.h"

static const char *TAG = "net";

typedef enum { NET_OFF = 0, NET_CONNECTING, NET_UP, NET_FAILED } net_state_t;
static const char *const STATE_NAMES[] = {"OFF", "CONNECTING", "UP", "FAILED"};

static net_frame_cb_t s_cb;
static void *s_ctx;
static dev_config_t s_cfg;
static SemaphoreHandle_t s_tx_lock;
static volatile net_state_t s_state = NET_OFF;
static volatile int s_client = -1;
static volatile bool s_authed;
static volatile int8_t s_rssi;
static char s_ip[16];
static char s_host[16];
static uint8_t s_mac[6];
static uint8_t s_nonce[16];
static uint8_t s_tx[PIP_MAX_FRAME];
static pip_parser_t s_parser;
static uint32_t s_failures;
static esp_timer_handle_t s_retry;
static bool s_wifi_ready;

static uint32_t now_ms(void) { return (uint32_t)(esp_timer_get_time() / 1000); }

static void drop_client(void)
{
    int c = s_client;
    s_authed = false;
    s_client = -1;
    if (c >= 0) {
        shutdown(c, SHUT_RDWR);
    }
}

static void retry_cb(void *arg) { esp_wifi_connect(); }

static void on_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        if (s_cfg.ssid[0]) {
            s_state = NET_CONNECTING;
            esp_wifi_connect();
        }
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        s_ip[0] = 0;
        drop_client();
        if (!s_cfg.ssid[0]) {
            s_state = NET_OFF;
            return;
        }
        s_failures++;
        s_state = s_failures > 6 ? NET_FAILED : NET_CONNECTING;
        /* back off: 1 s, 2 s, 4 s ... capped at 30 s (wrong password must not spin the radio) */
        uint64_t delay_ms = 1000ull << (s_failures > 5 ? 5 : s_failures);
        delay_ms = delay_ms > 30000 ? 30000 : delay_ms;
        esp_timer_stop(s_retry);
        esp_timer_start_once(s_retry, delay_ms * 1000ull);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *e = (const ip_event_got_ip_t *)data;
        snprintf(s_ip, sizeof s_ip, IPSTR, IP2STR(&e->ip_info.ip));
        s_failures = 0;
        s_state = NET_UP;
        ESP_LOGI(TAG, "wifi up: %s (%s.local)", s_ip, s_host);
    }
}

static bool verify(const uint8_t *mac32)
{
    if (!s_cfg.has_token) {
        return false;
    }
    uint8_t want[32];
    if (mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), s_cfg.token, sizeof s_cfg.token, s_nonce,
                        sizeof s_nonce, want) != 0) {
        return false;
    }
    uint8_t diff = 0; /* constant time */
    for (int i = 0; i < 32; i++) {
        diff |= (uint8_t)(want[i] ^ mac32[i]);
    }
    return diff == 0;
}

static bool raw_send(int c, uint8_t type, uint8_t flags, uint16_t seq, const uint8_t *p, uint16_t len)
{
    xSemaphoreTake(s_tx_lock, portMAX_DELAY);
    size_t n = pip_encode(type, flags, seq, p, len, s_tx, sizeof s_tx);
    bool ok = n > 0;
    for (size_t off = 0; ok && off < n;) {
        int w = send(c, s_tx + off, n - off, 0);
        if (w <= 0) {
            ok = false;
        } else {
            off += (size_t)w;
        }
    }
    xSemaphoreGive(s_tx_lock);
    return ok;
}

static void serve_client(int c)
{
    int one = 1;
    setsockopt(c, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    struct timeval rt = {.tv_sec = 0, .tv_usec = 50000}, st = {.tv_sec = 2, .tv_usec = 0};
    setsockopt(c, SOL_SOCKET, SO_RCVTIMEO, &rt, sizeof rt);
    setsockopt(c, SOL_SOCKET, SO_SNDTIMEO, &st, sizeof st);
    pip_parser_init(&s_parser);
    esp_fill_random(s_nonce, sizeof s_nonce);
    s_authed = false;
    s_client = c;
    uint8_t hello[22];
    memcpy(hello, s_nonce, 16);
    memcpy(hello + 16, s_mac, 6);
    raw_send(c, PIP_AUTH_CHALLENGE, 0, 0, hello, sizeof hello);
    uint32_t t0 = now_ms();
    static uint8_t buf[1024];
    pip_frame_t f;
    for (;;) {
        int n = recv(c, buf, sizeof buf, 0);
        if (n == 0) {
            break; /* peer closed */
        }
        if (n < 0) {
            if (errno != EAGAIN && errno != EWOULDBLOCK) {
                break;
            }
            if (!s_authed && now_ms() - t0 > 5000u) {
                ESP_LOGW(TAG, "client did not authenticate");
                break;
            }
            while (s_parser.len > 0 && pip_parser_idle(&s_parser, &f)) {
                if (s_authed && s_cb) s_cb(&f, s_ctx);
            }
            if (s_client < 0) break; /* dropped elsewhere (Wi-Fi lost / new token) */
            continue;
        }
        for (int i = 0; i < n; i++) {
            if (!pip_parser_feed(&s_parser, buf[i], &f)) {
                continue;
            }
            if (s_authed) {
                if (s_cb) s_cb(&f, s_ctx);
            } else if (f.type == PIP_AUTH_RESPONSE && f.len == 32 && verify(f.payload)) {
                s_authed = true;
                ESP_LOGI(TAG, "PC authenticated over Wi-Fi");
            } else {
                ESP_LOGW(TAG, "rejected unauthenticated frame 0x%02x", f.type);
                s_client = -1;
                break;
            }
        }
        if (s_client < 0) break;
    }
    s_authed = false;
    s_client = -1;
    close(c);
}

static void server_task(void *arg)
{
    for (;;) {
        if (s_state != NET_UP) {
            vTaskDelay(pdMS_TO_TICKS(500));
            continue;
        }
        int ls = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
        if (ls < 0) {
            vTaskDelay(pdMS_TO_TICKS(1000));
            continue;
        }
        int one = 1;
        setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
        struct sockaddr_in addr = {.sin_family = AF_INET, .sin_port = htons(PIP_TCP_PORT), .sin_addr.s_addr = htonl(INADDR_ANY)};
        if (bind(ls, (struct sockaddr *)&addr, sizeof addr) != 0 || listen(ls, 1) != 0) {
            close(ls);
            vTaskDelay(pdMS_TO_TICKS(1000));
            continue;
        }
        while (s_state == NET_UP) {
            fd_set rf;
            FD_ZERO(&rf);
            FD_SET(ls, &rf);
            struct timeval tv = {.tv_sec = 1, .tv_usec = 0};
            if (select(ls + 1, &rf, NULL, NULL, &tv) <= 0) {
                continue;
            }
            int c = accept(ls, NULL, NULL);
            if (c >= 0) {
                serve_client(c); /* one PC at a time */
            }
        }
        close(ls);
    }
}

static void rssi_task(void *arg)
{
    for (;;) {
        wifi_ap_record_t ap;
        if (s_state == NET_UP && esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
            s_rssi = ap.rssi;
        }
        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}

static void configure(void)
{
    wifi_config_t wc = {0};
    /* SSID is up to 32 bytes and the passphrase up to 64, not necessarily NUL-terminated in wifi_config_t */
    memcpy(wc.sta.ssid, s_cfg.ssid, strnlen(s_cfg.ssid, sizeof wc.sta.ssid));
    memcpy(wc.sta.password, s_cfg.pass, strnlen(s_cfg.pass, sizeof wc.sta.password));
    wc.sta.threshold.authmode = s_cfg.pass[0] ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    wc.sta.pmf_cfg.capable = true;
    esp_wifi_set_config(WIFI_IF_STA, &wc);
}

void net_link_init(const dev_config_t *cfg, net_frame_cb_t cb, void *ctx)
{
    s_cfg = *cfg;
    s_cb = cb;
    s_ctx = ctx;
    s_tx_lock = xSemaphoreCreateMutex();
    esp_read_mac(s_mac, ESP_MAC_WIFI_STA);
    snprintf(s_host, sizeof s_host, "pip-%02x%02x", s_mac[4], s_mac[5]);
    if (esp_netif_init() != ESP_OK || esp_event_loop_create_default() != ESP_OK) {
        ESP_LOGE(TAG, "netif init failed");
        return;
    }
    esp_netif_t *sta = esp_netif_create_default_wifi_sta();
    esp_netif_set_hostname(sta, s_host);
    wifi_init_config_t wic = WIFI_INIT_CONFIG_DEFAULT();
    if (esp_wifi_init(&wic) != ESP_OK) {
        ESP_LOGE(TAG, "wifi init failed");
        return;
    }
    esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_event, NULL);
    esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_event, NULL);
    const esp_timer_create_args_t ta = {.callback = retry_cb, .name = "wifi_retry"};
    esp_timer_create(&ta, &s_retry);
    esp_wifi_set_storage(WIFI_STORAGE_RAM); /* credentials live in our own NVS namespace */
    esp_wifi_set_mode(WIFI_MODE_STA);
    configure();
    esp_wifi_start();
    esp_wifi_set_ps(WIFI_PS_NONE); /* USB powered; lowest latency for voice */
    s_wifi_ready = true;
    if (mdns_init() == ESP_OK) {
        mdns_hostname_set(s_host);
        mdns_instance_name_set("PIP focus companion");
        mdns_txt_item_t txt[1] = {{"proto", "1"}};
        mdns_service_add(NULL, "_pip", "_tcp", PIP_TCP_PORT, txt, 1);
    }
    xTaskCreatePinnedToCore(server_task, "net_srv", 6144, NULL, 5, NULL, 0);
    xTaskCreatePinnedToCore(rssi_task, "net_rssi", 2560, NULL, 2, NULL, 0);
}

void net_link_apply(const dev_config_t *cfg)
{
    s_cfg = *cfg;
    if (!s_wifi_ready) {
        return;
    }
    drop_client();
    esp_timer_stop(s_retry);
    s_failures = 0;
    esp_wifi_disconnect();
    configure();
    if (s_cfg.ssid[0]) {
        s_state = NET_CONNECTING;
        esp_wifi_connect();
    } else {
        s_state = NET_OFF;
    }
}

void net_link_send(uint8_t type, uint8_t flags, uint16_t seq, const uint8_t *payload, uint16_t len)
{
    int c = s_client;
    if (c < 0 || !s_authed) {
        return;
    }
    if (!raw_send(c, type, flags, seq, payload, len)) {
        drop_client();
    }
}

bool net_link_client_ready(void) { return s_client >= 0 && s_authed; }

static void json_safe(char *dst, size_t cap, const char *src)
{
    size_t o = 0;
    for (; *src && o + 1 < cap; src++) {
        unsigned char ch = (unsigned char)*src;
        dst[o++] = (ch < 0x20 || ch == '"' || ch == '\\') ? '_' : (char)ch;
    }
    dst[o] = 0;
}

int net_link_status_json(char *out, size_t cap)
{
    char ssid[40];
    json_safe(ssid, sizeof ssid, s_cfg.ssid);
    return snprintf(out, cap,
                    "\"wifi\":{\"configured\":%s,\"paired\":%s,\"state\":\"%s\",\"ssid\":\"%s\",\"ip\":\"%s\","
                    "\"host\":\"%s.local\",\"port\":%d,\"rssi\":%d,\"client\":%s}",
                    s_cfg.ssid[0] ? "true" : "false", s_cfg.has_token ? "true" : "false", STATE_NAMES[s_state], ssid,
                    s_ip, s_host, PIP_TCP_PORT, (int)s_rssi, net_link_client_ready() ? "true" : "false");
}
