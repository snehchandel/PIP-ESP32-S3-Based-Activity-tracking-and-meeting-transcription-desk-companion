/* private: choreography tables shared by mascot.c and mascot_acts.c */
#ifndef PIP_MASCOT_ACTS_H
#define PIP_MASCOT_ACTS_H

#include "mascot.h"

int mascot_act_variants(pip_mode_t mode, int act);
void mascot_pick_pose(mascot_pose_t *p, float t, int row, int rows);

#endif
