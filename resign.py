#!/usr/bin/env python3

import argparse, sys, os, re
import os.path as p

from plist import plistObject

def resign_ipa(ipa_file:str, mobile_provision:str, identity:str, entitlements:str = None):
    assert p.exists(ipa_file)
    assert p.exists(mobile_provision)
    assert identity
    mobile_provision = p.abspath(mobile_provision)
    ipa_file = p.abspath(ipa_file)
    with os.popen('security cms -D -i {}'.format(p.abspath(mobile_provision))) as pipe:
        provision_data = plistObject()
        provision_data.load_bytes(pipe.read().encode('utf-8'))
        print('mobile_provision.Entitlements', provision_data.data.get('Entitlements'))
    xcent_data = provision_data.data.get('Entitlements') # type: dict[str, any]
    if entitlements and p.exists(entitlements):
        entitlements_data = plistObject()
        entitlements_data.load(file_path=entitlements)
        xcent_data.update(entitlements_data.data)
    xcent_plist = plistObject()
    xcent_plist.data.update(xcent_data)
    xcent_path = p.abspath('app.xcent')
    xcent_plist.save(file_path=xcent_path)
    print(xcent_plist.dump())
    os.system('rm -fr temp && mkdir temp')
    os.chdir('temp')
    if p.exists('Payload'): os.system('rm -fr Payload')
    assert os.system('unzip -o {!r}'.format(ipa_file)) == 0
    app_path = os.popen('find Payload -maxdepth 1 -iname \'*.app\' | head -n 1').read() # type:str
    app_path = app_path.split('\n')[0]
    app_name = re.sub(r'\.[^.]+$', '', p.basename(ipa_file))
    assert app_path
    script = open(p.abspath('resign_ipa.sh'), 'w+')
    script.write('#!/usr/bin/env bash\n')
    script.write('rm -fr {}/_CodeSignature\n'.format(app_path))
    script.write('cp -fv {!r} {}/embedded.mobileprovision\n'.format(mobile_provision, app_path))
    pipe = os.popen('find {} \\( -iname "*.framework" -o -iname "*.dylib" \\)'.format(app_path))
    for library_item in pipe.readlines():
        script.write('codesign -v -f -s {!r} {!r}\n'.format(identity, library_item[:-1]))
    script.write('codesign -v -f -s {!r} --entitlements={!r} --timestamp=none {!r}\n'.format(identity, xcent_path, app_path))
    script.write('codesign -d --entitlements - {!r}\n'.format(app_path))
    script.write('zip -yr {}_resign.ipa Payload\n'.format(app_name))
    script.seek(0)
    print(script.read())
    script.close()
    assert os.system('bash -x {!r}'.format(script.name)) == 0
    os.system('cd .. && rm -fr temp')

if __name__ == '__main__':
    arguments = argparse.ArgumentParser()
    arguments.add_argument('--mobile-provision', '-p')
    arguments.add_argument('--sign-identity', '-i')
    arguments.add_argument('--list-identity', '-l', action='store_true')
    arguments.add_argument('--entitlements', '-t')
    arguments.add_argument('--ipa-file', '-f')
    options = arguments.parse_args(sys.argv[1:])
    if options.list_identity:
        print(os.popen('security find-identity -p codesigning -v').read())
    else:
        resign_ipa(ipa_file=options.ipa_file,
                   mobile_provision=options.mobile_provision,
                   identity=options.sign_identity,
                   entitlements=options.entitlements)
