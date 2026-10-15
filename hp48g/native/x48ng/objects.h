/* GPL-2.0-or-later */
#ifndef HP48G_OBJECTS_H
#define HP48G_OBJECTS_H
#include <stddef.h>
long push_native_object(const unsigned char *nibbles, size_t size);
long stack_object(int level);
void pop_native_object(void);
size_t native_object_size(long address, size_t limit, int depth);
#endif
