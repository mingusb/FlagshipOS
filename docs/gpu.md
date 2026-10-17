# NVIDIA GPU checks on WSL

Flagship can connect the Windows-provided WSL CUDA driver to each managed environment. GPU support remains specific to an API and application: a working CUDA application does not establish working OpenCL, graphics, video encoding or every upstream tool.

## Setup and diagnosis

On a WSL host with `/dev/dxg` and the NVIDIA libraries under `/usr/lib/wsl`, newly created environments receive the connection automatically. Existing environments can be updated individually:

```bash
flagship gpu parrot --setup
flagship gpu parrot --json
flagship run parrot -- hashcat -I
```

Repeat the first two commands for each installed profile. Without `--setup`, the command performs checks without installing packages. `--dry-run gpu parrot --setup` describes the operation without contacting a container. The usual managed-container ownership and mount checks apply.

The setup links the existing read-only WSL driver files into the environment and refreshes its library loader. If Hashcat is installed and lacks its NVRTC compiler library, setup first tries the collection's `libnvrtc` runtime package with package removals disabled. When no such package is available, it uses NVIDIA's own NVRTC 12.4.127 redistributable, pinned to the size and SHA-256 in the [official CUDA 12.4.1 manifest](https://developer.download.nvidia.com/compute/cuda/redist/redistrib_12.4.1.json). Its files and license remain under `/opt/flagship/nvrtc-12.4.127`; no foreign distribution repository is added.

Setup supplies the unversioned loader name required by packaged Hashcat builds and repairs ownership of the managed home's standard application directories, without recursively changing their contents. It does not install a Linux NVIDIA display or kernel driver. Existing conflicting paths cause an explicit failure instead of replacement. Network access is needed when a runtime is missing.

NVIDIA documents that WSL receives its CUDA driver from Windows and warns against installing a Linux GPU driver inside WSL. See the [CUDA on WSL guide](https://docs.nvidia.com/cuda/wsl-user-guide/index.html).

## What a passing check establishes

The CUDA check opens a context on each visible device, allocates 4 KiB of device memory, fills it with a known value, copies it back and compares every word before freeing the memory. The report includes device names, memory sizes and the driver API version. Its exit status reflects this bounded CUDA test.

OpenCL enumeration is reported separately, including errors and the actual GPU devices returned by the installed OpenCL loader. An empty GPU list does not mean CUDA failed. Conversely, `nvidia-smi` output alone does not establish either application compatibility or OpenCL support.

For an installed application, use its device-information command and retain the result. Hashcat's `-I`, John's `--list=opencl-devices` when supported by that build, and `clinfo -l` are discovery checks. They do not test cracking workloads, performance or all application features. A missing application is reported as absent; Flagship does not substitute another collection's binary for a profile-specific check.

The [validation record](validation.md) distinguishes actual device checks from pending environments and untested application behavior. There is no claim that every GPU tool in all seven collections works under WSL.

The [six-environment device report](evidence/2026-10-17/gpu-six-collections.json) preserves actual CUDA memory checks and application device listings with their original timestamps and source hashes:

| Collection | CUDA memory test | Hashcat GPU discovery | OpenCL GPU discovery |
| --- | --- | --- | --- |
| Kali | Passed | RTX A5000 found through CUDA | No GPU |
| Parrot | Passed | RTX A5000 found through CUDA | No GPU |
| REMnux | Passed | Hashcat absent | No GPU |
| BackBox | Passed | RTX A5000 found through CUDA | No GPU |
| CAINE | Passed | Bundled 5.1.0 fails: no OpenCL platform | No GPU |
| Tsurugi | Passed | RTX A5000 found through CUDA | No GPU |
| SIFT | Pending full installation | Not yet checked | Not yet checked |

The installed John commands did not provide a working OpenCL-device listing. CAINE's older Hashcat is an explicit compatibility failure, even though the CUDA memory test passes there. These are discovery and memory checks, not application workload or performance tests.
