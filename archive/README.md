# 长期搁置功能

这里保留可恢复源码，区别于已接入 experiment 的新功能。默认前端模块图不引用这里，默认环境安装不安装专属依赖。已有权重和历史结果保留在原位置。

| 模块 ID | 内容 | 所需版本 |
| --- | --- | --- |
| builtin-separation | 原内置 PyMSS 分离 worker、分块及三轨实现 | experiment |
| native-alignment | Yohane/Qwen 原生音节/词对齐及开发界面 | experiment |

恢复命令：
```
./otto ui library --edition experiment --enable-archived native-alignment
OTTO_SEPARATION_PROVIDER=builtin ./otto ui library --edition experiment --enable-archived builtin-separation
```
前端归档模块集合改变时，启动器按需生成本地调试前端；不是发布安装包构建。缺少依赖时显式运行：
```
PYTHONPATH=src .runtime/envs/core/bin/python scripts/setup_inference.py --edition experiment --enable-archived native-alignment
```
内置分离恢复适配器使用旧的 models/separation 文件；通过开发 CLI 指定旧模型名，例如 becruily_deux。日常界面仍展示 Studio 模型，不把旧引擎当失败回退。

归档目录不等于删除：新增归档时隔离入口、依赖和模型下载，并在 editions.ARCHIVED 登记。恢复先做依赖及真实素材检查，不能因代码存在就声明效果合格。

`narabas_baseline/` 保存原 torch 基线比较诊断；正式 narabas ONNX/NumPy 解码留在主程序。
`setup_inference_legacy.py`、`prepare_models_legacy.py` 是旧配置参考，不作为默认安装入口。
发布构建工作暂停；未来恢复时必须按默认模块清单排除整个 archive，不可直接打包仓库目录。
