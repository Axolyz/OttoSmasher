#import <AppKit/AppKit.h>

#include <cstring>
#include <napi.h>

@interface OttoFileDragSource : NSObject <NSDraggingSource>
@end

@implementation OttoFileDragSource
- (NSDragOperation)draggingSession:(NSDraggingSession *)session
    sourceOperationMaskForDraggingContext:(NSDraggingContext)context {
  return context == NSDraggingContextOutsideApplication ? NSDragOperationCopy : NSDragOperationEvery;
}
@end

Napi::Value StartFileDrag(const Napi::CallbackInfo& info) {
  Napi::Env env = info.Env();
  if (!NSThread.isMainThread || info.Length() != 2 || !info[0].IsBuffer() || !info[1].IsArray()) {
    throw Napi::TypeError::New(env, "Expected a native view and file URLs on the main thread");
  }
  const auto handle = info[0].As<Napi::Buffer<char>>();
  if (handle.Length() != sizeof(void*)) {
    throw Napi::TypeError::New(env, "Invalid native view handle");
  }
  void* pointer = nullptr;
  std::memcpy(&pointer, handle.Data(), sizeof(pointer));
  NSView* view = (__bridge NSView*)pointer;
  NSWindow* window = view.window;
  if (!window) {
    throw Napi::Error::New(env, "The drag source window is unavailable");
  }

  const auto urls = info[1].As<Napi::Array>();
  NSMutableArray<NSDraggingItem*>* items = [NSMutableArray arrayWithCapacity:urls.Length()];
  NSPoint windowPoint = window.mouseLocationOutsideOfEventStream;
  NSPoint viewPoint = [view convertPoint:windowPoint fromView:nil];
  NSRect frame = [view backingAlignedRect:NSMakeRect(viewPoint.x - 0.5, viewPoint.y - 0.5, 1, 1)
                                  options:NSAlignAllEdgesNearest];
  // 同现有 Electron 拖出一样，用透明像素让以图标左上角定位的 DAW 也贴近指针。
  static NSImage* icon = [NSImage imageWithSize:NSMakeSize(1, 1) flipped:NO drawingHandler:^BOOL(NSRect rect) {
    return YES;
  }];
  for (uint32_t i = 0; i < urls.Length(); ++i) {
    const auto encoded = urls.Get(i).As<Napi::String>().Utf8Value();
    // 从已经编码的 URL 创建 NSURL；CFURLCreateWithFileSystemPath 会把 NFC 文件名分解。
    NSURL* url = [NSURL URLWithString:[NSString stringWithUTF8String:encoded.c_str()]];
    if (!url.isFileURL) {
      throw Napi::TypeError::New(env, "Expected a file URL");
    }
    NSDraggingItem* item = [[NSDraggingItem alloc] initWithPasteboardWriter:url];
    [item setDraggingFrame:frame contents:icon];
    [items addObject:item];
  }

  NSEvent* event = [NSEvent mouseEventWithType:NSEventTypeLeftMouseDragged
                                     location:windowPoint
                                modifierFlags:0
                                    timestamp:NSApp.currentEvent.timestamp
                                 windowNumber:window.windowNumber
                                      context:nil
                                  eventNumber:0
                                   clickCount:1
                                     pressure:1.0];
  if (!event || !items.count) {
    throw Napi::Error::New(env, "The drag session could not be prepared");
  }
  static OttoFileDragSource* source = [OttoFileDragSource new];
  [view beginDraggingSessionWithItems:items event:event source:source];
  return env.Undefined();
}
