/* Tiny portable TCP + monotonic clock layer for sim_rlcd (Winsock / BSD sockets). */
#ifndef SIM_NET_H
#define SIM_NET_H

#include <stddef.h>
#include <stdint.h>

#ifdef _WIN32
#include <winsock2.h>
typedef SOCKET sim_sock_t;
#define SIM_SOCK_INVALID INVALID_SOCKET
#else
typedef int sim_sock_t;
#define SIM_SOCK_INVALID (-1)
#endif

int sim_net_init(void);
sim_sock_t sim_listen(const char *host, int port);
/* Wait up to timeout_ms for a client; returns SIM_SOCK_INVALID if none. */
sim_sock_t sim_accept(sim_sock_t ls, int timeout_ms);
/* Returns bytes read (0 = timeout, nothing available), -1 on disconnect/error. */
int sim_recv(sim_sock_t s, uint8_t *buf, size_t cap, int timeout_ms);
int sim_sock_send_all(sim_sock_t s, const uint8_t *buf, size_t n);
void sim_sock_close(sim_sock_t s);
uint32_t sim_now_ms(void);

#endif
