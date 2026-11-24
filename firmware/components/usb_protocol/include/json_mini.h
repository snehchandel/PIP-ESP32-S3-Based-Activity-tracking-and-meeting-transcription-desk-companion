/* Minimal allocation-free JSON reader for flat host->device payloads (C99). */
#ifndef JSON_MINI_H
#define JSON_MINI_H

#include <stdbool.h>
#include <stddef.h>

typedef struct {
    const char *p; /* start of value */
    size_t n;      /* length of raw value text */
} jm_span_t;

/* Validate that [s, s+n) is a single well-formed JSON object. */
bool jm_valid_object(const char *s, size_t n);
/* Find member `key` of the top-level object in [s, s+n). */
bool jm_find(const char *s, size_t n, const char *key, jm_span_t *out);
bool jm_get_str(const char *s, size_t n, const char *key, char *out, size_t cap);
bool jm_get_long(const char *s, size_t n, const char *key, long *out);
bool jm_get_bool(const char *s, size_t n, const char *key, bool *out);
/* Iterate array elements: pass the array span, an index cursor starting at 0. */
bool jm_array_next(jm_span_t arr, size_t *cursor, jm_span_t *elem);
/* Decode a JSON string value span (with quotes) into UTF-8. */
bool jm_span_str(jm_span_t v, char *out, size_t cap);

#endif
