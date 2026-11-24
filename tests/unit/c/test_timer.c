/* Local timer, rescue split invariant, offline event queue. */
#include <string.h>

#include "local_timer.h"
#include "tinytest.h"

int main(void)
{
    local_timer_t t;
    lt_load(&t, 120000, 120000, LT_PAUSED, 0);
    lt_start(&t, 1000);
    CHECK(!lt_tick(&t, 31000));
    CHECK_EQ(t.remaining_ms, 90000);
    lt_pause(&t, 41000);
    CHECK_EQ(t.state, LT_PAUSED);
    CHECK_EQ(t.remaining_ms, 80000);
    CHECK(!lt_tick(&t, 500000)); /* paused: nothing elapses */
    CHECK_EQ(t.remaining_ms, 80000);
    lt_start(&t, 600000);
    CHECK(lt_tick(&t, 680000)); /* reaches zero exactly once */
    CHECK_EQ(t.state, LT_STOPPED);
    CHECK(!lt_tick(&t, 690000));
    lt_start(&t, 700000); /* cannot start an empty timer */
    CHECK_EQ(t.state, LT_STOPPED);

    /* rescue split: never loses work, min 120 s each half */
    uint32_t c, nx;
    lt_split_calc(1500, &c, &nx);
    CHECK_EQ(c, 750);
    CHECK_EQ(nx, 750);
    lt_split_calc(1501, &c, &nx);
    CHECK_EQ(c, 750);
    CHECK_EQ(nx, 751);
    lt_split_calc(200, &c, &nx);
    CHECK_EQ(c, 120);
    CHECK_EQ(nx, 120);
    for (uint32_t rem = 1; rem < 4000; rem += 7) {
        lt_split_calc(rem, &c, &nx);
        CHECK(c + nx >= rem);
        CHECK(c >= 120 && nx >= 120);
    }

    /* offline queue: ordering, overflow evicts oldest TIMER_DELTA first */
    oev_queue_t q;
    oev_init(&q);
    oev_push(&q, OEV_STEP_COMPLETE, "s1", 0, 100);
    oev_push(&q, OEV_TIMER_DELTA, "s2", 5000, 101);
    for (int i = 0; i < 30; i++) {
        oev_push(&q, OEV_STEP_SPLIT, "s3", 1000, 102);
    }
    CHECK_EQ(q.count, 32);
    oev_push(&q, OEV_ALARM_ACK, "a1", 0, 103);
    CHECK_EQ(q.count, 32);
    CHECK_EQ(q.dropped, 1);
    CHECK_EQ(oev_at(&q, 0)->kind, OEV_STEP_COMPLETE); /* completion preserved */
    CHECK_EQ(oev_at(&q, 1)->kind, OEV_STEP_SPLIT);
    CHECK_EQ(oev_at(&q, 31)->kind, OEV_ALARM_ACK);
    CHECK_EQ(oev_at(&q, 31)->seq, 33);

    oev_queue_t q2;
    oev_init(&q2);
    oev_push(&q2, OEV_STEP_COMPLETE, "abc", 0, 1763900000u);
    char json[256];
    size_t n = oev_to_json(&q2, 77, json, sizeof json);
    CHECK(n > 0);
    CHECK(strcmp(json, "[{\"seq\":1,\"boot_id\":77,\"kind\":\"STEP_COMPLETE\",\"ref_id\":\"abc\",\"remaining_ms\":0,"
                       "\"ts_epoch\":1763900000}]") == 0);
    CHECK_EQ(oev_to_json(&q2, 77, json, 10), 0);
    oev_clear(&q2);
    CHECK_EQ(oev_to_json(&q2, 1, json, sizeof json), 2);
    TT_DONE();
}
