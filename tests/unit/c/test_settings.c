/* Saved Wi-Fi networks, network choice and the away-link address (dev_settings.c, DEVICE_CONFIG JSON). */
#include <string.h>

#include "dev_settings.h"
#include "tinytest.h"

static unsigned apply(dev_config_t *c, const char *json) { return dev_config_apply_json(c, json, strlen(json)); }

int main(void)
{
    dev_config_t c;
    dev_settings_defaults(&c);
    CHECK(c.n_nets == 0 && c.wake_on && strcmp(c.wake_word, "hiesp") == 0 && c.remote_host[0] == 0);

    /* saving networks: newest first, same network again only changes its password / moves it to the front */
    CHECK(apply(&c, "{\"wifi\":{\"ssid\":\"Home\",\"password\":\"homepass1\"}}") == DEVCFG_WIFI);
    CHECK(apply(&c, "{\"wifi\":{\"ssid\":\"Home\",\"password\":\"homepass1\"}}") == 0);
    CHECK(apply(&c, "{\"wifi\":{\"ssid\":\"Phone\",\"password\":\"hotspot99\"}}") == DEVCFG_WIFI);
    CHECK(c.n_nets == 2 && strcmp(c.nets[0].ssid, "Phone") == 0 && strcmp(c.nets[1].ssid, "Home") == 0);
    CHECK(apply(&c, "{\"wifi\":{\"ssid\":\"Home\",\"password\":\"newpass22\"}}") == DEVCFG_WIFI);
    CHECK(c.n_nets == 2 && strcmp(c.nets[0].ssid, "Home") == 0 && strcmp(c.nets[0].pass, "newpass22") == 0);
    CHECK(strcmp(c.nets[1].ssid, "Phone") == 0 && strcmp(c.nets[1].pass, "hotspot99") == 0);
    CHECK(apply(&c, "{\"wifi\":{\"ssid\":\"\"}}") == 0);

    /* a full list drops the oldest network */
    CHECK(dev_net_add(&c, "C", "cccccccc") && dev_net_add(&c, "D", "") && dev_net_add(&c, "E", "eeeeeeee"));
    CHECK(c.n_nets == DEV_MAX_NETS);
    CHECK(dev_net_add(&c, "F", "ffffffff"));
    CHECK(c.n_nets == DEV_MAX_NETS && strcmp(c.nets[0].ssid, "F") == 0 && dev_net_find(&c, "Phone") < 0);
    CHECK(dev_net_find(&c, "Home") == DEV_MAX_NETS - 1);

    /* forgetting one keeps the rest in order; clearing forgets all */
    CHECK(apply(&c, "{\"wifi_forget\":\"D\"}") == DEVCFG_WIFI);
    CHECK(apply(&c, "{\"wifi_forget\":\"D\"}") == 0);
    CHECK(c.n_nets == 4 && strcmp(c.nets[0].ssid, "F") == 0 && strcmp(c.nets[1].ssid, "E") == 0);
    CHECK(strcmp(c.nets[2].ssid, "C") == 0 && strcmp(c.nets[3].ssid, "Home") == 0 && c.nets[4].ssid[0] == 0);
    CHECK(apply(&c, "{\"wifi_clear\":true}") == DEVCFG_WIFI && c.n_nets == 0);
    CHECK(apply(&c, "{\"wifi_clear\":true}") == 0);

    /* picking: the strongest visible network, failures count against it, unseen ones in turn */
    dev_net_add(&c, "Office", "officepw");
    dev_net_add(&c, "Home", "homepass");
    dev_net_add(&c, "Phone", "phonepw1"); /* nets: Phone, Home, Office */
    int8_t rssi[DEV_MAX_NETS] = {DEV_NET_UNSEEN, -70, -55, DEV_NET_UNSEEN, DEV_NET_UNSEEN};
    uint8_t fails[DEV_MAX_NETS] = {0};
    CHECK(dev_net_pick(&c, rssi, fails, 0) == 2);
    fails[2] = 2; /* Office keeps refusing the password: Home (-70) beats Office (-55 - 30) */
    CHECK(dev_net_pick(&c, rssi, fails, 0) == 1);
    int8_t none[DEV_MAX_NETS] = {DEV_NET_UNSEEN, DEV_NET_UNSEEN, DEV_NET_UNSEEN, DEV_NET_UNSEEN, DEV_NET_UNSEEN};
    CHECK(dev_net_pick(&c, none, fails, 0) == 0 && dev_net_pick(&c, none, fails, 1) == 1);
    CHECK(dev_net_pick(&c, none, fails, 5) == 2);
    dev_config_t empty;
    dev_settings_defaults(&empty);
    CHECK(dev_net_pick(&empty, rssi, fails, 0) == -1);

    /* away link address */
    CHECK(apply(&c, "{\"remote\":{\"host\":\"my-pc.example.ts.net\",\"port\":10000}}") == DEVCFG_REMOTE);
    CHECK(strcmp(c.remote_host, "my-pc.example.ts.net") == 0 && c.remote_port == 10000 && !c.remote_tls);
    CHECK(apply(&c, "{\"remote\":{\"host\":\"my-pc.example.ts.net\",\"port\":10000}}") == 0);
    CHECK(apply(&c, "{\"remote\":{\"host\":\"my-pc.example.ts.net\",\"port\":10000,\"tls\":true}}") == DEVCFG_REMOTE);
    CHECK(c.remote_tls);
    CHECK(apply(&c, "{\"remote\":{\"host\":\"http://evil/\",\"port\":80}}") == 0);
    CHECK(apply(&c, "{\"remote\":{\"host\":\"ok.example\",\"port\":0}}") == 0);
    CHECK(apply(&c, "{\"remote\":{\"host\":\"ok.example\",\"port\":70000}}") == 0);
    CHECK(strcmp(c.remote_host, "my-pc.example.ts.net") == 0);
    CHECK(apply(&c, "{\"remote\":{\"host\":\"\"}}") == DEVCFG_REMOTE && c.remote_host[0] == 0 && c.remote_port == 0);
    CHECK(!c.remote_tls);
    CHECK(dev_remote_host_ok("203.0.113.7") && !dev_remote_host_ok("a b") && !dev_remote_host_ok(""));

    /* token + wake word, several changes in one payload */
    unsigned m = apply(&c, "{\"token\":\"000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f\","
                           "\"wake\":{\"enabled\":false,\"word\":\"jarvis\"},\"wifi\":{\"ssid\":\"Cafe\"}}");
    CHECK(m == (DEVCFG_TOKEN | DEVCFG_WAKE | DEVCFG_WIFI));
    CHECK(c.has_token && c.token[31] == 0x1f && !c.wake_on && strcmp(c.wake_word, "jarvis") == 0);
    CHECK(strcmp(c.nets[0].ssid, "Cafe") == 0 && c.nets[0].pass[0] == 0);
    CHECK(apply(&c, "{\"token\":\"zz\"}") == 0);
    TT_DONE();
}
