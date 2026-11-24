/* D2: protocol v1 over the built-in USB Serial/JTAG controller (single binary stream). */
#ifndef USB_TRANSPORT_H
#define USB_TRANSPORT_H

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"
#include "pip_protocol.h"

typedef void (*usb_frame_cb_t)(const pip_frame_t *frame, void *ctx);

esp_err_t usb_transport_init(usb_frame_cb_t cb, void *ctx);
/* Thread-safe. Silently drops when no USB host is attached. */
void usb_transport_send(uint8_t type, uint8_t flags, uint16_t seq, const uint8_t *payload, uint16_t len);
bool usb_transport_host_connected(void);
uint32_t usb_transport_crc_errors(void);

#endif
