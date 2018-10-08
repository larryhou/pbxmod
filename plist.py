#!/usr/bin/env python3

import argparse, sys, io, os, json, base64
from typing import Dict, List, Optional

SPACE_CHATSET = b' \t\r\n'

class plistObject(object):
    def __init__(self):
        self.__properties:dict[str, str] = {}
        self.__data = {}
        self.__buffer:io.BufferedReader = None
        self.__doctype:str = None

    def __read(self, size:int = 1)->bytes:
        char:bytes = self.__buffer.read(size)
        if not char: raise EOFError('expect more data')
        return char

    def __read_tag(self)->(str, Optional[Dict[str, str]]):
        tag, attrs = b'', None
        while True:
            char = self.__read()
            if char in b'</' and not tag: continue
            if char in SPACE_CHATSET:
                attrs = self.__read_attributes()
                break
            if tag and char in b'/>':
                self.__buffer.seek(-1, os.SEEK_CUR)
                break
            tag += char
        assert tag
        while True:
            if self.__read() == b'>': break
        return tag, attrs

    def __read_text(self):
        value = b''
        while True:
            char = self.__read()
            if char == b'<':
                n = self.__read()
                if n == b'!':
                    t = self.__read(7)
                    if t == b'[CDATA[':
                        value += self.__read_cdata()
                        continue
                    else:
                        self.__buffer.seek(-8, os.SEEK_CUR)
                else:
                    self.__buffer.seek(-2, os.SEEK_CUR)
                    break
            value += char
        return value

    def __read_doctype(self):
        doctype = b''
        while True:
            char = self.__read()
            if char == b'>': break
            doctype += char
        return doctype

    def __read_object(self):
        while True:
            char = self.__read()
            if char in SPACE_CHATSET: continue
            elif char == b'<':
                n = self.__read()
                if n == b'!':
                    t = self.__read()
                    if t == b'[':
                        assert self.__read(6) == b'CDATA['
                        return self.__read_cdata()
                    elif t == b'-':
                        self.__read_comment()
                    else:
                        self.__buffer.seek(-1, os.SEEK_CUR)
                        assert self.__read(7) == b'DOCTYPE'
                        self.__doctype=self.__read_doctype().strip().decode('utf-8')
                elif n == b'/':
                    raise SyntaxError('not expect {!r} here'.format(n))
                else:
                    self.__buffer.seek(-1, os.SEEK_CUR)
                    tag, attrs = self.__read_tag()
                    self.__buffer.seek(-2, os.SEEK_CUR)
                    empty = self.__read(2) == b'/>'
                    if   tag == b'array':
                        return self.__read_array() if not empty else []
                    elif tag == b'plist':
                        assert attrs
                        attrs['data'] = self.__read_object()
                        return attrs
                    elif tag == b'dict':
                        return self.__read_dictionary() if not empty else {}
                    elif tag == b'true' or tag == b'false':
                        return tag == b'true'
                    else:
                        value = None
                        if not empty:
                            value = self.__read_text().decode('utf-8')
                            closing_tag,_ = self.__read_tag()
                            assert tag == closing_tag # read closing tag
                        if tag == b'integer':
                            return int(value.strip()) if not empty else 0
                        elif tag == b'real':
                            return float(value.strip()) if not empty else 0
                        else:
                            value = value if not empty else ''
                            if tag == b'data': value = '{data}' + value
                            if tag == b'date': value = '{date}' + value
                            return value
            else: raise SyntaxError('expect "<" but found {!r} here'.format(char))

    def __read_array(self):
        result: list[any] = []
        while True:
            char = self.__read()
            if char in SPACE_CHATSET: continue
            if char == b'<':
                n = self.__read()
                if n == b'!':
                    assert self.__read(2) == b'--'
                    self.__read_comment()
                else:
                    self.__buffer.seek(-1, os.SEEK_CUR)
                    offset = self.__buffer.tell()
                    tag, _ = self.__read_tag()
                    if tag == b'array':
                        self.__buffer.seek(-8, os.SEEK_CUR)
                        assert self.__buffer.read(8) == b'</array>'
                        break
                    else:
                        self.__buffer.seek(offset - 1)
                        result.append(self.__read_object())
        return result

    def __read_dictionary(self):
        result:dict[str,any] = {}
        while True:
            char = self.__read()
            if char in SPACE_CHATSET: continue
            if char == b'<':
                n = self.__read()
                if n == b'!':
                    assert self.__read(2) == b'--'
                    self.__read_comment()
                else:
                    self.__buffer.seek(-1, os.SEEK_CUR)
                    tag, _ = self.__read_tag()
                    if tag == b'key':
                        name = self.__read_text()
                        assert self.__read_tag()[0] == b'key'
                        result[name.decode('utf-8')] = self.__read_object()
                    else:
                        self.__buffer.seek(-7, os.SEEK_CUR)
                        assert tag == b'dict' and self.__read(7) == b'</dict>'
                        break
            else: continue
        return result

    def __read_comment(self):
        print('read_comment')
        comment = b''
        while True:
            char = self.__read()
            if char == b'>':
                self.__buffer.seek(-3, os.SEEK_CUR)
                if self.__read(3) == b'-->': break
            comment += char
        return comment

    def __read_cdata(self):
        # print('read_cdata')
        cdata = b''
        while True:
            char = self.__read()
            if char == b']':
                n = self.__read(2)
                if n == b']>':
                    break
                else:
                    self.__buffer.seek(-2, os.SEEK_CUR)
            cdata += char
        # print(cdata)
        return cdata

    def __read_string(self)->bytes:
        result = b''
        quote, p = b'', b''
        while True:
            char = self.__read()
            if char in SPACE_CHATSET:continue
            if not quote:
                quote = char
                continue
            if char == quote and p != b'\\':
                break
            result += char
            p = char
        return result

    def __read_attributes(self)->Dict[str, str]:
        result:dict[str,str] = {}
        name:bytes = b''
        while True:
            char = self.__read()
            if char in SPACE_CHATSET:continue
            elif char == b'=':
                result[name.decode('utf-8')] = self.__read_string().decode('utf-8')
                name = b''
            elif char == b'>':
                self.__buffer.seek(-1, os.SEEK_CUR)
                break
            else:
                name += char
        return result

    def __read_properties(self):
        result = {}
        while True:
            char = self.__read()
            if char == b'<':
                n = self.__read()
                if n == b'?':
                    assert self.__read(3) == b'xml'
                    result = self.__read_attributes()
                    assert self.__read() == b'>'
                    break
                elif n == b'!':
                    assert self.__read(2) == b'--'
                    self.__read_comment()
                else:
                    self.__buffer.seek(-2, os.SEEK_CUR)
                    break
        return result

    def load(self, file_path:str):
        self.__buffer = open(file_path, mode='rb')
        self.__properties = self.__read_properties()
        self.__data = self.__read_object()
        self.__buffer.close()

    def __wrap_text(self, data:str)->str:
        if data.find('<') >= 0:
            return '<![CDATA[{}]]>'.format(data)
        else:return data

    def __dump_data(self, data, buffer:io.StringIO, indent:str='    ', padding:str=''):
        if isinstance(data, dict):
            if len(data) == 0:
                buffer.write('{}<dict/>\n'.format(padding))
                return
            buffer.write('{}<dict>\n'.format(padding))
            for name, value in data.items():
                buffer.write('{}{}<key>{}</key>\n'.format(padding, indent, name))
                self.__dump_data(value, indent=indent, padding=padding + indent, buffer=buffer)
            buffer.write('{}</dict>\n'.format(padding))
        elif isinstance(data, list):
            if len(data) == 0:
                buffer.write('{}<array/>\n'.format(padding))
                return
            buffer.write('{}<array>\n'.format(padding))
            for value in data:
                self.__dump_data(value, indent=indent, padding=padding+indent, buffer=buffer)
            buffer.write('{}</array>\n'.format(padding))
        elif isinstance(data, float):
            buffer.write('{}<real>{}</real>\n'.format(padding, data))
        elif isinstance(data, bool):
            buffer.write('{}<{}/>\n'.format(padding, 'true' if data else 'false'))
        elif isinstance(data, int):
            buffer.write('{}<integer>{}</integer>\n'.format(padding, data))
        elif isinstance(data, str):
            data_type = data[:6]
            if data_type == '{data}':
                encoded_data = data[6:]
                try:
                    base64.b64decode(encoded_data)
                except ValueError:
                    encoded_data = base64.b64encode(encoded_data)
                buffer.write('{}<data>{}</data>\n'.format(padding, encoded_data))
            elif data_type == '{date}':
                buffer.write('{}<date>{}</date>\n'.format(padding, data[6:]))
            else:
                if not data:
                    buffer.write('{}<string/>\n'.format(padding))
                    return
                buffer.write('{}<string>{}</string>\n'.format(padding, self.__wrap_text(data)))

    def json(self)->str:
        return json.dumps(self.__data.get('data'), indent=4, ensure_ascii=False) if self.__data else ''

    def dump(self)->str:
        buffer = io.StringIO()
        if self.__properties:
            buffer.write('<?xml')
            for name, value in self.__properties.items():
                buffer.write(' {}="{}"'.format(name, value))
            buffer.write('?>\n')
        if self.__doctype:
            buffer.write('<!DOCTYPE {}>\n'.format(self.__doctype))
        buffer.write('<plist')
        for name, value in self.__data.items():
            if name == 'data': continue
            buffer.write(' {}="{}"'.format(name, value))
        buffer.write('>\n')
        self.__dump_data(self.__data.get('data'), buffer=buffer, padding='    ')
        buffer.write('</plist>\n')
        buffer.seek(0)
        return buffer.read()

    def save(self, file_path:str = None):
        if not file_path:
            assert self.__buffer
            file_path = self.__buffer.name
        import utils
        utils.backup(file_path)
        with open(file_path, mode='w') as fp:
            fp.write(self.dump())

    def __merge_data(self, src, dst):
        if isinstance(src, list):
            assert isinstance(dst, list)
            for value in src:
                if value not in dst: dst.append(value)
        elif isinstance(src, dict):
            assert isinstance(dst, dict)
            for name, value in src.items():
                if name not in dst:
                    dst[name] = value
                elif type(value) == type(dst.get(name)):
                    if isinstance(value, list) or isinstance(value, dict):
                        self.__merge_data(value, dst.get(name))
                    else:
                        dst[name] = value
                else:
                    print('TYPE_NOT_MATCHING {!r} <=> {!r}'.format(value, dst.get(name)))
        else:
            print('TYPE_NOT_SUPPORT {!r} <=> {!r}'.format(src, dst))

    def merge(self, data:Dict[str,any]):
        self.__merge_data(src=data, dst=self.__data.get('data'))

    def merge_plist(self, file_path:str):
        target = plistObject()
        target.load(file_path)
        self.merge(data=target.__data.get('data'))

if __name__ == '__main__':
    arguments = argparse.ArgumentParser()
    arguments.add_argument('--plist-file', '-f', required=True)
    options = arguments.parse_args(sys.argv[1:])
    plist = plistObject()
    plist.load(file_path=options.plist_file)
    print(plist.json())
    print(plist.dump())
    json_string = plist.json()
    conf = json.loads(json_string) # type: dict[str, any]
    print(conf)
    conf['author'] = 'larryhou'
    plist.merge(conf)
    print(plist.dump())
