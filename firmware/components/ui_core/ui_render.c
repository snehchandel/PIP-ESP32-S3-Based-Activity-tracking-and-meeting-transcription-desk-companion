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
}

ui_screen_t ui_screen_for(const ui_model_t *m)
{
    switch (m->state) {
    case UI_STATE_ALARM_RINGING: return SCREEN_ALARM_RINGING;
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
    case UI_STATE_SLEEP:
    case UI_STATE_ERROR_RECOVERABLE: return SCREEN_STANDALONE_SLEEP;
    default: return SCREEN_IDLE_READY;
    }
}

const char *ui_screen_name(ui_screen_t s)
{
    static const char *const names[SCREEN_COUNT] = {
        "01_idle_ready", "02_listening",    "03_thinking",      "04_focus_running",
        "05_paused",     "06_break_screen", "07_step_done",     "08_daily_tasks",
        "09_alarm_ringing", "10_needs_confirmation", "11_standalone_sleep"};
    return (unsigned)s < SCREEN_COUNT ? names[s] : "unknown";
}

typedef void (*screen_fn)(rlcd_fb_t *, const ui_model_t *, ui_meta_t *);

void ui_render(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    static const screen_fn fns[SCREEN_COUNT] = {
        ui_screen_idle,  ui_screen_listening, ui_screen_thinking, ui_screen_focus, ui_screen_paused,
        ui_screen_break, ui_screen_done,      ui_screen_daily,    ui_screen_alarm, ui_screen_confirm,
        ui_screen_sleep};
    ui_screen_t s = ui_screen_for(m);
    if (meta) {
        memset(meta, 0, sizeof *meta);
        meta->screen = s;
    }
    fb_clear(fb, INK_WHITE);
    fns[s](fb, m, meta);
    if (m->toast[0] && s != SCREEN_STANDALONE_SLEEP) {
        /* transient 2 s toast: inverted pill floating above the status bar */
        const font_t *f = &FONT_16B;
        int w = text_width(f, m->toast) + 24;
        if (w > RLCD_W - 2 * UI_MARGIN) {
            w = RLCD_W - 2 * UI_MARGIN;
        }
        int x = (RLCD_W - w) / 2, y = BAR_Y - 34;
        fb_fill_rrect(fb, x - 2, y - 2, w + 4, 32, 14, INK_WHITE);
        fb_fill_rrect(fb, x, y, w, 28, 12, INK_BLACK);
        text_draw_fit(fb, f, x + 12, y + 4, w - 24, m->toast, INK_WHITE);
    }
}
