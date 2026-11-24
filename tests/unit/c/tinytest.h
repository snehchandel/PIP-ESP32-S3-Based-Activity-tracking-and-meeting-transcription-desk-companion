/* Minimal assertion harness for CTest C unit tests. */
#ifndef TINYTEST_H
#define TINYTEST_H

#include <stdio.h>
#include <stdlib.h>

static int tt_failures = 0;
static int tt_checks = 0;

#define CHECK(cond)                                                                    \
    do {                                                                               \
        tt_checks++;                                                                   \
        if (!(cond)) {                                                                 \
            tt_failures++;                                                             \
            fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);            \
        }                                                                              \
    } while (0)

#define CHECK_EQ(a, b)                                                                 \
    do {                                                                               \
        long long _a = (long long)(a), _b = (long long)(b);                            \
        tt_checks++;                                                                   \
        if (_a != _b) {                                                                \
            tt_failures++;                                                             \
            fprintf(stderr, "FAIL %s:%d: %s == %s (%lld != %lld)\n", __FILE__, __LINE__, \
                    #a, #b, _a, _b);                                                   \
        }                                                                              \
    } while (0)

#define TT_DONE()                                                                      \
    do {                                                                               \
        printf("%d checks, %d failures\n", tt_checks, tt_failures);                    \
        return tt_failures ? 1 : 0;                                                    \
    } while (0)

#endif
