#include <string.h>

#include "json_mini.h"
#include "tinytest.h"

int main(void)
{
    const char *j = "{ \"rev\": 12, \"ui_state\":\"RUNNING\", \"is_starter\": true, \"nested\": {\"rev\": 99},"
                    " \"title\": \"Caf\\u00e9 \\\"plan\\\"\", \"neg\": -5,"
                    " \"today\": [ {\"id\":\"a\",\"done\":false}, {\"id\":\"b\",\"done\":true} ], \"empty\": [] }";
    size_t n = strlen(j);
    CHECK(jm_valid_object(j, n));
    long v = 0;
    CHECK(jm_get_long(j, n, "rev", &v) && v == 12);
    CHECK(jm_get_long(j, n, "neg", &v) && v == -5);
    char s[32];
    CHECK(jm_get_str(j, n, "ui_state", s, sizeof s) && strcmp(s, "RUNNING") == 0);
    CHECK(jm_get_str(j, n, "title", s, sizeof s) && strcmp(s, "Caf\xC3\xA9 \"plan\"") == 0);
    bool b = false;
    CHECK(jm_get_bool(j, n, "is_starter", &b) && b);
    CHECK(!jm_get_long(j, n, "missing", &v));

    jm_span_t arr, el;
    size_t cur = 0;
    CHECK(jm_find(j, n, "today", &arr));
    CHECK(jm_array_next(arr, &cur, &el));
    CHECK(jm_get_str(el.p, el.n, "id", s, sizeof s) && strcmp(s, "a") == 0);
    CHECK(jm_array_next(arr, &cur, &el));
    CHECK(jm_get_bool(el.p, el.n, "done", &b) && b);
    CHECK(!jm_array_next(arr, &cur, &el));
    cur = 0;
    CHECK(jm_find(j, n, "empty", &arr) && !jm_array_next(arr, &cur, &el));

    /* truncation never splits a UTF-8 sequence */
    char tiny[6];
    CHECK(jm_get_str(j, n, "title", tiny, sizeof tiny));
    CHECK(strcmp(tiny, "Café") == 0); /* 5 bytes + NUL fit exactly */
    char tiny5[5];
    CHECK(jm_get_str(j, n, "title", tiny5, sizeof tiny5));
    CHECK(strcmp(tiny5, "Caf") == 0); /* 2-byte e-acute does not fit: cut cleanly before it */

    /* exact-fit ASCII: "15:00" fits a 6-byte field (regression found on hardware) */
    const char *t = "{\"hhmm\":\"15:00\"}";
    char hhmm[6];
    CHECK(jm_get_str(t, strlen(t), "hhmm", hhmm, sizeof hhmm) && strcmp(hhmm, "15:00") == 0);
    char cut[4];
    CHECK(jm_get_str(t, strlen(t), "hhmm", cut, sizeof cut) && strcmp(cut, "15:") == 0);

    CHECK(!jm_valid_object("{\"a\":", 5));
    CHECK(!jm_valid_object("[1,2]", 5));
    CHECK(!jm_valid_object("{\"a\":1} x", 9));
    CHECK(!jm_valid_object("{\"a\" 1}", 7));
    TT_DONE();
}
