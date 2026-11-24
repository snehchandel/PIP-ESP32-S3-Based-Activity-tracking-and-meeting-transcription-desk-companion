idf_component_register(
    SRCS "ui_draw.c" "ui_text.c" "ui_chrome.c" "ui_screens_a.c" "ui_screens_b.c" "ui_screens_c.c" "ui_mascot.c" "ui_render.c" "ui_draw_ext.c" "ui_props.c" "ui_slide.c" "ui_weather.c"
         "fonts_gen.c" "icons_gen.c"
    INCLUDE_DIRS "include"
    REQUIRES mascot_renderer)
