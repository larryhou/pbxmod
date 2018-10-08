#!/usr/bin/env python3

import shutil, time, re

def backup(file_path:str):
    suffix = time.strftime('_%Y-%m-%d_%H%M%S', time.localtime())
    backup_file_path = re.sub(r'(\.[^.]+)$', r'{}\g<1>'.format(suffix), file_path)
    shutil.copy(file_path, backup_file_path)