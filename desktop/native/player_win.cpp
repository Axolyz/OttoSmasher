// Windows libmpv child HWND. Same N-API contract as player.mm; no browser decoding.
#define NOMINMAX
#include <windows.h>
#include <node_api.h>
#include <mpv/client.h>
#include <map>
#include <string>
#include <vector>
#include <cmath>
#include <cstring>
#include <algorithm>
static decltype(&mpv_create) call_mpv_create;
static decltype(&mpv_set_option_string) call_mpv_set_option_string;
static decltype(&mpv_initialize) call_mpv_initialize;
static decltype(&mpv_terminate_destroy) call_mpv_terminate_destroy;
static decltype(&mpv_error_string) call_mpv_error_string;
static decltype(&mpv_observe_property) call_mpv_observe_property;
static decltype(&mpv_command_async) call_mpv_command_async;
static decltype(&mpv_wait_event) call_mpv_wait_event;
static decltype(&mpv_set_option) call_mpv_set_option;
static HMODULE library = nullptr;
static bool loadLibrary() {
 if(library) return true;
 HMODULE own; wchar_t location[32768];
 if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
   reinterpret_cast<LPCWSTR>(&loadLibrary), &own)) return false;
 GetModuleFileNameW(own,location,32768); std::wstring p(location); p=p.substr(0,p.find_last_of(L"\\")+1)+L"mpv-2.dll";
 library=LoadLibraryExW(p.c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
 if(!library) return false;
 call_mpv_create=reinterpret_cast<decltype(call_mpv_create)>(GetProcAddress(library,"mpv_create")); if(!call_mpv_create) return false;
 call_mpv_set_option_string=reinterpret_cast<decltype(call_mpv_set_option_string)>(GetProcAddress(library,"mpv_set_option_string")); if(!call_mpv_set_option_string) return false;
 call_mpv_initialize=reinterpret_cast<decltype(call_mpv_initialize)>(GetProcAddress(library,"mpv_initialize")); if(!call_mpv_initialize) return false;
 call_mpv_terminate_destroy=reinterpret_cast<decltype(call_mpv_terminate_destroy)>(GetProcAddress(library,"mpv_terminate_destroy")); if(!call_mpv_terminate_destroy) return false;
 call_mpv_error_string=reinterpret_cast<decltype(call_mpv_error_string)>(GetProcAddress(library,"mpv_error_string")); if(!call_mpv_error_string) return false;
 call_mpv_observe_property=reinterpret_cast<decltype(call_mpv_observe_property)>(GetProcAddress(library,"mpv_observe_property")); if(!call_mpv_observe_property) return false;
 call_mpv_command_async=reinterpret_cast<decltype(call_mpv_command_async)>(GetProcAddress(library,"mpv_command_async")); if(!call_mpv_command_async) return false;
 call_mpv_wait_event=reinterpret_cast<decltype(call_mpv_wait_event)>(GetProcAddress(library,"mpv_wait_event")); if(!call_mpv_wait_event) return false;
 call_mpv_set_option=reinterpret_cast<decltype(call_mpv_set_option)>(GetProcAddress(library,"mpv_set_option")); if(!call_mpv_set_option) return false;
 return true;
}
#define mpv_create call_mpv_create
#define mpv_set_option_string call_mpv_set_option_string
#define mpv_initialize call_mpv_initialize
#define mpv_terminate_destroy call_mpv_terminate_destroy
#define mpv_error_string call_mpv_error_string
#define mpv_observe_property call_mpv_observe_property
#define mpv_command_async call_mpv_command_async
#define mpv_wait_event call_mpv_wait_event
#define mpv_set_option call_mpv_set_option
struct Player {mpv_handle* mpv; HWND view; HWND parent;};
static std::map<int,Player*> players; static int serial=0;
static LRESULT CALLBACK videoProc(HWND w,UINT m,WPARAM a,LPARAM b) {
 if(m==WM_NCHITTEST) return HTTRANSPARENT;
 if(m==WM_ERASEBKGND) return 1;
 return DefWindowProcW(w,m,a,b);
}
static napi_value undefined(napi_env env) { napi_value v; napi_get_undefined(env,&v); return v; }
static napi_value str(napi_env env,const char *s) { napi_value v; napi_create_string_utf8(env,s ? s : "",NAPI_AUTO_LENGTH,&v); return v; }
static std::string string(napi_env e,napi_value v) { size_t n; napi_get_value_string_utf8(e,v,NULL,0,&n); std::vector<char> b(n+1); napi_get_value_string_utf8(e,v,b.data(),n+1,&n); return std::string(b.data(),n); }
static int number(napi_env e,napi_value v) { int32_t n=0; napi_get_value_int32(e,v,&n); return n; }
static double real(napi_env e,napi_value v) { double n=0; napi_get_value_double(e,v,&n); return n; }
static napi_value fail(napi_env e,const char *s) { napi_throw_error(e,NULL,s); return undefined(e); }
static Player *get(napi_env e,napi_value v) { auto it=players.find(number(e,v)); return it==players.end()?nullptr:it->second; }
static napi_value create(napi_env env,napi_callback_info info) {
 size_t argc=2;napi_value args[2];napi_get_cb_info(env,info,&argc,args,nullptr,nullptr);
 if(argc!=2||!loadLibrary()) return fail(env,"libmpv DLL missing or incompatible");
 void* bytes;size_t len;bool video=false;
 napi_get_buffer_info(env,args[0],&bytes,&len);napi_get_value_bool(env,args[1],&video);
 if(len!=sizeof(HWND)) return fail(env,"Invalid native HWND");
 HWND parent;memcpy(&parent,bytes,sizeof(parent));
 if(!IsWindow(parent)) return fail(env,"Parent window closed");
 Player* p=new Player{mpv_create(),nullptr,parent};
 if(!p->mpv){delete p;return fail(env,"mpv_create failed");}
 if(video){
  static bool registered=false;
  if(!registered){WNDCLASSW wc{};wc.lpfnWndProc=videoProc;wc.hInstance=GetModuleHandleW(nullptr);wc.lpszClassName=L"OttoMpvView";registered=RegisterClassW(&wc)!=0;}
  p->view=CreateWindowExW(WS_EX_TRANSPARENT|WS_EX_NOACTIVATE,L"OttoMpvView",L"",WS_CHILD|WS_CLIPSIBLINGS,
    0,0,1,1,parent,nullptr,GetModuleHandleW(nullptr),nullptr);
  if(!p->view){mpv_terminate_destroy(p->mpv);delete p;return fail(env,"Native video child window creation failed");}
  int64_t wid=reinterpret_cast<intptr_t>(p->view);mpv_set_option(p->mpv,"wid",MPV_FORMAT_INT64,&wid);
 }
 const char* opts[][2]={{"config","no"},{"terminal","no"},{"input-default-bindings","no"},{"input-vo-keyboard","no"},
 {"input-cursor","no"},{"osc","no"},{"sid","no"},{"sub-auto","no"},{"idle","yes"},{"keep-open","yes"},
 {"pause","yes"},{"hwdec","auto-safe"},{"vo",video?"gpu-next":"null"}};
 for(auto &opt:opts) mpv_set_option_string(p->mpv,opt[0],opt[1]);
 if(!video)mpv_set_option_string(p->mpv,"vid","no");
 int r=mpv_initialize(p->mpv);
 if(r<0){mpv_terminate_destroy(p->mpv);if(p->view)DestroyWindow(p->view);delete p;return fail(env,mpv_error_string(r));}
 const char* props[]={"time-pos","duration","paused-for-cache","pause","eof-reached","idle-active","volume","mute","speed","hwdec-current","video-codec","audio-codec-name","aid","audio-delay","current-tracks/audio/external-filename","video-params/w","video-params/h",nullptr};
 for(int i=0;props[i];i++)mpv_observe_property(p->mpv,i+1,props[i],MPV_FORMAT_STRING);
 int id=++serial;players[id]=p;napi_value v;napi_create_int32(env,id,&v);return v;
}
static napi_value command(napi_env env,napi_callback_info info) {
    size_t n=2;napi_value a[2];napi_get_cb_info(env,info,&n,a,NULL,NULL);Player *p=get(env,a[0]);if(!p)return fail(env,"Unknown player");
    uint32_t size;napi_get_array_length(env,a[1],&size);std::vector<std::string> words;std::vector<const char*> list;
    for(uint32_t i=0;i<size;i++){napi_value v;napi_get_element(env,a[1],i,&v);words.push_back(string(env,v));}
    for(auto &s:words)list.push_back(s.c_str());list.push_back(NULL);
    int r=mpv_command_async(p->mpv,0,list.data());if(r<0)return fail(env,mpv_error_string(r));return undefined(env);
}
static napi_value geometry(napi_env env,napi_callback_info info) {
 size_t n=6;napi_value a[6];napi_get_cb_info(env,info,&n,a,nullptr,nullptr);Player* p=get(env,a[0]);
 if(!p||!p->view)return undefined(env);
 bool visible=false;napi_get_value_bool(env,a[5],&visible);
 double scale=GetDpiForWindow(p->parent)/96.0;
 int x=std::lround(real(env,a[1])*scale),y=std::lround(real(env,a[2])*scale);
 int w=std::max(1,(int)std::lround(real(env,a[3])*scale)),h=std::max(1,(int)std::lround(real(env,a[4])*scale));
 SetWindowPos(p->view,HWND_TOP,x,y,w,h,SWP_NOACTIVATE|(visible?SWP_SHOWWINDOW:SWP_HIDEWINDOW));
 return undefined(env);
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
static void destroyPlayer(int id){auto i=players.find(id);if(i==players.end())return;Player* p=i->second;players.erase(i);
 mpv_terminate_destroy(p->mpv);if(p->view)DestroyWindow(p->view);delete p;
}
static napi_value destroy(napi_env env,napi_callback_info info){size_t n=1;napi_value a[1];napi_get_cb_info(env,info,&n,a,NULL,NULL);destroyPlayer(number(env,a[0]));return undefined(env);}
static void cleanup(void*){while(!players.empty())destroyPlayer(players.begin()->first);}
static napi_value init(napi_env env,napi_value exports){napi_property_descriptor p[]={{"create",0,create,0,0,0,napi_default,0},{"command",0,command,0,0,0,napi_default,0},{"geometry",0,geometry,0,0,0,napi_default,0},{"poll",0,poll,0,0,0,napi_default,0},{"destroy",0,destroy,0,0,0,napi_default,0}};napi_define_properties(env,exports,5,p);napi_add_env_cleanup_hook(env,cleanup,NULL);return exports;}
NAPI_MODULE(NODE_GYP_MODULE_NAME,init)
