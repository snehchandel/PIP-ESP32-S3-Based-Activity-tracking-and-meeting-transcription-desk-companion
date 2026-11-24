#include "sim_net.h"

#include <string.h>

#ifdef _WIN32
#include <ws2tcpip.h>
#include <windows.h>
#define CLOSESOCK closesocket
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>
#define CLOSESOCK close
#endif

int sim_net_init(void)
{
#ifdef _WIN32
    WSADATA w;
    return WSAStartup(MAKEWORD(2, 2), &w) == 0 ? 0 : -1;
#else
    return 0;
#endif
}

sim_sock_t sim_listen(const char *host, int port)
{
    sim_sock_t s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s == SIM_SOCK_INVALID) {
        return s;
    }
    int one = 1;
    setsockopt(s, SOL_SOCKET, SO_REUSEADDR, (const char *)&one, sizeof one);
    struct sockaddr_in a;
    memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_port = htons((unsigned short)port);
    if (inet_pton(AF_INET, host, &a.sin_addr) != 1 || bind(s, (struct sockaddr *)&a, sizeof a) != 0 ||
        listen(s, 1) != 0) {
        CLOSESOCK(s);
        return SIM_SOCK_INVALID;
    }
    return s;
}

static int wait_readable(sim_sock_t s, int timeout_ms)
{
    fd_set rf;
    FD_ZERO(&rf);
    FD_SET(s, &rf);
    struct timeval tv;
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;
    return select((int)s + 1, &rf, NULL, NULL, &tv);
}

sim_sock_t sim_accept(sim_sock_t ls, int timeout_ms)
{
    if (wait_readable(ls, timeout_ms) <= 0) {
        return SIM_SOCK_INVALID;
    }
    sim_sock_t c = accept(ls, NULL, NULL);
    if (c != SIM_SOCK_INVALID) {
        int one = 1;
        setsockopt(c, IPPROTO_TCP, 1 /* TCP_NODELAY */, (const char *)&one, sizeof one);
    }
    return c;
}

int sim_recv(sim_sock_t s, uint8_t *buf, size_t cap, int timeout_ms)
{
    int r = wait_readable(s, timeout_ms);
    if (r < 0) {
        return -1;
    }
    if (r == 0) {
        return 0;
    }
    int n = (int)recv(s, (char *)buf, (int)cap, 0);
    return n <= 0 ? -1 : n;
}

int sim_sock_send_all(sim_sock_t s, const uint8_t *buf, size_t n)
{
    while (n > 0) {
        int w = (int)send(s, (const char *)buf, (int)n, 0);
        if (w <= 0) {
            return -1;
        }
        buf += w;
        n -= (size_t)w;
    }
    return 0;
}

void sim_sock_close(sim_sock_t s) { CLOSESOCK(s); }

uint32_t sim_now_ms(void)
{
#ifdef _WIN32
    return (uint32_t)GetTickCount64();
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint32_t)(ts.tv_sec * 1000u + ts.tv_nsec / 1000000u);
#endif
}
