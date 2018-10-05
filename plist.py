#!/usr/bin/env python3

import argparse, sys, io, os, json
from typing import Dict, List, Optional

SPACE_CHATSET = b' \t\r\n'

class plistObject(object):
    def __init__(self):
        self.properties:dict[str,str] = {}
        self.data = {}
        self.buffer:io.BufferedReader = None

    def read(self, size:int = 1)->bytes:
        char:bytes = self.buffer.read(size)
        if not char: raise EOFError('expect more data')
        return char

    def read_tag(self)->(str, Optional[Dict[str, str]]):
        tag, attrs = b'', None
        while True:
            char = self.read()
            if char in b'</' and not tag: continue
            if char in SPACE_CHATSET:
                attrs = self.read_attributes()
                break
            if tag and char in b'/>':
                self.buffer.seek(-1, os.SEEK_CUR)
                break
            tag += char
        assert tag
        while True:
            if self.read() == b'>': break
        return tag, attrs

    def read_simple_text(self):
        value = b''
        while True:
            char = self.read()
            if char == b'<':
                self.buffer.seek(-1, os.SEEK_CUR)
                break
            value += char
        return value

    def read_doctype(self):
        while True:
            if self.read() == b'>': break

    def read_object(self):
        while True:
            char = self.read()
            if char in SPACE_CHATSET: continue
            elif char == b'<':
                n = self.read()
                if n == b'!':
                    t = self.read()
                    if t == b'[':
                        assert self.read(6) == b'CDATA['
                        return self.read_cdata()
                    elif t == b'-':
                        self.read_comment()
                    else:
                        self.buffer.seek(-1, os.SEEK_CUR)
                        assert self.read(7) == b'DOCTYPE'
                        self.read_doctype()
                elif n == b'/':
                    raise SyntaxError('not expect {!r} here'.format(n))
                else:
                    self.buffer.seek(-1, os.SEEK_CUR)
                    tag, attrs = self.read_tag()
                    self.buffer.seek(-2, os.SEEK_CUR)
                    empty = self.read(2) == b'/>'
                    if   tag == b'array':
                        return self.read_array() if not empty else []
                    elif tag == b'plist':
                        assert attrs
                        attrs['data'] = self.read_object()
                        return attrs
                    elif tag == b'dict':
                        return self.read_dictionary() if not empty else {}
                    elif tag == b'true' or tag == b'false':
                        return tag == b'true'
                    else:
                        value = None
                        if not empty:
                            value = self.read_simple_text().decode('utf-8')
                            closing_tag,_ = self.read_tag()
                            assert tag == closing_tag # read closing tag
                        if tag == b'integer':
                            return int(value.strip()) if not empty else 0
                        elif tag == b'real':
                            return float(value.strip()) if not empty else 0
                        else:
                            return value if not empty else ''
            else: raise SyntaxError('expect "<" but found {!r} here'.format(char))

    def read_array(self):
        result: list[any] = []
        while True:
            char = self.read()
            if char in SPACE_CHATSET: continue
            if char == b'<':
                n = self.read()
                if n == b'!':
                    assert self.read(2) == b'--'
                    self.read_comment()
                else:
                    self.buffer.seek(-1, os.SEEK_CUR)
                    offset = self.buffer.tell()
                    tag, _ = self.read_tag()
                    if tag == b'array':
                        self.buffer.seek(-8, os.SEEK_CUR)
                        assert self.buffer.read(8) == b'</array>'
                        break
                    else:
                        self.buffer.seek(offset-1)
                        result.append(self.read_object())
        return result

    def read_dictionary(self):
        result:dict[str,any] = {}
        while True:
            char = self.read()
            if char in SPACE_CHATSET: continue
            if char == b'<':
                n = self.read()
                if n == b'!':
                    assert self.read(2) == b'--'
                    self.read_comment()
                else:
                    self.buffer.seek(-1, os.SEEK_CUR)
                    tag, _ = self.read_tag()
                    if tag == b'key':
                        name = self.read_simple_text()
                        assert self.read_tag()[0] == b'key'
                        result[name.decode('utf-8')] = self.read_object()
                    else:
                        self.buffer.seek(-7, os.SEEK_CUR)
                        assert tag == b'dict' and self.read(7) == b'</dict>'
                        break
            else: continue
        return result

    def read_comment(self):
        print('read_comment')
        comment = b''
        while True:
            char = self.read()
            if char == b'>':
                self.buffer.seek(-3, os.SEEK_CUR)
                if self.read(3) == b'-->': break
            comment += char
        return comment

    def read_cdata(self):
        print('read_cdata')
        cdata = b''
        while True:
            char = self.read()
            if char == b']':
                n = self.read(2)
                if n == b']>':
                    break
                else:
                    self.buffer.seek(-2, os.SEEK_CUR)
            cdata += char
        return cdata

    def read_string(self)->bytes:
        result = b''
        quote, p = b'', b''
        while True:
            char = self.read()
            if char in SPACE_CHATSET:continue
            if not quote:
                quote = char
                continue
            if char == quote and p != b'\\':
                break
            result += char
            p = char
        return result

    def read_attributes(self)->Dict[str,str]:
        result:dict[str,str] = {}
        name:bytes = b''
        while True:
            char = self.read()
            if char in SPACE_CHATSET:continue
            elif char == b'=':
                result[name.decode('utf-8')] = self.read_string().decode('utf-8')
                name = b''
            elif char == b'>':
                self.buffer.seek(-1, os.SEEK_CUR)
                break
            else:
                name += char
        return result

    def read_properties(self):
        result = {}
        while True:
            char = self.read()
            if char == b'<':
                n = self.read()
                if n == b'?':
                    result = self.read_attributes()
                    assert self.read() == b'>'
                    break
                elif n == b'!':
                    assert self.read(2) == b'--'
                    self.read_comment()
                else:
                    self.buffer.seek(-2, os.SEEK_CUR)
                    break
        return result

    def load(self, file_path:str):
        self.buffer = open(file_path, mode='rb')
        self.properties = self.read_properties()
        print(self.properties)
        self.data = self.read_object()
        print(json.dumps(self.data, indent=4, ensure_ascii=False))

    def update(self, data:Dict[str,any]):
        pass

if __name__ == '__main__':
    arguments = argparse.ArgumentParser()
    arguments.add_argument('--plist-file', '-f', required=True)
    options = arguments.parse_args(sys.argv[1:])
    plist = plistObject()
    plist.load(file_path=options.plist_file)
