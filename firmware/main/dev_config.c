#include "dev_config.h"

#include <stdio.h>
#include <string.h>

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

/* slot 0 keeps the keys of firmware <= 1.7 ("ssid"/"pass"), so an update keeps the home network */
static void net_keys(int i, char *ssid_key, char *pass_key, size_t cap)
{
    if (i == 0) {
        snprintf(ssid_key, cap, "ssid");
        snprintf(pass_key, cap, "pass");
    } else {
        snprintf(ssid_key, cap, "ssid%d", i);
        snprintf(pass_key, cap, "pass%d", i);
    }
}

void dev_config_load(dev_config_t *c)
{
    dev_settings_defaults(c);
    nvs_handle_t h;
    if (nvs_open(NS, NVS_READONLY, &h) != ESP_OK) {
        return;
    }
    char sk[16], pk[16];
    for (int i = 0; i < DEV_MAX_NETS; i++) {
        dev_net_t net = {0};
        net_keys(i, sk, pk, sizeof sk);
        size_t n = sizeof net.ssid;
        if (nvs_get_str(h, sk, net.ssid, &n) != ESP_OK || !net.ssid[0] || dev_net_find(c, net.ssid) >= 0) {
            continue;
        }
        n = sizeof net.pass;
        nvs_get_str(h, pk, net.pass, &n);
        c->nets[c->n_nets++] = net;
    }
    size_t n = sizeof c->token;
    c->has_token = nvs_get_blob(h, "token", c->token, &n) == ESP_OK && n == sizeof c->token;
    uint8_t on = 1;
    if (nvs_get_u8(h, "wake_on", &on) == ESP_OK) {
        c->wake_on = on != 0;
    }
    n = sizeof c->wake_word;
    nvs_get_str(h, "wake_word", c->wake_word, &n);
    n = sizeof c->remote_host;
    nvs_get_str(h, "rhost", c->remote_host, &n);
    nvs_get_u16(h, "rport", &c->remote_port);
    uint8_t tls = 0;
    nvs_get_u8(h, "rtls", &tls);
    c->remote_tls = tls != 0;
    if (!dev_remote_host_ok(c->remote_host) || c->remote_port == 0) {
        c->remote_host[0] = 0;
        c->remote_port = 0;
    }
    nvs_close(h);
}

esp_err_t dev_config_save(const dev_config_t *c)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(NS, NVS_READWRITE, &h);
    if (err != ESP_OK) {
        return err;
    }
    char sk[16], pk[16];
    for (int i = 0; i < DEV_MAX_NETS; i++) {
        net_keys(i, sk, pk, sizeof sk);
        if (i < c->n_nets) {
            nvs_set_str(h, sk, c->nets[i].ssid);
            nvs_set_str(h, pk, c->nets[i].pass);
        } else {
            nvs_erase_key(h, sk);
            nvs_erase_key(h, pk);
        }
    }
    if (c->has_token) {
        nvs_set_blob(h, "token", c->token, sizeof c->token);
    } else {
        nvs_erase_key(h, "token");
    }
    nvs_set_u8(h, "wake_on", c->wake_on ? 1 : 0);
    nvs_set_str(h, "wake_word", c->wake_word);
    nvs_set_str(h, "rhost", c->remote_host);
    nvs_set_u16(h, "rport", c->remote_port);
    nvs_set_u8(h, "rtls", c->remote_tls ? 1 : 0);
    err = nvs_commit(h);
    nvs_close(h);
    return err;
}
