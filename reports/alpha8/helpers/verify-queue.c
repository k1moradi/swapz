#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#define PAGE 4096U
static uint32_t next_u32(uint32_t *x){uint32_t v=*x;v^=v<<13;v^=v>>17;v^=v<<5;*x=v;return v;}
static void fill(unsigned char *p,unsigned page){unsigned i;if(page%5U){for(i=0;i<PAGE;i++)p[i]=(unsigned char)(page*13U+(i%31U)*7U);}else{uint32_t x=0xa4210001U^(page*0x9e3779b9U);for(i=0;i<PAGE;i++)p[i]=(unsigned char)next_u32(&x);}}
int main(int argc,char **argv){if(argc!=3){fprintf(stderr,"usage: %s DEV PAGE_COUNT\n",argv[0]);return 2;}unsigned n=(unsigned)strtoul(argv[2],0,10);int fd=open(argv[1],O_RDONLY|O_DIRECT|O_CLOEXEC);if(fd<0){perror("open");return 1;}unsigned char *got=NULL,*want=NULL;if(posix_memalign((void**)&got,PAGE,PAGE)||posix_memalign((void**)&want,PAGE,PAGE))return 1;unsigned errors=0;for(unsigned i=0;i<n;i++){fill(want,i);ssize_t r=pread(fd,got,PAGE,(off_t)i*PAGE);if(r!=PAGE||memcmp(got,want,PAGE)){if(errors<16)fprintf(stderr,"mismatch page=%u got=%zd errno=%d\n",i,r,errno);errors++;}}printf("verify_pages=%u errors=%u result=%s\n",n,errors,errors?"FAIL":"PASS");free(got);free(want);close(fd);return errors?1:0;}
