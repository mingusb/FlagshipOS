"""Expose the existing Windows-provided CUDA driver to WSL Distrobox guests."""

import base64
import json
import os
from pathlib import Path
import platform


# Distrobox already shares the host filesystem at /run/host. WSL provides these
# driver files read-only; link to them without copying or replacing GPU drivers.
# Check every destination before writing anything. This same idempotent hook can
# migrate an existing managed container through `flagship run ... -- sudo sh -c`.
WSL_GPU_SCRIPT = r'''
set -eu
host=/run/host/usr/lib/wsl
target=/usr/lib/wsl
config=/etc/ld.so.conf.d/00-flagship-wsl-gpu.conf
launcher=/usr/local/bin/nvidia-smi
fail() { printf 'Flagship WSL GPU: %s\n' "$1" >&2; exit 1; }
[ -c /dev/dxg ] || fail 'The WSL GPU device is unavailable.'
[ -r "$host/lib/libcuda.so.1" ] && [ -x "$host/lib/nvidia-smi" ] || fail 'The Windows-provided WSL driver is unavailable.'
if [ -L "$target" ]; then
    [ "$(readlink "$target")" = "$host" ] || fail 'An unrelated /usr/lib/wsl link already exists.'
elif [ -e "$target" ]; then
    fail 'An existing /usr/lib/wsl directory requires review; no files were replaced.'
fi
if [ -L "$config" ]; then
    fail 'The loader configuration is an unrelated symbolic link.'
elif [ -e "$config" ]; then
    [ -f "$config" ] && [ "$(cat "$config")" = '/usr/lib/wsl/lib' ] || fail 'The existing loader configuration differs.'
fi
if [ -L "$launcher" ]; then
    [ "$(readlink "$launcher")" = '/usr/lib/wsl/lib/nvidia-smi' ] || fail 'An unrelated nvidia-smi launcher exists.'
elif [ -e "$launcher" ]; then
    fail 'An existing nvidia-smi launcher requires review; no files were replaced.'
fi
command -v ldconfig >/dev/null || fail 'ldconfig is required.'
[ -L "$target" ] || ln -s "$host" "$target"
if [ ! -e "$config" ]; then
    printf '%s\n' '/usr/lib/wsl/lib' > "$config"
    chmod 644 "$config"
fi
mkdir -p /usr/local/bin
[ -L "$launcher" ] || ln -s /usr/lib/wsl/lib/nvidia-smi "$launcher"
ldconfig
printf '%s\n' 'Flagship connected the Windows-provided WSL GPU driver. Per-tool GPU support still requires verification.'
'''

# Hashcat's packaged build dynamically opens the unversioned NVRTC development
# name. Prefer the distribution's compiler runtime when this application is
# present; never install a display/kernel driver or remove collection tools.
HASHCAT_RUNTIME_SCRIPT = r'''
set -eu
command -v hashcat >/dev/null 2>&1 || exit 0
target=/usr/lib/x86_64-linux-gnu/libnvrtc.so
[ -e "$target" ] && exit 0
if [ -L "$target" ]; then
    printf '%s\n' 'Flagship GPU: an existing NVRTC link is broken; review it before continuing.' >&2
    exit 1
fi
runtime_path() { ldconfig -p | awk '/libnvrtc\.so\.[0-9]+ .*x86-64/ { print $NF; exit }'; }
library=$(runtime_path)
if [ -z "$library" ]; then
    apt-get update
    package=$(apt-cache pkgnames libnvrtc | awk '/^libnvrtc[0-9]+([.][0-9]+)*$/' | sort -V | tail -n 1)
    case "$package" in libnvrtc[0-9]*) ;; *) exit 77 ;; esac
    DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-remove --no-install-recommends "$package"
    library=$(runtime_path)
fi
library=$(readlink -f "$library")
case "$library" in /usr/lib/x86_64-linux-gnu/*) ;; *) printf '%s\n' 'Flagship GPU: NVRTC library location requires review.' >&2; exit 1 ;; esac
[ -f "$library" ]
ln -s "$library" "$target"
printf '%s\n' 'Flagship connected the distribution NVRTC runtime for Hashcat device discovery.'
'''

DEVICE_PROBE = r'''
import ctypes as c
import json
import shutil
r = {'scope': 'CUDA device discovery and a 4 KiB device-memory round trip; OpenCL GPU enumeration, not all application functionality',
     'cuda': {'passed': False, 'devices': []}, 'opencl': {'gpu_devices': []},
     'tools': {name: shutil.which(name) for name in ('nvidia-smi', 'hashcat', 'john', 'clinfo')}}
def checked(library, name, types, *args):
    fn = getattr(library, name)
    fn.argtypes, fn.restype = types, c.c_int
    result = fn(*args)
    if result:
        raise RuntimeError(name + ' returned ' + str(result))
try:
    cuda = c.CDLL('libcuda.so.1')
    checked(cuda, 'cuInit', [c.c_uint], 0)
    version, count = c.c_int(), c.c_int()
    checked(cuda, 'cuDriverGetVersion', [c.POINTER(c.c_int)], c.byref(version))
    checked(cuda, 'cuDeviceGetCount', [c.POINTER(c.c_int)], c.byref(count))
    r['cuda']['driver_api_version'] = version.value
    for index in range(count.value):
        device, name, memory = c.c_int(), c.create_string_buffer(256), c.c_size_t()
        checked(cuda, 'cuDeviceGet', [c.POINTER(c.c_int), c.c_int], c.byref(device), index)
        checked(cuda, 'cuDeviceGetName', [c.c_void_p, c.c_int, c.c_int], name, len(name), device)
        checked(cuda, 'cuDeviceTotalMem_v2', [c.POINTER(c.c_size_t), c.c_int], c.byref(memory), device)
        context, pointer = c.c_void_p(), c.c_uint64()
        try:
            checked(cuda, 'cuCtxCreate_v2', [c.POINTER(c.c_void_p), c.c_uint, c.c_int], c.byref(context), 0, device)
            checked(cuda, 'cuMemAlloc_v2', [c.POINTER(c.c_uint64), c.c_size_t], c.byref(pointer), 4096)
            checked(cuda, 'cuMemsetD32_v2', [c.c_uint64, c.c_uint, c.c_size_t], pointer, 0x12345678, 1024)
            copied = (c.c_uint32 * 1024)()
            checked(cuda, 'cuMemcpyDtoH_v2', [c.c_void_p, c.c_uint64, c.c_size_t], copied, pointer, 4096)
            if any(value != 0x12345678 for value in copied):
                raise RuntimeError('GPU device-memory round trip returned different bytes')
            r['cuda']['devices'].append({'ordinal': index, 'name': name.value.decode(), 'memory_bytes': memory.value,
                                         'device_memory_round_trip_bytes': 4096, 'passed': True})
        finally:
            if pointer.value:
                checked(cuda, 'cuMemFree_v2', [c.c_uint64], pointer)
            if context.value:
                checked(cuda, 'cuCtxDestroy_v2', [c.c_void_p], context)
    r['cuda']['passed'] = bool(r['cuda']['devices'])
except (OSError, RuntimeError, AttributeError) as error:
    r['cuda']['error'] = str(error)
try:
    cl = c.CDLL('libOpenCL.so.1')
    count = c.c_uint()
    checked(cl, 'clGetPlatformIDs', [c.c_uint, c.c_void_p, c.POINTER(c.c_uint)], 0, None, c.byref(count))
    platforms = (c.c_void_p * count.value)()
    checked(cl, 'clGetPlatformIDs', [c.c_uint, c.c_void_p, c.c_void_p], count, platforms, None)
    for platform_id in platforms:
        count = c.c_uint()
        fn = cl.clGetDeviceIDs
        fn.argtypes, fn.restype = [c.c_void_p, c.c_ulonglong, c.c_uint, c.c_void_p, c.c_void_p], c.c_int
        result = fn(platform_id, 4, 0, None, c.byref(count))
        if result == -1:
            continue
        if result:
            raise RuntimeError('clGetDeviceIDs returned ' + str(result))
        devices = (c.c_void_p * count.value)()
        if fn(platform_id, 4, count, devices, None):
            raise RuntimeError('clGetDeviceIDs enumeration failed')
        for device in devices:
            row = {}
            for label, attribute in (('name', 0x102B), ('vendor', 0x102C)):
                value = c.create_string_buffer(1024)
                checked(cl, 'clGetDeviceInfo', [c.c_void_p, c.c_uint, c.c_size_t, c.c_void_p, c.c_void_p],
                        device, attribute, len(value), value, None)
                row[label] = value.value.decode()
            r['opencl']['gpu_devices'].append(row)
except (OSError, RuntimeError, AttributeError) as error:
    r['opencl']['error'] = str(error)
print('FLAGSHIP_GPU_JSON=' + json.dumps(r))
'''


def host_available():
    """Detect the WSL driver interface, without claiming application support."""
    return ("microsoft" in platform.release().lower()
            and Path("/dev/dxg").is_char_device()
            and Path("/usr/lib/wsl/lib/libcuda.so.1").is_file()
            and Path("/usr/lib/wsl/lib/nvidia-smi").is_file())


def setup_hook(with_runtime=False):
    # Distrobox embeds hook strings inside a second double-quoted shell parse.
    payload = base64.b64encode(WSL_GPU_SCRIPT.encode()).decode("ascii")
    hook = "printf %s " + payload + " | base64 --decode | sh"
    if with_runtime:
        from . import gpu_nvrtc
        distribution = base64.b64encode(HASHCAT_RUNTIME_SCRIPT.encode()).decode('ascii')
        vendor = base64.b64encode(Path(gpu_nvrtc.__file__).read_bytes()).decode('ascii')
        coordinator = ('set -eu\nif printf %s ' + distribution + ' | base64 --decode | sh; then exit 0; else result=$?; fi\n'
                       + '[ "$result" -eq 77 ] || exit "$result"\n'
                       + 'printf %s ' + vendor + ' | base64 --decode | python3\n')
        payload = base64.b64encode(coordinator.encode()).decode("ascii")
        hook += " && printf %s " + payload + " | base64 --decode | sh"
    return hook


def main(ctx, profile, setup=False, as_json=False):
    from . import cli as core
    from . import integration
    if ctx.dry_run:
        print(json.dumps({'profile': profile, 'setup': setup,
                          'scope': 'WSL host-driver bridge; distribution or verified NVIDIA NVRTC runtime when Hashcat is present; CUDA/OpenCL checks'}))
        return 0
    core.require_runtime()
    core.managed_container(ctx, profile)
    if setup:
        if not host_available():
            raise core.CommandError('GPU setup requires an NVIDIA-capable WSL host with its Windows-provided driver.')
        with core.state_lock(ctx):
            core.managed_container(ctx, profile)
            hook = integration.home_directory_hook(ctx.home(profile), os.getuid(), os.getgid())
            hook += ' && ' + setup_hook(with_runtime=True)
            arguments = core.enter_argv(profile, ['sudo', 'sh', '-c', hook])
            if as_json:
                core.capture(arguments)
            else:
                core.checked_stream(arguments)
    result = core.capture(core.enter_argv(profile, ['python3', '-c', DEVICE_PROBE]), check=False)
    lines = [line for line in result.stdout.splitlines() if line.startswith('FLAGSHIP_GPU_JSON=')]
    if result.returncode or len(lines) != 1:
        raise core.CommandError('GPU probe did not return a valid report: ' + result.stderr.strip())
    report = json.loads(lines[0].partition('=')[2])
    report['profile'] = profile
    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print(profile + ': ' + ('CUDA check passed' if report['cuda']['passed'] else 'CUDA check failed'))
        for device in report['cuda']['devices']:
            print('  ' + device['name'] + ' (' + str(device['memory_bytes'] // (1024 ** 2)) + ' MiB); 4 KiB GPU-memory round trip passed')
        if report['cuda'].get('error'):
            print('  ' + report['cuda']['error'])
        print('OpenCL GPU devices: ' + str(len(report['opencl']['gpu_devices'])))
        print('This does not certify every GPU application; CUDA and OpenCL support are separate.')
    return 0 if report['cuda']['passed'] else 1
