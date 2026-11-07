"""Cross-process account transaction ownership, retained while the game bridge is detached for restart."""
from contextlib import contextmanager
import ctypes

NAME = r'Local\REA_ACCOUNT_OPERATION_emulator_5554'


def _kernel():
    """Declare pointer-sized mutex handles explicitly on 64-bit Windows."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    kernel.OpenMutexW.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    return kernel


def ensure_account_available():
    """Block new ordinary helper connections during account file replacement; permit the owner's same thread."""
    kernel = _kernel()
    handle = kernel.OpenMutexW(0x100001, False, NAME)
    if not handle:
        return
    try:
        result = kernel.WaitForSingleObject(handle, 0)
        if result in (0, 0x80):
            kernel.ReleaseMutex(handle)
        if result != 0:
            raise RuntimeError('另一个账号切换尚未完成，请等待，或通过账号管理重新恢复票据')
    finally:
        kernel.CloseHandle(handle)


@contextmanager
def account_operation():
    """Hold ownership across stop/write/start and native authentication, including periods without a Frida bridge."""
    kernel = _kernel()
    handle = kernel.CreateMutexW(None, False, NAME)
    if not handle:
        raise RuntimeError('无法取得账号操作权限')
    acquired = False
    try:
        acquired = kernel.WaitForSingleObject(handle, 0) in (0, 0x80)
        if not acquired:
            raise RuntimeError('已有账号保存或切换正在进行，请稍后重试')
        yield
    finally:
        if acquired:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)
