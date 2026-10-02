// Inference-free adapter to the pinned upstream pydomino decoder.
#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>
#include <sstream>
#include "phoneme_transition.hpp"
#include "viterbi.hpp"
namespace py = pybind11;
using Array = py::array_t<float, py::array::c_style | py::array::forcecast>;
PYBIND11_MODULE(otto_domino_decoder, m) {
    m.def("decode", [](Array transitions, Array blanks, std::string phones, int samples, int minimum) {
        if (transitions.ndim()!=3 || transitions.shape(0)!=1 || blanks.size()!=transitions.shape(1) || samples<=0 || minimum<0)
            throw std::invalid_argument("Invalid pydomino output shapes or duration");
        PhonemeTransitionTokenizer tokenizer;
        std::istringstream stream(phones);
        auto ids = tokenizer.read_phonemes(stream);
        int frames = transitions.shape(1);
        if (ids.empty() || frames<2) throw std::invalid_argument("Empty phoneme sequence or model output");
        if (minimum * (ids.size()-1)+1 > frames)
            minimum = (frames-1) / (ids.size()-1);
        std::vector<int> times(ids.size(), 0);
        { py::gil_scoped_release unlock;
          solve_viterbi(frames, transitions.shape(2), transitions.data(), blanks.data(), minimum, ids, times); }
        auto labels = tokenizer.to_phonemes(ids);
        std::vector<std::tuple<double,double,std::string>> result;
        float begin = 0;
        for (size_t i=0; i<ids.size(); ++i) {
            float end = float(times[i])/100;
            result.emplace_back(begin, end, labels[i]); begin = end;
        }
        result.emplace_back(begin, float(samples)/16000, labels[ids.size()]);
        return result;
    });
}
