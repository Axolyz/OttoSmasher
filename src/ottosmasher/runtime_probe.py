"""Weight-free ONNX Add graph used only by the explicit runtime health check."""


def _varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result) + bytes([value])


def _number(field, value):
    return _varint(field << 3) + _varint(value)


def _field(field, value):
    value = value.encode() if isinstance(value, str) else value
    return _varint((field << 3) | 2) + _varint(len(value)) + value


def _value(name):
    shape = _field(1, _number(1, 1)) + _field(1, _number(1, 2))
    tensor = _number(1, 1) + _field(2, shape)
    return _field(1, name) + _field(2, _field(1, tensor))


_node = _field(1, "x") + _field(1, "x") + _field(2, "y") + _field(4, "Add")
_graph = (
    _field(1, _node) + _field(2, "otto-runtime-probe") + _field(11, _value("x")) + _field(12, _value("y"))
)
MODEL = _number(1, 8) + _field(7, _graph) + _field(8, _number(2, 13))
