"""Small bounded protobuf codec for verified heart-club request/response fields."""


class ProtocolError(RuntimeError):
    """A safe parsing failure that never includes response bodies or credentials."""


def varint(number):
    """Encode a nonnegative protobuf integer without introducing a code-generator dependency."""
    if not isinstance(number, int) or not 0 <= number < 2**64:
        raise ProtocolError('整数参数无效')
    output = bytearray()
    while number > 127:
        output.append((number & 127) | 128)
        number >>= 7
    output.append(number)
    return bytes(output)


def message_string(tag, value):
    """Encode one UTF-8 length-delimited field for the verified OAuth/gift messages."""
    data = value.encode('utf-8')
    return varint((tag << 3) | 2) + varint(len(data)) + data


def parse(data):
    """Decode bounded wire fields in memory; callers decide which values may reach the UI."""
    if len(data) > 2 * 1024 * 1024:
        raise ProtocolError('服务器响应过大')
    pos = 0
    result = []
    def read_varint():
        """Read at most ten bytes and reject truncated or oversized protobuf integers."""
        nonlocal pos
        number = 0
        for shift in range(0, 70, 7):
            if pos >= len(data):
                raise ProtocolError('服务器响应不完整')
            byte = data[pos]
            pos += 1
            number |= (byte & 127) << shift
            if not byte & 128:
                return number
        raise ProtocolError('服务器整数编码异常')
    while pos < len(data):
        tag = read_varint()
        field, wire = tag >> 3, tag & 7
        if not field or len(result) > 100000:
            raise ProtocolError('服务器字段编码异常')
        if wire == 0:
            value = read_varint()
        elif wire in (1, 2, 5):
            length = read_varint() if wire == 2 else 8 if wire == 1 else 4
            value = data[pos:pos + length]
            pos += length
            if len(value) != length:
                raise ProtocolError('服务器响应不完整')
        else:
            raise ProtocolError('服务器响应类型暂不支持')
        result.append((field, wire, value))
    return result


def get(fields, tag, default=None):
    """Return a single known field while preserving absent protobuf defaults explicitly."""
    return next((value for number, wire, value in fields if number == tag), default)


def text(value):
    """Decode a string inside the credential layer; never format the value into an exception."""
    try:
        return value.decode('utf-8')
    except (AttributeError, UnicodeDecodeError):
        raise ProtocolError('服务器文本编码异常') from None
