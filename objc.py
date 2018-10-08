#!/usr/bin/env python3

import argparse,sys,os,re,io
from typing import Tuple

objc_method_pattern = re.compile(r'^\s*[+-]\s*\(')

class objcClass(object):
    def __init__(self, file_path:str):
        self.__file_path:str = file_path
        assert os.path.isfile(file_path)
        with open(file_path, mode='r+') as fp:
            self.buffer:io.StringIO = io.StringIO(fp.read())
        # self.dump_import_headers()
        # self.dump_include_files()
        self.dump_method_names()

    def __read(self, size:int = 1):
        char = self.buffer.read(size)
        if not char: raise EOFError('expect more data')
        return char

    @property
    def length(self):
        offset = self.buffer.tell()
        self.buffer.seek(0, os.SEEK_END)
        length = self.buffer.tell()
        self.buffer.seek(offset)
        return length

    def __insert(self, string:str, offset:int):
        if not string: return
        self.buffer.seek(offset)
        tail = self.buffer.read()
        self.buffer.seek(offset)
        self.buffer.write(string)
        if tail:
            self.buffer.write(tail)

    def __replace_range(self, offset:int, length:int, replacement:str = None):
        buffer_length = self.length
        assert offset + length <= buffer_length
        self.buffer.seek(offset + length)
        tail = self.buffer.read()
        replacement_length = len(replacement) if replacement else 0
        if replacement_length < length:
            self.buffer.truncate(buffer_length - (length - replacement_length))
        self.buffer.seek(offset)
        if replacement:
            self.buffer.write(replacement)
        if tail:
            self.buffer.write(tail)

    def import_header(self, header:str):
        if header.find('<') < 0 and not header.startswith('"'):
            header = '"{}"'.format(header)
        self.__insert('#import {}\n'.format(header), offset=0)

    def include_class(self, file_path:str):
        if file_path.find('<') < 0 and not file_path.startswith('"'):
            file_path = '"{}"'.format(file_path)
        self.__insert('#include {}\n'.format(file_path), offset=0)

    def insert_below(self, refer:str, code:str):
        offset, length = self.__search(refer, block_enabled=True)
        if offset >= 0:
            self.__insert('\n{}'.format(code), offset + length)

    def insert_above(self, refer:str, code:str):
        offset, length = self.__search(refer, block_enabled=True)
        if offset >= 0:
            self.__insert('{}\n'.format(code), offset)

    def __search(self, code:str, block_enabled:bool = False)->Tuple[int, int]:
        if not code: return -1, -1
        self.buffer.seek(0)
        trim_code = code.strip()
        while True:
            offset = self.buffer.tell()
            line = self.buffer.readline()
            if not line: return -1, -1
            trim_line = line.strip()
            if trim_line and trim_code.find(trim_line) >= 0 or trim_line.find(trim_code) >= 0:
                print('>>>', line)
                length = self.buffer.tell() - offset
                self.buffer.seek(offset)
                sqr_num, cur_num = 0, 0
                logic_code = ''
                while True:
                    char = self.__read()
                    logic_code += char
                    if char == ';':
                        if sqr_num == 0:
                            if cur_num == 0: length = self.buffer.tell() - offset
                            elif block_enabled: continue
                            return offset, length
                    elif char == '{':
                        cur_num += 1
                    elif char == '}':
                        cur_num -= 1
                        if block_enabled and cur_num == 0 and sqr_num == 0:
                            return offset, self.buffer.tell() - offset
                    elif char == '[':
                        sqr_num += 1
                    elif char == ']':
                        sqr_num -= 1

    def replace(self, code:str, replacement:str):
        offset, length = self.__search(code)
        if offset >= 0:
            self.__replace_range(offset, length, replacement)

    def delete(self, code:str):
        offset, length = self.__search(code, block_enabled=True)
        if offset >= 0:
            truncate_length = self.length - length
            self.buffer.seek(offset + length)
            tail = self.buffer.read()
            self.buffer.truncate(truncate_length)
            self.buffer.seek(offset)
            self.buffer.write(tail)

    def insert_within_method(self, method:str, code:str, refer:str = None, below_refer:bool = True):
        if not method: return
        self.buffer.seek(0)
        trim_refer = refer.strip()
        while True:
            offset = self.buffer.tell()
            line = self.buffer.readline()
            if objc_method_pattern.search(line):
                self.buffer.seek(offset)
                if self.__read_method_def() != method: continue
                cur_num, program_line = 0, ''
                while True:
                    char = self.__read()
                    if char == '{':
                        cur_num += 1
                        if not trim_refer:
                            self.__insert(string='\n{}'.format(code), offset=self.buffer.tell())
                            return
                        offset = self.buffer.tell()
                    elif char == '}':
                        cur_num -= 1
                    elif char == ';':
                        program_line += char
                        if cur_num == 1:
                            trim_line = program_line.strip()
                            if trim_line and trim_line.find(trim_refer) >= 0 or trim_refer.find(trim_line) >= 0:
                                if below_refer:
                                    self.__insert(string='\n{}'.format(code), offset=self.buffer.tell())
                                else:
                                    self.__insert(string='\n{}'.format(code), offset=offset)
                                return
                            offset = self.buffer.tell()

    def dump_method_names(self):
        self.buffer.seek(0)
        s_pattern = re.compile(r'^\s*@implementation')
        e_pattern = re.compile(r'^\s*@end')
        in_scope = False
        while True:
            offset = self.buffer.tell()
            line = self.buffer.readline()
            if not in_scope:
                if not s_pattern.search(line): continue
                in_scope = True
            else:
                if e_pattern.search(line):break
                if objc_method_pattern.search(line):
                    self.buffer.seek(offset)
                    print(self.__read_method_def())
                    self.__read_method_body()

    def __read_method_def(self):
        return_type:str = ''
        method_type:str = ''
        parse_step = 1
        while True:
            char = self.__read()
            if char == '(':
                assert len(method_type) == 1
                parse_step = 2
            elif char == ')':
                parameters:list[str] = []
                while True:
                    name,param_type,param_name = self.__read_method_parameter()
                    if not name: return '{}({}){}'.format(method_type, return_type, ''.join(parameters))
                    parameters.append(name + (':' if param_name else ''))
            else:
                if char in ' \t\n': continue
                if parse_step == 1:
                    method_type += char
                elif parse_step == 2:
                    return_type += char

    def __read_method_parameter(self)->Tuple[str, str, str]:
        name:str = ''
        param_name:str = ''
        param_type:str = ''
        parse_step:int = 1
        while True:
            char = self.__read()
            if char == ':': continue
            elif char == '(':
                parse_step = 2
            elif char == ')':
                parse_step = 3
            elif char == '{':
                self.buffer.seek(self.buffer.tell() - 1)
                return name, param_type, param_name
            else:
                if char in ' \t\n':
                    if parse_step != 3: continue
                    return name, param_type, param_name
                if parse_step == 1:
                    name += char
                elif parse_step == 2:
                    param_type += char
                elif parse_step == 3:
                    param_name += char

    def __read_method_body(self):
        parse_step = 1
        method_body:str = ''
        while True:
            char = self.__read()
            if char == '{':
                parse_step = 2
            elif char == '}':
                return method_body
            else:
                if parse_step == 2: method_body += char

    def dump_import_headers(self):
        self.buffer.seek(0)
        while True:
            line = self.buffer.readline()
            if not line: return
            if re.search(r'^\s*#import', line): print(line[:-1])

    def dump_include_files(self):
        self.buffer.seek(0)
        while True:
            line = self.buffer.readline()
            if not line: return
            if re.search(r'^\s*#include', line): print(line[:-1])

    def dump(self):
        self.buffer.seek(0)
        return self.buffer.read()

    def save(self):
        with open(self.__file_path, mode='w') as fp:
            self.buffer.seek(0)
            fp.write(self.buffer.read())

    def dump_match_code(self, code:str, block_enabled:bool = True):
        offset, length = self.__search(code, block_enabled)
        print('match => offset:{} length:{}'.format(offset, length))
        self.buffer.seek(offset)
        return self.buffer.read(length)

if __name__ == '__main__':
    arguments = argparse.ArgumentParser()
    arguments.add_argument('--objc-file', '-f', required=True)
    options = arguments.parse_args(sys.argv[1:])
    objc = objcClass(file_path=options.objc_file)
    objc.import_header('MyMNAObserver.h')
    objc.import_header('<GSDK_C11/GSDK.h>')
    objc.include_class('UI/OrientationSupport.h')
    # print(objc.dump())
    print(objc.dump_match_code('NSAssert(![self respondsToSelector: @selector(createUnityViewImpl)]'))
    print(objc.dump_match_code('AppController_SendNotificationWithArg(kUnityDidRegiste'))
    print(objc.dump_match_code('if (UnityIsPaused() && _wasPausedExternal == false'))
