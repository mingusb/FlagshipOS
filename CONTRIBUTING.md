# Contributing

Keep FlagshipOS focused on reproducible environment selection, explicit provisioning and transparent runtime boundaries. The Python CLI has no third-party runtime dependencies.

Before submitting a change:

1. Run `PYTHONPATH=src python3 -m unittest discover -s tests -v` on Linux.
2. Build a wheel with `python3 -m pip wheel --no-deps . --wheel-dir dist` and run `python3 tests/check_wheel.py dist`.
3. For a profile change, verify its official upstream source and content digest, record its limitations, and test the relevant container with harmless local commands.
4. Explain actual runtime evidence separately from catalog validation and unit tests.

Do not add host APT mixing, automatic privilege escalation, embedded credentials, uncontrolled command evaluation, target scanning, exploit chains or challenge payloads. Rootless Distrobox integration must not be represented as a malware isolation boundary.

The manual container workflow is intentionally separate from ordinary CI because it pulls distribution images. Contributor pull requests do not automatically execute imported filesystems or large tool installations.
