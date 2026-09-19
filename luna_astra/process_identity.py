"""Read-only process existence/creation identity; no signal that stops a process.

ALIVE is existence, not progress. UNKNOWN is never treated as EXITED. Only the
original process identity is checked; this is not a descendant-process census.
"""
from __future__ import annotations
import re
import os
from pathlib import Path
import sys


def probe(pid, expected=None):
    result={'pid':pid,'state':'UNKNOWN','identity':None,'reason':'invalid_or_missing_pid'}
    if type(pid) is not int or not 0<pid<2**31:return result
    if expected is not None:
        grammar=(r'win:[0-9]{1,20}' if os.name=='nt' else
                 r'linux:[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}:[0-9]{1,24}'
                 if sys.platform.startswith('linux') else None)
        if not isinstance(expected,str) or grammar is None or not re.fullmatch(grammar,expected):
            return {**result,'reason':'invalid_or_unsupported_creation_identity'}
    try:
        if os.name=='nt':
            import ctypes
            from ctypes import wintypes
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
            kernel.OpenProcess.restype=wintypes.HANDLE
            kernel.CloseHandle.argtypes=[wintypes.HANDLE]
            kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
            kernel.WaitForSingleObject.restype=wintypes.DWORD
            kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
            kernel.GetProcessTimes.restype=wintypes.BOOL
            handle=kernel.OpenProcess(0x00100000|0x1000,False,pid)
            if not handle:
                error=ctypes.get_last_error()
                if error==87:return {**result,'state':'EXITED','reason':'no_such_process'}
                return {**result,'reason':'process_query_denied_or_failed'}
            try:
                wait=kernel.WaitForSingleObject(handle,0)
                if wait==0:return {**result,'state':'EXITED','reason':'process_handle_signalled'}
                if wait!=258:return {**result,'reason':'process_wait_query_failed'}
                times=[wintypes.FILETIME() for _ in range(4)]
                if not kernel.GetProcessTimes(handle,*[ctypes.byref(t) for t in times]):
                    return {**result,'reason':'creation_time_unavailable'}
                identity='win:'+str((times[0].dwHighDateTime<<32)|times[0].dwLowDateTime)
            finally:kernel.CloseHandle(handle)
        elif sys.platform.startswith('linux'):
            try:
                text=(Path('/proc')/str(pid)/'stat').read_text()
            except FileNotFoundError:
                # A hidden/unmounted procfs is not proof that a process exited.
                os.kill(pid,0)
                return {**result,'reason':'procfs_identity_unavailable'}
            fields=text.rsplit(')',1)[1].split()
            if fields[0] in {'Z','X','x'}:
                return {**result,'state':'EXITED','reason':'exited_or_zombie'}
            boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
            identity='linux:'+boot+':'+fields[19]
        else:
            os.kill(pid,0)
            if expected is not None:return {**result,'reason':'creation_identity_not_supported'}
            return {**result,'state':'ALIVE','reason':'pid_exists_identity_unavailable'}
        if expected is not None and identity!=expected:
            return {**result,'state':'EXITED','identity':identity,'reason':'original_process_replaced'}
        return {**result,'state':'ALIVE','identity':identity,'reason':'process_exists_not_progress'}
    except ProcessLookupError:
        return {**result,'state':'EXITED','reason':'no_such_process'}
    except (OSError,ValueError,IndexError,AttributeError):
        return {**result,'reason':'process_observation_unavailable'}
