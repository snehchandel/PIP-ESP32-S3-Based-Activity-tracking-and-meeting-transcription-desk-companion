/* sim_rlcd --render-all <dir>: renders all 11 screens -> raw PNG + bounding-box meta JSON. */
#include <stdio.h>
#include <string.h>
#include <time.h>

#include "png_write.h"
#include "sim_scenarios.h"
#include "ui_render.h"

#ifdef _WIN32
#include <direct.h>
#define MKDIR(p) _mkdir(p)
#else
#include <sys/stat.h>
#define MKDIR(p) mkdir(p, 0755)
#endif

static int write_meta(const char *path, const ui_meta_t *meta, double render_ms)
{
    FILE *f = fopen(path, "w");
    if (!f) {
        return -1;
    }
    fprintf(f, "{\n  \"screen\": \"%s\",\n  \"render_ms\": %.4f,\n  \"boxes\": [\n", ui_screen_name(meta->screen),
            render_ms);
    for (int i = 0; i < meta->n; i++) {
        const ui_box_t *b = &meta->boxes[i];
        fprintf(f, "    {\"name\": \"%s\", \"x\": %d, \"y\": %d, \"w\": %d, \"h\": %d, \"parent\": %d}%s\n", b->name,
                b->r.x, b->r.y, b->r.w, b->r.h, b->parent, i + 1 < meta->n ? "," : "");
    }
    fprintf(f, "  ]\n}\n");
    fclose(f);
    return 0;
}

int sim_render_all(const char *dir)
{
    static rlcd_fb_t fb;
    static ui_meta_t meta;
    char path[512];
    MKDIR(dir);
    snprintf(path, sizeof path, "%s/raw", dir);
    MKDIR(path);
    snprintf(path, sizeof path, "%s/meta", dir);
    MKDIR(path);
    int failures = 0;
    for (int s = 0; s < SCREEN_COUNT; s++) {
        ui_model_t m;
        sim_scenario((ui_screen_t)s, &m);
        if (ui_screen_for(&m) != (ui_screen_t)s) {
            fprintf(stderr, "scenario %d selects wrong screen %d\n", s, (int)ui_screen_for(&m));
            failures++;
        }
        const int reps = 50;
        clock_t t0 = clock();
        for (int r = 0; r < reps; r++) {
            ui_render(&fb, &m, &meta);
        }
        double ms = (double)(clock() - t0) * 1000.0 / CLOCKS_PER_SEC / reps;
        snprintf(path, sizeof path, "%s/raw/%s.png", dir, ui_screen_name((ui_screen_t)s));
        failures += png_write_fb(path, &fb) != 0;
        snprintf(path, sizeof path, "%s/meta/%s.json", dir, ui_screen_name((ui_screen_t)s));
        failures += write_meta(path, &meta, ms) != 0;
        printf("rendered %-24s %6.3f ms  boxes=%d\n", ui_screen_name((ui_screen_t)s), ms, meta.n);
    }
    return failures ? 1 : 0;
}

/* sim_rlcd --render-acts <dir>: 4 frames of every PIP act (+ the 10 weather icons) for contact sheets. */
int sim_render_acts(const char *dir)
{
    static rlcd_fb_t fb;
    char path[512];
    MKDIR(dir);
    snprintf(path, sizeof path, "%s/acts", dir);
    MKDIR(path);
    int failures = 0;
    for (int mode = 0; mode < PIP_MODE_COUNT; mode++) {
        ui_model_t m;
        bool found = false;
        for (int s = 0; s < SCREEN_COUNT && !found; s++) {
            sim_scenario((ui_screen_t)s, &m);
            found = ui_mode_for(&m) == (pip_mode_t)mode;
        }
        if (!found) {
            continue;
        }
        int nacts = mode == PIP_MODE_PICK ? 1 : mascot_act_count((pip_mode_t)mode);
        for (int act = 0; act < nacts; act++) {
            for (int k = 0; k < 4; k++) {
                pip_perf_t pf = {(uint8_t)mode, (uint8_t)act, (uint8_t)(k % mascot_act_count((pip_mode_t)mode) == 0 ? 0 : 0),
                                 1, 1};
                float D = mascot_perf_seconds(&pf);
                float t = D * (0.2f + 0.2f * (float)k);
                if (mode == PIP_MODE_PICK) {
                    m.voice_choice = (uint8_t)k;
                    mascot_anim_t an;
                    mascot_anim_init(&an, 7, 0);
                    mascot_set_mode(&an, PIP_MODE_PICK, 0);
                    mascot_set_pick(&an, k, 4);
                    for (uint32_t ms = 0; ms <= 1500; ms += 50) mascot_anim_step(&an, ms);
                    m.pose = an.pose;
                } else {
                    mascot_perf_pose(&pf, t, D, &m.pose);
                }
                m.anim_ms = (uint32_t)(t * 1000.0f);
                ui_render(&fb, &m, NULL);
                snprintf(path, sizeof path, "%s/acts/%02d_%s__%02d_%s__%d.png", dir, mode, mascot_mode_name((pip_mode_t)mode),
                         act, mode == PIP_MODE_PICK ? "pick" : mascot_act_name((pip_mode_t)mode, act), k);
                failures += png_write_fb(path, &fb) != 0;
            }
        }
    }
    for (int code = 0; code < 10; code++) {
        ui_model_t m;
        sim_scenario(SCREEN_IDLE_READY, &m);
        m.out_valid = true;
        m.out_code = (uint8_t)code;
        m.anim_ms = 1234u * (uint32_t)(code + 1);
        ui_render(&fb, &m, NULL);
        snprintf(path, sizeof path, "%s/acts/weather_%d.png", dir, code);
        failures += png_write_fb(path, &fb) != 0;
    }
    printf("acts rendered (%d failures)\n", failures);
    return failures ? 1 : 0;
}
