"""Native desktop identity for both bundled and Python-launched applications."""
import sys

DISPLAY_NAME = 'HP 48GX Calculator'


def prepare_application_name():
    """Set Cocoa's display identity before Qt creates the native application.

    Keep Qt's applicationName unchanged: it identifies existing saved profiles.
    Bundle metadata changes are in memory only, never in the Python installation.
    """
    if sys.platform == 'win32':
        import ctypes
        shell=ctypes.WinDLL('shell32')
        identity=shell.SetCurrentProcessExplicitAppUserModelID
        identity.argtypes=[ctypes.c_wchar_p];identity.restype=ctypes.c_long
        result=identity('org.hp48g.desktop')
        if result<0:raise OSError(f'Could not set application identity: {result:#x}')
        return
    if sys.platform != 'darwin':
        return
    import ctypes

    ctypes.CDLL('/System/Library/Frameworks/Foundation.framework/Foundation')
    objc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')
    pointer = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.objc_getClass.restype = pointer
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = pointer

    def send(receiver, selector, *arguments, result=pointer):
        signature = ctypes.CFUNCTYPE(result, pointer, pointer, *([pointer] * len(arguments)))
        return signature(('objc_msgSend', objc))(
            receiver, objc.sel_registerName(selector.encode()), *arguments)

    def string(value):
        return send(objc.objc_getClass(b'NSString'), 'stringWithUTF8String:',
                    ctypes.cast(ctypes.c_char_p(value.encode()), pointer))

    pool = send(objc.objc_getClass(b'NSAutoreleasePool'), 'new')
    try:
        name = string(DISPLAY_NAME)
        bundle = send(objc.objc_getClass(b'NSBundle'), 'mainBundle')
        for selector in ('infoDictionary', 'localizedInfoDictionary'):
            info = send(bundle, selector)
            if info:
                for key in ('CFBundleName', 'CFBundleDisplayName'):
                    send(info, 'setObject:forKey:', name, string(key), result=None)
        process = send(objc.objc_getClass(b'NSProcessInfo'), 'processInfo')
        send(process, 'setProcessName:', name, result=None)
    finally:
        send(pool, 'drain', result=None)


def application_icon():
    """One identity for windows, the task switcher, Dock, and tray."""
    from pathlib import Path
    from PySide6.QtGui import QIcon
    assets=Path(__file__).parent/'assets'
    icon=QIcon(str(assets/'hp48gx-icon.ico'))
    icon.addFile(str(assets/'hp48gx-icon.png'))
    return icon
