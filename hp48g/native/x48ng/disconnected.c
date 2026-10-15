/* GPL-2.0-or-later. Desktop bridge intentionally has no serial/IR transport. */
#include "core/emulate.h"
int init_serial(void) { return 0; }
void serial_baud(int baud) { (void)baud; }
void receive_char(void) {}
void transmit_char(void) {
    saturn.tcs &= 0x0e;
    if(saturn.io_ctrl & 0x04) do_interupt();
}
