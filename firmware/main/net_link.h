/* Wi-Fi link (ADR-019, ADR-035).
 *
 * Networks: PIP remembers up to DEV_MAX_NETS Wi-Fi networks (home, office, a phone hotspot ...) and joins the
 * strongest one in range (dev_net_pick), so it can be carried between places.
 *
 * LAN link: PIP advertises itself as pip-xxxx.local (_pip._tcp) and accepts ONE authenticated TCP connection from
 * the PC on port 18422 carrying the exact same protocol v1 frames as USB. On connect PIP sends PIP_AUTH_CHALLENGE
 * (16-byte nonce + MAC); the PC must answer PIP_AUTH_RESPONSE = HMAC-SHA256(link token, nonce) within 5 s.
 *
 * Away link: when PIP is on a network where the PC cannot reach it (not on the cable, no LAN client for
 * AWAY_QUIET_MS), it dials OUT to the PC's public address (remote_host:remote_port, e.g. a Tailscale Funnel name or
 * a router port forward). Mutual proof of the link token, then every frame travels in an AES-256-GCM record:
 *   PIP -> PC   AUTH_CHALLENGE  nonce_d(16) + MAC(6)
 *   PC  -> PIP  AUTH_RESPONSE   HMAC(token, nonce_d)(32) + nonce_p(16)
 *   PIP -> PC   AUTH_RESPONSE   HMAC(token, "PIP-DEV" | nonce_p | nonce_d)(32)
 *   K = HMAC(token, "PIP-AWAY-1" | nonce_d | nonce_p); key up (PIP->PC) = HMAC(K, "up"), down = HMAC(K, "down")
 *   record = len(u16 LE) | AES-256-GCM(key, iv = counter(u64 LE) | 0000, aad = len bytes, frame bytes) | tag(16)
 * With remote_tls the stream is first wrapped in TLS to the public name (TLS-routed tunnels such as Tailscale
 * Funnel need SNI); the sealed records travel inside it unchanged.
 * The token is provisioned over USB only, so only a PC that was once cabled to PIP can take either link. */
#ifndef NET_LINK_H
#define NET_LINK_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "dev_config.h"
#include "pip_protocol.h"

#define PIP_TCP_PORT 18422
#define AWAY_QUIET_MS 10000u   /* no cable, no LAN client this long -> dial the PC's public address */
#define AWAY_IDLE_MS 30000u    /* the PC heartbeats every second; this much silence means the link is dead */

typedef void (*net_frame_cb_t)(const pip_frame_t *frame, void *ctx);
typedef bool (*net_busy_fn_t)(void); /* true while the PC is driving PIP over USB (then PIP never dials out) */

void net_link_init(const dev_config_t *cfg, net_frame_cb_t cb, void *ctx, net_busy_fn_t usb_busy);
/* settings changed (DEVCFG_* bits): rejoin Wi-Fi only if the current network is gone, drop links on a new token */
void net_link_apply(const dev_config_t *cfg, unsigned changed);
void net_link_send(uint8_t type, uint8_t flags, uint16_t seq, const uint8_t *payload, uint16_t len);
bool net_link_client_ready(void);
/* JSON fragment (no braces) for DIAG_REPORT: "wifi":{...} */
int net_link_status_json(char *out, size_t cap);

#endif
