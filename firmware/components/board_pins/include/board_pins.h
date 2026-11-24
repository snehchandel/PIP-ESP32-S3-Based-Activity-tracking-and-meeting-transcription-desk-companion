/* Locked GPIO / I2C map for Waveshare ESP32-S3-RLCD-4.2 (spec v6 section 3.1).
 * Verified against waveshareteam/ESP32-S3-RLCD-4.2 examples (user_config.h, board_cfg.txt,
 * button_bsp.c, adc_bsp.cpp). Never reassign these; never touch GPIO26-37 (flash/PSRAM). */
#ifndef BOARD_PINS_H
#define BOARD_PINS_H

#define PIN_RLCD_SCLK 11
#define PIN_RLCD_MOSI 12
#define PIN_RLCD_CS 40
#define PIN_RLCD_DC 5
#define PIN_RLCD_RST 41
#define PIN_RLCD_TE 6

#define PIN_I2S_BCLK 9
#define PIN_I2S_MCLK 16
#define PIN_I2S_LRCLK 45
#define PIN_I2S_DIN 10  /* ES7210 mic ADC -> ESP */
#define PIN_I2S_DOUT 8  /* ESP -> ES8311 speaker codec */
#define PIN_SPK_AMP_EN 46

#define PIN_I2C_SDA 13
#define PIN_I2C_SCL 14
#define I2C_FREQ_HZ 100000

#define PIN_KEY 18
#define PIN_BOOT 0
#define PIN_BAT_ADC 4 /* ADC1_CH3 */

#define I2C_ADDR_SHTC3 0x70
#define I2C_ADDR_PCF85063 0x51
#define I2C_ADDR_ES8311 0x18
#define I2C_ADDR_ES7210 0x40
#define I2C_ADDR_ES7210_ALT 0x42

/* Battery: board divider measured x3 in vendor code (ADR-004 overrides spec's 2.0). */
#define BAT_DIVIDER_NUM 3
#define BAT_DIVIDER_DEN 1
#define BAT_MV_EMPTY 3300
#define BAT_MV_FULL 4180

/* Compile-time guardrails: no pin may sit on octal flash/PSRAM lines 26..37. */
#define PIN_IS_RESERVED(p) ((p) >= 26 && (p) <= 37)
typedef char board_pin_guard_t[(PIN_IS_RESERVED(PIN_RLCD_SCLK) || PIN_IS_RESERVED(PIN_RLCD_MOSI) ||
                                PIN_IS_RESERVED(PIN_RLCD_CS) || PIN_IS_RESERVED(PIN_RLCD_DC) ||
                                PIN_IS_RESERVED(PIN_RLCD_RST) || PIN_IS_RESERVED(PIN_KEY) ||
                                PIN_IS_RESERVED(PIN_I2C_SDA) || PIN_IS_RESERVED(PIN_I2C_SCL) ||
                                PIN_IS_RESERVED(PIN_I2S_BCLK) || PIN_IS_RESERVED(PIN_I2S_MCLK) ||
                                PIN_IS_RESERVED(PIN_I2S_LRCLK) || PIN_IS_RESERVED(PIN_SPK_AMP_EN))
                                   ? -1
                                   : 1];

#endif
