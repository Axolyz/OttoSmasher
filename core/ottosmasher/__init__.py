"""OttoSmasher Core。"""

import os

# ONNX Runtime 1.30 在 macOS / Linux 自带遥测（Microsoft 1DS）：建运行环境后几秒向收集端发 HTTPS。
# 进程退出时它的静态析构与上传线程抢一个已销毁的锁，偶发 SIGABRT（退出码 134）——
# 任务进程交回结果后才崩也会被记成失败（job-worker-exited），Core 收到 app.quit 退出时也会崩（留下系统崩溃报告）。
# 只认 import onnxruntime 之前的环境变量（disable_telemetry_events() 拦不住），所以放在包入口；任务进程继承。
os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")

__version__ = "0.1.5"
