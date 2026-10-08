// pydomino @4930396 的音素转移 tokenizer 与 Viterbi 解码的 Python 绑定（规格 14 §14.3）。
// 只包装上游 C++（third_party/pydomino/src，MIT），不改它的算法；ONNX 推理在 Python 侧由统一的会话工厂完成。
// 构建：tools/build_domino.py。
//
//   tokenize("pau a pau") -> [转移 ID, ...]      上游 read_phonemes：两端补 pau、按上游规则判定清音 I/U、未定义的转移抛 ValueError
//   to_phonemes([ID, ...]) -> ["pau", "a", ...]  转移 ID 列 → 音素列（比 ID 多一个）
//   solve(transition_logprobs, blank_logprobs, T, K, min_frames, ids) -> [转移发生的帧号, ...]
//       transition_logprobs：T×K 的 float32（C 顺序）；blank_logprobs：T 个 float32

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <exception>
#include <sstream>
#include <string>
#include <vector>

#include "phoneme_transition.hpp"
#include "viterbi.hpp"

namespace {

PhonemeTransitionTokenizer& tokenizer() {
  static PhonemeTransitionTokenizer tok;
  return tok;
}

bool to_int_vector(PyObject* seq, std::vector<int>& out) {
  PyObject* fast = PySequence_Fast(seq, "expected a sequence of int");
  if (!fast) return false;
  Py_ssize_t n = PySequence_Fast_GET_SIZE(fast);
  out.resize(static_cast<size_t>(n));
  for (Py_ssize_t i = 0; i < n; ++i) {
    long v = PyLong_AsLong(PySequence_Fast_GET_ITEM(fast, i));
    if (v == -1 && PyErr_Occurred()) {
      Py_DECREF(fast);
      return false;
    }
    out[static_cast<size_t>(i)] = static_cast<int>(v);
  }
  Py_DECREF(fast);
  return true;
}

PyObject* int_list(const std::vector<int>& v) {
  PyObject* list = PyList_New(static_cast<Py_ssize_t>(v.size()));
  if (!list) return nullptr;
  for (size_t i = 0; i < v.size(); ++i) PyList_SET_ITEM(list, static_cast<Py_ssize_t>(i), PyLong_FromLong(v[i]));
  return list;
}

PyObject* py_tokenize(PyObject*, PyObject* args) {
  const char* text = nullptr;
  if (!PyArg_ParseTuple(args, "s", &text)) return nullptr;
  try {
    std::istringstream ss{std::string(text)};
    return int_list(tokenizer().read_phonemes(ss));
  } catch (const std::exception& e) {
    PyErr_SetString(PyExc_ValueError, e.what());
    return nullptr;
  }
}

PyObject* py_to_phonemes(PyObject*, PyObject* args) {
  PyObject* seq = nullptr;
  if (!PyArg_ParseTuple(args, "O", &seq)) return nullptr;
  std::vector<int> ids;
  if (!to_int_vector(seq, ids)) return nullptr;
  if (ids.empty()) {
    PyErr_SetString(PyExc_ValueError, "empty token sequence");
    return nullptr;
  }
  try {
    std::vector<std::string> ph = tokenizer().to_phonemes(ids);
    PyObject* list = PyList_New(static_cast<Py_ssize_t>(ph.size()));
    if (!list) return nullptr;
    for (size_t i = 0; i < ph.size(); ++i) PyList_SET_ITEM(list, static_cast<Py_ssize_t>(i), PyUnicode_FromString(ph[i].c_str()));
    return list;
  } catch (const std::exception& e) {
    PyErr_SetString(PyExc_ValueError, e.what());
    return nullptr;
  }
}

PyObject* py_solve(PyObject*, PyObject* args) {
  Py_buffer trans{}, blank{};
  int frames = 0, vocab = 0, min_frames = 0;
  PyObject* seq = nullptr;
  if (!PyArg_ParseTuple(args, "y*y*iiiO", &trans, &blank, &frames, &vocab, &min_frames, &seq)) return nullptr;
  PyObject* result = nullptr;
  std::vector<int> ids;
  if (!to_int_vector(seq, ids)) goto done;
  if (frames < 2 || vocab < 1 || ids.empty() || min_frames < 0) {
    PyErr_SetString(PyExc_ValueError, "bad viterbi arguments");
    goto done;
  }
  if (trans.len != static_cast<Py_ssize_t>(frames) * vocab * static_cast<Py_ssize_t>(sizeof(float)) ||
      blank.len != static_cast<Py_ssize_t>(frames) * static_cast<Py_ssize_t>(sizeof(float))) {
    PyErr_SetString(PyExc_ValueError, "logprob buffer size does not match T and K");
    goto done;
  }
  for (int id : ids) {
    if (id < 0 || id >= vocab) {
      PyErr_SetString(PyExc_ValueError, "token id out of range");
      goto done;
    }
  }
  try {
    std::vector<int> times(ids.size(), 0);
    Py_BEGIN_ALLOW_THREADS
    solve_viterbi(frames, vocab, static_cast<const float*>(trans.buf), static_cast<const float*>(blank.buf), min_frames, ids, times);
    Py_END_ALLOW_THREADS
    result = int_list(times);
  } catch (const std::exception& e) {
    PyErr_SetString(PyExc_RuntimeError, e.what());
  }
done:
  PyBuffer_Release(&trans);
  PyBuffer_Release(&blank);
  return result;
}

PyMethodDef methods[] = {
    {"tokenize", py_tokenize, METH_VARARGS, "phoneme string -> transition token ids (upstream read_phonemes)"},
    {"to_phonemes", py_to_phonemes, METH_VARARGS, "transition token ids -> phonemes"},
    {"solve", py_solve, METH_VARARGS, "viterbi: (transition_logprobs, blank_logprobs, T, K, min_frames, ids) -> transition frames"},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef module = {PyModuleDef_HEAD_INIT, "_domino", "pydomino tokenizer and Viterbi decoder (upstream C++ @4930396)", -1, methods};

}  // namespace

PyMODINIT_FUNC PyInit__domino(void) { return PyModule_Create(&module); }
