/* HP48G Desktop headless bridge; GPL-2.0-or-later.
 * Hosts the upstream x48ng Saturn engine in a separate process. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#ifdef _WIN32
#include <windows.h>
#include <io.h>
#endif
#include <time.h>
#include <sys/time.h>
#include "objects.h"
#include "romio.h"
#include "options.h"
#include "emulator_api.h"
#include "core/emulate.h"
#include "core/init.h"
#include "core/memory.h"
#include "core/persistence.h"
#include "core/timers.h"
#include "core/debugger.h"

struct ui_config ui4x_config={0};
config_t x48ng_config={0};
int enter_debugger=0, exec_flags=0;
bool in_debugger=false;
bool bridge_idle=false;
static char profile[4096];
static unsigned long long instruction_count=0;
static double instructions_per_second=0, governor_start=0;
static unsigned long long governor_count=0;
static char input[1048576];
static size_t input_size=0;
static int quitting=0;
int ui4x_get_nb_keys(void) { return NB_HP48_KEYS; }
int ui4x_get_lcd_height(void) { return 64; }
void ui4x_exit(void) {}
int check_breakpoint(int type, Address addr) { return 0; }
int debug(void) { return 0; }
char *ui4x_make_filename_absolute_for_loading(char *name) {
    static char path[8192];
    snprintf(path,sizeof(path),"%s/%s",profile,name); return path;
}
char *ui4x_make_filename_absolute_for_saving(char *name) {
    return ui4x_make_filename_absolute_for_loading(name);
}
static void reply(long id,int ok,const char *message) {
    printf("{\"id\":%ld,\"ok\":%s,\"message\":\"%s\"}\n",id,ok?"true":"false",message); fflush(stdout);
}
/* Speaker is OUT bit 11, shared by ROM BEEP and alarm routines. */
static int speaker_state=0;
static unsigned long long speaker_instruction=0;
static unsigned short waveform[4096];
static size_t waveform_size=0;
static void flush_waveform(void) {
    if(!waveform_size)return;
    printf("{\"audio\":{\"pcm\":\"");
    for(size_t i=0;i<waveform_size;i++)printf("%02x%02x",waveform[i]&255,waveform[i]>>8);
    printf("\"}}\n");fflush(stdout);waveform_size=0;
}
static long beep_return=-1,beep_frequency=0,beep_ms=0;
static int beep_edges=0,beep_sent=0;
static double beep_deadline=0;
static double now_seconds(void) {
#ifdef _WIN32
    LARGE_INTEGER ticks,freq;QueryPerformanceCounter(&ticks);QueryPerformanceFrequency(&freq);
    return (double)ticks.QuadPart/freq.QuadPart;
#else
    struct timespec ts;clock_gettime(CLOCK_MONOTONIC,&ts);
    return ts.tv_sec+ts.tv_nsec/1e9;
#endif
}
void bridge_wait_tick(void) {
#ifdef _WIN32
    Sleep(15);
#else
    usleep(15625);
#endif
    sigalarm_triggered=true;
}
void bridge_speaker(void) {
    int state=(saturn.out[2]&8)!=0;
    if(state!=speaker_state) {
        if(beep_return<0 && speaker_instruction>0) {
            double rate=instructions_per_second>0?instructions_per_second:500000;
            unsigned long long elapsed=instruction_count-speaker_instruction;
            if(elapsed<rate*.1) {
                int samples=(int)(elapsed*44100/rate+.5);
                for(int i=0;i<samples;i++) {
                    waveform[waveform_size++]=(unsigned short)(speaker_state?12000:-12000);
                    if(waveform_size==4096)flush_waveform();
                }
            }
        }
        speaker_instruction=instruction_count;speaker_state=state;
        if(beep_return>=0) {
            if(++beep_edges==4 && beep_frequency>0 && beep_ms>0) {
                printf("{\"audio\":{\"frequency\":%ld,\"duration\":%.6f}}\n",beep_frequency,beep_ms/1000.0);fflush(stdout);
                beep_sent=1;beep_deadline=now_seconds()+beep_ms/1000.0;
            }
        }
    }
}
void ui4x_refresh_output(void) {
    flush_waveform();
    static unsigned char previous[64*17];
    static int old_ann=-1,old_on=-1;
    unsigned char pixels[64*17]={0};
    int lines=display.lines; if(lines<0) lines=0; if(lines>63) lines=63;
    if(display.on) for(int y=0;y<64;y++) {
        long address=y<=lines?display.disp_start+y*display.nibs_per_line:display.menu_start+(y-lines-1)*34;
        int offset=y<=lines?display.offset:0;
        for(int x=0;x<131;x++) {
            int xx=x+offset;
            if(bus_fetch_nibble((address+xx/4)&0xfffff)&(1<<(xx%4))) pixels[y*17+x/8]|=1<<(7-x%8);
        }
    }
    int ann=get_annunciators(),on=display.on;
    if(memcmp(previous,pixels,sizeof(pixels))==0 && ann==old_ann && on==old_on) return;
    memcpy(previous,pixels,sizeof(pixels));old_ann=ann;old_on=on;
    printf("{\"frame\":\"");
    for(size_t i=0;i<sizeof(pixels);i++) printf("%02x",pixels[i]);
    printf("\",\"annunciators\":%d,\"on\":%s}\n",ann,on?"true":"false"); fflush(stdout);
}
static int value_nodes;
static void print_value(long address,int depth) {
    if(depth>40 || ++value_nodes>8192) {printf("null");return;}
    long type=read_nibbles(address,5);
    /* Lists may contain pointers to canonical ROM constants. */
    if(type!=0x2933 && type!=0x2977 && type!=0x2a2c && type!=0x2a74 && type!=0x2e48 && type!=0x2a4e) {
        long referred=read_nibbles(type,5);
        if(referred==0x2933 || referred==0x2977 || referred==0x2a2c || referred==0x2a74 || referred==0x2e48) {address=type;type=referred;}
    }
    printf("{\"type\":%ld",type);
    if(type==0x2a74) {
        long cursor=address+5;printf(",\"items\":[");int first=1;
        while(cursor<0xffffb && read_nibbles(cursor,5)!=0x312b && value_nodes<8192) {
            size_t size=native_object_size(cursor,0x90000,0);if(!size)break;
            if(!first)printf(",");first=0;print_value(cursor,depth+1);cursor+=size;
        }
        printf("]");
    } else {
        size_t size=native_object_size(address,0x90000,0);
        printf(",\"raw\":\"");for(size_t i=0;i<size;i++)printf("%x",bus_fetch_nibble(address+i));printf("\"");
    }
    printf("}");
}
static void handle_line(char *line) {
    char verb[20]; long id=0; int key,down;
    if(sscanf(line,"%19s %ld",verb,&id)!=2) { reply(0,0,"Invalid request"); return; }
    if(strcmp(verb,"KEY")==0 && sscanf(line,"%*s %*ld %d %d",&key,&down)==2) {
        if(key<0 || key>=49 || (down!=0 && down!=1)) { reply(id,0,"Invalid key"); return; }
        if(down) press_key(key); else release_key(key);
        reply(id,1,"Key accepted");
    } else if(strcmp(verb,"PUSH")==0) {
        char *data=strchr(line,' ');data=data?strchr(data+1,' '):NULL;
        if(!data || !bridge_idle || (get_annunciators()&16)) {reply(id,0,"Wait until the calculator is idle");return;}
        if(!display.on || (get_annunciators()&7)) {reply(id,0,"Use the normal stack view with shift and alpha off before importing or running text");return;}
        data++;size_t size=strlen(data);
        if(size<5 || size>0x90000) {reply(id,0,"Invalid object size");return;}
        unsigned char *nibbles=malloc(size);
        if(!nibbles) {reply(id,0,"Out of host memory");return;}
        for(size_t i=0;i<size;i++) {
            char c=data[i];
            if(c>='0'&&c<='9')nibbles[i]=c-'0';
            else if(c>='a'&&c<='f')nibbles[i]=c-'a'+10;
            else {free(nibbles);reply(id,0,"Invalid nibble");return;}
        }
        long addr=push_native_object(nibbles,size);free(nibbles);
        reply(id,addr!=0,addr?"Object imported":"Insufficient calculator memory or unavailable stack");
    } else if((strcmp(verb,"EXPORT")==0 || strcmp(verb,"TAKE")==0)) {
        int level=1;sscanf(line,"%*s %*ld %d",&level);
        if(strcmp(verb,"TAKE")==0 && level!=1) {reply(id,0,"Only level 1 can be taken");return;}
        if(!bridge_idle) {reply(id,0,"Wait until the calculator is idle");return;}
        long address=stack_object(level);size_t size=address?native_object_size(address,0x90000,0):0;
        if(!size) {reply(id,0,"Stack object unavailable");return;}
        printf("{\"id\":%ld,\"ok\":true,\"object\":\"",id);
        for(size_t i=0;i<size;i++)printf("%x",bus_fetch_nibble(address+i));
        printf("\",\"value\":");value_nodes=0;print_value(address,0);printf("}\n");fflush(stdout);
        if(strcmp(verb,"TAKE")==0) pop_native_object();
    } else if(strcmp(verb,"CONSUME")==0) {
        char *expected=strchr(line,' ');expected=expected?strchr(expected+1,' '):NULL;
        long address=stack_object(1);size_t size=address?native_object_size(address,0x90000,0):0;
        if(!bridge_idle || !expected || !size || strlen(++expected)!=size) {reply(id,0,"Reply changed; stack was preserved");return;}
        for(size_t i=0;i<size;i++)if(expected[i]!="0123456789abcdef"[bus_fetch_nibble(address+i)]) {reply(id,0,"Reply changed; stack was preserved");return;}
        pop_native_object();reply(id,1,"Reply consumed");
    } else if(strcmp(verb,"DEBUGSTATE")==0) {
        if(!bridge_idle) {reply(id,0,"Pause the calculator first");return;}
        printf("{\"id\":%ld,\"ok\":true,\"pc\":%ld,\"returns\":[",id,saturn.pc);
        long a=read_nibbles(opt_gx?0x806ee:0x7056f,5),b=read_nibbles(opt_gx?0x806f3:0x70574,5);
        int first=1;
        if(a>=(opt_gx?0x80000:0x70000) && b>=a && b<0x100000) {
            if(b-a>200)a=b-200;
            for(long p=a;p+5<=b;p+=5) {printf("%s%ld",first?"":",",read_nibbles(p,5));first=0;}
        }
        printf("],\"stack\":[");first=1;
        for(int level=1;level<=32;level++) {
            long address=stack_object(level);if(!address)break;
            if(!first)printf(",");first=0;value_nodes=0;print_value(address,0);
        }
        printf("]}\n");fflush(stdout);
    } else if(strcmp(verb,"SPEED")==0) {
        long rate=0;
        if(sscanf(line,"%*s %*ld %ld",&rate)!=1 || rate<0 || rate>10000000) {reply(id,0,"Invalid instruction rate");return;}
        instructions_per_second=rate;governor_start=now_seconds();governor_count=instruction_count;
        reply(id,1,"Instruction rate changed");
    } else if(strcmp(verb,"STATUS")==0) {
        printf("{\"id\":%ld,\"ok\":true,\"idle\":%s,\"busy\":%s}\n",id,bridge_idle?"true":"false",(get_annunciators()&16)?"true":"false");fflush(stdout);
    } else if(strcmp(verb,"SAVE")==0) reply(id,write_files(),"State saved");
    else if(strcmp(verb,"QUIT")==0) { reply(id,1,"Closing"); quitting=1; exit(0); }
    else if(strcmp(verb,"READ")==0) {
        long address; int count;
        if(sscanf(line,"%*s %*ld %lx %d",&address,&count)!=2 || address<0 || address>0xfffff || count<0 || count>65536) {reply(id,0,"Invalid memory range");return;}
        printf("{\"id\":%ld,\"ok\":true,\"nibbles\":\"",id);
        for(int i=0;i<count;i++) printf("%x",bus_fetch_nibble((address+i)&0xfffff));
        printf("\"}\n");fflush(stdout);
    } else reply(id,0,"Unknown request");
}
void ui4x_handle_pending_inputs(void) {
    char buf[4096]; ssize_t n;
    while(1) {
#ifdef _WIN32
        DWORD available=0;
        if(!PeekNamedPipe(GetStdHandle(STD_INPUT_HANDLE),NULL,0,NULL,&available,NULL))exit(0);
        if(!available) {n=-1;break;}
        n=_read(0,buf,available<sizeof(buf)?available:sizeof(buf));
#else
        n=read(STDIN_FILENO,buf,sizeof(buf));
#endif
        if(n<=0)break;
        for(ssize_t i=0;i<n;i++) {
            if(buf[i]=='\n') { input[input_size]=0;handle_line(input);input_size=0; }
            else if(input_size<sizeof(input)-1) input[input_size++]=buf[i];
            else { reply(0,0,"Request too long");input_size=0; }
        }
    }
    if(n==0) exit(0);
}
int main(int argc,char **argv) {
    if(argc!=2 || strlen(argv[1])>=sizeof(profile)) {fprintf(stderr,"usage: hp48g-rom-core PROFILE\n");return 2;}
    strcpy(profile,argv[1]);
#ifdef _WIN32
    _setmode(0,_O_BINARY);_setmode(1,_O_BINARY);
#else
    fcntl(STDIN_FILENO,F_SETFL,fcntl(STDIN_FILENO,F_GETFL,0)|O_NONBLOCK);
#endif
    init_emulator();
    /* Host keys are up after launching/restoring, even if a snapshot caught a press. */
    for(int i=0;i<KEYS_BUFFER_SIZE;i++)saturn.keybuf[i]=0;
    if(!saturn.port1 && !saturn.port2) load_cards();
    double last_tick=now_seconds();
    reset_timer(T1_TIMER);reset_timer(RUN_TIMER);reset_timer(IDLE_TIMER);set_accesstime();
    start_timer(T1_TIMER);start_timer(RUN_TIMER);
    sched_timer1=t1_i_per_tick=saturn.t1_tick;sched_timer2=t2_i_per_tick=saturn.t2_tick;set_t1=saturn.timer1;
    printf("{\"ready\":true,\"protocol\":1}\n");fflush(stdout);
    while(!quitting) {
        /* Revision R makebeep entry: D[A] Hz, C[A] milliseconds.
         * Observe parameters without modifying ROM or bypassing its mute flag. */
        if(saturn.pc==0x017a6 && saturn.rstk_ptr>=0) {
            beep_frequency=beep_ms=0;
            for(int i=4;i>=0;i--) {beep_frequency=beep_frequency*16+saturn.reg[D][i];beep_ms=beep_ms*16+saturn.reg[C][i];}
            beep_return=saturn.rstk[saturn.rstk_ptr];beep_edges=beep_sent=0;
        }
        if(beep_return>=0 && saturn.pc==beep_return) {
            while(beep_sent && now_seconds()<beep_deadline) {
                ui4x_handle_pending_inputs();ui4x_refresh_output();usleep(5000);
                if(saturn.keybuf[0]&0x8000)break;
            }
            beep_return=-1;
        }
        step_instruction();instruction_count++;
        if((instruction_count&1023)==0) {
            double now=now_seconds();
            if(now-last_tick>=.015625) {last_tick=now;sigalarm_triggered=true;}
            if(instructions_per_second>0) {
                double ahead=(instruction_count-governor_count)/instructions_per_second-(now-governor_start);
                if(ahead>.001) {
#ifdef _WIN32
                    Sleep((DWORD)(ahead*1000));
#else
                    usleep((unsigned int)(ahead*1000000));
#endif
                }
                if(now-governor_start>1) {governor_start=now;governor_count=instruction_count;}
            }
        }
        /* The ROM debounces keys using instruction loops. Match upstream's
         * minimum instruction time while a physical key is held. */
        for(int key=0;key<KEYS_BUFFER_SIZE;key++) if(saturn.keybuf[key]) {
            struct timeval before,now;gettimeofday(&before,NULL);
            do {gettimeofday(&now,NULL);} while(now.tv_sec==before.tv_sec && now.tv_usec-before.tv_usec<2);
            break;
        }
        if(enter_debugger) {fprintf(stderr,"Saturn trap %d at %05lx\n",enter_debugger,saturn.pc);return 3;}
        if(schedule_event<0) schedule_event=0;
        if(schedule_event--<=0) schedule();
    }
    return 0;
}
