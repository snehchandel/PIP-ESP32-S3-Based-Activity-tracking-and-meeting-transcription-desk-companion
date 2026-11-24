/* sim_rlcd: host-native PIP device simulator built from the exact portable firmware modules.
 *   sim_rlcd --render-all <dir>          batch render all 11 screens (PNG + meta JSON)
 *   sim_rlcd --tcp 127.0.0.1:18422       virtual device speaking USB protocol v1 over TCP
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int sim_render_all(const char *dir);
int sim_tcp_run(const char *host, int port, const char *offline_events_json);

static void usage(void)
{
    fprintf(stderr, "usage: sim_rlcd --render-all <dir> | --tcp <host:port> [--offline-events <json>]\n");
}

int main(int argc, char **argv)
{
    if (argc >= 3 && strcmp(argv[1], "--render-all") == 0) {
        return sim_render_all(argv[2]);
    }
    if (argc >= 3 && strcmp(argv[1], "--tcp") == 0) {
        char host[64];
        const char *colon = strrchr(argv[2], ':');
        if (!colon || (size_t)(colon - argv[2]) >= sizeof host) {
            usage();
            return 2;
        }
        memcpy(host, argv[2], (size_t)(colon - argv[2]));
        host[colon - argv[2]] = 0;
        const char *offline = NULL;
        if (argc >= 5 && strcmp(argv[3], "--offline-events") == 0) {
            offline = argv[4];
        }
        return sim_tcp_run(host, atoi(colon + 1), offline);
    }
    usage();
    return 2;
}
