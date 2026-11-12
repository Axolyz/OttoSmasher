// mpv 渲染桥（ARCHITECTURE §10.1）：libmpv 负责解码、音频输出与范围截停；
// 画面用 render API 的软件渲染输出 RGBX，由独立的渲染线程写进双缓冲，页面每帧取最新一帧贴到 <canvas>。
// 界面线程只做一次拷贝，不参与解码与缩放；界面卡顿不影响声音与截停（规格 15 §15.2）。

#ifdef _WIN32
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif

#include <mpv/client.h>
#include <mpv/render.h>
#include <napi.h>

#include <atomic>
#include <ctime>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace {

// 当前线程用掉的 CPU 时间（毫秒）
double ThreadCpuMs() {
#ifdef _WIN32
  FILETIME created, exited, kernel, user;
  if (!GetThreadTimes(GetCurrentThread(), &created, &exited, &kernel, &user)) return 0;
  const auto ticks = [](const FILETIME& f) { return (static_cast<unsigned long long>(f.dwHighDateTime) << 32) | f.dwLowDateTime; };
  return static_cast<double>(ticks(kernel) + ticks(user)) / 1e4;  // 单位 100 ns
#else
  timespec c{};
  clock_gettime(CLOCK_THREAD_CPUTIME_ID, &c);
  return c.tv_sec * 1e3 + c.tv_nsec / 1e6;
#endif
}

struct EventMsg {
  std::string type;
  std::string name;
  int format = 0;
  double num = 0;
  std::string str;
  bool flag = false;
  int reason = -1;
  int error = 0;
};

class Player : public Napi::ObjectWrap<Player> {
 public:
  static Napi::Object Init(Napi::Env env, Napi::Object exports) {
    Napi::Function fn = DefineClass(env, "Player",
        {InstanceMethod("command", &Player::Command), InstanceMethod("setProperty", &Player::SetProperty),
         InstanceMethod("getProperty", &Player::GetProperty), InstanceMethod("observe", &Player::Observe),
         InstanceMethod("setSize", &Player::SetSize), InstanceMethod("copyFrame", &Player::CopyFrame),
         InstanceMethod("stats", &Player::Stats), InstanceMethod("destroy", &Player::Destroy)});
    exports.Set("Player", fn);
    exports.Set("clientApiVersion", Napi::Number::New(env, static_cast<double>(mpv_client_api_version())));
    return exports;
  }

  // new Player({ video: boolean, options: {k: v} }, onEvent)
  explicit Player(const Napi::CallbackInfo& info) : Napi::ObjectWrap<Player>(info) {
    Napi::Env env = info.Env();
    if (info.Length() < 2 || !info[0].IsObject() || !info[1].IsFunction()) {
      throw Napi::TypeError::New(env, "Player(options, onEvent)");
    }
    Napi::Object opts = info[0].As<Napi::Object>();
    video_ = opts.Has("video") && opts.Get("video").ToBoolean().Value();

    mpv_ = mpv_create();
    if (!mpv_) throw Napi::Error::New(env, "mpv_create failed");
    set_opt("vo", video_ ? "libmpv" : "null");
    if (!video_) set_opt("vid", "no");
    set_opt("idle", "yes");
    set_opt("keep-open", "yes");
    set_opt("sid", "no");
    set_opt("osc", "no");
    set_opt("input-default-bindings", "no");
    set_opt("terminal", "no");
    if (opts.Has("options") && opts.Get("options").IsObject()) {
      Napi::Object o = opts.Get("options").As<Napi::Object>();
      Napi::Array keys = o.GetPropertyNames();
      for (uint32_t i = 0; i < keys.Length(); i++) {
        std::string k = keys.Get(i).ToString();
        set_opt(k.c_str(), o.Get(k).ToString().Utf8Value().c_str());
      }
    }
    if (mpv_initialize(mpv_) < 0) throw Napi::Error::New(env, "mpv_initialize failed");

    if (video_) {
      mpv_render_param params[] = {
          {MPV_RENDER_PARAM_API_TYPE, const_cast<char*>(MPV_RENDER_API_TYPE_SW)},
          {MPV_RENDER_PARAM_INVALID, nullptr},
      };
      if (mpv_render_context_create(&rctx_, mpv_, params) < 0) {
        throw Napi::Error::New(env, "mpv_render_context_create(sw) failed");
      }
      mpv_render_context_set_update_callback(rctx_, &Player::OnRenderUpdate, this);
      render_thread_ = std::thread([this] { RenderLoop(); });
    }

    tsfn_ = Napi::ThreadSafeFunction::New(env, info[1].As<Napi::Function>(), "mpv-events", 0, 1);
    event_thread_ = std::thread([this] { EventLoop(); });
    // 窗口重载时 JS 不一定来得及 destroy，环境清理时 tsfn_ 已被 Node 回收，这时候析构函数再 Release 会永远卡在已释放的锁上（整个窗口卡死）。
    // 清理钩子后注册先执行：赶在 tsfn_ 被回收之前收尾。
    env_ = env;
    napi_add_env_cleanup_hook(env_, &Player::OnEnvCleanup, this);
  }

  ~Player() override { Shutdown(); }

 private:
  void set_opt(const char* k, const char* v) { mpv_set_option_string(mpv_, k, v); }

  // ---------- 事件

  void EventLoop() {
    while (!quit_) {
      mpv_event* ev = mpv_wait_event(mpv_, 0.25);
      if (ev->event_id == MPV_EVENT_NONE) continue;
      if (ev->event_id == MPV_EVENT_SHUTDOWN) break;
      auto* m = new EventMsg();
      m->type = mpv_event_name(ev->event_id);
      m->error = ev->error;
      if (ev->event_id == MPV_EVENT_PROPERTY_CHANGE) {
        auto* p = static_cast<mpv_event_property*>(ev->data);
        m->name = p->name;
        m->format = p->format;
        if (p->format == MPV_FORMAT_DOUBLE && p->data) m->num = *static_cast<double*>(p->data);
        else if (p->format == MPV_FORMAT_FLAG && p->data) m->flag = *static_cast<int*>(p->data) != 0;
        else if (p->format == MPV_FORMAT_INT64 && p->data) m->num = static_cast<double>(*static_cast<int64_t*>(p->data));
        else if (p->format == MPV_FORMAT_STRING && p->data) m->str = *static_cast<char**>(p->data);
      } else if (ev->event_id == MPV_EVENT_END_FILE) {
        auto* e = static_cast<mpv_event_end_file*>(ev->data);
        m->reason = e->reason;
        m->error = e->error;
      }
      napi_status st = tsfn_.NonBlockingCall(m, [](Napi::Env env, Napi::Function cb, EventMsg* msg) {
        Napi::Object o = Napi::Object::New(env);
        o.Set("type", msg->type);
        if (!msg->name.empty()) {
          o.Set("name", msg->name);
          if (msg->format == MPV_FORMAT_DOUBLE || msg->format == MPV_FORMAT_INT64) o.Set("value", msg->num);
          else if (msg->format == MPV_FORMAT_FLAG) o.Set("value", msg->flag);
          else if (msg->format == MPV_FORMAT_STRING) o.Set("value", msg->str);
          else o.Set("value", env.Null());
        }
        if (msg->reason >= 0) o.Set("reason", msg->reason);
        if (msg->error < 0) o.Set("error", std::string(mpv_error_string(msg->error)));
        delete msg;
        cb.Call({o});
      });
      if (st != napi_ok) {
        delete m;
        break;
      }
    }
  }

  // ---------- 渲染（独立线程）

  static void OnRenderUpdate(void* ctx) {
    auto* self = static_cast<Player*>(ctx);
    {
      std::lock_guard<std::mutex> lk(self->m_);
      self->update_pending_ = true;
    }
    self->cv_.notify_one();
  }

  void RenderLoop() {
    std::unique_lock<std::mutex> lk(m_);
    while (!quit_) {
      cv_.wait(lk, [this] { return update_pending_ || quit_; });
      if (quit_) break;
      update_pending_ = false;
      bool force = force_render_;  // 画布尺寸变了：即使暂停、没有新帧，也重画当前帧（否则切回页面后是黑的）
      force_render_ = false;
      int w = width_, h = height_;
      lk.unlock();
      uint64_t flags = mpv_render_context_update(rctx_);
      if (((flags & MPV_RENDER_UPDATE_FRAME) || force) && w > 0 && h > 0) {
        size_t stride = static_cast<size_t>(w) * 4;
        back_.resize(stride * h);
        int size[2] = {w, h};
        mpv_render_param params[] = {
            {MPV_RENDER_PARAM_SW_SIZE, size},
            {MPV_RENDER_PARAM_SW_FORMAT, const_cast<char*>("rgb0")},
            {MPV_RENDER_PARAM_SW_STRIDE, &stride},
            {MPV_RENDER_PARAM_SW_POINTER, back_.data()},
            {MPV_RENDER_PARAM_INVALID, nullptr},
        };
        auto t0 = std::chrono::steady_clock::now();
        double c0 = ThreadCpuMs();
        int r = mpv_render_context_render(rctx_, params);
        double c1 = ThreadCpuMs();
        auto dt = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
        double cpu = c1 - c0;
        lk.lock();
        if (r >= 0) {
          std::swap(front_, back_);
          front_w_ = w;
          front_h_ = h;
          frame_seq_++;
          render_ms_total_ += dt;
          render_cpu_total_ += cpu;
          if (cpu > render_cpu_max_) render_cpu_max_ = cpu;
          if (dt > render_ms_max_) render_ms_max_ = dt;
          rendered_++;
        }
        continue;
      }
      lk.lock();
    }
  }

  // ---------- JS 方法

  Napi::Value Command(const Napi::CallbackInfo& info) {
    Napi::Env env = info.Env();
    if (!mpv_ || info.Length() < 1 || !info[0].IsArray()) throw Napi::TypeError::New(env, "command(string[])");
    Napi::Array arr = info[0].As<Napi::Array>();
    std::vector<std::string> store(arr.Length());
    std::vector<const char*> args(arr.Length() + 1, nullptr);
    for (uint32_t i = 0; i < arr.Length(); i++) {
      store[i] = arr.Get(i).ToString().Utf8Value();
      args[i] = store[i].c_str();
    }
    int r = mpv_command(mpv_, args.data());
    return Napi::Number::New(env, r);
  }

  Napi::Value SetProperty(const Napi::CallbackInfo& info) {
    Napi::Env env = info.Env();
    std::string k = info[0].ToString(), v = info[1].ToString();
    return Napi::Number::New(env, mpv_set_property_string(mpv_, k.c_str(), v.c_str()));
  }

  Napi::Value GetProperty(const Napi::CallbackInfo& info) {
    Napi::Env env = info.Env();
    std::string k = info[0].ToString();
    char* v = mpv_get_property_string(mpv_, k.c_str());
    if (!v) return env.Null();
    Napi::String s = Napi::String::New(env, v);
    mpv_free(v);
    return s;
  }

  // observe(name, "double" | "flag" | "string" | "int64")
  Napi::Value Observe(const Napi::CallbackInfo& info) {
    Napi::Env env = info.Env();
    std::string k = info[0].ToString(), f = info[1].ToString();
    mpv_format fmt = f == "double" ? MPV_FORMAT_DOUBLE : f == "flag" ? MPV_FORMAT_FLAG : f == "int64" ? MPV_FORMAT_INT64 : MPV_FORMAT_STRING;
    return Napi::Number::New(env, mpv_observe_property(mpv_, 0, k.c_str(), fmt));
  }

  Napi::Value SetSize(const Napi::CallbackInfo& info) {
    {
      std::lock_guard<std::mutex> lk(m_);
      width_ = info[0].ToNumber().Int32Value();
      height_ = info[1].ToNumber().Int32Value();
      update_pending_ = true;
      force_render_ = true;
    }
    cv_.notify_one();
    return info.Env().Undefined();
  }

  // copyFrame(target: Uint8Array, lastSeq: number) → { seq, width, height } 或 null（没有新帧）
  Napi::Value CopyFrame(const Napi::CallbackInfo& info) {
    Napi::Env env = info.Env();
    Napi::Uint8Array target = info[0].As<Napi::Uint8Array>();
    double last = info[1].ToNumber().DoubleValue();
    std::lock_guard<std::mutex> lk(m_);
    if (static_cast<double>(frame_seq_) <= last || front_.empty()) return env.Null();
    size_t n = static_cast<size_t>(front_w_) * front_h_ * 4;
    if (target.ByteLength() < n) throw Napi::RangeError::New(env, "target too small");
    std::memcpy(target.Data(), front_.data(), n);
    Napi::Object o = Napi::Object::New(env);
    o.Set("seq", static_cast<double>(frame_seq_));
    o.Set("width", front_w_);
    o.Set("height", front_h_);
    return o;
  }

  Napi::Value Stats(const Napi::CallbackInfo& info) {
    Napi::Env env = info.Env();
    std::lock_guard<std::mutex> lk(m_);
    Napi::Object o = Napi::Object::New(env);
    o.Set("rendered", static_cast<double>(rendered_));
    o.Set("renderMsAvg", rendered_ ? render_ms_total_ / static_cast<double>(rendered_) : 0.0);
    o.Set("renderMsMax", render_ms_max_);
    o.Set("renderCpuMsAvg", rendered_ ? render_cpu_total_ / static_cast<double>(rendered_) : 0.0);
    o.Set("renderCpuMsMax", render_cpu_max_);
    return o;
  }

  Napi::Value Destroy(const Napi::CallbackInfo& info) {
    Shutdown();
    return info.Env().Undefined();
  }

  static void OnEnvCleanup(void* self) { static_cast<Player*>(self)->Shutdown(); }

  void Shutdown() {
    if (!mpv_) return;
    napi_remove_env_cleanup_hook(env_, &Player::OnEnvCleanup, this);
    {
      std::lock_guard<std::mutex> lk(m_);
      quit_ = true;
    }
    cv_.notify_all();
    if (render_thread_.joinable()) render_thread_.join();
    if (rctx_) {
      mpv_render_context_free(rctx_);  // 必须在 mpv_destroy 之前
      rctx_ = nullptr;
    }
    mpv_wakeup(mpv_);
    if (event_thread_.joinable()) event_thread_.join();
    tsfn_.Release();
    mpv_terminate_destroy(mpv_);
    mpv_ = nullptr;
  }

  napi_env env_ = nullptr;
  mpv_handle* mpv_ = nullptr;
  mpv_render_context* rctx_ = nullptr;
  bool video_ = false;
  std::thread render_thread_, event_thread_;
  Napi::ThreadSafeFunction tsfn_;
  std::mutex m_;
  std::condition_variable cv_;
  std::atomic<bool> quit_{false};
  bool update_pending_ = false;
  bool force_render_ = false;
  int width_ = 0, height_ = 0;
  std::vector<uint8_t> front_, back_;
  int front_w_ = 0, front_h_ = 0;
  uint64_t frame_seq_ = 0, rendered_ = 0;
  double render_ms_total_ = 0, render_ms_max_ = 0, render_cpu_total_ = 0, render_cpu_max_ = 0;
};

}  // namespace

#ifdef __APPLE__
Napi::Value StartFileDrag(const Napi::CallbackInfo& info);
#endif

Napi::Object InitAll(Napi::Env env, Napi::Object exports) {
#ifdef __APPLE__
  exports.Set("startFileDrag", Napi::Function::New(env, StartFileDrag));
#endif
  return Player::Init(env, exports);
}

NODE_API_MODULE(mpv_bridge, InitAll)
