/* app_controller integration: host frames, gesture matrix, offline log + reconnect. */
#include <stdio.h>
#include <string.h>

#include "app_controller.h"
#include "ui_layout.h"
#include "ui_render.h"
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

static int played_bytes;
static int play_events;
static int voice_aborts;

static void cap_play(void *ctx, uint8_t type, const uint8_t *p, uint16_t len)
{
    (void)ctx;
    play_events++;
    if (type == PIP_AUDIO_END_OUT && len >= 5 && p[4] == 1) {
        voice_aborts++;
    }
    if (type == PIP_AUDIO_DATA_OUT) {
        played_bytes += len - 6;
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
    app_io_t io = {NULL, cap_send, cap_chime, NULL, NULL, cap_play};
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

    /* PLAY_CHIME plays through the io callback; DIAG_REPORT request is answered */
    int chimes = C.chimes;
    uint8_t chime[4] = {2, 70, 0, 0};
    pip_frame_t cf = {PIP_PLAY_CHIME, PIP_FLAG_ACK_REQUIRED, 60, 4, chime};
    app_on_frame(&A, &cf);
    CHECK_EQ(C.chimes, chimes + 1);
    int diags = C.count[PIP_DIAG_REPORT];
    frame(&A, PIP_DIAG_REPORT, 0, 61, NULL);
    CHECK_EQ(C.count[PIP_DIAG_REPORT], diags + 1);
    CHECK(strstr((const char *)C.last_payload, "\"fw_ver\":\"" APP_FW_VERSION "\"") != NULL);
    /* AUDIO_*_OUT (host Piper voice) reaches the playback adapter; reliable frames are ACKed OK */
    int acks = C.count[PIP_ACK];
    uint8_t aout[12] = {0};
    pip_frame_t of = {PIP_AUDIO_START_OUT, PIP_FLAG_ACK_REQUIRED, 62, 12, aout};
    app_on_frame(&A, &of);
    CHECK_EQ(C.count[PIP_ACK], acks + 1);
    CHECK_EQ(C.last_payload[2], PIP_ACK_OK);
    static uint8_t pcm[6 + 640];
    pip_frame_t df = {PIP_AUDIO_DATA_OUT, 0, 63, sizeof pcm, pcm};
    app_on_frame(&A, &df);
    CHECK_EQ(played_bytes, 640);
    int aborts0 = voice_aborts; /* the earlier alarm dismissal already sent one abort */

    /* host can end a ringing alarm (app dismiss / 30 s test timeout) */
    frame(&A, PIP_ALARM_TRIGGER, 0, 64, "{\"alarm_id\":\"t\",\"title\":\"Test\",\"hhmm\":\"10:00\",\"audio_mode\":\"CHIME\"}");
    CHECK_EQ(A.m.state, UI_STATE_ALARM_RINGING);
    frame(&A, PIP_UI_UPDATE, 0, 65, "{\"rev\":9,\"ui_state\":\"RUNNING\",\"alarm_ringing\":false,\"step_id\":\"s2\","
                                    "\"timer_state\":\"RUNNING\",\"remaining_ms\":500000}");
    CHECK_EQ(A.m.state, UI_STATE_RUNNING);
    CHECK_EQ(voice_aborts, aborts0 + 1); /* any spoken wake-up still buffered is dropped */
    /* a dismiss on PIP itself also silences the speech at once */
    frame(&A, PIP_ALARM_TRIGGER, 0, 66, "{\"alarm_id\":\"v\",\"title\":\"Gym\",\"hhmm\":\"05:00\",\"audio_mode\":\"TTS\"}");
    gesture(&A, BTN_BOOT, GEST_SHORT);
    CHECK(A.m.state != UI_STATE_ALARM_RINGING);
    CHECK_EQ(voice_aborts, aborts0 + 2);
    /* host confirmation toast: shown once per id for APP_ACK_TOAST_MS */
    frame(&A, PIP_UI_UPDATE, 0, 67, "{\"rev\":10,\"ui_state\":\"RUNNING\",\"toast\":\"Alarm set: Wed 05:00\",\"toast_id\":7}");
    CHECK(strcmp(A.m.toast, "Alarm set: Wed 05:00") == 0);
    for (uint32_t k = 0; k < APP_ACK_TOAST_MS / 1000u - 1u; k++) { /* host heartbeats keep the link up */
        frame(&A, PIP_HEARTBEAT, 0, 69, NULL);
        app_tick(&A, A.now_ms + 1000);
    }
    CHECK(A.m.toast[0] != 0);
    frame(&A, PIP_HEARTBEAT, 0, 69, NULL);
    app_tick(&A, A.now_ms + 1500);
    CHECK(A.m.toast[0] == 0);
    frame(&A, PIP_UI_UPDATE, 0, 68, "{\"rev\":11,\"ui_state\":\"RUNNING\",\"toast\":\"Alarm set: Wed 05:00\",\"toast_id\":7}");
    CHECK(A.m.toast[0] == 0); /* same id again: not re-shown */
    /* unknown type is NACKed with UNKNOWN_TYPE */
    pip_frame_t uf = {0x99, PIP_FLAG_ACK_REQUIRED, 63, 0, NULL};
    app_on_frame(&A, &uf);
    CHECK_EQ(C.last_payload[2], PIP_ACK_UNKNOWN_TYPE);

    /* voice: KEY hold opens the activity picker (no recording, nothing reported), KEY click cycles,
     * KEY hold records with the chosen activity, BOOT backs out */
    int btn_reports = C.count[PIP_BTN_EVENT];
    int starts = C.count[PIP_AUDIO_START];
    ui_state_t prior = A.m.state;
    gesture(&A, BTN_KEY, GEST_HOLD_START);
    CHECK_EQ(A.m.state, UI_STATE_VOICE_PICK);
    gesture(&A, BTN_KEY, GEST_HOLD_END); /* releasing the opening hold does nothing */
    CHECK_EQ(A.m.state, UI_STATE_VOICE_PICK);
    CHECK_EQ(A.m.voice_choice, 1); /* Brain dump by default */
    gesture(&A, BTN_KEY, GEST_SHORT);
    gesture(&A, BTN_KEY, GEST_SHORT);
    gesture(&A, BTN_KEY, GEST_SHORT);
    CHECK_EQ(A.m.voice_choice, 0); /* -> Focus -> Alarms -> Calendar */
    gesture(&A, BTN_KEY, GEST_HOLD_START);
    CHECK_EQ(A.m.state, UI_STATE_LISTENING);
    CHECK_EQ(C.count[PIP_AUDIO_START], starts + 1);
    CHECK_EQ(C.last_payload[10], 1); /* activity id 1 = calendar in the former reserved field */
    gesture(&A, BTN_KEY, GEST_HOLD_END);
    CHECK_EQ(A.m.state, UI_STATE_TRANSCRIBING);
    CHECK_EQ(C.count[PIP_BTN_EVENT], btn_reports); /* picker + recording never toggled the host timer */
    A.m.state = prior;
    gesture(&A, BTN_KEY, GEST_HOLD_START);
    gesture(&A, BTN_BOOT, GEST_SHORT);
    CHECK_EQ(A.m.state, prior);
    /* wake word: first time opens the activity picker (no recording yet); again records hands-free */
    starts = C.count[PIP_AUDIO_START];
    CHECK(app_voice_wake(&A));
    CHECK_EQ(A.m.state, UI_STATE_VOICE_PICK);
    CHECK_EQ(C.count[PIP_AUDIO_START], starts);
    gesture(&A, BTN_KEY, GEST_SHORT); /* move the highlight */
    CHECK(app_voice_wake(&A));
    CHECK_EQ(A.m.state, UI_STATE_LISTENING);
    CHECK(A.hands_free);
    CHECK_EQ(C.count[PIP_AUDIO_START], starts + 1);
    CHECK_EQ(C.last_payload[10], ui_voice_choice_activity(A.m.voice_choice)); /* the highlighted activity */
    app_voice_end(&A); /* silence detected on the device */
    CHECK_EQ(A.m.state, UI_STATE_TRANSCRIBING);
    CHECK(!A.hands_free);
    CHECK(!app_voice_wake(&A)); /* busy transcribing: the wake word is ignored */
    A.m.state = prior;
    /* host raises "AI has left the device": shown with a flash, any click dismisses and reports */
    frame(&A, PIP_UI_UPDATE, 0, 70, "{\"rev\":20,\"ui_state\":\"ERROR_RECOVERABLE\",\"error_title\":\"AI has left the device\","
                                    "\"error_text\":\"Kimi couldn't be reached.\",\"step_id\":\"s2\",\"remaining_ms\":500000,"
                                    "\"timer_state\":\"RUNNING\",\"out_temp_c10\":-35,\"out_hum\":78,\"out_code\":2}");
    CHECK_EQ(A.m.state, UI_STATE_ERROR_RECOVERABLE);
    CHECK(strcmp(A.m.error_title, "AI has left the device") == 0);
    CHECK(A.m.out_valid && A.m.out_temp_c10 == -35 && A.m.out_hum == 78 && A.m.out_code == 2);
    app_tick(&A, A.now_ms + 350);
    CHECK(A.m.error_flash); /* attention flash (inverted frame) */
    app_tick(&A, A.now_ms + 3000);
    CHECK(!A.m.error_flash); /* flash stops, message stays */
    CHECK_EQ(A.m.state, UI_STATE_ERROR_RECOVERABLE);
    frame(&A, PIP_HEARTBEAT, 0, 71, NULL); /* host still linked */
    app_tick(&A, A.now_ms + 1);
    btn_reports = C.count[PIP_BTN_EVENT];
    gesture(&A, BTN_BOOT, GEST_SHORT);
    CHECK(A.m.state != UI_STATE_ERROR_RECOVERABLE);
    CHECK_EQ(C.count[PIP_BTN_EVENT], btn_reports + 1);
    /* device-side watchdog: stuck in THINKING without the host answering -> local error */
    A.m.state = UI_STATE_THINKING;
    for (uint32_t s = 0; s <= APP_STUCK_MS / 1000u + 1u; s++) { /* host keeps the link alive but never answers */
        A.now_ms += 1000;
        frame(&A, PIP_HEARTBEAT, 0, (uint16_t)(80 + s), NULL);
        app_tick(&A, A.now_ms);
    }
    CHECK_EQ(A.m.state, UI_STATE_ERROR_RECOVERABLE);
    CHECK(strcmp(A.m.error_title, "PIP got stuck") == 0);
    gesture(&A, BTN_KEY, GEST_SHORT);
    CHECK(A.m.state != UI_STATE_ERROR_RECOVERABLE);
    app_set_indoor(&A, true, 218, 41);
    CHECK(A.m.in_valid && A.m.in_temp_c10 == 218 && A.m.in_hum == 41);

    /* offline ringing repeats the alarm chime for one minute, then stops */
    app_tick(&A, A.now_ms + APP_LINK_TIMEOUT_MS + 500);
    CHECK_EQ(A.m.link, LINK_STANDALONE);
    app_ring_alarm(&A, "off", "Wake", "06:00", 0);
    int before_ring = C.chimes;
    uint32_t t0 = A.now_ms;
    for (uint32_t t = 0; t <= APP_RING_CHIME_FOR_MS + 10000u; t += 500u) {
        app_tick(&A, t0 + t);
    }
    int rings = C.chimes - before_ring;
    CHECK(rings >= 20 && rings <= 26); /* every 2.5 s for 60 s (plus the trigger chime) */
    CHECK_EQ(A.m.state, UI_STATE_ALARM_RINGING); /* screen stays until dismissed */
    gesture(&A, BTN_KEY, GEST_SHORT);

    /* calendar sync fills agenda */
    frame(&A, PIP_CALENDAR_SYNC, 0, 53,
          "{\"rev\":2,\"date_label\":\"Mon, Nov 23\",\"today\":[{\"id\":\"t1\",\"title\":\"Team Sync\","
          "\"hhmm\":\"\",\"kind\":0,\"done\":true}],\"tomorrow_count\":2,\"parked_count\":3,"
          "\"upcoming\":[{\"day\":\"Wed\",\"hhmm\":\"05:00\",\"title\":\"Gym wake-up\",\"kind\":2},"
          "{\"day\":\"Thu\",\"hhmm\":\"\",\"title\":\"Dentist\",\"kind\":0}],"
          "\"upcoming_alarms\":[{\"id\":\"al2\",\"epoch_s\":1763928000,\"title\":\"Gym\",\"chime_id\":4,"
          "\"enabled\":true}]}");
    CHECK_EQ(A.m.today_count, 1);
    CHECK(A.m.today[0].done);
    CHECK_EQ(A.alarm_count, 1);
    CHECK(strcmp(A.m.date_label, "Mon, Nov 23") == 0);
    CHECK_EQ(A.m.upcoming_count, 2); /* the board's "Coming up" list, separate from upcoming_alarms */
    CHECK(strcmp(A.m.upcoming[0].day, "Wed") == 0 && strcmp(A.m.upcoming[0].hhmm, "05:00") == 0);
    CHECK(strcmp(A.m.upcoming[1].title, "Dentist") == 0 && A.m.upcoming[1].hhmm[0] == 0);

    /* screen changes slide: frames keep coming for SLIDE_MS, then the plain new screen */
    static rlcd_fb_t plain;
    uint32_t t = A.now_ms + 1000u;
    A.m.state = UI_STATE_IDLE_READY;
    A.m.page = PAGE_FOCUS;
    A.now_ms = t;
    A.dirty = true;
    app_render_if_dirty(&A);
    A.sliding = false;
    A.m.page = PAGE_AGENDA; /* 2x: calendar -> slides in from the right */
    A.dirty = true;
    CHECK(app_render_if_dirty(&A));
    CHECK(A.sliding && A.slide_dir == 1);
    int frames = 1;
    bool mid_checked = false;
    ui_render(&plain, &A.m, NULL); /* PIP is one character: it stays put while the pages slide under it */
    for (t += 10u; t < A.slide_start_ms + SLIDE_MS + 100u; t += 10u) {
        A.now_ms = t;
        bool drew = app_render_if_dirty(&A);
        frames += drew;
        if (drew && A.sliding && !mid_checked && t >= A.slide_start_ms + SLIDE_MS / 3u) {
            mid_checked = true;
            for (int y = 146; y < 184; y++) { /* PIP's head at home: identical to the plain new screen */
                for (int x = 52; x < 100; x++) {
                    CHECK_EQ(fb_get(&A.fb, x, y), fb_get(&plain, x, y));
                }
            }
        }
    }
    CHECK(mid_checked);
    CHECK(!A.sliding);
    CHECK(frames >= 8 && frames <= 14); /* ~25 FPS, then one final frame */
    ui_render(&plain, &A.m, NULL);
    CHECK(memcmp(plain.px, A.fb.px, sizeof plain.px) == 0);
    A.m.page = PAGE_FOCUS; /* and back: from the left */
    A.dirty = true;
    app_render_if_dirty(&A);
    CHECK(A.sliding && A.slide_dir == -1);
    A.m.state = UI_STATE_ALARM_RINGING; /* interrupted mid-slide: alarms drop in from the top */
    A.now_ms += 100u;
    app_render_if_dirty(&A);
    CHECK(A.sliding && A.slide_dir == 2);
    TT_DONE();
}
