/* Minimal UI boundary for the headless GPL-2.0-or-later x48ng process.
 * The actual desktop interface is implemented in Python/PySide6. */
#ifndef HP48G_HEADLESS_UI_H
#define HP48G_HEADLESS_UI_H
#include <stdbool.h>
#define NB_HP48_KEYS 49
#define NB_ANNUNCIATORS 6
#define LCD_WIDTH 131
struct ui_config { bool verbose; char *wire_name, *ir_name; };
extern struct ui_config ui4x_config;
int ui4x_get_nb_keys(void);
int ui4x_get_lcd_height(void);
void ui4x_exit(void);
void ui4x_refresh_output(void);
void ui4x_handle_pending_inputs(void);
char *ui4x_make_filename_absolute_for_loading(char *name);
char *ui4x_make_filename_absolute_for_saving(char *name);
#endif
