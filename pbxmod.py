#!/usr/bin/env python3

import argparse, sys, os, io, json, enum, hashlib, time, random
from typing import List, Dict

TERMINATOR_CHARSET = b' \t\n,;'

class XcodeProject(object):
    def __init__(self):
        self.__buffer = None # type: io.BufferedReader
        self.__pbx_data = {} # type: dict
        self.__pbx_project = None # type: PBXProject
        self.__library = self.__pbx_data['objects'] = {} # type: dict

    def get_pbx_object(self, uuid:str)->Dict:
        return self.__library.get(uuid)

    def has_pbx_object(self, uuid:str)->bool:
        return uuid in self.__library

    def add_pbx_object(self, uuid:str, data:any):
        self.__library[uuid] = data

    def __read(self, size = 0):
        char = self.__buffer.read(size)
        if not char: raise EOFError('expect more data')
        return char

    def __skip_comment(self):
        offset = self.__buffer.tell() - 1
        char = self.__read(1)
        if char == b'*':
            while True:
                a = self.__read(1)
                if a == b'*':
                    b = self.__read(1)
                    if b == b'/':break
        elif char == b'/':
            while True:
                a = self.__read(1)
                if a == b'\n':break
        else:
            self.__buffer.seek(-1, os.SEEK_CUR)
        length = self.__buffer.tell() - offset
        return length > 0

    def __read_array(self):
        data, balance = [], 1
        while True:
            char = self.__read(1)
            if char == b'/':
                self.__skip_comment()
            elif char == b'(':
                balance += 1
            elif char == b')':
                balance -= 1
            else:
                self.__buffer.seek(-1, os.SEEK_CUR)
                item = self.__read_object()
                if item: data.append(item)
            if balance == 0: break
        return data

    def __read_string(self):
        while True:
            char = self.__read(1)
            if char == b'/':
                self.__skip_comment()
                continue
            elif char not in TERMINATOR_CHARSET:
                s = char
                break
        data = s
        if s != b'\'' and s != b'"':
            while True:
                char = self.__read(1)
                if char in TERMINATOR_CHARSET: return data
                data += char
        else:
            p = b''
            while True:
                char = self.__read(1)
                if not char: break
                data += char
                if char == s and (not p or p != b'\\'): return data
                p = char
        return data

    def __read_dictionary(self):
        data, balance = {}, 1
        while True:
            char = self.__read(1)
            if char == b'/':
                self.__skip_comment()
            elif char == b'{':
                balance += 1
            elif char == b'}':
                balance -= 1
            elif char in TERMINATOR_CHARSET:
                continue
            else:
                self.__buffer.seek(-1, os.SEEK_CUR)
                name = self.__read_string().decode('utf-8')
                while True:
                    c = self.__read(1)
                    if c == b'=':
                        value = self.__read_object()
                        break
                data[name] = value
            if balance == 0:break
        return data

    def __read_object(self):
        while True:
            char = self.__read(1)
            if char == b'/':
                self.__skip_comment()
            elif char == b'{':
                return self.__read_dictionary()
            elif char == b'}':
                raise RuntimeError('not expect \'}\' here')
            elif char == b')':
                self.__buffer.seek(-1, os.SEEK_CUR)
                return None
            elif char == b'(':
                return self.__read_array()
            elif char in TERMINATOR_CHARSET:
                continue
            else:
                self.__buffer.seek(-1, os.SEEK_CUR)
                return self.__read_string().decode('utf-8')

    def __generate_pbx_project(self):
        self.__pbx_project = PBXProject(project=self)
        self.__pbx_project.load(uuid=self.__pbx_data.get('rootObject'))

    def load_pbxproj(self, file_path:str):
        print('>>> {}'.format(file_path))
        self.__buffer = open(file_path, mode='rb')
        self.__pbx_data = self.__read_object()
        self.__library = self.__pbx_data.get('objects')  # type: dict
        print(json.dumps(self.__pbx_data))
        self.__generate_pbx_project()

    def dump_pbxproj(self):
        print(json.dumps(self.__pbx_data, indent=4))

class PBXObject(object):
    def __init__(self, project:XcodeProject):
        self.project = project
        self.data = None # type:dict
        self.uuid = None # type:str
        self.isa = __class__.__name__ # type:str

    def load(self, uuid:str):
        self.uuid = uuid
        self.data = self.project.get_pbx_object(uuid)
        self.isa = self.data.get('isa') # type: str

class PBXBuildFile(PBXObject):
    def __init__(self, project:XcodeProject):
        super(PBXBuildFile, self).__init__(project)
        self.fileRef = PBXFileReference(self.project)

    def load(self, uuid:str):
        super(PBXBuildFile, self).load(uuid)
        self.fileRef.load(self.data.get('fileRef'))

class PBXFileReference(PBXObject):
    def __init__(self, project:XcodeProject):
        super(PBXFileReference, self).__init__(project)
        self.lastKnownFileType = None # type:str
        self.name = None  # type:str
        self.path = None  # type:str
        self.sourceTree = None  # type:str

    def load(self, uuid:str):
        super(PBXFileReference, self).load(uuid)
        self.lastKnownFileType = self.data.get('lastKnownFileType') # type:str
        self.name = self.data.get('name') # type:str
        self.path = self.data.get('path') # type:str
        self.sourceTree = self.data.get('sourceTree') # type:str

    @staticmethod
    def generate_uuid() -> str:
        md5 = hashlib.md5()
        timestamp = time.mktime(time.localtime()) + time.process_time()
        md5.update('{}-{}'.format(timestamp, random.random()).encode('utf-8'))
        return md5.hexdigest()[:24].upper()

    @staticmethod
    def create(project, file_path): # type: (XcodeProject, str)->PBXFileReference
        file_name = os.path.basename(file_path)
        base_path = os.path.dirname(file_path)
        known_types = {
            'h'  : ('sourcecode.c.h', 'SOURCE_ROOT'),
            'm'  : ('sourcecode.c.objc', 'SOURCE_ROOT'),
            'mm' : ('sourcecode.cpp.objcpp', 'SOURCE_ROOT'),
            'cpp': ('sourcecode.cpp.cpp', 'SOURCE_ROOT'),
            'entitlements': ('text.plist.entitlements', 'SOURCE_ROOT'),
            'tbd': ('sourcecode.text-based-dylib-definition', 'SDKROOT', 'usr/lib/'),
            'framework': ('wrapper.framework', 'SDKROOT', 'System/Library/Frameworks'),
            'dylib': ('compiled.mach-o.dylib', 'SDKROOT', 'usr/lib'),
            'bundle': ('wrapper.plug-in', 'SOURCE_ROOT'),
            'png': ('image.png', 'SOURCE_ROOT')
        }
        extension = file_name.split('.')[-1] # type:str
        data = {'isa': PBXFileReference.__name__, 'name': file_name, 'path': file_path}
        if extension not in known_types: raise NotImplementedError('not supported file {!r}'.format(file_path))
        meta = known_types.get(extension)
        data['lastKnownFileType'] = meta[0]
        data['sourceTree'] = meta[1]
        if extension in ('framework', 'tbd', 'dylib'):
            if not base_path: # system libraries
                data['path'] = '{}/{}'.format(meta[2], file_name)
            else:
                data['sourceTree'] = 'SOURCE_ROOT'
        while True:
            uuid = PBXFileReference.generate_uuid()
            if not project.has_pbx_object(uuid):
                project.add_pbx_object(uuid, data)
                ref = PBXFileReference(project)
                ref.load(uuid)
                return ref

class PBXBuildPhase(PBXObject):
    def __init__(self, project:XcodeProject):
        super(PBXBuildPhase, self).__init__(project)
        self.name = None # type: str
        self.runOnlyForDeploymentPostprocessing = None # type: str

    def load(self, uuid:str):
        super(PBXBuildPhase, self).load(uuid)
        if 'name' in self.data: self.name = self.data.get('name') # type: str
        self.runOnlyForDeploymentPostprocessing = self.data.get('runOnlyForDeploymentPostprocessing') # type: str

class PBXSourcesBuildPhase(PBXObject):
    def __init__(self, project:XcodeProject):
        super(PBXSourcesBuildPhase, self).__init__(project)
        self.files = []  # type: list[PBXBuildFile]

    def load(self, uuid:str):
        super(PBXSourcesBuildPhase, self).load(uuid)
        for file_uuid in self.data.get('files'):
            file_item = PBXBuildFile(self.project)
            file_item.load(file_uuid)
            self.files.append(file_item)

class PBXResourcesBuildPhase(PBXSourcesBuildPhase):
    def __init__(self, project:XcodeProject):
        super(PBXResourcesBuildPhase, self).__init__(project)

    def load(self, uuid:str):
        super(PBXResourcesBuildPhase, self).load(uuid)

class PBXShellScriptBuildPhase(PBXBuildPhase):
    def __init__(self, project:XcodeProject):
        super(PBXShellScriptBuildPhase, self).__init__(project)
        self.shellPath = '/usr/bin/sh'
        self.shellScript = None # type: str
        self.name = '\"Run Script\"'

    def load(self, uuid:str):
        super(PBXShellScriptBuildPhase, self).load(uuid)
        self.shellPath = self.data.get('shellPath') # type: str
        self.shellScript = self.data.get('shellScript')  # type: str

class PBXCopyFilesBuildPhase(PBXSourcesBuildPhase):
    def __init__(self, project:XcodeProject):
        super(PBXCopyFilesBuildPhase, self).__init__(project)

    def load(self, uuid:str):
        super(PBXCopyFilesBuildPhase, self).load(uuid)

class PBXFrameworksBuildPhase(PBXSourcesBuildPhase):
    def __init__(self, project:XcodeProject):
        super(PBXFrameworksBuildPhase, self).__init__(project)

    def load(self, uuid:str):
        super(PBXFrameworksBuildPhase, self).load(uuid)

class PBXNativeTarget(PBXObject):
    def __init__(self, project:XcodeProject):
        super(PBXNativeTarget, self).__init__(project)
        self.buildConfigurationList = XCConfigurationList(self.project)
        self.buildPhases = []
        self.productName = None # type: str
        self.name = None # type: str

    def load(self, uuid:str):
        super(PBXNativeTarget, self).load(uuid)
        self.buildConfigurationList.load(self.data.get('buildConfigurationList'))
        for phase_uuid in self.data.get('buildPhases'):
            phase_name = self.project.get_pbx_object(phase_uuid).get('isa')
            phase_item = globals().get(phase_name)(self.project) # type: PBXObject
            phase_item.load(phase_uuid)
            self.buildPhases.append(phase_item)
        self.name = self.data.get('name') # type: str
        self.productName = self.data.get('productName') # type: str

class XCConfigurationList(PBXObject):
    def __init__(self, project:XcodeProject):
        super(XCConfigurationList, self).__init__(project)
        self.buildConfigurations = [] # type: list[XCBuildConfiguration]

    @property
    def defaultConfigurationName(self)->str:
        return self.data.get('defaultConfigurationName')

    def load(self, uuid:str):
        super(XCConfigurationList, self).load(uuid)
        for config_uuid in self.data.get('buildConfigurations'): # type: str
            config_item = XCBuildConfiguration(self.project)
            config_item.load(config_uuid)
            self.buildConfigurations.append(config_item)

class XCBuildConfiguration(PBXObject):
    def __init__(self, project:XcodeProject):
        super(XCBuildConfiguration, self).__init__(project)

    @property
    def name(self)->str: return self.data.get('name')

    @property
    def buildSettings(self)->Dict[str, str]:
        return self.data.get('buildSettings')

    def load(self, uuid:str):
        super(XCBuildConfiguration, self).load(uuid)

class FlagsType(enum.Enum):
    COMPILE, LINKING, C_PLUS_PLUS = range(3)

class PBXProject(PBXObject):
    def __init__(self, project:XcodeProject):
        super(PBXProject, self).__init__(project)
        self.targets = []  # type: list[PBXNativeTarget]
        self.buildConfigurationList = XCConfigurationList(self.project)

    def load(self, uuid:str):
        super(PBXProject, self).load(uuid)
        for target_uuid in self.data.get('targets'): # type: str
            target_item = PBXNativeTarget(self.project)
            target_item.load(target_uuid)
            self.targets.append(target_item)

    def dump(self)->str:
        return ''

    def add_build_setting(self, field_name:str, field_value:any, config_name:str = None):
        target = self.targets[0]
        for config in target.buildConfigurationList.buildConfigurations:
            if not config_name or config.name == config_name:
                config.buildSettings[field_name] = field_value

    def add_framework(self, items:List[str]):
        pass

    def add_libraries(self, items:List[str]):
        pass

    def add_assets(self):
        pass

    def add_flags(self, flags:List[str], flags_type:FlagsType = FlagsType.COMPILE):
        pass

if __name__ == '__main__':
    arguments = argparse.ArgumentParser()
    arguments.add_argument('--file-path', '-f', required=True)
    options = arguments.parse_args(sys.argv[1:])
    xcode_project = XcodeProject()
    xcode_project.load_pbxproj(file_path=options.file_path)