// Touch probe: runs the exact touch_button.c used by the firmware and prints
// its state over the USB-Serial/JTAG console, 10 times per second.
// Boot order mimics the patched pico-keys-sdk: SAR ADC entropy on (DRBG
// seeding) -> off -> touch sensor start.
// Only the app partition is replaced (encrypted write at 0x20000); part0 is untouched.
#include <stdio.h>
#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "touch_button.h"
#include "bootloader_random.h"
#include "esp_random.h"

void app_main(void)
{
    bootloader_random_enable();
    for (int i = 0; i < 2048; i++) {
        (void)esp_random();
    }
    bootloader_random_disable();
    printf("RNG enable -> disable done\n");

    touch_button_start(1);  // TOUCH1 = GPIO1
    uint32_t t = 0;
    while (1) {
        touch_button_info_t i;
        touch_button_info(&i);
        printf("T %" PRIu32 " st=%d n=%" PRIu32 " v=%" PRIu32 " base=%" PRIu32 " pressed=%d\n",
               t, i.status, i.samples, i.value, i.baseline, i.pressed);
        t += 100;
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}
