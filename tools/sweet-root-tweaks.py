#!/usr/bin/env python3
"""Apply the SWEET bring-up changes to an iOS root made by tools/mkiosroot.sh.

  sudo sweet-root-tweaks.py MOUNTED_ROOT [--hal-plugin DIR]

MOUNTED_ROOT is the HFS+ image mounted read-write (Linux: run
`fsck.hfsplus -fy` on the image, then `mount -t hfsplus -o loop,force`).
Run as root (it writes root/mobile owned files). Idempotent. Everything is
reversible: launchd.plist is backed up as launchd.plist.orig, VirtualAudio is
moved to HAL.disabled, the rest only adds preference keys. This is what
turned the plain mkiosroot.sh output into the images that reach the home
screen (image versions v8-v14 in NOTES.md):

  launchd.plist   _PanicOnCrash -> _PanicOnCrasX (a crashing daemon must not
                  panic the system); CommCenter jobs removed (no baseband: it
                  crash-loops and Setup blocks on its CoreTelephony XPC);
                  fairplayd.H2 and bluetoothd jobs removed (no FairPlay keys,
                  no Bluetooth chip: on the J7 they relaunched 20 and 18
                  times in the first 8 minutes of every boot)
  containers      /private/var/containers/{Bundle,Data/System,Shared/SystemGroup,Temp}
                  (on iOS they live on the data volume)
  migration       LastSystemVersion so DataMigration does not run for an hour
                  on every boot
  audio           VirtualAudio HAL plug-in disabled (mediaserverd crash);
                  with --hal-plugin DIR (on7xelte, xnu 0158) instead the
                  RedwoodAudio plug-in from DIR (RedwoodAudio + RedwoodAudio.plist,
                  tools/RedwoodAudio) is installed as
                  /System/Library/Audio/Plug-Ins/HAL/RedwoodAudio.driver and
                  VirtualAudio stays (or is moved back from HAL.disabled): it
                  finds the "Speaker" device it wants there
  MediaToolbox    StartRecorderServer=false (camera filter prewarm calls a
                  NULL OpenGL function without a GPU -> mediaserverd crash loop)
  SpringBoard     BKNoWatchdogs (one slow CPU path, no scene-create watchdog
                  kills), no cloud-configuration UI
  Setup           skipped: SetupDone, SetupFinishedAllSteps, SetupVersion 11,
                  mini-buddy flags off
  activation      mobileactivationd data ark seeded; the actual Activated state
                  comes from its Hactivation branch, selected by the /chosen
                  security-status properties in tools/mkadt.py
"""
import glob, os, plistlib, shutil, sys

BUILD, VERSION = '20H392', '16.7.16'
MOBILE = 501
# Jobs that only crash-loop without the hardware they drive, by program name.
# Copy launchd.plist.orig back over launchd.plist to bring them back.
DISABLED_PROGRAMS = ('fairplayd.H2', 'bluetoothd')


def load(path):
    with open(path, 'rb') as f:
        return plistlib.load(f)


def save(path, data, uid, gid, mode, fmt=plistlib.FMT_BINARY):
    with open(path, 'wb') as f:
        plistlib.dump(data, f, fmt=fmt)
    os.chown(path, uid, gid)
    os.chmod(path, mode)


def merge_pref(root, name, values):
    """Merge keys into /var/mobile/Library/Preferences/NAME.plist (mobile, 0600)."""
    path = os.path.join(root, 'private/var/mobile/Library/Preferences', name + '.plist')
    data = load(path) if os.path.exists(path) else {}
    data.update(values)
    save(path, data, MOBILE, MOBILE, 0o600)
    print('pref', name, sorted(values))


def launchd(root):
    path = os.path.join(root, 'System/Library/xpc/launchd.plist')
    st = os.stat(path)
    # Nothing is deleted for good: the untouched plist stays next to the
    # active one (copy it back to re-enable CommCenter and _PanicOnCrash).
    orig = path + '.orig'
    if not os.path.exists(orig):
        shutil.copy2(path, orig)
        os.chown(orig, st.st_uid, st.st_gid)
        print('backup', orig)
    plist = load(path)
    jobs = plist['LaunchDaemons']
    renamed = 0
    for job in jobs.values():
        if '_PanicOnCrash' in job:
            job['_PanicOnCrasX'] = job.pop('_PanicOnCrash')
            renamed += 1
    removed = [k for k, j in jobs.items() if j.get('Label') == 'com.apple.CommCenter']
    for k in removed:
        del jobs[k]

    def program(job):
        p = job.get('Program') or (job.get('ProgramArguments') or [''])[0]
        return os.path.basename(p)
    off = [k for k, j in jobs.items() if program(j) in DISABLED_PROGRAMS]
    for k in off:
        print('disabled job', jobs[k].get('Label'), program(jobs[k]))
    missing = set(DISABLED_PROGRAMS) - {program(jobs[k]) for k in off}
    if missing:  # already removed by an earlier run, or renamed in this iOS
        print('warning: no job runs', sorted(missing))
    for k in off:
        del jobs[k]
    save(path, plist, st.st_uid, st.st_gid, st.st_mode & 0o7777)
    print(f'launchd.plist: {renamed} _PanicOnCrash renamed, {len(removed)} CommCenter jobs removed, '
          f'{len(off)} jobs disabled')


def containers(root):
    base = os.path.join(root, 'private/var/containers')
    for sub, uid in (('Bundle', 33), ('Data/System', 0), ('Shared/SystemGroup', 0), ('Temp', 0)):
        d = os.path.join(base, sub)
        if not os.path.isdir(d):
            os.makedirs(d)
            os.chown(d, uid, uid)
            os.chmod(d, 0o755)
            print('mkdir', d)


def find_container(root, kind, identifier):
    for meta in glob.glob(os.path.join(root, 'private/var/containers', kind, '*',
                                       '.com.apple.mobile_container_manager.metadata.plist')):
        if load(meta).get('MCMMetadataIdentifier') == identifier:
            return os.path.dirname(meta)
    return None


def activation(root):
    c = find_container(root, 'Data/System', 'com.apple.mobileactivationd')
    if c is None:
        print('warning: no mobileactivationd system container in the image; skipped data ark')
        return
    d = os.path.join(c, 'Library/internal')
    os.makedirs(d, exist_ok=True)
    os.chown(d, MOBILE, MOBILE)
    os.chmod(d, 0o755)
    save(os.path.join(d, 'data_ark.plist'), {
        '-ActivationState': 'Activated', '-BrickState': False,
        '-BuildVersion': BUILD, '-ProductVersion': VERSION,
        '-DataMigrationCompleted': True, '-PreSydroDataMigrationCompleted': True,
    }, MOBILE, MOBILE, 0o600)
    print('data ark', d)


def hal_plugin(root, plugdir):
    drv = os.path.join(root, 'System/Library/Audio/Plug-Ins/HAL/RedwoodAudio.driver')
    os.makedirs(drv, exist_ok=True)
    os.chown(drv, 0, 0)
    os.chmod(drv, 0o755)
    exe = os.path.join(drv, 'RedwoodAudio')
    shutil.copyfile(os.path.join(plugdir, 'RedwoodAudio'), exe)
    os.chown(exe, 0, 0)
    os.chmod(exe, 0o755)
    info = os.path.join(drv, 'Info.plist')
    shutil.copyfile(os.path.join(plugdir, 'RedwoodAudio.plist'), info)
    os.chown(info, 0, 0)
    os.chmod(info, 0o644)
    print('RedwoodAudio.driver installed')
    src = os.path.join(root, 'Library/Audio/Plug-Ins/HAL.disabled/VirtualAudio.plugin')
    dst = os.path.join(root, 'Library/Audio/Plug-Ins/HAL/VirtualAudio.plugin')
    if os.path.exists(src) and not os.path.exists(dst):
        shutil.move(src, dst)
        print('VirtualAudio.plugin enabled again')


def audio(root, plugdir=None):
    src = os.path.join(root, 'Library/Audio/Plug-Ins/HAL/VirtualAudio.plugin')
    dst_dir = os.path.join(root, 'Library/Audio/Plug-Ins/HAL.disabled')
    if plugdir:
        hal_plugin(root, plugdir)
    elif os.path.exists(src):
        os.makedirs(dst_dir, exist_ok=True)
        shutil.move(src, dst_dir)
        print('VirtualAudio.plugin disabled')
    for conf in glob.glob(os.path.join(root, 'System/Library/Frameworks/MediaToolbox.framework/*/SubServerConfiguration.plist')):
        st = os.stat(conf)
        data = load(conf)
        data['StartRecorderServer'] = False
        save(conf, data, st.st_uid, st.st_gid, st.st_mode & 0o7777, plistlib.FMT_XML)
        print('StartRecorderServer off', os.path.relpath(conf, root))


def main():
    args = sys.argv[1:]
    plugdir = None
    if len(args) == 3 and args[1] == '--hal-plugin':
        plugdir = args[2]
        args = args[:1]
    if len(args) != 1 or not os.path.isdir(os.path.join(args[0], 'System/Library/xpc')):
        sys.exit(__doc__)
    root = args[0]
    launchd(root)
    containers(root)
    activation(root)
    audio(root, plugdir)
    merge_pref(root, 'com.apple.migration', {
        'LastSystemVersion': BUILD,
        'DMUserDataDisposition': {'SyntheticDidUpgrade': False, 'buildVersion': BUILD}})
    merge_pref(root, 'com.apple.springboard', {
        'BKNoWatchdogs': True,
        'FBLaunchWatchdogExceptions': {'com.apple.purplebuddy': 100.0},
        'MCForceShowCloudConfigurationUI': False})
    merge_pref(root, 'com.apple.purplebuddy', {
        'SetupDone': True, 'SetupFinishedAllSteps': True, 'SetupVersion': 11,
        'daemonizeNeedsToRun': False})
    merge_pref(root, 'com.apple.purplebuddy.notbackedup', {
        k: False for k in ('ShouldRunDiagnosticsMiniBuddy', 'ShouldRunHSA2MiniBuddy',
                           'ShouldRunKeychainSyncMiniBuddy', 'ShouldRunMesaMiniBuddy',
                           'ShouldRunPaymentMiniBuddy', 'ShouldRunStandardMiniBuddy',
                           'SilentICDPUpgrade')})
    merge_pref(root, 'com.apple.managedconfiguration.notbackedup', {
        'LockdownActivationIndicatesCloudConfigurationAvailable': False})


if __name__ == '__main__':
    main()
