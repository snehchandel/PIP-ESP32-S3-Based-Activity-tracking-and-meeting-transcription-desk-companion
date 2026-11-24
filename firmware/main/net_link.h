/* Wi-Fi link: PIP joins the home network (STA), advertises itself as pip-xxxx.local (_pip._tcp) and accepts
 * ONE authenticated TCP connection from the PC on port 18422 carrying the exact same protocol v1 frames as USB.
 * Authentication: on connect PIP sends PIP_AUTH_CHALLENGE (16-byte random nonce + MAC); the PC must answer with
 * PIP_AUTH_RESPONSE = HMAC-SHA256(link token, nonce) within 5 s, otherwise the socket is closed. The token is
 * provisioned over USB, so only a PC that was once physically connected can drive PIP over the LAN. */
#ifndef NET_LINK_H
#define NET_LINK_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "dev_config.h"
#include "pip_protocol.h"

#define PIP_TCP_PORT 18422

typedef void (*net_frame_cb_t)(const pip_frame_t *frame, void *ctx);

void net_link_init(const dev_config_t *cfg, net_frame_cb_t cb, void *ctx);
/* new credentials / token: reconnect (or switch Wi-Fi off when the SSID is empty) */
void net_link_apply(const dev_config_t *cfg);
void net_link_send(uint8_t type, uint8_t flags, uint16_t seq, const uint8_t *payload, uint16_t len);
bool net_link_client_ready(void);
/* JSON fragment (no braces) for DIAG_REPORT: "wifi":{...} */
int net_link_status_json(char *out, size_t cap);

#endif
