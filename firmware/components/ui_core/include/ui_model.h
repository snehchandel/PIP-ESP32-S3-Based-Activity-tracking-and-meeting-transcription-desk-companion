/* Everything a screen needs to render. Filled by app_controller from local timer,
 * host UI_UPDATE / CALENDAR_SYNC / ALARM_TRIGGER frames and board telemetry. */
#ifndef UI_MODEL_H
#define UI_MODEL_H

#include <stdbool.h>
#include <stdint.h>

#include "mascot.h"

typedef enum {
    UI_STATE_IDLE_READY = 0,
    UI_STATE_LISTENING,
    UI_STATE_TRANSCRIBING,
    UI_STATE_THINKING,
    UI_STATE_RUNNING,
    UI_STATE_PAUSED,
    UI_STATE_BREAK,
    UI_STATE_STEP_DONE,
    UI_STATE_ALARM_RINGING,
    UI_STATE_NEEDS_CONFIRMATION,
    UI_STATE_SLEEP,
    UI_STATE_ERROR_RECOVERABLE,
    UI_STATE_VOICE_PICK, /* device-local: choose what the voice message is about */
    UI_STATE_COUNT
} ui_state_t;

typedef enum { PAGE_FOCUS = 0, PAGE_AGENDA = 1 } ui_page_t;
typedef enum { LINK_STANDALONE = 0, LINK_TETHERED = 1 } link_state_t;
typedef enum { TIMER_STOPPED = 0, TIMER_RUNNING = 1, TIMER_PAUSED = 2 } timer_state_t;

#define UI_AGENDA_MAX 8
#define UI_VOICE_CHOICES 4 /* picker order: Calendar, Brain dump, Focus, Alarms */

typedef struct {
    char id[24];
    char title[40];
    char hhmm[6];
    uint8_t kind; /* 0 task, 1 reminder, 2 alarm */
    bool done;
} agenda_item_t;

typedef struct {
    ui_state_t state;
    ui_page_t page;
    link_state_t link;

    bool clock_valid;
    uint8_t hh, mm;
    char date_label[20];

    bool has_active_step;
    char task_title[64]; /* host sends the short device title (<= 22 chars) */
    char step_id[24];
    char step_title[96];
    uint8_t step_index, step_total; /* 1-based index */
    bool is_starter;
    timer_state_t timer_state;
    uint32_t remaining_ms;
    uint32_t step_total_ms;
    char next_step_title[64];
    uint16_t next_step_min;
    uint16_t parked_count;
    char next_alarm_hhmm[6];
    char clarification[96];

    uint16_t listen_elapsed_s;
    uint16_t listen_max_s;
    uint8_t audio_level; /* 0..8 bars */
    char thinking_stage[32];
    uint8_t voice_choice; /* picker index 0..3 */

    char alarm_title[64];
    char alarm_hhmm[6];
    uint8_t alarm_audio; /* 0 chime, 1 voice */

    uint32_t break_remaining_ms;
    char done_title[96];

    agenda_item_t today[UI_AGENDA_MAX];
    uint8_t today_count;
    uint8_t tomorrow_count;

    bool batt_valid;
    uint8_t batt_pct;

    /* environment: on-board SHTC3 + outdoor weather synced from the PC */
    bool in_valid;
    int16_t in_temp_c10; /* 0.1 C */
    uint8_t in_hum;      /* % RH */
    bool out_valid;
    int16_t out_temp_c10;
    uint8_t out_hum;
    uint8_t out_code; /* 0 sun, 1 cloud, 2 rain, 3 snow, 4 storm, 5 fog, 6 sun+cloud, 7 moon, 8 moon+cloud, 9 drizzle */

    char error_title[28];
    char error_text[120];
    bool error_flash; /* inverted frame of the attention flash */

    mascot_pose_t pose; /* live animation pose */
    uint32_t anim_ms;   /* animation clock for header icons */
    char toast[40];
} ui_model_t;

typedef enum {
    SCREEN_IDLE_READY = 0,
    SCREEN_LISTENING,
    SCREEN_THINKING,
    SCREEN_FOCUS_RUNNING,
    SCREEN_PAUSED,
    SCREEN_BREAK,
    SCREEN_STEP_DONE,
    SCREEN_DAILY_TASKS,
    SCREEN_ALARM_RINGING,
    SCREEN_NEEDS_CONFIRMATION,
    SCREEN_STANDALONE_SLEEP,
    SCREEN_VOICE_PICK,
    SCREEN_ERROR,
    SCREEN_COUNT
} ui_screen_t;

void ui_model_init(ui_model_t *m);
ui_screen_t ui_screen_for(const ui_model_t *m);
const char *ui_screen_name(ui_screen_t s);
/* Which mascot expression the current screen shows (drives the animation repertoire). */
pip_expr_t ui_expr_for(const ui_model_t *m);
/* Which PIP act library the current screen uses. */
pip_mode_t ui_mode_for(const ui_model_t *m);
/* Picker labels and their protocol activity ids (0 brain dump, 1 calendar, 2 focus, 3 alarms). */
const char *ui_voice_choice_label(uint8_t choice);
uint8_t ui_voice_choice_activity(uint8_t choice);

#endif
