#ifndef _OPTIONS_H
#  define _OPTIONS_H 1

#  include <stdbool.h>

#  include "ui4x/src/api.h"

#  ifndef VERSION_MAJOR
#    define VERSION_MAJOR 0
#  endif
#  ifndef VERSION_MINOR
#    define VERSION_MINOR 0
#  endif
#  ifndef PATCHLEVEL
#    define PATCHLEVEL 0
#  endif

typedef struct config_t {
    bool enable_wire;
    bool enable_ir;
    bool enable_debugger;
    bool throttle;
    bool reset;
    bool inhibit_shutdown;

    bool print_config_and_exit;

    char* ir_serial_device;
} config_t;
extern config_t x48ng_config;

/*************/
/* functions */
/*************/
extern char* config_to_string( void );
extern config_t* config_init( int argc, char* argv[] );

#endif /* !_OPTIONS_H */
