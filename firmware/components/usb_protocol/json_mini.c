#include "json_mini.h"

#include <stdlib.h>
#include <string.h>

static const char *ws(const char *p, const char *e)
{
    while (p < e && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')) {
        p++;
    }
    return p;
}

/* Returns pointer just past the value starting at p, or NULL if malformed. */
static const char *skip_value(const char *p, const char *e, int depth)
{
    p = ws(p, e);
    if (p >= e || depth > 16) {
        return NULL;
    }
    if (*p == '"') {
        for (p++; p < e; p++) {
            if (*p == '\\') {
                p++;
            } else if (*p == '"') {
                return p + 1;
            }
        }
        return NULL;
    }
    if (*p == '{' || *p == '[') {
        char close = *p == '{' ? '}' : ']';
        int obj = *p == '{';
        p = ws(p + 1, e);
        if (p < e && *p == close) {
            return p + 1;
        }
        for (;;) {
            if (obj) {
                p = skip_value(p, e, depth + 1); /* key */
                p = p ? ws(p, e) : NULL;
                if (!p || p >= e || *p != ':') {
                    return NULL;
                }
                p++;
            }
            p = skip_value(p, e, depth + 1);
            p = p ? ws(p, e) : NULL;
            if (!p || p >= e) {
                return NULL;
            }
            if (*p == close) {
                return p + 1;
            }
            if (*p != ',') {
                return NULL;
            }
            p++;
        }
    }
    const char *s = p;
    while (p < e && (strchr("+-.eE", *p) || (*p >= '0' && *p <= '9') || (*p >= 'a' && *p <= 'z'))) {
        p++;
    }
    return p > s ? p : NULL;
}

bool jm_valid_object(const char *s, size_t n)
{
    const char *e = s + n;
    const char *p = ws(s, e);
    if (p >= e || *p != '{') {
        return false;
    }
    p = skip_value(p, e, 0);
    return p && ws(p, e) == e;
}

bool jm_span_str(jm_span_t v, char *out, size_t cap)
{
    if (v.n < 2 || v.p[0] != '"' || cap == 0) {
        return false;
    }
    size_t o = 0;
    const char *p = v.p + 1, *e = v.p + v.n - 1;
    while (p < e && o + 1 < cap) { /* always keep room for the terminator */
        char c = *p++;
        if (c != '\\') {
            out[o++] = c;
            continue;
        }
        if (p >= e) {
            break;
        }
        c = *p++;
        if (c == 'n') {
            out[o++] = '\n';
        } else if (c == 't') {
            out[o++] = ' ';
        } else if (c == 'u' && e - p >= 4) {
            char hex[5] = {p[0], p[1], p[2], p[3], 0};
            unsigned long cp = strtoul(hex, NULL, 16);
            size_t need = cp < 0x80 ? 1 : (cp < 0x800 ? 2 : 3);
            if (o + need + 1 > cap) {
                break; /* never write a partial code point */
            }
            p += 4;
            if (cp < 0x80) {
                out[o++] = (char)cp;
            } else if (cp < 0x800) {
                out[o++] = (char)(0xC0 | (cp >> 6));
                out[o++] = (char)(0x80 | (cp & 0x3F));
            } else {
                out[o++] = (char)(0xE0 | (cp >> 12));
                out[o++] = (char)(0x80 | ((cp >> 6) & 0x3F));
                out[o++] = (char)(0x80 | (cp & 0x3F));
            }
        } else {
            out[o++] = c; /* \" \\ \/ and others */
        }
    }
    /* never leave a truncated UTF-8 sequence at the end */
    size_t k = o;
    while (k > 0 && ((unsigned char)out[k - 1] & 0xC0) == 0x80) {
        k--;
    }
    if (k > 0 && ((unsigned char)out[k - 1] & 0x80)) {
        unsigned char lead = (unsigned char)out[k - 1];
        size_t need = lead >= 0xF0 ? 4 : lead >= 0xE0 ? 3 : 2;
        if (o - (k - 1) < need) {
            o = k - 1;
        }
    }
    out[o] = 0;
    return true;
}

bool jm_find(const char *s, size_t n, const char *key, jm_span_t *out)
{
    const char *e = s + n;
    const char *p = ws(s, e);
    if (p >= e || *p != '{') {
        return false;
    }
    p = ws(p + 1, e);
    size_t klen = strlen(key);
    while (p < e && *p == '"') {
        const char *ks = p + 1;
        const char *ke = skip_value(p, e, 1);
        if (!ke) {
            return false;
        }
        int match = (size_t)(ke - 1 - ks) == klen && memcmp(ks, key, klen) == 0;
        p = ws(ke, e);
        if (p >= e || *p != ':') {
            return false;
        }
        const char *vs = ws(p + 1, e);
        const char *ve = skip_value(vs, e, 1);
        if (!ve) {
            return false;
        }
        if (match) {
            out->p = vs;
            out->n = (size_t)(ve - vs);
            return true;
        }
        p = ws(ve, e);
        if (p < e && *p == ',') {
            p = ws(p + 1, e);
        }
    }
    return false;
}

bool jm_get_str(const char *s, size_t n, const char *key, char *out, size_t cap)
{
    jm_span_t v;
    return jm_find(s, n, key, &v) && jm_span_str(v, out, cap);
}

bool jm_get_long(const char *s, size_t n, const char *key, long *out)
{
    jm_span_t v;
    if (!jm_find(s, n, key, &v) || v.n == 0 || v.n > 20 || v.p[0] == '"') {
        return false;
    }
    char tmp[24];
    memcpy(tmp, v.p, v.n);
    tmp[v.n] = 0;
    char *end = NULL;
    *out = strtol(tmp, &end, 10);
    return end != tmp;
}

bool jm_get_bool(const char *s, size_t n, const char *key, bool *out)
{
    jm_span_t v;
    if (!jm_find(s, n, key, &v)) {
        return false;
    }
    *out = v.n == 4 && memcmp(v.p, "true", 4) == 0;
    return v.n == 4 || v.n == 5;
}

bool jm_array_next(jm_span_t arr, size_t *cursor, jm_span_t *elem)
{
    const char *e = arr.p + arr.n;
    const char *p = arr.p + *cursor;
    if (*cursor == 0) {
        p = ws(arr.p, e);
        if (p >= e || *p != '[') {
            return false;
        }
        p++;
    }
    p = ws(p, e);
    if (p < e && *p == ',') {
        p = ws(p + 1, e);
    }
    if (p >= e || *p == ']') {
        return false;
    }
    const char *ve = skip_value(p, e, 1);
    if (!ve) {
        return false;
    }
    elem->p = p;
    elem->n = (size_t)(ve - p);
    *cursor = (size_t)(ve - arr.p);
    return true;
}
