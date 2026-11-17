set(SDK_SRC ${CMAKE_CURRENT_LIST_DIR}/../../../pico-fido/pico-keys-sdk/src)
idf_component_register(SRCS "touchprobe.c" "${SDK_SRC}/touch_button.c"
                       INCLUDE_DIRS "${SDK_SRC}"
                       REQUIRES esp_driver_touch_sens bootloader_support)
