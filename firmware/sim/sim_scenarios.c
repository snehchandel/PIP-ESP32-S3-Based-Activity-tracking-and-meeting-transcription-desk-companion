/* Visual-verification scenarios for `sim_rlcd --render-all` (sim-only; never linked on device).
 * Each scenario populates a ui_model_t so that ui_screen_for() selects the named screen. */
#include "sim_scenarios.h"

#include <stdio.h>
#include <string.h>

static void base(ui_model_t *m)
{
    ui_model_init(m);
    m->link = LINK_TETHERED;
    m->clock_valid = true;
    m->hh = 14;
    m->mm = 32;
    m->batt_valid = true;
    m->batt_pct = 82;
    snprintf(m->next_alarm_hhmm, sizeof m->next_alarm_hhmm, "15:00");
    m->parked_count = 3;
    m->has_active_step = true;
    snprintf(m->task_title, sizeof m->task_title, "Q3 report");
    snprintf(m->step_id, sizeof m->step_id, "step-1");
    snprintf(m->step_title, sizeof m->step_title, "Open template & add 3 headings");
    m->step_index = 1;
    m->step_total = 4;
    m->is_starter = true;
    m->remaining_ms = 2u * 60u * 1000u;
    m->step_total_ms = 2u * 60u * 1000u;
    snprintf(m->task_title, sizeof m->task_title, "Q3 report");
    m->in_valid = true;
    m->in_temp_c10 = 218;
    m->in_hum = 41;
    m->out_valid = true;
    m->out_temp_c10 = -35;
    m->out_hum = 78;
    m->out_code = 1;
}

void sim_scenario(ui_screen_t s, ui_model_t *m)
{
    base(m);
    switch (s) {
    case SCREEN_IDLE_READY: {
        snprintf(m->date_label, sizeof m->date_label, "Tue, Nov 24");
        m->today_count = 2;
        snprintf(m->today[0].title, sizeof m->today[0].title, "Pick up your son");
        snprintf(m->today[0].hhmm, sizeof m->today[0].hhmm, "15:43");
        snprintf(m->today[1].title, sizeof m->today[1].title, "Plan bedtime routine");
        snprintf(m->today[1].hhmm, sizeof m->today[1].hhmm, "17:00");
        static const char *const up[][3] = {{"Wed", "05:00", "Gym wake-up"}, {"Wed", "", "Draft Q3 summary"},
                                            {"Thu", "10:30", "Dentist"}};
        m->upcoming_count = 3;
        for (int i = 0; i < 3; i++) {
            snprintf(m->upcoming[i].day, sizeof m->upcoming[i].day, "%s", up[i][0]);
            snprintf(m->upcoming[i].hhmm, sizeof m->upcoming[i].hhmm, "%s", up[i][1]);
            snprintf(m->upcoming[i].title, sizeof m->upcoming[i].title, "%s", up[i][2]);
        }
        break;
    }
    case SCREEN_LISTENING:
        m->state = UI_STATE_LISTENING;
        m->listen_elapsed_s = 14;
        m->audio_level = 5;
        break;
    case SCREEN_THINKING:
        m->state = UI_STATE_THINKING;
        snprintf(m->thinking_stage, sizeof m->thinking_stage, "Breaking into steps...");
        break;
    case SCREEN_FOCUS_RUNNING:
        m->state = UI_STATE_RUNNING;
        m->timer_state = TIMER_RUNNING;
        m->is_starter = false;
        m->step_index = 2;
        m->remaining_ms = 25u * 60u * 1000u;
        m->step_total_ms = 25u * 60u * 1000u;
        snprintf(m->step_title, sizeof m->step_title, "Draft the summary section for Q3");
        m->remaining_ms = 18u * 60u * 1000u + 42u * 1000u;
        break;
    case SCREEN_PAUSED:
        m->state = UI_STATE_PAUSED;
        m->timer_state = TIMER_PAUSED;
        m->step_index = 2;
        m->is_starter = false;
        m->remaining_ms = 18u * 60u * 1000u + 42u * 1000u;
        m->step_total_ms = 25u * 60u * 1000u;
        snprintf(m->step_title, sizeof m->step_title, "Draft the summary section for Q3");
        break;
    case SCREEN_BREAK:
        m->state = UI_STATE_BREAK;
        m->break_remaining_ms = 5u * 60u * 1000u;
        break;
    case SCREEN_STEP_DONE:
        m->state = UI_STATE_STEP_DONE;
        snprintf(m->done_title, sizeof m->done_title, "Open template & add 3 headings");
        snprintf(m->next_step_title, sizeof m->next_step_title, "Export Q3 metrics");
        m->next_step_min = 10;
        break;
    case SCREEN_DAILY_TASKS:
        m->page = PAGE_AGENDA;
        snprintf(m->date_label, sizeof m->date_label, "Mon, Nov 23");
        m->today_count = 3;
        snprintf(m->today[0].title, sizeof m->today[0].title, "Team Sync");
        m->today[0].done = true;
        snprintf(m->today[1].title, sizeof m->today[1].title, "Draft Q3");
        snprintf(m->today[2].title, sizeof m->today[2].title, "Call dentist");
        snprintf(m->today[2].hhmm, sizeof m->today[2].hhmm, "15:00");
        m->tomorrow_count = 2;
        break;
    case SCREEN_ALARM_RINGING:
        m->state = UI_STATE_ALARM_RINGING;
        snprintf(m->alarm_hhmm, sizeof m->alarm_hhmm, "15:00");
        snprintf(m->alarm_title, sizeof m->alarm_title, "Call the dentist about Tuesday");
        m->alarm_audio = 0;
        break;
    case SCREEN_NEEDS_CONFIRMATION:
        m->state = UI_STATE_NEEDS_CONFIRMATION;
        snprintf(m->clarification, sizeof m->clarification, "Gym on Friday at 2:00 PM?");
        break;
    case SCREEN_VOICE_PICK:
        m->state = UI_STATE_VOICE_PICK;
        m->voice_choice = 1;
        snprintf(m->wake_label, sizeof m->wake_label, "Hi ESP");
        break;
    case SCREEN_ERROR:
        m->state = UI_STATE_ERROR_RECOVERABLE;
        snprintf(m->error_title, sizeof m->error_title, "AI has left the device");
        snprintf(m->error_text, sizeof m->error_text, "Kimi couldn't be reached. Your words are saved as a parked note.");
        break;
    case SCREEN_STANDALONE_SLEEP:
    default:
        m->state = UI_STATE_SLEEP;
        m->link = LINK_STANDALONE;
        m->has_active_step = false;
        m->parked_count = 0;
        break;
    }
}
