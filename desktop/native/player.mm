#import <Cocoa/Cocoa.h>
#import <OpenGL/gl3.h>
#include <node_api.h>
#include <mpv/client.h>
#include <mpv/render_gl.h>
#include <dlfcn.h>
#include <map>
#include <string>
#include <vector>

@interface OttoVideo : NSOpenGLView {
@public mpv_render_context *renderer;
}
@end
@implementation OttoVideo
- (NSView *)hitTest:(NSPoint)p { return nil; }
- (void)drawRect:(NSRect)rect {
    if (!renderer) return;
    [[self openGLContext] makeCurrentContext];
    NSRect size = [self convertRectToBacking:self.bounds];
    mpv_opengl_fbo fbo = {0, (int)size.size.width, (int)size.size.height, 0};
    int flip = 1, block = 0;
    mpv_render_param args[] = {{MPV_RENDER_PARAM_OPENGL_FBO, &fbo},
        {MPV_RENDER_PARAM_FLIP_Y, &flip}, {MPV_RENDER_PARAM_BLOCK_FOR_TARGET_TIME, &block}, {MPV_RENDER_PARAM_INVALID, NULL}};
    mpv_render_context_update(renderer);
    mpv_render_context_render(renderer, args);
    [[self openGLContext] flushBuffer];
    mpv_render_context_report_swap(renderer);
}
@end
struct Player { mpv_handle *mpv; OttoVideo *view; NSTimer *timer; };
static std::map<int,Player*> players;
static int serial = 0;
static void *glproc(void *,const char *name) { return dlsym(RTLD_DEFAULT,name); }
static napi_value undefined(napi_env env) { napi_value v; napi_get_undefined(env,&v); return v; }
static napi_value str(napi_env env,const char *s) { napi_value v; napi_create_string_utf8(env,s ? s : "",NAPI_AUTO_LENGTH,&v); return v; }
static std::string string(napi_env e,napi_value v) { size_t n; napi_get_value_string_utf8(e,v,NULL,0,&n); std::vector<char> b(n+1); napi_get_value_string_utf8(e,v,b.data(),n+1,&n); return std::string(b.data(),n); }
static int number(napi_env e,napi_value v) { int32_t n=0; napi_get_value_int32(e,v,&n); return n; }
static double real(napi_env e,napi_value v) { double n=0; napi_get_value_double(e,v,&n); return n; }
static napi_value fail(napi_env e,const char *s) { napi_throw_error(e,NULL,s); return undefined(e); }
static Player *get(napi_env e,napi_value v) { auto it=players.find(number(e,v)); return it==players.end()?nullptr:it->second; }
static napi_value create(napi_env env,napi_callback_info info) {
    size_t argc=2; napi_value args[2]; napi_get_cb_info(env,info,&argc,args,NULL,NULL);
    bool video=false; napi_get_value_bool(env,args[1],&video);
    Player *p=new Player{mpv_create(),nil,nil};
    if (!p->mpv) { delete p; return fail(env,"mpv_create failed"); }
    mpv_set_option_string(p->mpv,"config","no");
    mpv_set_option_string(p->mpv,"terminal","no");
    mpv_set_option_string(p->mpv,"input-default-bindings","no");
    mpv_set_option_string(p->mpv,"input-vo-keyboard","no");
    mpv_set_option_string(p->mpv,"osc","no");
    mpv_set_option_string(p->mpv,"sid","no");
    mpv_set_option_string(p->mpv,"sub-auto","no");
    mpv_set_option_string(p->mpv,"idle","yes");
    mpv_set_option_string(p->mpv,"keep-open","yes");
    mpv_set_option_string(p->mpv,"pause","yes");
    mpv_set_option_string(p->mpv,"hwdec","auto-safe");
    mpv_set_option_string(p->mpv,"vo",video?"libmpv":"null");
    if(!video) mpv_set_option_string(p->mpv,"vid","no");
    int result=mpv_initialize(p->mpv);
    if(result<0) {mpv_terminate_destroy(p->mpv);delete p;return fail(env,mpv_error_string(result));}
    if(video) {
        void *buffer; size_t len; napi_get_buffer_info(env,args[0],&buffer,&len);
        if(len!=sizeof(void*)) {mpv_terminate_destroy(p->mpv);delete p;return fail(env,"Invalid native view handle");}
        NSView *host=*reinterpret_cast<NSView**>(buffer);
        NSOpenGLPixelFormatAttribute attrs[]={NSOpenGLPFAOpenGLProfile,NSOpenGLProfileVersion3_2Core,NSOpenGLPFADoubleBuffer,NSOpenGLPFAAccelerated,NSOpenGLPFAColorSize,24,0};
        NSOpenGLPixelFormat *fmt=[[NSOpenGLPixelFormat alloc] initWithAttributes:attrs];
        p->view=[[OttoVideo alloc] initWithFrame:NSMakeRect(0,0,640,360) pixelFormat:fmt];
        [fmt release];
        [p->view setWantsBestResolutionOpenGLSurface:YES];
        [host addSubview:p->view positioned:NSWindowAbove relativeTo:nil];
        [[p->view openGLContext] makeCurrentContext];
        mpv_opengl_init_params gl={glproc,NULL};
        mpv_render_param opts[]={{MPV_RENDER_PARAM_API_TYPE,(void*)MPV_RENDER_API_TYPE_OPENGL},{MPV_RENDER_PARAM_OPENGL_INIT_PARAMS,&gl},{MPV_RENDER_PARAM_INVALID,NULL}};
        result=mpv_render_context_create(&p->view->renderer,p->mpv,opts);
        if(result<0) { [p->view removeFromSuperview];[p->view release];mpv_terminate_destroy(p->mpv);delete p;return fail(env,mpv_error_string(result)); }
        OttoVideo *view=p->view;
        p->timer=[[NSTimer scheduledTimerWithTimeInterval:1.0/60 repeats:YES block:^(NSTimer*){ if(!view.hidden && view->renderer && (mpv_render_context_update(view->renderer) & MPV_RENDER_UPDATE_FRAME)) [view setNeedsDisplay:YES]; }] retain];
        p->view.hidden=YES;
    }
    const char* props[]={"time-pos","duration","paused-for-cache","pause","eof-reached","idle-active","volume","mute","speed","hwdec-current","video-codec","audio-codec-name","aid","audio-delay","current-tracks/audio/external-filename","video-params/w","video-params/h",NULL};
    for(int i=0;props[i];i++) mpv_observe_property(p->mpv,i+1,props[i],MPV_FORMAT_STRING);
    int id=++serial; players[id]=p; napi_value v;napi_create_int32(env,id,&v); return v;
}
static napi_value command(napi_env env,napi_callback_info info) {
    size_t n=2;napi_value a[2];napi_get_cb_info(env,info,&n,a,NULL,NULL);Player *p=get(env,a[0]);if(!p)return fail(env,"Unknown player");
    uint32_t size;napi_get_array_length(env,a[1],&size);std::vector<std::string> words;std::vector<const char*> list;
    for(uint32_t i=0;i<size;i++){napi_value v;napi_get_element(env,a[1],i,&v);words.push_back(string(env,v));}
    for(auto &s:words)list.push_back(s.c_str());list.push_back(NULL);
    int r=mpv_command_async(p->mpv,0,list.data());if(r<0)return fail(env,mpv_error_string(r));return undefined(env);
}
static napi_value geometry(napi_env env,napi_callback_info info) {
    size_t n=6;napi_value a[6];napi_get_cb_info(env,info,&n,a,NULL,NULL);Player *p=get(env,a[0]);if(!p||!p->view)return undefined(env);
    bool visible;napi_get_value_bool(env,a[5],&visible);NSView *host=p->view.superview;
    double x=real(env,a[1]),y=real(env,a[2]),w=real(env,a[3]),h=real(env,a[4]);
    [p->view setFrame:NSMakeRect(x,host.isFlipped?y:host.bounds.size.height-y-h,w,h)];p->view.hidden=!visible;
    [[p->view openGLContext] update]; if(visible) [p->view setNeedsDisplay:YES]; return undefined(env);
}
static napi_value poll(napi_env env,napi_callback_info info) {
    size_t n=1;napi_value a[1];napi_get_cb_info(env,info,&n,a,NULL,NULL);Player *p=get(env,a[0]);if(!p)return fail(env,"Unknown player");
    napi_value obj;napi_create_object(env,&obj);
    for(int i=0;i<128;i++){
        mpv_event *e=mpv_wait_event(p->mpv,0);if(e->event_id==MPV_EVENT_NONE)break;
        if(e->event_id==MPV_EVENT_PROPERTY_CHANGE){auto *v=(mpv_event_property*)e->data;if(v->format==MPV_FORMAT_STRING&&v->data)napi_set_named_property(env,obj,v->name,str(env,*(char**)v->data));}
        if(e->event_id==MPV_EVENT_PLAYBACK_RESTART)napi_set_named_property(env,obj,"restarted",str(env,"yes"));
        if(e->event_id==MPV_EVENT_FILE_LOADED)napi_set_named_property(env,obj,"loaded",str(env,"yes"));
        if(e->event_id==MPV_EVENT_END_FILE){auto *v=(mpv_event_end_file*)e->data;if(v->reason==MPV_END_FILE_REASON_ERROR)napi_set_named_property(env,obj,"error",str(env,mpv_error_string(v->error)));}
        if(e->event_id==MPV_EVENT_COMMAND_REPLY&&e->error<0)napi_set_named_property(env,obj,"error",str(env,mpv_error_string(e->error)));
    }
    return obj;
}
static void destroyPlayer(int id) {auto it=players.find(id);if(it==players.end())return;Player *p=it->second;players.erase(it);
    [p->timer invalidate];[p->timer release];if(p->view){[[p->view openGLContext] makeCurrentContext];mpv_render_context_free(p->view->renderer);p->view->renderer=NULL;[p->view removeFromSuperview];[p->view release];}
    mpv_terminate_destroy(p->mpv);delete p;
}
static napi_value destroy(napi_env env,napi_callback_info info){size_t n=1;napi_value a[1];napi_get_cb_info(env,info,&n,a,NULL,NULL);destroyPlayer(number(env,a[0]));return undefined(env);}
static void cleanup(void*){while(!players.empty())destroyPlayer(players.begin()->first);}
static napi_value init(napi_env env,napi_value exports){napi_property_descriptor p[]={{"create",0,create,0,0,0,napi_default,0},{"command",0,command,0,0,0,napi_default,0},{"geometry",0,geometry,0,0,0,napi_default,0},{"poll",0,poll,0,0,0,napi_default,0},{"destroy",0,destroy,0,0,0,napi_default,0}};napi_define_properties(env,exports,5,p);napi_add_env_cleanup_hook(env,cleanup,NULL);return exports;}
NAPI_MODULE(NODE_GYP_MODULE_NAME,init)
