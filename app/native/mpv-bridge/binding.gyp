{
  "targets": [
    {
      "target_name": "mpv_bridge",
      "sources": ["src/bridge.cc"],
      "include_dirs": [
        "<!(node -p \"require('node-addon-api').include_dir\")",
        "../../../third_party/libmpv/include"
      ],
      "defines": ["NAPI_VERSION=9", "NODE_ADDON_API_DISABLE_DEPRECATED"],
      "cflags_cc": ["-std=c++20", "-fexceptions"],
      "conditions": [
        ["OS=='mac'", {
          "xcode_settings": {
            "CLANG_CXX_LANGUAGE_STANDARD": "c++20",
            "GCC_ENABLE_CPP_EXCEPTIONS": "YES",
            "MACOSX_DEPLOYMENT_TARGET": "12.0",
            "OTHER_LDFLAGS": [
              "-L<(module_root_dir)/../../../third_party/libmpv/macos-arm64",
              "-lmpv.2",
              "-Wl,-rpath,@loader_path/../../../../../third_party/libmpv/macos-arm64",
              "-Wl,-rpath,@loader_path/../libmpv"
            ]
          }
        }],
        ["OS=='win'", {
          "libraries": ["<(module_root_dir)/../../../third_party/libmpv/win-x64/libmpv.dll.a"],
          "msvs_settings": {"VCCLCompilerTool": {"ExceptionHandling": 1, "AdditionalOptions": ["/std:c++20"]}}
        }]
      ]
    }
  ]
}
