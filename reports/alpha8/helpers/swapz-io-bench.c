#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <time.h>
#include <unistd.h>
#define PAGE 4096U
#define MAX_QD 32U
struct cfg;
struct sample { uint64_t ns; unsigned char write; };
struct worker { struct cfg *c; unsigned id; uint64_t reads,writes,errors,mismatches; struct sample *s; size_t n,cap; };
struct cfg {
 int fd; const char *device,*fixture,*classmap_path,*map_in,*map_out,*csv_out;
 unsigned qd,read_pct,seconds,iops,logical_pages,writer_pages,reader_start,reader_pages,fixture_pages;
 int read_current;
 uint64_t seed,start_ns,end_ns; unsigned char *data,*classmap; _Atomic uint64_t class_counts[5]; uint32_t *latest; pthread_mutex_t *locks;
 pthread_barrier_t barrier; _Atomic uint64_t next; _Atomic int stop; struct worker w[MAX_QD];
};
static uint64_t now_ns(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC_RAW,&t);return(uint64_t)t.tv_sec*1000000000ULL+t.tv_nsec;}
static uint64_t mix64(uint64_t x){x+=0x9e3779b97f4a7c15ULL;x=(x^(x>>30))*0xbf58476d1ce4e5b9ULL;x=(x^(x>>27))*0x94d049bb133111ebULL;return x^(x>>31);}
static int full_pwrite(int fd,const void*buf,size_t len,off_t off){size_t d=0;while(d<len){ssize_t n=pwrite(fd,(const char*)buf+d,len-d,off+(off_t)d);if(n<0&&errno==EINTR)continue;if(n<=0)return-1;d+=(size_t)n;}return 0;}
static int full_pread(int fd,void*buf,size_t len,off_t off){size_t d=0;while(d<len){ssize_t n=pread(fd,(char*)buf+d,len-d,off+(off_t)d);if(n<0&&errno==EINTR)continue;if(n<=0)return-1;d+=(size_t)n;}return 0;}
static void fail(struct worker*w,const char*what,uint64_t seq){fprintf(stderr,"IOBENCH_ERROR worker=%u op=%" PRIu64 " what=%s errno=%d\n",w->id,seq,what,errno);w->errors++;atomic_store(&w->c->stop,1);}
static int sample_add(struct worker*w,uint64_t ns,int wr){if(w->n==w->cap){size_t nc=w->cap?w->cap*2:4096;struct sample*p=realloc(w->s,nc*sizeof(*p));if(!p)return-1;w->s=p;w->cap=nc;}w->s[w->n++]=(struct sample){ns,(unsigned char)wr};return 0;}
static void *worker_main(void *arg)
{
	struct worker *w = arg;
	struct cfg *c = w->c;
	void *buf = NULL;
	if (posix_memalign(&buf, PAGE, PAGE)) {
		fail(w, "aligned_alloc", 0);
		return NULL;
	}
	pthread_barrier_wait(&c->barrier);
	while (now_ns() < c->start_ns && !atomic_load(&c->stop)) {
		struct timespec ts = { 0, 100000 };
		nanosleep(&ts, NULL);
	}
	while (!atomic_load(&c->stop) && now_ns() < c->end_ns) {
		uint64_t seq = atomic_fetch_add(&c->next, 1);
		uint64_t h = mix64(seq ^ c->seed);
		int wr = (h % 100) >= c->read_pct;
		uint64_t t0;
		if (c->iops) {
			uint64_t due = c->start_ns + (seq * 1000000000ULL) / c->iops;
			if (due >= c->end_ns)
				break;
			while (!atomic_load(&c->stop)) {
				uint64_t n = now_ns(), left;
				struct timespec ts;
				if (n >= due)
					break;
				left = due - n;
				ts.tv_sec = (time_t)(left / 1000000000ULL);
				ts.tv_nsec = (long)(left % 1000000000ULL);
				nanosleep(&ts, NULL);
			}
		}
		if (now_ns() >= c->end_ns)
			break;
		t0 = now_ns();
		if (wr) {
			unsigned slot = (unsigned)(mix64(h) % c->writer_pages);
			unsigned fi = (unsigned)(mix64(h + 0x12345) % c->fixture_pages);
			pthread_mutex_lock(&c->locks[slot]);
			if (full_pwrite(c->fd, c->data + (size_t)fi * PAGE,
					PAGE, (off_t)slot * PAGE)) {
				fail(w, "pwrite", seq);
			} else {
				c->latest[slot] = fi;
				w->writes++;
				if (c->classmap && c->classmap[fi] < 5)
					atomic_fetch_add(&c->class_counts[c->classmap[fi]], 1);
			}
			pthread_mutex_unlock(&c->locks[slot]);
		} else {
			unsigned rp = (unsigned)(mix64(h + 0xabcde) % c->reader_pages);
			unsigned logical = c->reader_start + rp;
			unsigned fi = logical % c->fixture_pages;
			int locked = 0;
			int io_error;
			int mismatch;
			if (c->read_current && logical < c->writer_pages) {
				pthread_mutex_lock(&c->locks[logical]);
				locked = 1;
				fi = c->latest[logical];
			}
			io_error = full_pread(c->fd, buf, PAGE, (off_t)logical * PAGE);
			mismatch = !io_error && memcmp(buf, c->data + (size_t)fi * PAGE, PAGE);
			if (locked)
				pthread_mutex_unlock(&c->locks[logical]);
			if (io_error) {
				fail(w, "pread", seq);
			} else if (mismatch) {
				w->mismatches++;
				fprintf(stderr, "IOBENCH_MISMATCH worker=%u logical=%u fixture=%u\n",
					w->id, logical, fi);
				atomic_store(&c->stop, 1);
			} else {
				w->reads++;
			}
		}
		if (sample_add(w, now_ns() - t0, wr)) {
			fail(w, "sample_alloc", seq);
			break;
		}
	}
	free(buf);
	return NULL;
}
static int load_fixture(struct cfg*c){int fd=open(c->fixture,O_RDONLY|O_CLOEXEC);if(fd<0)return-1;off_t end=lseek(fd,0,SEEK_END);if(end<=0||end%PAGE){close(fd);errno=EINVAL;return-1;}c->fixture_pages=(unsigned)(end/PAGE);if(posix_memalign((void**)&c->data,PAGE,(size_t)end)){close(fd);errno=ENOMEM;return-1;}if(full_pread(fd,c->data,(size_t)end,0)){close(fd);return-1;}close(fd);return 0;}
static int load_classmap(struct cfg*c){if(!c->classmap_path)return 0;int fd=open(c->classmap_path,O_RDONLY|O_CLOEXEC);if(fd<0)return-1;c->classmap=malloc(c->fixture_pages);if(!c->classmap){close(fd);return-1;}if(full_pread(fd,c->classmap,c->fixture_pages,0)){close(fd);return-1;}close(fd);for(unsigned i=0;i<c->fixture_pages;i++)if(c->classmap[i]>4){errno=EINVAL;return-1;}return 0;}
static int load_map(struct cfg*c){c->latest=calloc(c->writer_pages,sizeof(*c->latest));if(!c->latest)return-1;for(unsigned i=0;i<c->writer_pages;i++)c->latest[i]=i%c->fixture_pages;if(c->map_in){int fd=open(c->map_in,O_RDONLY|O_CLOEXEC);if(fd<0)return-1;if(full_pread(fd,c->latest,c->writer_pages*sizeof(*c->latest),0)){close(fd);return-1;}close(fd);for(unsigned i=0;i<c->writer_pages;i++)if(c->latest[i]>=c->fixture_pages){errno=EINVAL;return-1;}}return 0;}
static int save_map(struct cfg*c){if(!c->map_out)return 0;int fd=open(c->map_out,O_WRONLY|O_CREAT|O_TRUNC|O_CLOEXEC,0644);if(fd<0)return-1;size_t n=c->writer_pages*sizeof(*c->latest);int rc=full_pwrite(fd,c->latest,n,0);if(!rc)rc=fsync(fd);close(fd);return rc;}
static int cmd_prefill(struct cfg*c){for(unsigned i=0;i<c->logical_pages;i++){unsigned fi=i%c->fixture_pages;if(full_pwrite(c->fd,c->data+(size_t)fi*PAGE,PAGE,(off_t)i*PAGE)){fprintf(stderr,"PREFILL_FAIL page=%u errno=%d\n",i,errno);return 1;}}if(fsync(c->fd)){perror("prefill fsync");return 1;}printf("{\"mode\":\"prefill\",\"pages\":%u,\"bytes\":%" PRIu64 ",\"fsync\":\"PASS\"}\n",c->logical_pages,(uint64_t)c->logical_pages*PAGE);return 0;}
static int cmd_verify(struct cfg*c){void*buf=NULL;if(posix_memalign(&buf,PAGE,PAGE))return 2;uint64_t mismatches=0;for(unsigned i=0;i<c->logical_pages;i++){unsigned fi=i%c->fixture_pages;if(i<c->writer_pages)fi=c->latest[i];if(full_pread(c->fd,buf,PAGE,(off_t)i*PAGE)){fprintf(stderr,"VERIFY_READ_FAIL page=%u errno=%d\n",i,errno);free(buf);return 1;}if(memcmp(buf,c->data+(size_t)fi*PAGE,PAGE)){if(mismatches<8)fprintf(stderr,"VERIFY_MISMATCH page=%u fixture=%u\n",i,fi);mismatches++;}}free(buf);printf("{\"mode\":\"verify\",\"pages\":%u,\"bytes\":%" PRIu64 ",\"mismatches\":%" PRIu64 ",\"result\":\"%s\"}\n",c->logical_pages,(uint64_t)c->logical_pages*PAGE,mismatches,mismatches?"FAIL":"PASS");return mismatches?1:0;}
static int cmp_sample(const void*a,const void*b){uint64_t x=((const struct sample*)a)->ns,y=((const struct sample*)b)->ns;return x<y?-1:x>y?1:0;}
static void percentile(struct sample*s,size_t n,double p,uint64_t*out){if(!n){*out=0;return;}size_t idx=(size_t)(p*(double)n);if(idx>=n)idx=n-1;*out=s[idx].ns;}
static int cmd_run(struct cfg*c){pthread_t th[MAX_QD];struct rusage before,after;size_t total=0;uint64_t reads=0,writes=0,errors=0,mismatches=0;struct sample*all=NULL;size_t nread=0,nwrite=0;struct sample*rs=NULL,*ws=NULL;if(c->qd<1||c->qd>MAX_QD||!c->writer_pages||c->writer_pages>c->logical_pages||!c->reader_pages||c->reader_start+c->reader_pages>c->logical_pages){fprintf(stderr,"invalid run geometry\n");return 2;}c->locks=calloc(c->writer_pages,sizeof(*c->locks));if(!c->locks)return 2;for(unsigned i=0;i<c->writer_pages;i++)pthread_mutex_init(&c->locks[i],NULL);if(pthread_barrier_init(&c->barrier,NULL,c->qd+1))return 2;atomic_init(&c->next,0);atomic_init(&c->stop,0);for(unsigned i=0;i<c->qd;i++){c->w[i]=(struct worker){.c=c,.id=i};if(pthread_create(&th[i],NULL,worker_main,&c->w[i])){perror("pthread_create");return 2;}}c->start_ns=now_ns()+500000000ULL;c->end_ns=c->start_ns+(uint64_t)c->seconds*1000000000ULL;getrusage(RUSAGE_SELF,&before);pthread_barrier_wait(&c->barrier);for(unsigned i=0;i<c->qd;i++)pthread_join(th[i],NULL);getrusage(RUSAGE_SELF,&after);int fsync_rc=fsync(c->fd);for(unsigned i=0;i<c->qd;i++){reads+=c->w[i].reads;writes+=c->w[i].writes;errors+=c->w[i].errors;mismatches+=c->w[i].mismatches;total+=c->w[i].n;}all=malloc(total*sizeof(*all));if(total&&!all)return 2;size_t at=0;for(unsigned i=0;i<c->qd;i++){memcpy(all+at,c->w[i].s,c->w[i].n*sizeof(*all));at+=c->w[i].n;}for(size_t i=0;i<total;i++)if(all[i].write)nwrite++;else nread++;rs=malloc(nread*sizeof(*rs));ws=malloc(nwrite*sizeof(*ws));if((nread&&!rs)||(nwrite&&!ws))return 2;size_t ri=0,wi=0;for(size_t i=0;i<total;i++)if(all[i].write)ws[wi++]=all[i];else rs[ri++]=all[i];qsort(rs,nread,sizeof(*rs),cmp_sample);qsort(ws,nwrite,sizeof(*ws),cmp_sample);uint64_t rp50,rp95,rp99,rmax,wp50,wp95,wp99,wmax;percentile(rs,nread,.50,&rp50);percentile(rs,nread,.95,&rp95);percentile(rs,nread,.99,&rp99);rmax=nread?rs[nread-1].ns:0;percentile(ws,nwrite,.50,&wp50);percentile(ws,nwrite,.95,&wp95);percentile(ws,nwrite,.99,&wp99);wmax=nwrite?ws[nwrite-1].ns:0;double cpu=(after.ru_utime.tv_sec-before.ru_utime.tv_sec)+(after.ru_stime.tv_sec-before.ru_stime.tv_sec)+(after.ru_utime.tv_usec-before.ru_utime.tv_usec+after.ru_stime.tv_usec-before.ru_stime.tv_usec)/1e6;int map_rc=save_map(c);if(c->csv_out){FILE*f=fopen(c->csv_out,"w");if(!f){perror("csv");return 1;}fprintf(f,"operation,latency_ns\n");for(size_t i=0;i<total;i++)fprintf(f,"%s,%" PRIu64 "\n",all[i].write?"write":"read",all[i].ns);fclose(f);}printf("{\"mode\":\"run\",\"qd\":%u,\"seconds\":%u,\"requested_iops\":%u,\"read_pct\":%u,\"reads\":%" PRIu64 ",\"writes\":%" PRIu64 ",\"errors\":%" PRIu64 ",\"mismatches\":%" PRIu64 ",\"read_samples\":%zu,\"write_samples\":%zu,\"read_p50_ns\":%" PRIu64 ",\"read_p95_ns\":%" PRIu64 ",\"read_p99_ns\":%" PRIu64 ",\"read_max_ns\":%" PRIu64 ",\"write_p50_ns\":%" PRIu64 ",\"write_p95_ns\":%" PRIu64 ",\"write_p99_ns\":%" PRIu64 ",\"write_max_ns\":%" PRIu64 ",\"process_cpu_s\":%.6f,\"peak_rss_kb\":%ld,\"fsync_rc\":%d,\"map_rc\":%d,\"write_class_counts\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 "],\"seed\":%" PRIu64 "}\n",c->qd,c->seconds,c->iops,c->read_pct,reads,writes,errors,mismatches,nread,nwrite,rp50,rp95,rp99,rmax,wp50,wp95,wp99,wmax,cpu,after.ru_maxrss,fsync_rc,map_rc,atomic_load(&c->class_counts[0]),atomic_load(&c->class_counts[1]),atomic_load(&c->class_counts[2]),atomic_load(&c->class_counts[3]),atomic_load(&c->class_counts[4]),c->seed);free(all);free(rs);free(ws);for(unsigned i=0;i<c->qd;i++)free(c->w[i].s);return errors||mismatches||fsync_rc||map_rc?1:0;}
static void usage(const char*p){fprintf(stderr,"usage: %s --mode prefill|run|verify --device DEV --fixture BIN [--logical-pages N --writer-pages N --reader-start N --reader-pages N --read-current --qd N --read-pct N --seconds N --iops N --seed N --map-in PATH --map-out PATH --csv PATH]\n",p);}
int main(int argc,char**argv){struct cfg c={.logical_pages=4096,.writer_pages=1024,.reader_start=2048,.reader_pages=1024,.qd=1,.read_pct=20,.seconds=30,.seed=0x57A7C0DEULL};const char*mode=NULL;for(int i=1;i<argc;i++){if(!strcmp(argv[i],"--mode")&&++i<argc)mode=argv[i];else if(!strcmp(argv[i],"--device")&&++i<argc)c.device=argv[i];else if(!strcmp(argv[i],"--fixture")&&++i<argc)c.fixture=argv[i];else if(!strcmp(argv[i],"--classmap")&&++i<argc)c.classmap_path=argv[i];else if(!strcmp(argv[i],"--logical-pages")&&++i<argc)c.logical_pages=strtoul(argv[i],NULL,10);else if(!strcmp(argv[i],"--writer-pages")&&++i<argc)c.writer_pages=strtoul(argv[i],NULL,10);else if(!strcmp(argv[i],"--reader-start")&&++i<argc)c.reader_start=strtoul(argv[i],NULL,10);else if(!strcmp(argv[i],"--reader-pages")&&++i<argc)c.reader_pages=strtoul(argv[i],NULL,10);else if(!strcmp(argv[i],"--read-current"))c.read_current=1;else if(!strcmp(argv[i],"--qd")&&++i<argc)c.qd=strtoul(argv[i],NULL,10);else if(!strcmp(argv[i],"--read-pct")&&++i<argc)c.read_pct=strtoul(argv[i],NULL,10);else if(!strcmp(argv[i],"--seconds")&&++i<argc)c.seconds=strtoul(argv[i],NULL,10);else if(!strcmp(argv[i],"--iops")&&++i<argc)c.iops=strtoul(argv[i],NULL,10);else if(!strcmp(argv[i],"--seed")&&++i<argc)c.seed=strtoull(argv[i],NULL,0);else if(!strcmp(argv[i],"--map-in")&&++i<argc)c.map_in=argv[i];else if(!strcmp(argv[i],"--map-out")&&++i<argc)c.map_out=argv[i];else if(!strcmp(argv[i],"--csv")&&++i<argc)c.csv_out=argv[i];else{usage(argv[0]);return 2;}}if(!mode||!c.device||!c.fixture||load_fixture(&c)||load_classmap(&c)||load_map(&c)){perror("input/preload");usage(argv[0]);return 2;}c.fd=open(c.device,O_RDWR|O_DIRECT|O_CLOEXEC);if(c.fd<0){perror("open target O_DIRECT");return 2;}int rc;if(!strcmp(mode,"prefill"))rc=cmd_prefill(&c);else if(!strcmp(mode,"run"))rc=cmd_run(&c);else if(!strcmp(mode,"verify"))rc=cmd_verify(&c);else{usage(argv[0]);rc=2;}close(c.fd);return rc;}
