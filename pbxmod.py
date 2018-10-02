#!/usr/bin/env python3

import argparse, sys, os, io, json, enum, hashlib, time, random, shutil
from typing import List, Dict, Tuple

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
        self.__generate_pbx_project()

    def dump_pbxproj(self):
        # print(json.dumps(self.__pbx_data, indent=4))
        buffer = self.to_pbx_json(self.__pbx_data)
        buffer.seek(0)
        print(buffer.read())

    def is_pbx_key(self, value:str)->bool:
        return len(value) == 24 and value in self.has_pbx_object(value)

    def to_pbx_json(self, data:any, indent:str = '    ', padding:str = '', buffer:io.StringIO = None)->io.StringIO:
        if not buffer: buffer = io.StringIO()
        if isinstance(data, dict):
            buffer.write('{\n')
            for name, value in data.items():
                buffer.write('{}{}{} = '.format(padding, indent, name))
                if isinstance(value, str):
                    if not value: value = '\"\"'
                    buffer.write('{};\n'.format(value))
                else:
                    self.to_pbx_json(value, buffer=buffer, padding=padding + indent)
            buffer.write('{}}};\n'.format(padding))
        elif isinstance(data, list):
            buffer.write('(\n')
            for value in data: self.to_pbx_json(value, buffer=buffer, padding=padding + indent)
            buffer.write('{});\n'.format(padding))
        else:
            buffer.write('{}{};\n'.format(padding, data))
        return buffer

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

    def fill(self):
        for name, value in self.data.items():
            if hasattr(self, name) and isinstance(value, str): # only for string values
                if len(value) == 24 and value.isupper(): continue # PBXObject reference
                self.__setattr__(name, value)
        return self

    def generate_uuid(self) -> str:
        md5 = hashlib.md5()
        timestamp = time.mktime(time.localtime()) + time.process_time()
        md5.update('{}-{}'.format(timestamp, random.random()).encode('utf-8'))
        return md5.hexdigest()[:24].upper()

    def attach(self):
        if not self.data:
            self.data = {'isa': __class__.__name__}
        if self.uuid and self.project.has_pbx_object(self.uuid):
            self.project.add_pbx_object(self.uuid, self.data)
        else:
            while True:
                uuid = self.generate_uuid()
                if not self.project.has_pbx_object(uuid):
                    self.project.add_pbx_object(uuid, self.data)
                    self.uuid = uuid
                    break
        return self

class PBXBuildFile(PBXObject):
    def __init__(self, project:XcodeProject):
        super(PBXBuildFile, self).__init__(project)
        self.fileRef = PBXFileReference(self.project)
        self.settings = {}

    def load(self, uuid:str):
        super(PBXBuildFile, self).load(uuid)
        self.fileRef.load(self.data.get('fileRef'))
        self.settings = self.data.get('settings')

    @staticmethod
    def create(project:XcodeProject, file_path:str):
        file = PBXFileReference.create(project, file_path)
        item = PBXBuildFile(project).attach()
        item.data['fileRef'] = file.uuid
        item.fileRef = file
        return item

    def add_attributes(self, attributes:Tuple[str] = ('CodeSignOnCopy', 'RemoveHeadersOnCopy')):
        field_name = 'ATTRIBUTES'
        if field_name not in self.settings:
            self.settings[field_name] = []
        attr_list = self.settings[field_name] # type: list[str]
        for item in attributes:
            if item not in attr_list: attr_list.append(item)

class PBXGroup(PBXObject):
    def __init__(self, project:XcodeProject):
        super(PBXGroup, self).__init__(project)
        self.children = [] # type:list[PBXObject]
        self.path = None # type:str
        self.sourceTree = None  # type:str

    def load(self, uuid:str):
        super(PBXGroup, self).load(uuid)
        self.path = self.data.get('path') # type:str
        self.sourceTree = self.data.get('sourceTree')  # type:str
        self.children = []
        for item_uuid in self.data.get('children'):
            data = self.project.get_pbx_object(item_uuid) # type:dict
            item = globals().get(data.get('isa'))(self.project) # type: PBXObject
            # print(item, item_uuid)
            item.load(item_uuid)
            self.children.append(item)

    def sync(self, item:PBXBuildFile):
        components = item.fileRef.path.split('/')
        parent = self
        while len(components) > 1:
            node = parent.fdir(components[0])
            parent.append(node)
            del components[0]
            parent = node
        parent.append(item)

    def fdir(self, name:str):
        for item in self.children:
            if isinstance(item, PBXGroup):
                if item.path == name: return item
        item = PBXGroup.create(self.project, name)
        self.append(item)
        return item

    def append(self, item:PBXObject):
        children = self.data.get('children') # type:list[str]
        if not item.uuid not in children:
            self.children.append(item)
            children.append(item.uuid)

    @staticmethod
    def create(project:XcodeProject, path:str, source_tree:str = '\"<group>\"'):
        group = PBXGroup(project).attach()
        group.data.update({'path':path, 'sourceTree':source_tree})
        group.fill()
        return group

class PBXVariantGroup(PBXObject):
    def __init__(self, project:XcodeProject):
        super(PBXVariantGroup, self).__init__(project)
        self.children = [] # type:list[PBXObject]
        self.name = None # type:str
        self.sourceTree = None # type:str

    def load(self, uuid:str):
        super(PBXVariantGroup, self).load(uuid)
        self.name = self.data.get('name') # type:str
        self.sourceTree = self.data.get('sourceTree') # type:str
        self.children = []
        for item_uuid in self.data.get('children'):
            data = self.project.get_pbx_object(item_uuid) # type:dict
            item = globals().get(data.get('isa'))(self.project) # type: PBXObject
            # print(item, item_uuid)
            item.load(item_uuid)
            self.children.append(item)

class PBXFileReference(PBXObject):
    library = {} # type: dict[str, PBXFileReference]
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
        PBXFileReference.library[self.path] = self

    # def generate_uuid(self) -> str:
    #     md5 = hashlib.md5()
    #     timestamp = time.mktime(time.localtime()) + time.process_time()
    #     md5.update('{}-{}'.format(timestamp, random.random()).encode('utf-8'))
    #     return md5.hexdigest()[:24].upper()

    @staticmethod
    def create(project, file_path): # type: (XcodeProject, str)->PBXFileReference
        if file_path in PBXFileReference.library:
            return PBXFileReference.library.get(file_path)
        file_name = os.path.basename(file_path)
        base_path = os.path.dirname(file_path)
        known_types = {
            'h'  : ('sourcecode.c.h', 'SOURCE_ROOT'),
            'm'  : ('sourcecode.c.objc', 'SOURCE_ROOT'),
            'a'  : ('archive.ar', 'SOURCE_ROOT'),
            'mm' : ('sourcecode.cpp.objcpp', 'SOURCE_ROOT'),
            'cpp': ('sourcecode.cpp.cpp', 'SOURCE_ROOT'),
            'xib': ('file.xib', 'SOURCE_ROOT'),
            'entitlements': ('text.plist.entitlements', 'SOURCE_ROOT'),
            'tbd': ('sourcecode.text-based-dylib-definition', 'SDKROOT', 'usr/lib/'),
            'framework': ('wrapper.framework', 'SDKROOT', 'System/Library/Frameworks'),
            'dylib': ('compiled.mach-o.dylib', 'SDKROOT', 'usr/lib'),
            'bundle': ('wrapper.plug-in', 'SOURCE_ROOT'),
            'png': ('image.png', 'SOURCE_ROOT'),
            'xcassets': ('folder.assetcatalog', 'SOURCE_ROOT')
        }
        extension = file_name.split('.')[-1] # type:str
        if extension not in known_types:
            if os.path.isdir(file_path):
                folder = PBXFileReference(project).attach()
                folder.data.update({'lastKnownFileType':'folder', 'sourceTree':'SOURCE_ROOT', 'path':file_path})
                folder.fill()
                return folder
            raise NotImplementedError('not supported file {!r}'.format(file_path))
        ref = PBXFileReference(project).attach()
        data = ref.data
        data.update({'name': file_name, 'path': file_path})
        meta = known_types.get(extension)
        data['lastKnownFileType'] = meta[0]
        data['sourceTree'] = meta[1]
        if extension in ('framework', 'tbd', 'dylib'):
            if not base_path: # system libraries
                data['path'] = '{}/{}'.format(meta[2], file_name)
            else:
                data['sourceTree'] = 'SOURCE_ROOT'
        ref.fill()
        PBXFileReference.library[ref.path] = ref
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
        self.files = []
        for file_uuid in self.data.get('files'):
            file_item = PBXBuildFile(self.project)
            file_item.load(file_uuid)
            self.files.append(file_item)

    def append(self, item:PBXBuildFile):
        files = self.data.get('files') # type:list[str]
        if item.uuid not in files:
            self.files.append(item)
            files.append(item.uuid)

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
        self.dstPath = '\"\"'
        self.dstSubfolderSpec = 10 # Frameworks

    def load(self, uuid:str):
        super(PBXCopyFilesBuildPhase, self).load(uuid)
        self.dstPath = self.data.get('dstPath')
        self.dstSubfolderSpec = self.data.get('dstSubfolderSpec')

class PBXFrameworksBuildPhase(PBXSourcesBuildPhase):
    def __init__(self, project:XcodeProject):
        super(PBXFrameworksBuildPhase, self).__init__(project)

    def load(self, uuid:str):
        super(PBXFrameworksBuildPhase, self).load(uuid)

class PBXNativeTarget(PBXObject):
    def __init__(self, project:XcodeProject):
        super(PBXNativeTarget, self).__init__(project)
        self.buildConfigurationList = XCConfigurationList(self.project)
        self.buildPhases = [] # type: list[PBXBuildPhase]
        self.productName = None # type: str
        self.name = None # type: str

    def load(self, uuid:str):
        super(PBXNativeTarget, self).load(uuid)
        self.buildConfigurationList.load(self.data.get('buildConfigurationList'))
        self.buildPhases = []
        for phase_uuid in self.data.get('buildPhases'):
            phase_name = self.project.get_pbx_object(phase_uuid).get('isa')
            phase_item = globals().get(phase_name)(self.project) # type: PBXObject
            phase_item.load(phase_uuid)
            self.buildPhases.append(phase_item)
        self.name = self.data.get('name') # type: str
        self.productName = self.data.get('productName') # type: str

    def append_build_phase(self, phase:PBXBuildPhase):
        phase_list = self.data.get('buildPhases') # type:list[str]
        if phase.uuid not in phase_list:
            phase_list.append(phase.uuid)
            self.buildPhases.append(phase)

class XCConfigurationList(PBXObject):
    def __init__(self, project:XcodeProject):
        super(XCConfigurationList, self).__init__(project)
        self.buildConfigurations = [] # type: list[XCBuildConfiguration]

    @property
    def defaultConfigurationName(self)->str:
        return self.data.get('defaultConfigurationName')

    def load(self, uuid:str):
        super(XCConfigurationList, self).load(uuid)
        self.buildConfigurations = []
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
    def buildSettings(self)->Dict[str, any]:
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
        self.mainGroup = PBXGroup(self.project)

        self.frameworks_phase_build = None # type: PBXFrameworksBuildPhase
        self.frameworks_phase_embed = None # type: PBXCopyFilesBuildPhase
        self.resources_phase = None # type:PBXResourcesBuildPhase
        self.sources_phase = None # type:PBXSourcesBuildPhase

    def load(self, uuid:str):
        super(PBXProject, self).load(uuid)
        self.targets = []
        for target_uuid in self.data.get('targets'): # type: str
            target_item = PBXNativeTarget(self.project)
            target_item.load(target_uuid)
            self.targets.append(target_item)
        self.mainGroup.load(self.data.get('mainGroup'))
        target = self.targets[0]
        for phase in target.buildPhases:
            if phase.isa == PBXFrameworksBuildPhase.__name__:
                if not self.frameworks_phase_build: self.frameworks_phase_build = phase
            elif phase.isa == PBXCopyFilesBuildPhase.__name__:
                if not self.frameworks_phase_embed: self.frameworks_phase_embed = phase
                phase.dstSubfolderSpec = 10 # force to Frameworks
            elif phase.isa == PBXResourcesBuildPhase.__name__:
                if not self.resources_phase: self.resources_phase = phase
            elif phase.isa == PBXSourcesBuildPhase.__name__:
                if not self.sources_phase: self.sources_phase = phase
        assert self.frameworks_phase_embed
        assert self.frameworks_phase_build
        assert self.resources_phase
        assert self.sources_phase

    def add_build_setting(self, field_name:str, field_value:any, config_name:str = None):
        target = self.targets[0]
        for config in target.buildConfigurationList.buildConfigurations:
            if not config_name or config.name == config_name:
                value = config.buildSettings[field_name]
                if isinstance(value, list):
                    value.append(field_value)
                    self.__unique_array(value)
                else:
                    config.buildSettings[field_name] = field_value

    def add_embedded_framework(self, framework_path:str):
        self.add_framework(framework_path)
        file = PBXBuildFile.create(self.project, framework_path)
        file.add_attributes()
        self.frameworks_phase_embed.append(file)

    def add_framework(self, framework_path:str, need_sync = True):
        file = PBXBuildFile.create(self.project, framework_path)
        self.frameworks_phase_build.append(file)
        if need_sync: self.mainGroup.sync(file)

    def add_library(self, library_path:str):
        self.add_framework(library_path)

    def add_entitlements(self, file_path, need_sync = True):
        file = PBXBuildFile.create(self.project, file_path)
        self.add_build_setting('CODE_SIGN_ENTITLEMENTS', '$PROJECT_DIR/{}'.format(file_path))
        if need_sync: self.mainGroup.sync(file)

    def add_asset(self, file_path:str):
        file_name = os.path.basename(file_path)
        extension = file_name.split('.')[-1]
        file = PBXBuildFile.create(self.project, file_path)
        self.mainGroup.sync(file)
        file_type = file.fileRef.lastKnownFileType
        if extension in ('a', 'tbd', 'framework', 'dylib'):
            self.add_framework(file_path, need_sync=False)
        elif extension in ('m', 'mm', 'cpp'):
            self.sources_phase.append(file)
        elif extension in ('bundle', 'xib', 'png') or file_type.startswith('folder'):
            self.resources_phase.append(file)
        elif extension == 'entitlements':
            self.add_entitlements(file_path, need_sync=False)

    def __unique_array(self, array:List[any]):
        unique_list = []  # type: list[any]
        for item in array:
            if item not in unique_list: unique_list.append(item)
        array.clear()
        array.extend(unique_list)

    def __ensure_array_field(self, field_name:str):
        target = self.targets[0]
        for config in target.buildConfigurationList.buildConfigurations:
            field_value = config.buildSettings.get(field_name)
            if not field_value:
                config.buildSettings[field_name] = []
            elif isinstance(field_value, str):
                config.buildSettings[field_name] = [field_value]
            elif isinstance(field_value, list):
                self.__unique_array(array=field_value)
            else:
                raise AttributeError('not expect {}={!r} here'.format(field_name, type(field_value)))

    def add_flags(self, flags:List[str], flags_type:str = FlagsType.COMPILE.name, config_name:str = None):
        flags_type = flags_type.upper()
        if flags_type == FlagsType.COMPILE:
            field_name = 'OTHER_CFLAGS'
        elif flags_type == FlagsType.LINKING.name:
            field_name = 'OTHER_LDFLAGS'
        elif flags_type == FlagsType.C_PLUS_PLUS.name:
            field_name = 'OTHER_CPLUSPLUSFLAGS'
        else:raise AttributeError('not expect flags with type')
        self.__ensure_array_field(field_name)
        target = self.targets[0]
        for config in target.buildConfigurationList.buildConfigurations:
            if not config_name or config.name == config_name:
                field_value = config.buildSettings[field_name] # type: list[str]
                field_value.extend(flags)
                self.__unique_array(field_value)

    def add_shell(self, script_path:str, shell:str = '/bin/sh'):
        phase = PBXShellScriptBuildPhase(self.project)
        phase.attach()
        phase.data.update({'buildActionMask':'2147483647','files':[],'inputPaths':[], 'outputPaths':[], 'runOnlyForDeploymentPostprocessing':'0'})
        phase.data.update({'shellPath':shell, 'shellScript':'''
        /bin/chmod +x $PROJECT_DIR/{}
        $PROJECT_DIR/{}\n
        '''.format(script_path, script_path)})
        self.targets[0].append_build_phase(phase)

    def set_manual_codesign(self, development_team:str, provisioning_uuid:str, provisioning_name:str, sign_identity:str = 'iPhone Developer', config_name:str = None):
        self.add_build_setting('DEVELOPMENT_TEAM', development_team, config_name)
        self.add_build_setting('CODE_SIGN_IDENTITY', sign_identity, config_name)
        self.add_build_setting('PROVISIONING_PROFILE', provisioning_uuid, config_name)
        self.add_build_setting('PROVISIONING_PROFILE_SPECIFIER', provisioning_name, config_name)
        self.add_build_setting('CODE_SIGN_STYLE', 'Manual', config_name)

    def set_automatic_codesign(self, development_team:str, sign_identity:str = 'iPhone Developer', config_name:str = None):
        self.add_build_setting('CODE_SIGN_STYLE', 'Automatic', config_name)
        self.add_build_setting('DEVELOPMENT_TEAM', development_team, config_name)
        self.add_build_setting('CODE_SIGN_IDENTITY', sign_identity, config_name)

    def set_package_name(self, name:str):
        self.add_build_setting('PRODUCT_NAME', name)

if __name__ == '__main__':
    arguments = argparse.ArgumentParser()
    arguments.add_argument('--file-path', '-f', required=True)
    options = arguments.parse_args(sys.argv[1:])
    xcode_project = XcodeProject()
    xcode_project.load_pbxproj(file_path=options.file_path)
    xcode_project.dump_pbxproj()