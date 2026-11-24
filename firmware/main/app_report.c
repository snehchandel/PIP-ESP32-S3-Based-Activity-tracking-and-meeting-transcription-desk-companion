/* Outgoing device reports: HEARTBEAT and DIAG_REPORT. */
#include <stdio.h>
#include <string.h>

#include "app_controller.h"

void app_send_heartbeat(app_t *a)
{
    pip_heartbeat_t h = {PIP_PROTO_VER, (uint8_t)a->m.link, 0, a->now_ms / 1000u, app_epoch_now(a), a->state_rev};
    h.flags = (uint16_t)((a->oev.count ? 1u : 0u) | (a->is_sim ? 2u : 0u));
    uint8_t b[16];
    app_send(a, PIP_HEARTBEAT, false, b, (uint16_t)pip_pack_heartbeat(&h, b));
}

void app_send_diag(app_t *a)
{
    app_diag_t d;
    memset(&d, 0, sizeof d);
    d.batt_mv = -1;
    snprintf(d.reset_reason, sizeof d.reset_reason, "UNKNOWN");
    if (a->io.diag) {
        a->io.diag(a->io.ctx, &d);
    }
    char buf[640];
    int n = snprintf(buf, sizeof buf,
                     "{\"fw_ver\":\"%s\",\"is_sim\":%s,\"reset_reason\":\"%s\",\"link_mode\":\"%s\",\"proto_ver\":%d,"
                     "\"free_heap_b\":%lu,\"free_psram_b\":%lu,\"batt_mv\":%ld,\"batt_pct\":%d,\"rtc_ok\":%s,"
                     "\"i2c_addrs\":\"%s\",\"display_ok\":%s,\"audio_ok\":%s,\"crc_errors\":%lu,"
                     "\"dropped_audio_chunks\":%lu,\"state_rev\":%lu,\"boot_id\":%lu,\"offline_queue\":%u,"
                     "\"ui_state\":\"%s\"}",
                     APP_FW_VERSION, a->is_sim ? "true" : "false", d.reset_reason,
                     a->m.link == LINK_TETHERED ? "TETHERED" : "STANDALONE", PIP_PROTO_VER,
                     (unsigned long)d.free_heap_b, (unsigned long)d.free_psram_b, (long)d.batt_mv,
                     a->m.batt_valid ? (int)a->m.batt_pct : -1, d.rtc_ok ? "true" : "false", d.i2c_addrs,
                     d.display_ok ? "true" : "false", d.audio_ok ? "true" : "false", (unsigned long)a->crc_errors,
                     (unsigned long)d.dropped_audio_chunks, (unsigned long)a->state_rev, (unsigned long)a->boot_id,
                     (unsigned)a->oev.count, app_state_name(a->m.state));
    if (n > 0 && (size_t)n < sizeof buf) {
        app_send(a, PIP_DIAG_REPORT, false, (const uint8_t *)buf, (uint16_t)n);
    }
}
