/* app_controller integration: host frames, gesture matrix, offline log + reconnect. */
#include <stdio.h>
#include <string.h>

#include "app_controller.h"
#include "tinytest.h"

typedef struct {
    int count[256];
    uint16_t last_seq[256];
    uint8_t last_payload[PIP_MAX_PAYLOAD];
    uint16_t last_len;
    int chimes;
} cap_t;

static cap_t C;

static void cap_send(void *ctx, uint8_t type, uint8_t flags, uint16_t seq, const uint8_t *p, uint16_t len)
{
    (void)ctx;
    (void)flags;
    C.count[type]++;
    C.last_seq[type] = seq;
    if (type != PIP_HEARTBEAT) {
        memcpy(C.last_payload, p, len);
        C.last_len = len;
    }
}

static void cap_chime(void *ctx, uint8_t id)
{
    (void)ctx;
    (void)id;
    C.chimes++;
}

static void frame(app_t *a, uint8_t type, uint8_t flags, uint16_t seq, const char *json)
{
    pip_frame_t f = {type, flags, seq, (uint16_t)(json ? strlen(json) : 0), (const uint8_t *)json};
    app_on_frame(a, &f);
}

static void gesture(app_t *a, btn_id_t b, gesture_t g)
{
    gesture_event_t e = {b, g, 0, a->now_ms};
    app_on_gesture(a, &e);
}

static app_t A;

int main(void)
{
    app_io_t io = {NULL, cap_send, cap_chime, NULL, NULL};
    app_init(&A, &io, 1000, 5, false);
    app_tick(&A, 1000);
    CHECK_EQ(A.m.link, LINK_STANDALONE);

    /* host connects and pushes a running step */
    const char *ui = "{\"rev\":3,\"ui_state\":\"RUNNING\",\"page\":\"FOCUS\",\"task_title\":\"Q3\",\"step_id\":\"s1\","
                     "\"step_title\":\"Open template\",\"step_index\":1,\"step_total\":3,\"is_starter\":true,"
                     "\"timer_state\":\"RUNNING\",\"remaining_ms\":120000,\"step_total_ms\":120000,"
                     "\"next_step_id\":\"s2\",\"next_step_title\":\"Write intro\",\"next_step_min\":10,"
                     "\"parked_count\":1,\"tz_offset_min\":-300}";
    frame(&A, PIP_UI_UPDATE, PIP_FLAG_ACK_REQUIRED, 40, ui);
    app_tick(&A, 1100);
    CHECK_EQ(A.m.link, LINK_TETHERED);
    CHECK_EQ(A.m.state, UI_STATE_RUNNING);
    CHECK_EQ(A.timer.state, LT_RUNNING);
    CHECK_EQ(A.state_rev, 3);
    CHECK_EQ(C.count[PIP_ACK], 1);
    CHECK_EQ(C.count[PIP_DIAG_REPORT], 1); /* sent on link-up */
    CHECK(app_render_if_dirty(&A));

    /* malformed JSON is NACKed, state untouched */
    frame(&A, PIP_UI_UPDATE, PIP_FLAG_ACK_REQUIRED, 41, "{\"rev\":");
    CHECK_EQ(C.last_payload[2], PIP_ACK_BAD_JSON);
    CHECK_EQ(A.m.state, UI_STATE_RUNNING);

    /* KEY short pauses (tethered: BTN_EVENT reported, no offline log) */
    A.now_ms = 31100;
    frame(&A, PIP_HEARTBEAT, 0, 42, NULL); /* host heartbeat keeps the link alive */
    app_tick(&A, 31100);
    CHECK_EQ(A.m.link, LINK_TETHERED);
    gesture(&A, BTN_KEY, GEST_SHORT);
    CHECK_EQ(A.m.state, UI_STATE_PAUSED);
    CHECK_EQ(C.count[PIP_BTN_EVENT], 1);
    CHECK_EQ(A.oev.count, 0);
    CHECK(A.timer.remaining_ms <= 90000 && A.timer.remaining_ms >= 89000);

    /* DUMP_FB answers with exactly 4 chunks */
    frame(&A, PIP_DUMP_FB, 0, 43, NULL);
    CHECK_EQ(C.count[PIP_DUMP_FB], 4);

    /* link drops after 3 s of silence -> standalone; actions are logged offline */
    app_tick(&A, 31100 + 3500);
    CHECK_EQ(A.m.link, LINK_STANDALONE);
    gesture(&A, BTN_BOOT, GEST_RESCUE);
    CHECK_EQ(A.oev.count, 1);
    CHECK(A.timer.remaining_ms >= 120000);
    gesture(&A, BTN_BOOT, GEST_SHORT);
    CHECK_EQ(A.m.state, UI_STATE_STEP_DONE);
    CHECK_EQ(A.oev.count, 2);
    CHECK_EQ(A.oev.ev[1].kind, OEV_STEP_COMPLETE);
    /* KEY short on Step Done starts the next step offline */
    gesture(&A, BTN_KEY, GEST_SHORT);
    CHECK_EQ(A.m.state, UI_STATE_RUNNING);
    CHECK(strcmp(A.m.step_id, "s2") == 0);
    CHECK_EQ(A.timer.remaining_ms, 600000);
    /* voice needs the PC */
    gesture(&A, BTN_KEY, GEST_HOLD_START);
    CHECK_EQ(A.m.state, UI_STATE_RUNNING);
    CHECK(strcmp(A.m.toast, "Connect PC for Voice") == 0);

    /* reconnect: OFFLINE_EVENTS sent (reliable) and cleared only after matching ACK */
    int before = C.count[PIP_OFFLINE_EVENTS];
    frame(&A, PIP_HEARTBEAT, 0, 50, NULL);
    app_tick(&A, A.now_ms + 10);
    CHECK_EQ(C.count[PIP_OFFLINE_EVENTS], before + 1);
    CHECK(strstr((const char *)C.last_payload, "STEP_COMPLETE") != NULL);
    uint16_t oseq = C.last_seq[PIP_OFFLINE_EVENTS];
    uint8_t ackp[6] = {(uint8_t)(oseq + 1), (uint8_t)((oseq + 1) >> 8), 0, 0, 0, 0};
    pip_frame_t af = {PIP_ACK, 0, 51, 6, ackp};
    app_on_frame(&A, &af); /* wrong ref_seq: keep queue */
    CHECK(A.oev.count > 0);
    ackp[0] = (uint8_t)oseq;
    ackp[1] = (uint8_t)(oseq >> 8);
    app_on_frame(&A, &af);
    CHECK_EQ(A.oev.count, 0);

    /* alarm: KEY double dismisses and restores previous screen */
    frame(&A, PIP_ALARM_TRIGGER, PIP_FLAG_ACK_REQUIRED, 52,
          "{\"alarm_id\":\"al1\",\"title\":\"Call dentist\",\"hhmm\":\"15:00\",\"audio_mode\":\"CHIME\"}");
    CHECK_EQ(A.m.state, UI_STATE_ALARM_RINGING);
    gesture(&A, BTN_KEY, GEST_DOUBLE);
    CHECK_EQ(A.m.state, UI_STATE_RUNNING);
    CHECK_EQ(A.m.page, PAGE_FOCUS);
    /* KEY double toggles agenda; BOOT short returns to focus */
    gesture(&A, BTN_KEY, GEST_DOUBLE);
    CHECK_EQ(A.m.page, PAGE_AGENDA);
    gesture(&A, BTN_BOOT, GEST_SHORT);
    CHECK_EQ(A.m.page, PAGE_FOCUS);
    CHECK_EQ(A.m.state, UI_STATE_RUNNING);

    /* calendar sync fills agenda */
    frame(&A, PIP_CALENDAR_SYNC, 0, 53,
          "{\"rev\":2,\"date_label\":\"Mon, Nov 23\",\"today\":[{\"id\":\"t1\",\"title\":\"Team Sync\","
          "\"hhmm\":\"\",\"kind\":0,\"done\":true}],\"tomorrow_count\":2,\"parked_count\":3,"
          "\"upcoming_alarms\":[{\"id\":\"al2\",\"epoch_s\":1763928000,\"title\":\"Gym\",\"chime_id\":4,"
          "\"enabled\":true}]}");
    CHECK_EQ(A.m.today_count, 1);
    CHECK(A.m.today[0].done);
    CHECK_EQ(A.alarm_count, 1);
    CHECK(strcmp(A.m.date_label, "Mon, Nov 23") == 0);
    TT_DONE();
}
