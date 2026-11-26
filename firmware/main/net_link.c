#include "net_link.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_crt_bundle.h"
#include "esp_event.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "esp_tls.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "lwip/netdb.h"
#include "lwip/sockets.h"
#include "mbedtls/gcm.h"
#include "mbedtls/md.h"
#include "mdns.h"

static const char *TAG = "net";

typedef enum { NET_OFF = 0, NET_CONNECTING, NET_UP, NET_FAILED } net_state_t;
static const char *const STATE_NAMES[] = {"OFF", "CONNECTING", "UP", "FAILED"};
typedef enum { AWAY_OFF = 0, AWAY_WAITING, AWAY_DIALING, AWAY_UP, AWAY_FAILED } away_state_t;
static const char *const AWAY_NAMES[] = {"OFF", "WAITING", "DIALING", "UP", "FAILED"};

#define REC_MAX PIP_MAX_FRAME /* one encoded frame per sealed record */
#define TAG_LEN 16

static net_frame_cb_t s_cb;
static void *s_ctx;
static net_busy_fn_t s_usb_busy;
static dev_config_t s_cfg;
static SemaphoreHandle_t s_cfg_lock; /* s_cfg: written by the link rx tasks, read by the Wi-Fi event + server tasks */
static SemaphoreHandle_t s_tx_lock;
static volatile net_state_t s_state = NET_OFF;
static volatile int s_client = -1;
static volatile bool s_authed;
static volatile bool s_dialed; /* the current client is the away link (sealed records) */
static volatile int8_t s_rssi;
static char s_ip[16];
static char s_host[16];
static uint8_t s_mac[6];
static uint8_t s_nonce[16];
static pip_parser_t s_parser;
static uint32_t s_failures;
static esp_timer_handle_t s_retry;
static bool s_wifi_ready;

/* networks */
static volatile int s_cur = -1;     /* index into s_cfg.nets being joined / joined */
static dev_net_t s_joined;          /* copy of that network (indices shift when the list changes) */
static uint8_t s_fails[DEV_MAX_NETS];
static unsigned s_rotate;
static volatile bool s_scanning;

/* away link */
static volatile away_state_t s_away = AWAY_OFF;
static uint32_t s_busy_ms;          /* last moment the PC used the cable or a LAN client was connected */
static uint32_t s_next_dial_ms;
static uint32_t s_backoff_ms = 2000;
static uint32_t s_dials, s_away_ok;
static volatile bool s_sealed;      /* tx side: frames go out as GCM records */
/* the link's big buffers live in one PSRAM block: internal RAM is tight with Wi-Fi + WakeNet (~30 KB free) */
typedef struct {
    uint8_t tx[PIP_MAX_FRAME]; /* encoded outgoing frame (under s_tx_lock) */
    uint8_t rx[1024];          /* socket reads (one session at a time, all on the net_srv task) */
    mbedtls_gcm_context gtx, grx;
} net_bufs_t;
static net_bufs_t *s_b;
#define s_tx (s_b->tx)
#define s_gtx (s_b->gtx)
#define s_grx (s_b->grx)
static uint64_t s_ctr_tx, s_ctr_rx;
static uint8_t *s_seal;             /* PSRAM: 2 + REC_MAX + TAG_LEN, outgoing record (under s_tx_lock) */
static uint8_t *s_rrec;             /* PSRAM: incoming record being assembled */
static uint8_t *s_rplain;           /* PSRAM: decrypted incoming record */
static size_t s_rlen;
static esp_tls_t *s_tls;            /* away link over TLS (Tailscale Funnel ...): all reads/writes under s_tx_lock */

#define RECV_NONE (-1) /* nothing arrived within ~50 ms */
#define RECV_ERR (-2)

static uint32_t now_ms(void) { return (uint32_t)(esp_timer_get_time() / 1000); }
/* USB starts before Wi-Fi: DIAG / DEVICE_CONFIG over the cable can reach us before net_link_init() made the lock
 * (only the USB rx task touches s_cfg until then, so no lock is needed yet) */
static void cfg_lock(void)
{
    if (s_cfg_lock) {
        xSemaphoreTake(s_cfg_lock, portMAX_DELAY);
    }
}
static void cfg_unlock(void)
{
    if (s_cfg_lock) {
        xSemaphoreGive(s_cfg_lock);
    }
}

static void drop_client(void)
{
    int c = s_client;
    s_authed = false;
    s_client = -1;
    if (c >= 0) {
        shutdown(c, SHUT_RDWR);
    }
}

/* ---- Wi-Fi: several saved networks, the strongest one in range wins ------------------------------------- */

static void join(int i)
{
    cfg_lock();
    if (i < 0 || i >= s_cfg.n_nets) {
        cfg_unlock();
        return;
    }
    s_joined = s_cfg.nets[i];
    cfg_unlock();
    s_cur = i;
    wifi_config_t wc = {0};
    /* SSID is up to 32 bytes and the passphrase up to 64, not necessarily NUL-terminated in wifi_config_t */
    memcpy(wc.sta.ssid, s_joined.ssid, strnlen(s_joined.ssid, sizeof wc.sta.ssid));
    memcpy(wc.sta.password, s_joined.pass, strnlen(s_joined.pass, sizeof wc.sta.password));
    wc.sta.threshold.authmode = s_joined.pass[0] ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    wc.sta.pmf_cfg.capable = true;
    esp_wifi_set_config(WIFI_IF_STA, &wc);
    esp_wifi_connect();
}

static void start_join(void)
{
    cfg_lock();
    int n = s_cfg.n_nets;
    cfg_unlock();
    if (n == 0) {
        s_state = NET_OFF;
        s_cur = -1;
        return;
    }
    if (s_state != NET_FAILED) {
        s_state = NET_CONNECTING;
    }
    if (n == 1) {
        join(0); /* no scan needed (also finds a hidden network) */
        return;
    }
    if (s_scanning) {
        return;
    }
    wifi_scan_config_t sc = {0};
    s_scanning = esp_wifi_scan_start(&sc, false) == ESP_OK;
    if (!s_scanning) {
        join((int)(s_rotate++ % (unsigned)n));
    }
}

static void on_scan_done(void)
{
    s_scanning = false;
    int8_t rssi[DEV_MAX_NETS];
    for (int i = 0; i < DEV_MAX_NETS; i++) {
        rssi[i] = DEV_NET_UNSEEN;
    }
    wifi_ap_record_t ap;
    cfg_lock();
    while (esp_wifi_scan_get_ap_record(&ap) == ESP_OK) {
        int i = dev_net_find(&s_cfg, (const char *)ap.ssid);
        if (i >= 0 && ap.rssi > rssi[i]) {
            rssi[i] = ap.rssi;
        }
    }
    int pick = dev_net_pick(&s_cfg, rssi, s_fails, s_rotate++);
    cfg_unlock();
    esp_wifi_clear_ap_list();
    join(pick);
}

static void retry_cb(void *arg) { start_join(); }

static void on_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        start_join();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_SCAN_DONE) {
        on_scan_done();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        s_ip[0] = 0;
        drop_client();
        cfg_lock();
        int n = s_cfg.n_nets;
        cfg_unlock();
        if (n == 0) {
            s_state = NET_OFF;
            s_cur = -1;
            return;
        }
        if (esp_timer_is_active(s_retry)) {
            return; /* our own disconnect (new settings): a rejoin is already scheduled */
        }
        int cur = s_cur;
        if (cur >= 0 && cur < DEV_MAX_NETS && s_fails[cur] < 10) {
            s_fails[cur]++;
        }
        s_failures++;
        s_state = s_failures > 6 ? NET_FAILED : NET_CONNECTING;
        /* back off: 1 s, 2 s, 4 s ... capped at 30 s (wrong password must not spin the radio) */
        uint64_t delay_ms = 1000ull << (s_failures > 5 ? 5 : s_failures);
        delay_ms = delay_ms > 30000 ? 30000 : delay_ms;
        esp_timer_start_once(s_retry, delay_ms * 1000ull);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *e = (const ip_event_got_ip_t *)data;
        snprintf(s_ip, sizeof s_ip, IPSTR, IP2STR(&e->ip_info.ip));
        s_failures = 0;
        if (s_cur >= 0 && s_cur < DEV_MAX_NETS) {
            s_fails[s_cur] = 0;
        }
        s_busy_ms = now_ms(); /* give the PC a moment to find PIP on this network before dialing out */
        s_next_dial_ms = s_busy_ms;
        s_backoff_ms = 2000;
        s_state = NET_UP;
        ESP_LOGI(TAG, "wifi up: %s (%s.local)", s_ip, s_host);
    }
}

/* ---- session I/O: a plain socket, or TLS around it (mbedtls is not safe for a read and a write at once, so
 *      TLS reads poll the socket unlocked and then read under s_tx_lock, like the writes) ------------------------ */

/* caller holds s_tx_lock */
static bool sess_write(int c, const uint8_t *p, size_t n)
{
    uint32_t t0 = now_ms();
    for (size_t off = 0; off < n;) {
        int w = s_tls ? (int)esp_tls_conn_write(s_tls, p + off, n - off) : send(c, p + off, n - off, 0);
        if (w > 0) {
            off += (size_t)w;
        } else if (s_tls && (w == ESP_TLS_ERR_SSL_WANT_WRITE || w == ESP_TLS_ERR_SSL_WANT_READ) &&
                   now_ms() - t0 < 2000u) {
            vTaskDelay(1);
        } else {
            return false;
        }
    }
    return true;
}

static int sess_recv(int c, uint8_t *buf, size_t cap)
{
    if (!s_tls) {
        int n = recv(c, buf, cap, 0);
        if (n < 0) {
            return errno == EAGAIN || errno == EWOULDBLOCK ? RECV_NONE : RECV_ERR;
        }
        return n;
    }
    if (esp_tls_get_bytes_avail(s_tls) <= 0) {
        fd_set rf;
        FD_ZERO(&rf);
        FD_SET(c, &rf);
        struct timeval tv = {.tv_sec = 0, .tv_usec = 50000};
        int sel = select(c + 1, &rf, NULL, NULL, &tv);
        if (sel == 0) {
            return RECV_NONE;
        }
        if (sel < 0) {
            return RECV_ERR;
        }
    }
    xSemaphoreTake(s_tx_lock, portMAX_DELAY);
    int n = (int)esp_tls_conn_read(s_tls, buf, cap);
    xSemaphoreGive(s_tx_lock);
    if (n >= 0) {
        return n;
    }
    return n == ESP_TLS_ERR_SSL_WANT_READ || n == ESP_TLS_ERR_SSL_WANT_WRITE ? RECV_NONE : RECV_ERR;
}

/* ---- authentication + sealed records ------------------------------------------------------------------------ */

static bool hmac256(const uint8_t *key, size_t kn, const uint8_t *msg, size_t mn, uint8_t out[32])
{
    return mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), key, kn, msg, mn, out) == 0;
}

static bool same32(const uint8_t *a, const uint8_t *b)
{
    uint8_t diff = 0; /* constant time */
    for (int i = 0; i < 32; i++) {
        diff |= (uint8_t)(a[i] ^ b[i]);
    }
    return diff == 0;
}

static bool verify(const uint8_t *token, const uint8_t *mac32)
{
    uint8_t want[32];
    return hmac256(token, 32, s_nonce, sizeof s_nonce, want) && same32(want, mac32);
}

static void ctr_iv(uint8_t iv[12], uint64_t ctr)
{
    for (int i = 0; i < 8; i++) {
        iv[i] = (uint8_t)(ctr >> (8 * i));
    }
    iv[8] = iv[9] = iv[10] = iv[11] = 0;
}

/* the PC proved the token: prove ours, derive the session keys, switch to sealed records */
static bool away_keys(const uint8_t *token, const uint8_t nonce_p[16], int c)
{
    uint8_t msg[10 + 32], proof[32], k[32], kup[32], kdown[32];
    memcpy(msg, "PIP-DEV", 7);
    memcpy(msg + 7, nonce_p, 16);
    memcpy(msg + 23, s_nonce, 16);
    if (!hmac256(token, 32, msg, 39, proof)) {
        return false;
    }
    memcpy(msg, "PIP-AWAY-1", 10);
    memcpy(msg + 10, s_nonce, 16);
    memcpy(msg + 26, nonce_p, 16);
    if (!hmac256(token, 32, msg, 42, k) || !hmac256(k, 32, (const uint8_t *)"up", 2, kup) ||
        !hmac256(k, 32, (const uint8_t *)"down", 4, kdown)) {
        return false;
    }
    xSemaphoreTake(s_tx_lock, portMAX_DELAY);
    size_t n = pip_encode(PIP_AUTH_RESPONSE, 0, 0, proof, sizeof proof, s_tx, sizeof s_tx);
    bool ok = n > 0 && sess_write(c, s_tx, n);
    mbedtls_gcm_free(&s_gtx);
    mbedtls_gcm_free(&s_grx);
    mbedtls_gcm_init(&s_gtx);
    mbedtls_gcm_init(&s_grx);
    ok = ok && mbedtls_gcm_setkey(&s_gtx, MBEDTLS_CIPHER_ID_AES, kup, 256) == 0 &&
         mbedtls_gcm_setkey(&s_grx, MBEDTLS_CIPHER_ID_AES, kdown, 256) == 0;
    s_ctr_tx = s_ctr_rx = 0;
    s_rlen = 0;
    s_sealed = ok;
    xSemaphoreGive(s_tx_lock);
    memset(k, 0, sizeof k);
    memset(kup, 0, sizeof kup);
    memset(kdown, 0, sizeof kdown);
    return ok;
}

/* encrypted record of s_tx[0..n) into s_seal (caller holds s_tx_lock); 0 on failure */
static size_t seal(size_t n)
{
    uint8_t iv[12];
    ctr_iv(iv, s_ctr_tx++);
    s_seal[0] = (uint8_t)n;
    s_seal[1] = (uint8_t)(n >> 8);
    if (mbedtls_gcm_crypt_and_tag(&s_gtx, MBEDTLS_GCM_ENCRYPT, n, iv, sizeof iv, s_seal, 2, s_tx, s_seal + 2,
                                  TAG_LEN, s_seal + 2 + n) != 0) {
        return 0;
    }
    return n + 2 + TAG_LEN;
}

static void dispatch(const uint8_t *b, size_t n)
{
    pip_frame_t f;
    for (size_t i = 0; i < n; i++) {
        if (pip_parser_feed(&s_parser, b[i], &f) && s_cb) {
            s_cb(&f, s_ctx);
        }
    }
}

/* incoming sealed bytes: assemble records, open them, feed the frames on; false = tampered / malformed */
static bool open_records(const uint8_t *b, size_t n)
{
    while (n > 0) {
        size_t rec = s_rlen >= 2 ? (size_t)(s_rrec[0] | s_rrec[1] << 8) : 0;
        size_t need = s_rlen < 2 ? 2 : 2 + rec + TAG_LEN;
        size_t take = need - s_rlen < n ? need - s_rlen : n;
        memcpy(s_rrec + s_rlen, b, take);
        s_rlen += take;
        b += take;
        n -= take;
        if (s_rlen == 2) {
            rec = (size_t)(s_rrec[0] | s_rrec[1] << 8);
            if (rec == 0 || rec > REC_MAX) {
                return false;
            }
        } else if (s_rlen == 2 + rec + TAG_LEN) {
            uint8_t iv[12];
            ctr_iv(iv, s_ctr_rx++);
            if (mbedtls_gcm_auth_decrypt(&s_grx, rec, iv, sizeof iv, s_rrec, 2, s_rrec + 2 + rec, TAG_LEN,
                                         s_rrec + 2, s_rplain) != 0) {
                return false;
            }
            s_rlen = 0;
            dispatch(s_rplain, rec);
        }
    }
    return true;
}

static bool raw_send(int c, uint8_t type, uint8_t flags, uint16_t seq, const uint8_t *p, uint16_t len)
{
    xSemaphoreTake(s_tx_lock, portMAX_DELAY);
    size_t n = pip_encode(type, flags, seq, p, len, s_tx, sizeof s_tx);
    const uint8_t *out = s_tx;
    if (n > 0 && s_sealed) {
        n = seal(n);
        out = s_seal;
    }
    bool ok = n > 0 && sess_write(c, out, n);
    xSemaphoreGive(s_tx_lock);
    return ok;
}

/* One PC session (LAN client or the dialed away link). Returns true if the PC authenticated. */
static bool serve_session(int c, bool dialed)
{
    int one = 1;
    setsockopt(c, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    struct timeval rt = {.tv_sec = 0, .tv_usec = 50000}, st = {.tv_sec = 2, .tv_usec = 0};
    setsockopt(c, SOL_SOCKET, SO_RCVTIMEO, &rt, sizeof rt);
    setsockopt(c, SOL_SOCKET, SO_SNDTIMEO, &st, sizeof st);
    uint8_t token[32];
    cfg_lock();
    bool has_token = s_cfg.has_token;
    memcpy(token, s_cfg.token, sizeof token);
    cfg_unlock();
    pip_parser_init(&s_parser);
    esp_fill_random(s_nonce, sizeof s_nonce);
    s_authed = false;
    s_sealed = false;
    s_dialed = dialed;
    s_client = c;
    uint8_t hello[22];
    memcpy(hello, s_nonce, 16);
    memcpy(hello + 16, s_mac, 6);
    raw_send(c, PIP_AUTH_CHALLENGE, 0, 0, hello, sizeof hello);
    uint32_t t0 = now_ms(), last_rx = t0;
    bool ever = false;
    uint8_t *buf = s_b->rx;
    pip_frame_t f;
    for (;;) {
        int n = sess_recv(c, buf, sizeof s_b->rx);
        if (n == 0 || n == RECV_ERR) {
            break; /* peer closed / socket error */
        }
        if (n < 0) {
            if (!s_authed && now_ms() - t0 > 5000u) {
                ESP_LOGW(TAG, "%s did not authenticate", dialed ? "away PC" : "client");
                break;
            }
            if (dialed && s_authed && now_ms() - last_rx > AWAY_IDLE_MS) {
                ESP_LOGW(TAG, "away link silent, redialing");
                break;
            }
            while (!s_sealed && s_parser.len > 0 && pip_parser_idle(&s_parser, &f)) {
                if (s_authed && s_cb) s_cb(&f, s_ctx);
            }
            if (s_client < 0) break; /* dropped elsewhere (Wi-Fi lost / new token / new address) */
            continue;
        }
        last_rx = now_ms();
        if (s_sealed) {
            if (!open_records(buf, (size_t)n)) {
                ESP_LOGW(TAG, "away link: bad record, closing");
                break;
            }
            if (s_client < 0) break;
            continue;
        }
        for (int i = 0; i < n; i++) {
            if (!pip_parser_feed(&s_parser, buf[i], &f)) {
                continue;
            }
            if (s_authed) {
                if (s_cb) s_cb(&f, s_ctx);
            } else if (!dialed && has_token && f.type == PIP_AUTH_RESPONSE && f.len == 32 && verify(token, f.payload)) {
                s_authed = ever = true;
                ESP_LOGI(TAG, "PC authenticated over Wi-Fi");
            } else if (dialed && has_token && f.type == PIP_AUTH_RESPONSE && f.len == 48 && verify(token, f.payload) &&
                       away_keys(token, f.payload + 32, c)) {
                s_authed = ever = true;
                s_away = AWAY_UP;
                s_away_ok++;
                ESP_LOGI(TAG, "away link up (encrypted)");
                if (i + 1 < n && !open_records(buf + i + 1, (size_t)(n - i - 1))) {
                    s_client = -1;
                }
                break;
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
    xSemaphoreTake(s_tx_lock, portMAX_DELAY);
    s_sealed = false;
    s_dialed = false;
    esp_tls_t *tls = s_tls;
    s_tls = NULL;
    xSemaphoreGive(s_tx_lock);
    if (tls) {
        esp_tls_conn_destroy(tls); /* closes the socket too */
    } else {
        close(c);
    }
    memset(token, 0, sizeof token);
    return ever;
}

/* ---- away link: dial the PC's public address -------------------------------------------------------------- */

static int dial(const char *host, uint16_t port)
{
    struct addrinfo hints = {.ai_family = AF_INET, .ai_socktype = SOCK_STREAM}, *res = NULL;
    char ps[8];
    snprintf(ps, sizeof ps, "%u", (unsigned)port);
    if (getaddrinfo(host, ps, &hints, &res) != 0 || !res) {
        ESP_LOGW(TAG, "away: cannot resolve %s", host);
        return -1;
    }
    int c = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
    if (c < 0) {
        freeaddrinfo(res);
        return -1;
    }
    int fl = fcntl(c, F_GETFL, 0);
    fcntl(c, F_SETFL, fl | O_NONBLOCK);
    int r = connect(c, res->ai_addr, res->ai_addrlen);
    freeaddrinfo(res);
    if (r != 0 && errno != EINPROGRESS) {
        close(c);
        return -1;
    }
    if (r != 0) {
        fd_set wf;
        FD_ZERO(&wf);
        FD_SET(c, &wf);
        struct timeval tv = {.tv_sec = 5, .tv_usec = 0};
        int err = 0;
        socklen_t el = sizeof err;
        if (select(c + 1, NULL, &wf, NULL, &tv) <= 0 || getsockopt(c, SOL_SOCKET, SO_ERROR, &err, &el) != 0 || err) {
            close(c);
            return -1;
        }
    }
    fcntl(c, F_SETFL, fl);
    return c;
}

/* TLS to the tunnel's public name (certificate checked against the built-in CA bundle, SNI = host). The
 * records inside stay sealed with the link token, so the tunnel never sees PIP's data either. */
static int dial_tls(const char *host, uint16_t port)
{
    esp_tls_t *tls = esp_tls_init();
    if (!tls) {
        return -1;
    }
    esp_tls_cfg_t cfg = {.crt_bundle_attach = esp_crt_bundle_attach, .timeout_ms = 8000};
    if (esp_tls_conn_new_sync(host, (int)strlen(host), port, &cfg, tls) != 1) {
        ESP_LOGW(TAG, "away: TLS to %s:%u failed", host, (unsigned)port);
        esp_tls_conn_destroy(tls);
        return -1;
    }
    int c = -1;
    if (esp_tls_get_conn_sockfd(tls, &c) != ESP_OK || c < 0) {
        esp_tls_conn_destroy(tls);
        return -1;
    }
    fcntl(c, F_SETFL, fcntl(c, F_GETFL, 0) | O_NONBLOCK); /* reads happen under the tx lock: never block in them */
    s_tls = tls; /* serve_session() owns it from here and destroys it */
    return c;
}

static void maybe_dial(void)
{
    char host[sizeof s_cfg.remote_host];
    cfg_lock();
    snprintf(host, sizeof host, "%s", s_cfg.remote_host);
    uint16_t port = s_cfg.remote_port;
    bool token = s_cfg.has_token, tls = s_cfg.remote_tls;
    cfg_unlock();
    uint32_t t = now_ms();
    if (!host[0] || !port || !token || !s_seal) {
        s_away = AWAY_OFF;
        return;
    }
    if (s_usb_busy && s_usb_busy()) {
        s_busy_ms = t; /* on the cable: the PC has PIP already */
        s_away = AWAY_WAITING;
        return;
    }
    if (t - s_busy_ms < AWAY_QUIET_MS || (int32_t)(t - s_next_dial_ms) < 0) {
        if (s_away != AWAY_FAILED) {
            s_away = AWAY_WAITING;
        }
        return;
    }
    s_away = AWAY_DIALING;
    s_dials++;
    int c = tls ? dial_tls(host, port) : dial(host, port);
    bool linked = c >= 0 && serve_session(c, true);
    if (linked) {
        s_backoff_ms = 2000;
        s_away = AWAY_WAITING;
        s_busy_ms = now_ms(); /* give a LAN client the first chance again */
    } else {
        s_away = AWAY_FAILED;
        s_backoff_ms = s_backoff_ms >= 30000 ? 60000 : s_backoff_ms * 2;
        ESP_LOGW(TAG, "away: %s:%u %s, next try in %lu s", host, (unsigned)port, c >= 0 ? "refused us" : "unreachable",
                 (unsigned long)(s_backoff_ms / 1000));
    }
    s_next_dial_ms = now_ms() + s_backoff_ms;
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
            if (select(ls + 1, &rf, NULL, NULL, &tv) > 0) {
                int c = accept(ls, NULL, NULL);
                if (c >= 0) {
                    serve_session(c, false); /* one PC at a time */
                    s_busy_ms = now_ms();
                }
                continue;
            }
            maybe_dial(); /* nobody came over the LAN: perhaps PIP is away from home */
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

void net_link_init(const dev_config_t *cfg, net_frame_cb_t cb, void *ctx, net_busy_fn_t usb_busy)
{
    s_cfg = *cfg;
    s_cb = cb;
    s_ctx = ctx;
    s_usb_busy = usb_busy;
    s_tx_lock = xSemaphoreCreateMutex();
    s_cfg_lock = xSemaphoreCreateMutex();
    s_b = heap_caps_calloc(1, sizeof *s_b, MALLOC_CAP_SPIRAM);
    if (!s_b) {
        s_b = calloc(1, sizeof *s_b);
    }
    if (!s_b) {
        ESP_LOGE(TAG, "no memory for the Wi-Fi link");
        return;
    }
    mbedtls_gcm_init(&s_gtx);
    mbedtls_gcm_init(&s_grx);
    /* record buffers in PSRAM: internal RAM is tight with Wi-Fi + WakeNet (the away link is off without them) */
    s_seal = heap_caps_malloc(2 + REC_MAX + TAG_LEN, MALLOC_CAP_SPIRAM);
    s_rrec = heap_caps_malloc(2 + REC_MAX + TAG_LEN, MALLOC_CAP_SPIRAM);
    s_rplain = heap_caps_malloc(REC_MAX, MALLOC_CAP_SPIRAM);
    if (!s_seal || !s_rrec || !s_rplain) {
        ESP_LOGE(TAG, "no PSRAM for the away link");
        heap_caps_free(s_seal);
        heap_caps_free(s_rrec);
        heap_caps_free(s_rplain);
        s_seal = s_rrec = s_rplain = NULL;
    }
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

void net_link_apply(const dev_config_t *cfg, unsigned changed)
{
    cfg_lock();
    s_cfg = *cfg;
    cfg_unlock();
    if (!s_wifi_ready) {
        return;
    }
    if (changed & DEVCFG_TOKEN) {
        drop_client(); /* authenticated with the old token */
    }
    if ((changed & DEVCFG_REMOTE) && s_dialed) {
        drop_client(); /* dial the new address */
    }
    if ((changed & DEVCFG_REMOTE)) {
        s_next_dial_ms = now_ms();
        s_backoff_ms = 2000;
    }
    if (!(changed & DEVCFG_WIFI)) {
        return;
    }
    memset(s_fails, 0, sizeof s_fails); /* indices moved */
    int still = dev_net_find(cfg, s_joined.ssid);
    if (s_state == NET_UP && still >= 0 && strcmp(cfg->nets[still].pass, s_joined.pass) == 0) {
        s_cur = still; /* a network was added or forgotten, but not this one: stay connected */
        return;
    }
    drop_client();
    esp_timer_stop(s_retry);
    s_failures = 0;
    if (cfg->n_nets == 0) {
        s_state = NET_OFF;
        s_cur = -1;
        esp_wifi_disconnect();
        return;
    }
    s_state = NET_CONNECTING;
    esp_timer_start_once(s_retry, 300 * 1000ull); /* before the disconnect: its event sees the rejoin scheduled */
    esp_wifi_disconnect();
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

static int json_safe(char *dst, size_t cap, const char *src)
{
    size_t o = 0;
    for (; *src && o + 1 < cap; src++) {
        unsigned char ch = (unsigned char)*src;
        dst[o++] = (ch < 0x20 || ch == '"' || ch == '\\') ? '_' : (char)ch;
    }
    dst[o] = 0;
    return (int)o;
}

int net_link_status_json(char *out, size_t cap)
{
    char ssid[40], nets[DEV_MAX_NETS * 36 + 4], host[sizeof s_cfg.remote_host];
    json_safe(ssid, sizeof ssid, s_state == NET_OFF || s_cur < 0 ? "" : s_joined.ssid);
    size_t o = 0;
    cfg_lock();
    for (int i = 0; i < s_cfg.n_nets && o + 40 < sizeof nets; i++) {
        nets[o++] = i ? ',' : '"';
        if (i) nets[o++] = '"';
        o += (size_t)json_safe(nets + o, 34, s_cfg.nets[i].ssid);
        nets[o++] = '"';
    }
    nets[o] = 0;
    bool configured = s_cfg.n_nets > 0, paired = s_cfg.has_token;
    json_safe(host, sizeof host, s_cfg.remote_host);
    unsigned port = s_cfg.remote_port;
    bool tls = s_cfg.remote_tls;
    cfg_unlock();
    return snprintf(out, cap,
                    "\"wifi\":{\"configured\":%s,\"paired\":%s,\"state\":\"%s\",\"ssid\":\"%s\",\"ip\":\"%s\","
                    "\"host\":\"%s.local\",\"port\":%d,\"rssi\":%d,\"client\":%s,\"via\":\"%s\",\"networks\":[%s],"
                    "\"away\":{\"host\":\"%s\",\"port\":%u,\"tls\":%s,\"state\":\"%s\",\"dials\":%lu,\"links\":%lu}}",
                    configured ? "true" : "false", paired ? "true" : "false", STATE_NAMES[s_state], ssid, s_ip, s_host,
                    PIP_TCP_PORT, (int)s_rssi, net_link_client_ready() ? "true" : "false",
                    !net_link_client_ready() ? "" : s_dialed ? "away" : "lan", nets, host, port, tls ? "true" : "false",
                    AWAY_NAMES[s_away],
                    (unsigned long)s_dials, (unsigned long)s_away_ok);
}
