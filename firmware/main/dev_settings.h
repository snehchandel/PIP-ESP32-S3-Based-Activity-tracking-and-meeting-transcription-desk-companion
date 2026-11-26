/* PIP's own settings (saved Wi-Fi networks, the link token shared with the PC, wake word, the away-link address)
 * and the PIP_DEVICE_CONFIG JSON that changes them. Portable C99 (no ESP-IDF): compiled into the firmware and
 * the host C tests. Persistence lives in dev_config.c (NVS), the Wi-Fi radio in net_link.c. */
#ifndef DEV_SETTINGS_H
#define DEV_SETTINGS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define DEV_MAX_NETS 5
#define DEV_NET_UNSEEN (-128) /* "not in the last scan" for dev_net_pick() */

typedef struct {
    char ssid[33];
    char pass[65];
} dev_net_t;

typedef struct {
    dev_net_t nets[DEV_MAX_NETS]; /* saved Wi-Fi networks, the most recently added first */
    uint8_t n_nets;
    uint8_t token[32];
    bool has_token;
    bool wake_on;
    char wake_word[24];   /* model keyword, e.g. "hiesp", "jarvis", "computer", "hijoy" */
    char remote_host[64]; /* away link: the PC's public name PIP dials when it is not at home ("" = off) */
    uint16_t remote_port;
    bool remote_tls;      /* wrap the away link in TLS (needed by TLS-routed tunnels such as Tailscale Funnel) */
} dev_config_t;

/* what a DEVICE_CONFIG payload changed (bit mask) */
enum { DEVCFG_WIFI = 1, DEVCFG_TOKEN = 2, DEVCFG_WAKE = 4, DEVCFG_REMOTE = 8 };

void dev_settings_defaults(dev_config_t *c);

/* Apply a PIP_DEVICE_CONFIG JSON payload onto *c. Returns DEVCFG_* bits for what changed.
 *   "wifi":{"ssid","password"}  save a network (or its new password) and make it the first choice
 *   "wifi_forget":"<ssid>"      forget one network;  "wifi_clear":true forgets all of them
 *   "token":"<64 hex>"          link token (only ever sent over USB)
 *   "wake":{"enabled","word"}   wake word
 *   "remote":{"host","port","tls"}  away link: the address PIP dials; an empty host switches it off */
unsigned dev_config_apply_json(dev_config_t *c, const char *json, size_t n);

int dev_net_find(const dev_config_t *c, const char *ssid);
/* save (or update) a network and move it to the front; the oldest one is dropped when the list is full */
bool dev_net_add(dev_config_t *c, const char *ssid, const char *pass);
bool dev_net_forget(dev_config_t *c, const char *ssid);

/* Which saved network to join: rssi[i] is the strongest signal seen for nets[i] in the last scan (DEV_NET_UNSEEN
 * if absent), fails[i] how often joining it failed in a row. The best visible one wins (each failure costs 15 dB,
 * so a wrong password does not lock PIP onto one network); with none visible (hidden SSIDs, no scan) the networks
 * are tried in turn by `rotate`. Returns -1 when nothing is saved. */
int dev_net_pick(const dev_config_t *c, const int8_t *rssi, const uint8_t *fails, unsigned rotate);

/* a host name PIP may dial: 1..63 chars of letters, digits, '.', '-', '_' (no scheme, no port) */
bool dev_remote_host_ok(const char *host);

#endif
