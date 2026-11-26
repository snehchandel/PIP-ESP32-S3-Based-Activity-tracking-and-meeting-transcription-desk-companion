#include "dev_settings.h"

#include <stdio.h>
#include <string.h>

#include "json_mini.h"

void dev_settings_defaults(dev_config_t *c)
{
    memset(c, 0, sizeof *c);
    c->wake_on = true;
    snprintf(c->wake_word, sizeof c->wake_word, "hiesp");
}

int dev_net_find(const dev_config_t *c, const char *ssid)
{
    for (int i = 0; i < c->n_nets && i < DEV_MAX_NETS; i++) {
        if (strcmp(c->nets[i].ssid, ssid) == 0) {
            return i;
        }
    }
    return -1;
}

bool dev_net_add(dev_config_t *c, const char *ssid, const char *pass)
{
    if (!ssid[0] || strlen(ssid) >= sizeof c->nets[0].ssid || strlen(pass) >= sizeof c->nets[0].pass) {
        return false;
    }
    int at = dev_net_find(c, ssid);
    if (at == 0 && strcmp(c->nets[0].pass, pass) == 0) {
        return false; /* already the first choice with this password */
    }
    int last = at >= 0 ? at : (c->n_nets < DEV_MAX_NETS ? c->n_nets : DEV_MAX_NETS - 1);
    for (int i = last; i > 0; i--) {
        c->nets[i] = c->nets[i - 1];
    }
    memset(&c->nets[0], 0, sizeof c->nets[0]);
    snprintf(c->nets[0].ssid, sizeof c->nets[0].ssid, "%s", ssid);
    snprintf(c->nets[0].pass, sizeof c->nets[0].pass, "%s", pass);
    if (at < 0 && c->n_nets < DEV_MAX_NETS) {
        c->n_nets++;
    }
    return true;
}

bool dev_net_forget(dev_config_t *c, const char *ssid)
{
    int at = dev_net_find(c, ssid);
    if (at < 0) {
        return false;
    }
    for (int i = at; i + 1 < c->n_nets; i++) {
        c->nets[i] = c->nets[i + 1];
    }
    c->n_nets--;
    memset(&c->nets[c->n_nets], 0, sizeof c->nets[0]);
    return true;
}

int dev_net_pick(const dev_config_t *c, const int8_t *rssi, const uint8_t *fails, unsigned rotate)
{
    if (c->n_nets == 0) {
        return -1;
    }
    int best = -1, best_score = 0;
    for (int i = 0; i < c->n_nets; i++) {
        if (rssi[i] == DEV_NET_UNSEEN) {
            continue;
        }
        int score = rssi[i] - 15 * (int)fails[i];
        if (best < 0 || score > best_score) {
            best = i;
            best_score = score;
        }
    }
    return best >= 0 ? best : (int)(rotate % c->n_nets);
}

bool dev_remote_host_ok(const char *host)
{
    size_t n = strlen(host);
    if (n == 0 || n >= sizeof((dev_config_t *)0)->remote_host) {
        return false;
    }
    for (size_t i = 0; i < n; i++) {
        char ch = host[i];
        bool ok = (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9') || ch == '.' ||
                  ch == '-' || ch == '_';
        if (!ok) {
            return false;
        }
    }
    return true;
}

static int hexval(char ch)
{
    if (ch >= '0' && ch <= '9') return ch - '0';
    if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
    if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
    return -1;
}

unsigned dev_config_apply_json(dev_config_t *c, const char *json, size_t n)
{
    unsigned changed = 0;
    jm_span_t sp;
    bool clear = false;
    if (jm_get_bool(json, n, "wifi_clear", &clear) && clear && c->n_nets > 0) {
        memset(c->nets, 0, sizeof c->nets);
        c->n_nets = 0;
        changed |= DEVCFG_WIFI;
    }
    char ssid[sizeof c->nets[0].ssid];
    if (jm_get_str(json, n, "wifi_forget", ssid, sizeof ssid) && dev_net_forget(c, ssid)) {
        changed |= DEVCFG_WIFI;
    }
    if (jm_find(json, n, "wifi", &sp)) {
        char pass[sizeof c->nets[0].pass];
        if (jm_get_str(sp.p, sp.n, "ssid", ssid, sizeof ssid) && ssid[0]) {
            pass[0] = 0;
            (void)jm_get_str(sp.p, sp.n, "password", pass, sizeof pass);
            if (dev_net_add(c, ssid, pass)) {
                changed |= DEVCFG_WIFI;
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
            changed |= DEVCFG_TOKEN; /* drop any client authenticated with the old token */
        }
    }
    if (jm_find(json, n, "wake", &sp)) {
        bool on = c->wake_on;
        char word[sizeof c->wake_word];
        if (jm_get_bool(sp.p, sp.n, "enabled", &on) && on != c->wake_on) {
            c->wake_on = on;
            changed |= DEVCFG_WAKE;
        }
        if (jm_get_str(sp.p, sp.n, "word", word, sizeof word) && word[0] && strcmp(word, c->wake_word) != 0) {
            snprintf(c->wake_word, sizeof c->wake_word, "%s", word);
            changed |= DEVCFG_WAKE;
        }
    }
    if (jm_find(json, n, "remote", &sp)) {
        char host[sizeof c->remote_host + 8];
        long port = 0;
        bool tls = false;
        host[0] = 0;
        (void)jm_get_str(sp.p, sp.n, "host", host, sizeof host);
        (void)jm_get_long(sp.p, sp.n, "port", &port);
        (void)jm_get_bool(sp.p, sp.n, "tls", &tls);
        bool off = host[0] == 0;
        if (off || (dev_remote_host_ok(host) && port > 0 && port <= 65535)) {
            uint16_t p16 = off ? 0 : (uint16_t)port;
            tls = tls && !off;
            if (strcmp(host, c->remote_host) != 0 || p16 != c->remote_port || tls != c->remote_tls) {
                snprintf(c->remote_host, sizeof c->remote_host, "%s", off ? "" : host);
                c->remote_port = p16;
                c->remote_tls = tls;
                changed |= DEVCFG_REMOTE;
            }
        }
    }
    return changed;
}
