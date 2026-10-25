"""Strict recursive-descent parser for Lua SavedVariables table literals.

Accepts data, never expressions, functions, or executable Lua statements.
"""
import re


class LuaError(ValueError):
    pass


class Parser:
    def __init__(self, text):
        self.text, self.i = text.lstrip('\ufeff'), 0

    def skip(self):
        while self.i < len(self.text):
            if self.text[self.i].isspace():
                self.i += 1
            elif self.text.startswith('--', self.i):
                self.i += 2
                if self.long_string(peek=True):
                    self.long_string()
                else:
                    end = self.text.find('\n', self.i)
                    self.i = len(self.text) if end < 0 else end + 1
            else:
                break

    def token(self, value):
        self.skip()
        if self.text.startswith(value, self.i):
            self.i += len(value)
            return True
        return False

    def need(self, value):
        if not self.token(value):
            raise LuaError(f'Expected {value!r} at offset {self.i}')

    def name(self):
        self.skip()
        m = re.match(r'[A-Za-z_][A-Za-z_0-9]*', self.text[self.i:])
        if not m:
            raise LuaError(f'Expected name at offset {self.i}')
        self.i += len(m[0])
        return m[0]

    def long_string(self, peek=False):
        m = re.match(r'\[(=*)\[', self.text[self.i:])
        if not m:
            return False if peek else None
        if peek:
            return True
        start = self.i + len(m[0])
        end = self.text.find(']' + m[1] + ']', start)
        if end < 0:
            raise LuaError('Unterminated long string')
        self.i = end + len(m[1]) + 2
        return self.text[start:end].removeprefix('\r\n').removeprefix('\n')

    def value(self, depth=0):
        if depth > 100:
            raise LuaError('Table nesting exceeds 100')
        self.skip()
        if self.i >= len(self.text):
            raise LuaError('Unexpected end of file')
        if self.long_string(peek=True):
            return self.long_string()
        c = self.text[self.i]
        if c in '\"\'':
            self.i += 1
            out = []
            while self.i < len(self.text):
                ch = self.text[self.i]
                self.i += 1
                if ch == c:
                    return ''.join(out)
                if ch == '\\':
                    if self.i >= len(self.text):
                        break
                    ch = self.text[self.i]
                    self.i += 1
                    escapes = {'n': '\n', 'r': '\r', 't': '\t', 'a': '\a', 'b': '\b', 'f': '\f', 'v': '\v', '\\': '\\', '\"': '\"', "'": "'"}
                    if ch in escapes:
                        ch = escapes[ch]
                    elif ch.isdigit():
                        digits = ch
                        while len(digits) < 3 and self.i < len(self.text) and self.text[self.i].isdigit():
                            digits += self.text[self.i]; self.i += 1
                        if int(digits) > 255:
                            raise LuaError('Invalid decimal escape')
                        ch = chr(int(digits))
                    elif ch == 'z':
                        while self.i < len(self.text) and self.text[self.i].isspace():
                            self.i += 1
                        ch = ''
                    else:
                        raise LuaError(f'Unsupported escape: {ch}')
                out.append(ch)
            raise LuaError('Unterminated string')
        if self.token('{'):
            result, index = {}, 1
            while not self.token('}'):
                if self.token('['):
                    key = self.value(depth + 1); self.need(']'); self.need('=')
                    val = self.value(depth + 1)
                else:
                    saved = self.i
                    try:
                        key = self.name()
                        named = self.token('=')
                    except LuaError:
                        named = False
                    if named:
                        val = self.value(depth + 1)
                    else:
                        self.i = saved
                        key, val = index, self.value(depth + 1)
                        index += 1
                if key is None or isinstance(key, (dict, list)):
                    raise LuaError('Invalid table key')
                result[key] = val
                if not (self.token(',') or self.token(';')):
                    self.need('}')
                    break
            return result
        m = re.match(r'[+-]?(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)', self.text[self.i:])
        if m:
            self.i += len(m[0])
            return float(m[0]) if any(x in m[0].lower() for x in ('.', 'e')) and 'x' not in m[0].lower() else int(m[0], 16 if 'x' in m[0].lower() else 10)
        name = self.name()
        if name not in ('true', 'false', 'nil'):
            raise LuaError(f'Executable or unsupported Lua value: {name}')
        return {'true': True, 'false': False, 'nil': None}[name]


def loads(text):
    parser, result = Parser(text), {}
    parser.skip()
    while parser.i < len(parser.text):
        name = parser.name(); parser.need('=')
        result[name] = parser.value()
        parser.token(';'); parser.skip()
    return result


def sequence(value):
    if isinstance(value, dict):
        return [v for k, v in sorted(value.items(), key=lambda p: str(p[0]).zfill(12))]
    return value or []
