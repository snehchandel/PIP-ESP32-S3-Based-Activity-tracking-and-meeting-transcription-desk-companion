#include "ui_render.h"

#include <string.h>

#include "ui_layout.h"

void ui_model_init(ui_model_t *m)
{
    memset(m, 0, sizeof *m);
    m->state = UI_STATE_IDLE_READY;
    m->page = PAGE_FOCUS;
    m->link = LINK_STANDALONE;
    m->listen_max_s = 60;
    m->voice_choice = 1; /* Brain dump */
    mascot_home_pose(&m->pose);
}

ui_screen_t ui_screen_for(const ui_model_t *m)
{
    switch (m->state) {
    case UI_STATE_ALARM_RINGING: return SCREEN_ALARM_RINGING;
    case UI_STATE_ERROR_RECOVERABLE: return SCREEN_ERROR;
    case UI_STATE_VOICE_PICK: return SCREEN_VOICE_PICK;
    case UI_STATE_LISTENING: return SCREEN_LISTENING;
    case UI_STATE_TRANSCRIBING:
    case UI_STATE_THINKING: return SCREEN_THINKING;
    case UI_STATE_NEEDS_CONFIRMATION: return SCREEN_NEEDS_CONFIRMATION;
    default: break;
    }
    if (m->page == PAGE_AGENDA) {
        return SCREEN_DAILY_TASKS;
    }
    switch (m->state) {
    case UI_STATE_STEP_DONE: return SCREEN_STEP_DONE;
    case UI_STATE_BREAK: return SCREEN_BREAK;
    case UI_STATE_RUNNING: return SCREEN_FOCUS_RUNNING;
    case UI_STATE_PAUSED: return SCREEN_PAUSED;
    case UI_STATE_SLEEP: return SCREEN_STANDALONE_SLEEP;
    default: return SCREEN_IDLE_READY;
    }
}

pip_expr_t ui_expr_for(const ui_model_t *m)
{
    static const pip_expr_t by_screen[SCREEN_COUNT] = {
        PIP_EXPR_READY, PIP_EXPR_LISTENING, PIP_EXPR_THINKING, PIP_EXPR_WORKING, PIP_EXPR_PAUSED, PIP_EXPR_PAUSED,
        PIP_EXPR_DONE,  PIP_EXPR_READY,     PIP_EXPR_ALARM,    PIP_EXPR_THINKING, PIP_EXPR_SLEEP, PIP_EXPR_LISTENING,
        PIP_EXPR_THINKING};
    return by_screen[ui_screen_for(m)];
}

pip_mode_t ui_mode_for(const ui_model_t *m)
{
    static const pip_mode_t by_screen[SCREEN_COUNT] = {
        PIP_MODE_IDLE,   PIP_MODE_LISTEN,  PIP_MODE_THINK,   PIP_MODE_FOCUS, PIP_MODE_PAUSE,
        PIP_MODE_BREAK,  PIP_MODE_DONE,    PIP_MODE_AGENDA,  PIP_MODE_ALARM, PIP_MODE_CONFIRM,
        PIP_MODE_SLEEP,  PIP_MODE_PICK,    PIP_MODE_ERROR};
    return by_screen[ui_screen_for(m)];
}

const char *ui_screen_name(ui_screen_t s)
{
    static const char *const names[SCREEN_COUNT] = {
        "01_idle_ready",     "02_listening",          "03_thinking",         "04_focus_running", "05_paused",
        "06_break_screen",   "07_step_done",          "08_daily_tasks",      "09_alarm_ringing",
        "10_needs_confirmation", "11_standalone_sleep", "12_voice_pick", "13_error"};
    return (unsigned)s < SCREEN_COUNT ? names[s] : "unknown";
}

const char *ui_voice_choice_label(uint8_t choice)
{
    static const char *const labels[UI_VOICE_CHOICES] = {"Calendar", "Brain dump", "Focus", "Alarms"};
    return labels[choice % UI_VOICE_CHOICES];
}

uint8_t ui_voice_choice_activity(uint8_t choice)
{
    static const uint8_t act[UI_VOICE_CHOICES] = {1, 0, 2, 3}; /* -> protocol activity id */
    return act[choice % UI_VOICE_CHOICES];
}

typedef void (*screen_fn)(rlcd_fb_t *, const ui_model_t *, ui_meta_t *);

void ui_render(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    static const screen_fn fns[SCREEN_COUNT] = {
        ui_screen_idle,  ui_screen_listening, ui_screen_thinking, ui_screen_focus, ui_screen_paused,
        ui_screen_break, ui_screen_done,      ui_screen_daily,    ui_screen_alarm, ui_screen_confirm,
        ui_screen_sleep, ui_screen_voice_pick, ui_screen_error};
    ui_screen_t s = ui_screen_for(m);
    if (meta) {
        memset(meta, 0, sizeof *meta);
        meta->screen = s;
    }
    fb_clear(fb, INK_WHITE);
    fns[s](fb, m, meta);
    if (m->toast[0] && s != SCREEN_STANDALONE_SLEEP && s != SCREEN_ERROR) {
        /* transient 2 s toast: inverted pill floating above the status bar */
        const font_t *f = &FONT_14B;
        int w = text_width(f, m->toast) + 24;
        if (w > RLCD_W - 2 * UI_MARGIN) {
            w = RLCD_W - 2 * UI_MARGIN;
        }
        int x = (RLCD_W - w) / 2, y = BAR_Y - 34;
        fb_fill_rrect(fb, x - 2, y - 2, w + 4, 32, 14, INK_WHITE);
        fb_fill_rrect(fb, x, y, w, 28, 12, INK_BLACK);
        text_draw_fit(fb, f, x + 12, y + 4, w - 24, m->toast, INK_WHITE);
    }
    if (m->error_flash && s == SCREEN_ERROR) {
        fb_invert(fb); /* attention flash: the reflective LCD can invert instantly */
    }
}
