/* GPL-2.0-or-later.
 * Temporary-object allocation follows RPL_CreateTemp/RPL_Push in Droid48's
 * binio.c, copyright (C) 1994 Eddie C. Dost, with bounds checks and no host
 * pointers in the emulated machine. See UPSTREAM.md for provenance.
 */
#include "core/emulate.h"
#include "core/memory.h"
#include "objects.h"
#include "romio.h"
#include <stdio.h>
#define TEMPTOP (opt_gx?0x806ee:0x7056f)
#define RSKTOP (opt_gx?0x806f3:0x70574)
#define DSKTOP (opt_gx?0x806f8:0x70579)
#define DSKBOT (opt_gx?0x806fd:0x7057e)
#define AVMEM (opt_gx?0x807ed:0x7066e)
static void write5(long address,long value) {
    for(int i=0;i<5;i++){bus_write_nibble(address+i,value&15);value>>=4;}
}
long stack_object(int level) {
    long top=read_nibbles(DSKTOP,5),bottom=read_nibbles(DSKBOT,5);
    if(level<1 || level>10000 || top<(opt_gx?0x80000:0x70000) || bottom>0x100000 || top+(long)level*5>bottom) return 0;
    return read_nibbles(top+(level-1)*5,5);
}
void pop_native_object(void) {
    if(!stack_object(1)) return;
    long top=read_nibbles(DSKTOP,5);
    write5(DSKTOP,top+5);write5(AVMEM,read_nibbles(AVMEM,5)+1);
}
long push_native_object(const unsigned char *nibbles,size_t size) {
    long a=read_nibbles(TEMPTOP,5),b=read_nibbles(RSKTOP,5),c=read_nibbles(DSKTOP,5);
    long total=(long)size+6;
    if(saturn.mem_cntl[1].config[0]!=(opt_gx?0x80000:0x70000) || a<(opt_gx?0x80000:0x70000) || b<a || c<b || c>0x100000 || size>0x90000 || b+total+5>c) { fprintf(stderr,"Import unavailable: base=%lx temp=%lx rstack=%lx dstack=%lx size=%zu\n",saturn.mem_cntl[1].config[0],a,b,c,size); return 0; }
    for(long i=b-a;i>0;i--) bus_write_nibble(a+total+i-1,bus_fetch_nibble(a+i-1));
    write5(TEMPTOP,a+total);write5(RSKTOP,b+total);write5(a+total-5,total);
    bus_write_nibble(a,0);
    for(size_t i=0;i<size;i++) bus_write_nibble(a+1+(long)i,nibbles[i]);
    write5(DSKTOP,c-5);write5(c-5,a+1);write5(AVMEM,(c-b-total)/5-1);
    return a+1;
}
size_t native_object_size(long address,size_t limit,int depth) {
    if(depth>100 || address<0 || address+5>0x100000 || limit<5) return 0;
    long prolog=read_nibbles(address,5);size_t n=0;
    switch(prolog) {
        case 0x02911:n=10;break;case 0x02933:n=21;break;case 0x02955:n=26;break;
        case 0x02977:n=37;break;case 0x0299d:n=47;break;case 0x029bf:n=7;break;
        case 0x02baa:n=15;break;case 0x02e92:n=11;break;
        case 0x02e48:case 0x02e6d:n=7+2*read_nibbles(address+5,2);break;
        case 0x02afc:
            n=7+2*read_nibbles(address+5,2);
            if(n>=limit) return 0;
            {size_t child=native_object_size(address+n,limit-n,depth+1);if(!child)return 0;n+=child;}
            break;
        case 0x02a74:case 0x02ab8:case 0x02ada:case 0x02d9d:
            n=5;
            while(n+5<=limit) {
                if(read_nibbles(address+n,5)==0x0312b) {n+=5;break;}
                size_t child=native_object_size(address+n,limit-n,depth+1);if(!child)return 0;n+=child;
            }
            if(n>limit || read_nibbles(address+n-5,5)!=0x0312b)return 0;
            break;
        case 0x02a96:
            n=read_nibbles(address+8,5);
            if(n==0)n=13;
            else {
                n+=8;if(n+2>limit)return 0;
                n+=2*read_nibbles(address+n,2)+4;if(n>=limit)return 0;
                size_t child=native_object_size(address+n,limit-n,depth+1);if(!child)return 0;n+=child;
            }break;
        case 0x029e8:case 0x02a0a:case 0x02a2c:case 0x02a4e:case 0x02b1e:
        case 0x02b40:case 0x02b62:case 0x02b88:case 0x02bcc:case 0x02bee:
        case 0x02c10:case 0x02dcc:
            if(limit<10)return 0;n=5+read_nibbles(address+5,5);if(n<10)return 0;break;
        default:n=5;
    }
    return n<=limit && address+(long)n<=0x100000?n:0;
}
