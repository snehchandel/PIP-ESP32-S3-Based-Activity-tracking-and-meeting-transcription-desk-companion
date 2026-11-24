/* sim_rlcd --tcp: virtual PIP device speaking protocol v1 over a TCP socket.
 * Runs the real app_controller, gesture FSM, local timer and 1-bit renderer in real time. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "app_controller.h"
#include "sim_net.h"

#define SCRIPT_MAX 16

typedef struct {
    uint32_t at_ms;
    uint8_t btn;
    bool pressed;
} raw_step_t;

typedef struct {
    sim_sock_t client;
    raw_step_t script[SCRIPT_MAX];
    int script_n;
    bool level[BTN_COUNT];
    app_t app;
} sim_t;

static sim_t S;

static void sim_send(void *ctx, uint8_t type, uint8_t flags, uint16_t seq, const uint8_t *payload, uint16_t len)
{
    static uint8_t out[PIP_MAX_FRAME];
    sim_t *s = (sim_t *)ctx;
    if (s->client == SIM_SOCK_INVALID) {
        return;
    }
    size_t n = pip_encode(type, flags, seq, payload, len, out, sizeof out);
    if (n && sim_sock_send_all(s->client, out, n) != 0) {
        sim_sock_close(s->client);
        s->client = SIM_SOCK_INVALID;
        printf("[sim] host disconnected (send)\n");
    }
}

static void sim_chime(void *ctx, uint8_t id)
{
    (void)ctx;
    printf("[sim] chime %u\n", (unsigned)id);
}

static void sim_capture(void *ctx, bool start, uint32_t stream_id)
{
    sim_t *s = (sim_t *)ctx;
    printf("[sim] mic capture %s (stream %lu) - simulator has no microphone\n", start ? "on" : "off",
           (unsigned long)stream_id);
    if (!start) {
        pip_audio_end_t e = {stream_id, 0, 0, 0, 0};
        uint8_t b[12];
        app_send(&s->app, PIP_AUDIO_END, true, b, (uint16_t)pip_pack_audio_end(&e, b));
    }
}

static void sim_diag(void *ctx, app_diag_t *d)
{
    (void)ctx;
    snprintf(d->reset_reason, sizeof d->reset_reason, "SIM_START");
    snprintf(d->i2c_addrs, sizeof d->i2c_addrs, "sim");
    d->rtc_ok = true;
    d->display_ok = true;
    d->audio_ok = false;
}

static void script_add(uint32_t at, uint8_t btn, bool pressed)
{
    if (S.script_n < SCRIPT_MAX) {
        S.script[S.script_n].at_ms = at;
        S.script[S.script_n].btn = btn;
        S.script[S.script_n].pressed = pressed;
        S.script_n++;
    }
}

static void on_sim_input(const pip_sim_input_t *in, uint32_t now)
{
    uint8_t b = in->btn_id ? BTN_BOOT : BTN_KEY;
    if (in->action == 0) {
        script_add(now, b, true);
        script_add(now + 80, b, false);
    } else if (in->action == 1) {
        script_add(now, b, true);
        script_add(now + 80, b, false);
        script_add(now + 200, b, true);
        script_add(now + 280, b, false);
    } else {
        script_add(now, b, true);
        script_add(now + (in->hold_ms ? in->hold_ms : 1300u), b, false);
    }
}

static void run_script(uint32_t now)
{
    int k = 0;
    for (int i = 0; i < S.script_n; i++) {
        if (S.script[i].at_ms <= now) {
            S.level[S.script[i].btn] = S.script[i].pressed;
        } else {
            S.script[k++] = S.script[i];
        }
    }
    S.script_n = k;
}

static void seed_offline_events(const char *spec)
{
    /* "KIND:ref_id[:remaining_ms],..." e.g. "STEP_COMPLETE:abc123" */
    char buf[512];
    snprintf(buf, sizeof buf, "%s", spec);
    for (char *tok = strtok(buf, ","); tok; tok = strtok(NULL, ",")) {
        char *ref = strchr(tok, ':');
        if (!ref) {
            continue;
        }
        *ref++ = 0;
        char *rem = strchr(ref, ':');
        uint32_t ms = 0;
        if (rem) {
            *rem++ = 0;
            ms = (uint32_t)strtoul(rem, NULL, 10);
        }
        oev_kind_t k = strcmp(tok, "STEP_SPLIT") == 0      ? OEV_STEP_SPLIT
                       : strcmp(tok, "TIMER_DELTA") == 0   ? OEV_TIMER_DELTA
                       : strcmp(tok, "ALARM_ACK") == 0     ? OEV_ALARM_ACK
                                                           : OEV_STEP_COMPLETE;
        oev_push(&S.app.oev, k, ref, ms, (uint32_t)time(NULL));
        printf("[sim] queued offline event %s %s\n", oev_kind_name((uint8_t)k), ref);
    }
}

int sim_tcp_run(const char *host, int port, const char *offline_events)
{
    if (sim_net_init() != 0) {
        return 1;
    }
    sim_sock_t ls = sim_listen(host, port);
    if (ls == SIM_SOCK_INVALID) {
        fprintf(stderr, "[sim] cannot listen on %s:%d\n", host, port);
        return 1;
    }
    S.client = SIM_SOCK_INVALID;
    app_io_t io = {&S, sim_send, sim_chime, sim_capture, sim_diag};
    uint32_t now = sim_now_ms();
    app_init(&S.app, &io, now, (uint32_t)time(NULL), true);
    app_set_epoch(&S.app, (uint32_t)time(NULL));
    app_set_battery(&S.app, -1); /* simulator has no battery: shown as "--%" */
    if (offline_events) {
        seed_offline_events(offline_events);
    }
    printf("[sim] PIP virtual device listening on %s:%d\n", host, port);
    fflush(stdout);
    pip_parser_t parser;
    pip_parser_init(&parser);
    static uint8_t rx[8192];
    for (;;) {
        if (S.client == SIM_SOCK_INVALID) {
            S.client = sim_accept(ls, 10);
            if (S.client != SIM_SOCK_INVALID) {
                pip_parser_init(&parser);
                printf("[sim] host connected\n");
                fflush(stdout);
            }
        } else {
            int n = sim_recv(S.client, rx, sizeof rx, 10);
            if (n < 0) {
                sim_sock_close(S.client);
                S.client = SIM_SOCK_INVALID;
                printf("[sim] host disconnected\n");
                fflush(stdout);
            }
            now = sim_now_ms();
            S.app.now_ms = now;
            for (int i = 0; i < n; i++) {
                pip_frame_t f;
                if (pip_parser_feed(&parser, rx[i], &f)) {
                    pip_sim_input_t in;
                    if (f.type == PIP_SIM_INPUT && pip_unpack_sim_input(f.payload, f.len, &in)) {
                        on_sim_input(&in, now);
                    }
                    app_on_frame(&S.app, &f);
                }
            }
            S.app.crc_errors = parser.crc_errors;
        }
        now = sim_now_ms();
        run_script(now);
        app_button_sample(&S.app, BTN_KEY, S.level[BTN_KEY], now);
        app_button_sample(&S.app, BTN_BOOT, S.level[BTN_BOOT], now);
        app_tick(&S.app, now);
        app_render_if_dirty(&S.app);
        fflush(stdout);
    }
}
