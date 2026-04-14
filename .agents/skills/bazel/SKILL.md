---
name: bazel
description: How to work with this project's Bazel-based build system.
---

# bazel

Note: All relative paths are relative to the root directory of this repository.

## Always use Bazelisk, not Bazel

Always run `bazelisk` via the vendored binary at `./bazelisk/linux/amd64`.
Never attempt to invoke a global `bazel` CLI tool. It doesn't exist.

## Build everything

```
./bazelisk/linux/amd64 build //...
```
