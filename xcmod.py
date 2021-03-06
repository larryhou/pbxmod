#!/usr/bin/env python3

import argparse, sys, os, io, json, enum, hashlib, time, random, re, tempfile
from typing import List, Dict, Tuple, Pattern

TERMINATOR_CHARSET = b' \t\n,;'

class XcodeProject(object):
    def __init__(self):
        self.__buffer: io.BufferedReader = None
        self.__pbx_data: dict[str,any] = {}
        self.__pbx_project: PBXProject = None
        self.__pbx_project_path: str = None
        self.__library = self.__pbx_data['objects'] = {} # type: dict[str:any]
        self.__pbx_library = PBXObjectLibrary(self)
        self.__ref_library: dict[str, PBXFileReference] = {}
        self.__xcode_project_path:str = None

    def append_pbx_object(self, item): # type: (PBXObject)->None
        self.__pbx_library[item.uuid] = item

    @property
    def pbx_project(self): return self.__pbx_project

    def get_pbx_object(self, uuid:str)->Dict:
        return self.__library.get(uuid)

    def has_pbx_object(self, uuid:str)->bool:
        return uuid in self.__library

    def add_pbx_object(self, uuid:str, data:any):
        self.__library[uuid] = data

    def del_pbx_object(self, uuid:str):
        del self.__library[uuid]

    def add_ref_file(self, file): # type: (PBXFileReference)->()
        self.__ref_library[file.path] = file

    def has_ref_file(self, file_path:str):
        return file_path in self.__ref_library

    def get_ref_file(self, file_path:str):
        return self.__ref_library.get(file_path)

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
        self.__pbx_library.clear()
        self.__pbx_project_path = file_path
        xcproj_path = os.path.join(os.path.dirname(self.__pbx_project_path), os.pardir)
        xcproj_path = os.path.abspath(xcproj_path)
        self.__xcode_project_path = xcproj_path
        self.__buffer = open(file_path, mode='rb')
        self.__pbx_data = self.__read_object()
        self.__library = self.__pbx_data.get('objects')  # type: dict
        self.__generate_pbx_project()
        return self.__pbx_project

    def save_pbxproj(self):
        import utils
        utils.backup(file_path=self.__pbx_project_path)
        with open(self.__pbx_project_path, mode='w') as fp:
            fp.write('// !$*UTF8*$!\n')
            fp.write(self.dump_pbxproj(note_enabled=True, json_format_enabled=False))
            fp.write('\n')

    def dump_pbxproj(self, note_enabled=True, json_format_enabled:bool = False):
        if json_format_enabled:
            return json.dumps(self.__pbx_data, indent=4)
        else:
            buffer = self.__to_pbx_json(self.__pbx_data, note_enabled=note_enabled)
            buffer.seek(0)
            return buffer.read()

    def import_assets(self, base_path:str, assets:[str], exclude_types:Tuple[str] = ('meta',)):
        if not assets: return
        xcproj_path = self.__xcode_project_path
        script = open(tempfile.mktemp('_import_xcode_assets.sh'), mode='w+')
        script.write('#!/usr/bin/env bash\n')
        exclude_rules = open(os.path.abspath('exclude_rules.txt'), 'w')
        exclude_rules.write('.*\n')
        include_files = open(os.path.abspath('include_files.txt'), 'w')
        for item_type in exclude_types: exclude_rules.write('*.{}\n'.format(item_type))
        exclude_rules.close()
        for file_path in assets:
            location = os.path.join(base_path, file_path)
            if os.path.isdir(location) or os.path.isfile(location):
                include_files.write(file_path)
                include_files.write('\n')
        include_files.close()
        script.write('cat {}\n'.format(include_files.name))
        script.write('cat {}\n'.format(exclude_rules.name))
        script.write('rsync -rvR --exclude-from="{}" --files-from="{}" "{}" "{}"\n'.format(exclude_rules.name, include_files.name, base_path, xcproj_path))
        script.write('rm -f {}\n'.format(exclude_rules.name))
        script.write('rm -f {}\n'.format(include_files.name))
        script.write('rm -f {}\n'.format(script.name))
        script.close()
        assert os.system('bash -x "{}"'.format(script.name)) == 0
        for file_path in assets:
            self.__pbx_project.add_asset(file_path)

    def __find_tree(self, location:str, pattern:Pattern)->List[str]:
        result: list[str] = []
        for node_name in os.listdir(location):
            if pattern and pattern.search(node_name): continue
            if node_name.startswith('.'): continue
            node_path = os.path.join(location, node_name)
            if os.path.isfile(node_path):
                result.append(node_path)
            elif os.path.isdir(node_path):
                extension = node_name.split('.')[-1]
                if extension in ('framework', 'bundle', 'xcassets'):
                    result.append(node_path)
                else:
                    result.extend(self.__find_tree(node_path, pattern))
        return result

    def import_xcmod(self, file_path:str):
        xcmod: dict[str, any] = json.load(open(file_path, 'r'))
        import_settings: dict[str, any] = xcmod.get('imports')
        if not import_settings: import_settings = {}
        base_path: str = import_settings.get('base_path')
        base_path = os.path.expanduser(base_path)
        if not os.path.exists(base_path):
            base_path = os.path.join(os.path.dirname(file_path), base_path) # relative to *.xcmod path
        if not os.path.exists(base_path): raise AssertionError('base_path[={}] not exists'.format(import_settings.get('base_path')))
        base_path = os.path.abspath(base_path)
        exclude_list: list[str] = import_settings.get('exclude')
        pattern:Pattern = re.compile(r'\.({})$'.format('|'.join(exclude_list))) if exclude_list else None
        # embed frameworks
        embed_frameworks: list[str] = import_settings.get('embed')
        if embed_frameworks:
            for framework_path in embed_frameworks:
                self.__pbx_project.embed_framework(framework_path)
        else:
            embed_frameworks = []
        # merge all kinds of assets
        assets: list[str] = []
        for item_cfg in import_settings.get('items'): # type:dict[str, str]
            item_path = item_cfg.get('path')
            if item_path in embed_frameworks: continue # same framework is imported only once
            if item_cfg.get('type') == 'tree':
                tree_assets = self.__find_tree(os.path.join(base_path, item_path), pattern)
                for node_path in tree_assets:
                    node_path = re.sub(r'^{}/'.format(base_path), '', node_path)
                    assets.append(node_path)
            else:
                assets.append(item_path)
        self.import_assets(base_path, assets + embed_frameworks, exclude_types=tuple(exclude_list))
        # merge build settings
        build_settings: dict[str, str] = xcmod.get('settings')
        if build_settings:
            for name, value in build_settings.items(): # type: str, str
                self.__pbx_project.add_build_setting(name, value)
        # merge flags
        self.__pbx_project.add_flags(xcmod.get('compiler_flags'), FlagsType.compiler)
        self.__pbx_project.add_flags(xcmod.get('link_flags'), FlagsType.link)
        self.save_pbxproj()
        # merge plist settings
        self.merge_plist(xcmod.get('plist'))
        # merge class injections
        self.merge_class(xcmod.get('class'))

    def merge_class(self, data:List[Dict[str, any]]):
        if not data: return
        from objc import objcClass
        for item in data:
            location = os.path.join(self.__xcode_project_path, item.get('path'))
            if not os.path.exists(location): continue
            objc = objcClass(file_path=location)
            import_headers = item.get('imports') # type: list[str]
            if import_headers:
                for header in import_headers: objc.import_header(header)
            include_classes = item.get('includes') # type: list[str]
            if include_classes:
                for class_item in include_classes: objc.include_class(class_item)
            injections = item.get('injections') # type: list[dict[str,str]]
            if injections:
                for code in injections:
                    if code.get('replace'):
                        objc.replace(code=code.get('code'), replacement=code.get('replace'))
                    else:
                        objc.insert_within_method(method=code.get('func'), code=code.get('code'))
            objc.save()

    def merge_plist(self, data:Dict[str, any]):
        if not data: return
        plist_path = self.__pbx_project.get_info_plist()
        from plist import plistObject
        plist = plistObject()
        plist.load(file_path=os.path.join(self.__xcode_project_path, plist_path))
        plist.merge(data)
        plist.save()

    def __is_pbx_key(self, value:str)->bool:
        return len(value) == 24 and self.has_pbx_object(value)

    def __to_pbx_json(self, data:any, note_enabled:bool, indent:str = '    ', padding:str = '', buffer:io.StringIO = None)->io.StringIO:
        if not buffer: buffer = io.StringIO()
        library = self.__pbx_library
        compact = True if not indent else False
        if isinstance(data, dict):
            if data.get('isa') in ('PBXFileReference', 'PBXBuildFile'):
                indent, padding, compact = '', '', True
            buffer.write('{')
            if not compact: buffer.write('\n')
            for name, value in data.items():
                buffer.write('{}{}{}'.format(padding, indent, name))
                if note_enabled and self.__is_pbx_key(name): buffer.write(' {}'.format(library.get(name).note()))
                buffer.write(' = ')
                if isinstance(value, str):
                    if not value: value = '\"\"'
                    buffer.write(value)
                    if note_enabled and self.__is_pbx_key(value): buffer.write(' {}'.format(library.get(value).note()))
                    buffer.write('; ')
                    if not compact: buffer.write('\n')
                else:
                    self.__to_pbx_json(value, buffer=buffer, padding=padding + indent, indent=indent, note_enabled=note_enabled)
                    buffer.write('; ')
                    if not compact: buffer.write('\n')
            buffer.write('{}}}'.format(padding))
        elif isinstance(data, list):
            buffer.write('(')
            if not compact: buffer.write('\n')
            for value in data:
                self.__to_pbx_json(value, buffer=buffer, padding=padding + indent, indent=indent, note_enabled=note_enabled)
                buffer.write(', ')
                if not compact: buffer.write('\n')
            buffer.write('{})'.format(padding))
        else:
            buffer.write('{}{}'.format(padding, data))
            if note_enabled and self.__is_pbx_key(data):buffer.write(' {}'.format(library.get(data).note()))
        return buffer

class PBXObjectLibrary(dict):
    def __init__(self, project:XcodeProject):
        super().__init__()
        self.__project = project

    def get(self, name):
        item = dict.get(self, name)
        if not item:
            unknown = PBXObjectUnresolved(self.__project)
            unknown.load(name)
            return unknown
        else:
            return item

    def __getattribute__(self, item):
        try:
            return dict.__getattribute__(self, item)
        except AttributeError:
            return self.get(item)

class PBXObject(object):
    def __init__(self, project:XcodeProject):
        self.project = project
        self.data: dict[str,any] = None
        self.uuid: str = None
        self.isa: str = self.__class__.__name__

    def load(self, uuid:str):
        self.uuid = uuid
        self.data = self.project.get_pbx_object(uuid)
        self.isa = self.data.get('isa') # type: str
        self.project.append_pbx_object(self)

    def note(self)->str:
        return '/* {} */'.format(self.__class__.__name__)

    def trim(self, value:str)->str:
        return re.sub(r'[\'"]', '', value) if value else ''

    def fill(self):
        for name, value in self.data.items():
            if hasattr(self, name) and isinstance(value, str): # only for string values
                if len(value) == 24 and value.isupper(): continue # PBXObject reference
                self.__setattr__(name, value)
        self.project.append_pbx_object(self)
        return self

    def generate_uuid(self) -> str:
        md5 = hashlib.md5()
        timestamp = time.mktime(time.localtime()) + time.process_time()
        md5.update('{}-{}'.format(timestamp, random.random()).encode('utf-8'))
        return md5.hexdigest()[:24].upper()

    def attach(self):
        if not self.data: self.data = {}
        self.data.update({'isa': self.__class__.__name__})
        if self.uuid:
            self.project.add_pbx_object(self.uuid, self.data)
        else:
            while True:
                uuid = self.generate_uuid()
                if not self.project.has_pbx_object(uuid):
                    self.project.add_pbx_object(uuid, self.data)
                    self.uuid = uuid
                    self.project.append_pbx_object(self)
                    break
        return self

    def detach(self):
        if self.uuid: self.project.del_pbx_object(self.uuid)

class PBXObjectUnresolved(PBXObject):
    def note(self):
        return '/* {} */'.format(self.__class__.__name__)

class PBXBuildFile(PBXObject):
    def __init__(self, project:XcodeProject):
        super(PBXBuildFile, self).__init__(project)
        self.fileRef = PBXFileReference(self.project)
        self.phase: PBXBuildPhase = None

    def load(self, uuid:str):
        super(PBXBuildFile, self).load(uuid)
        self.fileRef.load(self.data.get('fileRef'))

    def note(self)->str:
        ref = self.fileRef
        if self.phase:
            return '/* {} in {} */'.format(self.trim(ref.name if ref.name else ref.path), self.trim(self.phase.name))
        elif not ref.name.endswith('.h'):
            return '/* EXPECT_PHASE {} */'.format(self.trim(ref.name if ref.name else ref.path))
        else:
            return '/* {} */'.format(self.trim(ref.name if ref.name else ref.path))

    @staticmethod
    def create(project:XcodeProject, file_path:str):
        file = PBXFileReference.create(project, file_path)
        item = PBXBuildFile(project).attach()
        item.data['fileRef'] = file.uuid
        item.fileRef = file
        return item

    def add_attributes(self, attributes:Tuple[str] = ('CodeSignOnCopy', 'RemoveHeadersOnCopy')):
        if 'settings' not in self.data:
            self.data['settings'] = {}
        settings = self.data.get('settings') # type:dict[str, any]
        field_name = 'ATTRIBUTES'
        if field_name not in settings:
            settings[field_name] = []
        attr_list = settings[field_name] # type: list[str]
        for item in attributes:
            if item not in attr_list: attr_list.append(item)

class PBXGroup(PBXObject):
    def __init__(self, project:XcodeProject):
        super(PBXGroup, self).__init__(project)
        self.children = [] # type:list[PBXObject]
        self.path = None # type:str
        self.name = None # type:str
        self.sourceTree = None  # type:str

    def load(self, uuid:str):
        super(PBXGroup, self).load(uuid)
        # real disk folder name
        self.path = self.data.get('path') # type:str
        # virtual folder name in Xcode project
        self.name = self.data.get('name') # type:str
        self.sourceTree = self.data.get('sourceTree')  # type:str
        self.children = []
        for item_uuid in self.data.get('children'):
            data = self.project.get_pbx_object(item_uuid) # type:dict
            item = globals().get(data.get('isa'))(self.project) # type: PBXObject
            item.load(item_uuid)
            self.children.append(item)

    def note(self)->str:
        name = self.path if self.path else self.name
        return '/* {} */'.format(self.trim(name)) if name else ''

    def sync(self, file): # type: (PBXFileReference)->()
        components = self.trim(file.path).split('/')
        parent = self
        while len(components) > 1:
            node = parent.fdir(components[0])
            del components[0]
            parent = node
        if file not in self.children:
            parent.append(file)

    def fdir(self, name:str):
        for item in self.children:
            if isinstance(item, PBXGroup):
                if item.name == name: return item
        item = PBXGroup.create(self.project, name)
        self.append(item)
        return item

    def append(self, item:PBXObject):
        children = self.data.get('children') # type:list[str]
        if item.uuid not in children:
            self.children.append(item)
            children.append(item.uuid)

    @staticmethod
    def create(project:XcodeProject, path:str, source_tree:str = '\"<group>\"'):
        group = PBXGroup(project).attach()
        group.data.update({'name':path, 'sourceTree':source_tree, 'children':[]})
        group.fill()
        return group

class PBXVariantGroup(PBXObject):
    def __init__(self, project:XcodeProject):
        super(PBXVariantGroup, self).__init__(project)
        self.children = [] # type:list[PBXObject]
        self.name = None # type:str
        self.sourceTree = None # type:str

    def note(self)->str:
        return '/* {} */'.format(self.name)

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
        self.project.add_ref_file(self)

    def note(self)->str:
        return '/* {} */'.format(self.trim(self.name if self.name else self.path))

    @staticmethod
    def create(project, file_path): # type: (XcodeProject, str)->PBXFileReference
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
                project.add_ref_file(folder)
                folder.fill()
                return folder
            raise NotImplementedError('not supported file {!r}'.format(file_path))
        ref = PBXFileReference(project)
        data = ref.data = {}
        if '+' in file_name:
            file_name = '"{}"'.format(file_name)
            file_path = '"{}"'.format(file_path)
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
        if project.has_ref_file(ref.path):
            return project.get_ref_file(ref.path)
        else:
            ref.attach()
            project.add_ref_file(ref)
        return ref

class PBXBuildPhase(PBXObject):
    def __init__(self, project:XcodeProject):
        super(PBXBuildPhase, self).__init__(project)
        self.name = None # type: str
        self.runOnlyForDeploymentPostprocessing = None # type: str

    def note(self)->str:
        return '/* {} */'.format(self.trim(self.name))

    def load(self, uuid:str):
        super(PBXBuildPhase, self).load(uuid)
        if 'name' in self.data:
            self.name = self.data.get('name') # type: str
        else:
            type_name = self.__class__.__name__
            self.name = type_name[3:].replace('BuildPhase', '')
        self.runOnlyForDeploymentPostprocessing = self.data.get('runOnlyForDeploymentPostprocessing') # type: str

class PBXSourcesBuildPhase(PBXBuildPhase):
    def __init__(self, project:XcodeProject):
        super(PBXSourcesBuildPhase, self).__init__(project)
        self.files: list[PBXBuildFile] = []

    def load(self, uuid:str):
        super(PBXSourcesBuildPhase, self).load(uuid)
        self.files = []
        for file_uuid in self.data.get('files'):
            file_item = PBXBuildFile(self.project)
            file_item.load(file_uuid)
            file_item.phase = self
            self.files.append(file_item)

    def append(self, item:PBXBuildFile):
        for f in self.files:
            if f.fileRef.uuid == item.fileRef.uuid:
                item.detach()
                return
        files = self.data.get('files') # type:list[str]
        self.files.append(item)
        files.append(item.uuid)
        item.phase = self

class PBXResourcesBuildPhase(PBXSourcesBuildPhase):
    def __init__(self, project:XcodeProject):
        super(PBXResourcesBuildPhase, self).__init__(project)

    def load(self, uuid:str):
        super(PBXResourcesBuildPhase, self).load(uuid)

class PBXShellScriptBuildPhase(PBXBuildPhase):
    def __init__(self, project:XcodeProject):
        super(PBXShellScriptBuildPhase, self).__init__(project)
        self.shellPath = '/usr/bin/sh'
        self.shellScript: str = None
        self.name = '\"Run Script\"'

    def load(self, uuid:str):
        super(PBXShellScriptBuildPhase, self).load(uuid)
        self.shellPath: str = self.data.get('shellPath')
        self.shellScript: str = self.data.get('shellScript')


class PBXCopyFilesBuildPhase(PBXSourcesBuildPhase):
    def __init__(self, project:XcodeProject):
        super(PBXCopyFilesBuildPhase, self).__init__(project)
        self.dstPath = '\"\"'
        self.dstSubfolderSpec = 10 # Frameworks

    def load(self, uuid:str):
        super(PBXCopyFilesBuildPhase, self).load(uuid)
        self.dstPath = self.data.get('dstPath')
        self.dstSubfolderSpec = self.data.get('dstSubfolderSpec')

    @staticmethod
    def create(project:XcodeProject, name:str = None):
        phase = PBXCopyFilesBuildPhase(project).attach()
        phase.data.update({'buildActionMask':'2147483647', 'dstPath':'\"\"', 'dstSubfolderSpec':'10', 'files':[], 'runOnlyForDeploymentPostprocessing':'0'})
        if name: phase.data['name'] = name
        phase.load(phase.uuid)
        return phase

class PBXFrameworksBuildPhase(PBXSourcesBuildPhase):
    def __init__(self, project:XcodeProject):
        super(PBXFrameworksBuildPhase, self).__init__(project)

    def load(self, uuid:str):
        super(PBXFrameworksBuildPhase, self).load(uuid)

class PBXNativeTarget(PBXObject):
    def __init__(self, project:XcodeProject):
        super(PBXNativeTarget, self).__init__(project)
        self.buildConfigurationList = XCConfigurationList(self.project)
        self.buildPhases: list[PBXBuildPhase] = []
        self.productName: str = None
        self.name:str = None

    def note(self)->str:
        return '/* {} */'.format(self.trim(self.name))

    def load(self, uuid:str):
        super(PBXNativeTarget, self).load(uuid)
        self.buildConfigurationList.load(self.data.get('buildConfigurationList'))
        self.buildConfigurationList.target = self
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
        self.buildConfigurations: list[XCBuildConfiguration] = []
        self.target: PBXNativeTarget = None

    @property
    def defaultConfigurationName(self)->str:
        return self.data.get('defaultConfigurationName')

    def note(self):
        note = 'Build configuration list for '
        note += 'PBXNativeTarget {}'.format(self.target.name) if self.target else 'PBXProject'
        return '/* {} */'.format(note)

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

    def note(self)->str:
        return '/* {} */'.format(self.name)

    @property
    def buildSettings(self)->Dict[str, any]:
        return self.data.get('buildSettings')

    def load(self, uuid:str):
        super(XCBuildConfiguration, self).load(uuid)

class FlagsType(enum.Enum):
    compiler, link, cplus = range(3)

class PBXProject(PBXObject):
    def __init__(self, project:XcodeProject):
        super(PBXProject, self).__init__(project)
        self.targets: list[PBXNativeTarget] = []
        self.buildConfigurationList = XCConfigurationList(self.project)
        self.mainGroup = PBXGroup(self.project)

        self.frameworks_phase_build: PBXFrameworksBuildPhase = None
        self.frameworks_phase_embed: PBXCopyFilesBuildPhase = None
        self.resources_phase: PBXResourcesBuildPhase = None
        self.sources_phase: PBXSourcesBuildPhase = None

    def load(self, uuid:str):
        super(PBXProject, self).load(uuid)
        self.targets = []
        self.buildConfigurationList.load(self.data.get('buildConfigurationList'))
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
        if not self.frameworks_phase_embed:
            self.frameworks_phase_embed = PBXCopyFilesBuildPhase.create(self.project, '"Embeded Frameworks"')
            self.targets[0].append_build_phase(self.frameworks_phase_embed)
        assert self.frameworks_phase_embed
        assert self.frameworks_phase_build
        assert self.resources_phase
        assert self.sources_phase

    def add_build_setting(self, field_name:str, field_value:any, config_name:str = None):
        target = self.targets[0]
        for config in target.buildConfigurationList.buildConfigurations:
            if not config_name or config.name == config_name:
                if field_name not in config.buildSettings: config.buildSettings[field_name] = {}
                value = config.buildSettings[field_name]
                if isinstance(value, list):
                    value.append(field_value)
                    self.__unique_array(value)
                else:
                    config.buildSettings[field_name] = field_value

    def embed_framework(self, framework_path:str):
        file = PBXBuildFile.create(self.project, framework_path)
        file.add_attributes()
        self.frameworks_phase_embed.append(file)

    def add_framework(self, framework_path:str, need_sync = True):
        file = PBXBuildFile.create(self.project, framework_path)
        self.frameworks_phase_build.append(file)
        if need_sync:
            self.mainGroup.sync(file.fileRef)

    def add_library(self, library_path:str):
        self.add_framework(library_path)

    def add_entitlements(self, file_path, need_sync = True):
        self.add_build_setting('CODE_SIGN_ENTITLEMENTS', '$PROJECT_DIR/{}'.format(file_path))
        if need_sync:
            file = PBXFileReference.create(self.project, file_path)
            self.mainGroup.sync(file)

    def add_asset(self, file_path:str):
        file_name = os.path.basename(file_path)
        extension = file_name.split('.')[-1]
        file = PBXBuildFile.create(self.project, file_path)
        file_type = file.fileRef.lastKnownFileType
        if extension in ('a', 'tbd', 'framework', 'dylib'):
            file.detach()
            self.add_framework(file_path, need_sync=True)
        elif extension in ('m', 'mm', 'cpp'):
            self.sources_phase.append(file)
            self.mainGroup.sync(file.fileRef)
        elif extension in ('bundle', 'xib', 'png') or file_type.startswith('folder'):
            self.resources_phase.append(file)
            self.mainGroup.sync(file.fileRef)
        elif extension == 'entitlements':
            file.detach()
            self.add_entitlements(file_path, need_sync=False)
            self.mainGroup.sync(file.fileRef)
        else:
            file.detach()
            self.mainGroup.sync(file.fileRef)

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

    def add_flags(self, flags:List[str], flags_type:FlagsType = FlagsType.compiler, config_name:str = None):
        if not flags: return
        if flags_type == FlagsType.compiler:
            field_name = 'OTHER_CFLAGS'
        elif flags_type == FlagsType.link:
            field_name = 'OTHER_LDFLAGS'
        elif flags_type == FlagsType.cplus:
            field_name = 'OTHER_CPLUSPLUSFLAGS'
        else:raise AttributeError('not expect flags with type')
        self.__ensure_array_field(field_name)
        target = self.targets[0]
        for config in target.buildConfigurationList.buildConfigurations:
            if not config_name or config.name == config_name:
                if field_name not in config.buildSettings: config.buildSettings[field_name] = {}
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

    def get_info_plist(self)->str:
        config = self.targets[0].buildConfigurationList.buildConfigurations[0]
        return config.buildSettings.get('INFOPLIST_FILE')

if __name__ == '__main__':
    arguments = argparse.ArgumentParser()
    arguments.add_argument('--pbxproj-path', '-f', required=True)
    arguments.add_argument('--xcmod-path', '-x', required=True)
    options = arguments.parse_args(sys.argv[1:])
    xcode_project = XcodeProject()
    xcode_project.load_pbxproj(file_path=options.pbxproj_path)
    print(xcode_project.dump_pbxproj(True))
    xcode_project.import_xcmod(file_path=options.xcmod_path)