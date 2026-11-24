#include "dev_config.h"

#include <stdio.h>
#include <string.h>

#include "json_mini.h"
#include "nvs.h"
#include "nvs_flash.h"

#define NS "pip"

esp_err_t dev_config_init(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        err = nvs_flash_init();
    }
    return err;
}

void dev_config_load(dev_config_t *c)
{
    memset(c, 0, sizeof *c);
    c->wake_on = true;
    snprintf(c->wake_word, sizeof c->wake_word, "hiesp");
    nvs_handle_t h;
    if (nvs_open(NS, NVS_READONLY, &h) != ESP_OK) {
        return;
    }
    size_t n = sizeof c->ssid;
    nvs_get_str(h, "ssid", c->ssid, &n);
    n = sizeof c->pass;
    nvs_get_str(h, "pass", c->pass, &n);
    n = sizeof c->token;
    c->has_token = nvs_get_blob(h, "token", c->token, &n) == ESP_OK && n == sizeof c->token;
    uint8_t on = 1;
    if (nvs_get_u8(h, "wake_on", &on) == ESP_OK) {
        c->wake_on = on != 0;
    }
    n = sizeof c->wake_word;
    nvs_get_str(h, "wake_word", c->wake_word, &n);
    nvs_close(h);
}

esp_err_t dev_config_save(const dev_config_t *c)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(NS, NVS_READWRITE, &h);
    if (err != ESP_OK) {
        return err;
    }
    nvs_set_str(h, "ssid", c->ssid);
    nvs_set_str(h, "pass", c->pass);
    if (c->has_token) {
        nvs_set_blob(h, "token", c->token, sizeof c->token);
    } else {
        nvs_erase_key(h, "token");
    }
    nvs_set_u8(h, "wake_on", c->wake_on ? 1 : 0);
    nvs_set_str(h, "wake_word", c->wake_word);
    err = nvs_commit(h);
    nvs_close(h);
    return err;
}

static int hexval(char ch)
{
    if (ch >= '0' && ch <= '9') return ch - '0';
    if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
    if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
    return -1;
}

bool dev_config_apply_json(dev_config_t *c, const char *json, size_t n, bool *wifi_changed, bool *wake_changed)
{
    *wifi_changed = *wake_changed = false;
    jm_span_t sp;
    bool clear = false;
    if (jm_get_bool(json, n, "wifi_clear", &clear) && clear) {
        c->ssid[0] = c->pass[0] = 0;
        *wifi_changed = true;
    }
    if (jm_find(json, n, "wifi", &sp)) {
        char ssid[sizeof c->ssid], pass[sizeof c->pass];
        if (jm_get_str(sp.p, sp.n, "ssid", ssid, sizeof ssid) && ssid[0]) {
            pass[0] = 0;
            (void)jm_get_str(sp.p, sp.n, "password", pass, sizeof pass);
            if (strcmp(ssid, c->ssid) != 0 || strcmp(pass, c->pass) != 0) {
                snprintf(c->ssid, sizeof c->ssid, "%s", ssid);
                snprintf(c->pass, sizeof c->pass, "%s", pass);
                *wifi_changed = true;
            }
        }
    }
    char hex[80];
    if (jm_get_str(json, n, "token", hex, sizeof hex) && strlen(hex) == 64) {
        uint8_t t[32];
        bool ok = true;
        for (int i = 0; i < 32 && ok; i++) {
            int hi = hexval(hex[2 * i]), lo = hexval(hex[2 * i + 1]);
            ok = hi >= 0 && lo >= 0;
            t[i] = (uint8_t)(hi << 4 | lo);
        }
        if (ok && (!c->has_token || memcmp(t, c->token, sizeof t) != 0)) {
            memcpy(c->token, t, sizeof t);
            c->has_token = true;
            *wifi_changed = true; /* drop any client authenticated with the old token */
        }
    }
    if (jm_find(json, n, "wake", &sp)) {
        bool on = c->wake_on;
        char word[sizeof c->wake_word];
        if (jm_get_bool(sp.p, sp.n, "enabled", &on) && on != c->wake_on) {
            c->wake_on = on;
            *wake_changed = true;
        }
        if (jm_get_str(sp.p, sp.n, "word", word, sizeof word) && word[0] && strcmp(word, c->wake_word) != 0) {
            snprintf(c->wake_word, sizeof c->wake_word, "%s", word);
            *wake_changed = true;
        }
    }
    return *wifi_changed || *wake_changed;
}
