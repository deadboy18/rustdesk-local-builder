"""
orchestrator.py — actually run a build on this machine.

It mirrors the GitHub Actions workflows step-for-step, but as local subprocess
calls with live log streaming. A single Build drives one run: it checks out the
RustDesk source at the chosen tag, generates the flutter_rust_bridge code,
applies customizations (via customize.py), builds the selected targets, writes
the base64 custom_.txt, and collects artifacts into an output folder.

Nothing here needs the network *at import time* — the heavy toolchains
(Rust/Flutter/vcpkg/NDK) are invoked only when a build is actually started.

Set dry_run=True to print the exact command plan without executing anything —
useful to preview a build, or to inspect it on a machine without the toolchains.
"""

import os
import shutil
import subprocess
import sys
import threading
import time
import platform as _platform

from . import customize, detect

RUSTDESK_REPO = "https://github.com/rustdesk/rustdesk.git"

# toolchain versions (match the workflows / SKILL.md)
RUST_VERSION = "1.75"
FLUTTER_VERSION = "3.24.5"


def _cargo_bin():
    return os.path.join(os.path.expanduser("~"), ".cargo", "bin")


def _force_rmtree(path):
    """Remove a tree even if it has read-only files (Windows .git objects)."""
    import stat

    def _onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass
    shutil.rmtree(path, onerror=_onerror)


class BuildCancelled(Exception):
    pass


class Build:
    def __init__(self, version, target_ids, config, workspace,
                 log=None, dry_run=False):
        self.version = version.lstrip("v")
        self.target_ids = target_ids
        self.config = config
        self.workspace = os.path.abspath(workspace)
        self._log = log or (lambda m: print(m))
        self.dry_run = dry_run
        self.cancel_event = threading.Event()

        self.src_dir = os.path.join(self.workspace, "rustdesk-src")
        self.out_dir = os.path.join(self.workspace, "output", f"v{self.version}")
        self.patches_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "patches"))
        self.host = detect.host_info()
        self.artifacts = []

    # -- logging / cancel ---------------------------------------------------
    def log(self, msg=""):
        self._log(msg)

    def cancel(self):
        self.cancel_event.set()

    def _check_cancel(self):
        if self.cancel_event.is_set():
            raise BuildCancelled()

    # -- subprocess with streaming -----------------------------------------
    def _effective_path(self):
        """PATH the build should see: cargo's bin dir + whatever we inherited
        (which already includes any locally-installed .toolchains via env.json)."""
        parts = [p for p in (_cargo_bin(),) if os.path.isdir(p)]
        parts.append(os.environ.get("PATH", ""))
        return os.pathsep.join(parts)

    def run(self, cmd, cwd=None, env=None, shell=False, check=True):
        pretty = cmd if isinstance(cmd, str) else " ".join(cmd)
        self.log(f"$ {pretty}")
        if self.dry_run:
            return 0
        self._check_cancel()
        full_env = os.environ.copy()
        full_env["PATH"] = self._effective_path()
        if env:
            full_env.update(env)

        # Resolve the executable so Windows finds .exe/.bat/.cmd (via PATHEXT)
        # and tools in ~/.cargo/bin — a bare name otherwise raises WinError 2.
        if not shell and isinstance(cmd, list) and cmd:
            resolved = shutil.which(cmd[0], path=full_env["PATH"])
            if resolved:
                cmd = [resolved] + cmd[1:]
            else:
                msg = (f"'{cmd[0]}' was not found on PATH. If you just installed it, "
                       f"click re-scan; otherwise install it from the Toolchain panel.")
                if check:
                    raise RuntimeError(msg)
                self.log("  ! " + msg)
                return 127

        try:
            os.makedirs(self.workspace, exist_ok=True)
            proc = subprocess.Popen(
                cmd, cwd=cwd or self.workspace, env=full_env, shell=shell,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", bufsize=1,
            )
        except FileNotFoundError:
            exe = cmd if isinstance(cmd, str) else cmd[0]
            raise RuntimeError(f"could not launch '{exe}' — is it installed and on PATH?")
        try:
            for line in proc.stdout:
                self.log(line.rstrip("\n"))
                if self.cancel_event.is_set():
                    proc.terminate()
                    raise BuildCancelled()
        finally:
            proc.stdout.close()
        rc = proc.wait()
        if check and rc != 0:
            raise RuntimeError(f"command failed (exit {rc}): {pretty}")
        return rc

    # -- high-level plan ----------------------------------------------------
    def platforms_needed(self):
        matrix = {t["id"]: t for t in detect.TARGETS}
        plats = []
        for tid in self.target_ids:
            p = matrix[tid]["platform"] if tid in matrix else None
            if p and p not in plats:
                plats.append(p)
        return plats

    def plan(self):
        """Return a human-readable list of the steps that will run."""
        steps = ["Check out RustDesk source at the chosen tag",
                 "Generate flutter_rust_bridge code"]
        for p in self.platforms_needed():
            steps.append(f"Apply customizations for {p}")
            steps.append(f"Build {p} target(s)")
        steps.append("Write base64 custom_.txt + collect artifacts")
        return steps

    # -- steps --------------------------------------------------------------
    def checkout_source(self):
        self.log("\n=== 1. Check out RustDesk source ===")
        # Customizations mutate the source tree (sed/patch/rename), so every
        # build must start from a pristine checkout. If a previous tree is here,
        # remove it first — reusing it would double-apply patches and corrupt it.
        if os.path.exists(self.src_dir):
            self.log(f"  clearing previous source at {self.src_dir}")
            if not self.dry_run:
                shutil.rmtree(self.src_dir, ignore_errors=True)
                # a leftover read-only .git on Windows can resist removal
                if os.path.exists(self.src_dir):
                    _force_rmtree(self.src_dir)
        os.makedirs(self.workspace, exist_ok=True)
        # clone + 子模块是网络最脆的一步：失败清场重试（部分克隆会污染目标目录）
        last_err = None
        for attempt in range(1, 6):
            try:
                self.run(["git", "clone", "--depth", "1", "--branch", self.version,
                          "--recurse-submodules", RUSTDESK_REPO, self.src_dir])
                last_err = None
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                self.log(f"  ! clone attempt {attempt} failed: {e}")
                if not self.dry_run:
                    shutil.rmtree(self.src_dir, ignore_errors=True)
                    if os.path.exists(self.src_dir):
                        _force_rmtree(self.src_dir)
                time.sleep(10)
        if last_err:
            raise last_err

    def generate_bridge(self):
        self.log("\n=== 2. Generate flutter_rust_bridge ===")
        # Mirrors the generate-bridge job. cargo installs the codegen binary into
        # ~/.cargo/bin, which run() puts on PATH so it resolves on Windows too.
        # bridge.yml 还装 cargo-expand（frb 解析宏必需）+ flutter pub get（ffigen 需要
        # .dart_tool/package_config.json）。注意 bridge.yml 里 extended_text 13.0.0 的
        # pin 只适用于它那套 Flutter 3.22.3；本机单 Flutter 3.24.5 必须保留 pubspec
        # 原版 14.0.0，否则 flutter build 报一堆 API 不匹配。
        self.run(["cargo", "install", "cargo-expand", "--version", "1.0.95", "--locked"],
                 check=False)
        self.run(["cargo", "install", "flutter_rust_bridge_codegen",
                  "--version", "1.80.1", "--features", "uuid", "--locked"],
                 check=False)
        self.run(["flutter", "pub", "get"], cwd=os.path.join(self.src_dir, "flutter"),
                 check=False)
        codegen = shutil.which("flutter_rust_bridge_codegen", path=self._effective_path())
        if not codegen and not self.dry_run:
            self.log("  ! flutter_rust_bridge_codegen not found after cargo install; "
                     "skipping bridge regen (may already be generated in the source).")
            return
        self.run([codegen or "flutter_rust_bridge_codegen",
                  "--rust-input", "./src/flutter_ffi.rs",
                  "--dart-output", "./flutter/lib/generated_bridge.dart",
                  "--c-output", "./flutter/macos/Runner/bridge_generated.h"],
                 cwd=self.src_dir, check=False)
        # frb 生成时会把 DUMMY_WIRE_CODE_FOR_BINDGEN 暂时追加到 rust 输出文件喂
        # bindgen，正常结束才还原；codegen 中途 panic 就会残留，编译报
        # E0412（Dart_Handle not found）。这里兜底剪掉残留段。
        gen_rs = os.path.join(self.src_dir, "src", "bridge_generated.rs")
        marker = "// ----------- DUMMY CODE FOR BINDGEN ----------"
        try:
            with open(gen_rs, encoding="utf-8") as f:
                txt = f.read()
            if marker in txt:
                with open(gen_rs, "w", encoding="utf-8") as f:
                    f.write(txt[:txt.index(marker)].rstrip() + "\n")
                self.log("  · removed leftover dummy bindgen block in bridge_generated.rs")
        except OSError:
            pass

    def customize_for(self, platform):
        if self.dry_run:
            self.log(f"  (would apply {platform} customizations to {self.src_dir})")
            return
        env = self._env()
        customize.apply(self.src_dir, platform, env, self.patches_dir, log=self.log)

    def _env(self):
        from . import config_gen
        return config_gen.build_custom_env(self.config)

    def _py(self):
        """The Python that build.py should run under — guaranteed to exist."""
        return sys.executable or "python"

    def _bash(self):
        """bash for running RustDesk's NDK shell scripts (Git Bash on Windows)."""
        b = shutil.which("bash", path=self._effective_path())
        if b:
            return b
        # On Windows, Git ships bash but usually only git.exe is on PATH. Derive
        # bash from git's location: <Git>\cmd\git.exe -> <Git>\bin\bash.exe.
        git = shutil.which("git", path=self._effective_path())
        if git:
            gitroot = os.path.dirname(os.path.dirname(git))  # up from cmd/ or bin/
            for cand in (os.path.join(gitroot, "bin", "bash.exe"),
                         os.path.join(gitroot, "usr", "bin", "bash.exe")):
                if os.path.isfile(cand):
                    return cand
        # common install locations as a last resort
        for cand in (r"C:\Program Files\Git\bin\bash.exe",
                     r"C:\Program Files (x86)\Git\bin\bash.exe"):
            if os.path.isfile(cand):
                return cand
        return None

    # ---- native deps (vcpkg) ---------------------------------------------
    VCPKG_COMMIT = "120deac3062162151622ca4860575a33844ba10b"

    def setup_vcpkg(self, triplet):
        """Check out the pinned vcpkg commit and install RustDesk's native deps
        (ffmpeg, hwcodec, etc.) for `triplet`. Needs VCPKG_ROOT set."""
        root = os.environ.get("VCPKG_ROOT")
        if not root:
            self.log("  ! VCPKG_ROOT not set — skipping vcpkg dep install. "
                     "Set it to your vcpkg checkout so ffmpeg/hwcodec resolve.")
            return
        self.log(f"  vcpkg deps ({triplet}) from {root}")
        # CI 里 generator-windows.yml 有 VCPKG_DEFAULT_HOST_TRIPLET=<triplet>（缺了它
        # ffmpeg 等 host 依赖会建进 x64-windows 树，hwcodec 只认 x64-windows-static）
        os.environ["VCPKG_DEFAULT_HOST_TRIPLET"] = triplet
        self.run(["git", "-C", root, "fetch", "--depth", "1", "origin", self.VCPKG_COMMIT],
                 check=False)
        self.run(["git", "-C", root, "checkout", self.VCPKG_COMMIT], check=False)
        vcpkg_exe = os.path.join(root, "vcpkg.exe" if self.host["os"] == "Windows" else "vcpkg")
        self.run([vcpkg_exe, "install", "--triplet", triplet,
                  f"--x-install-root={os.path.join(root, 'installed')}"],
                 cwd=self.src_dir, check=False)

    # ---- per-platform builds ---------------------------------------------
    def build_windows(self):
        self.log("\n=== Build Windows x86_64 ===")
        self.log("  Note: a full Windows build also needs the RustDesk custom Flutter")
        self.log("  engine + LLVM 15. See README 'Windows toolchain'. Continuing with build.py.")
        self.setup_vcpkg("x64-windows-static")
        self.customize_for("windows")
        self.run([self._py(), "build.py", "--portable", "--hwcodec", "--flutter",
                  "--vram", "--skip-portable-pack"], cwd=self.src_dir)
        release = os.path.join(self.src_dir, "flutter", "build", "windows",
                               "x64", "runner", "Release")
        # category B: base64 custom_.txt next to the binary
        if not self.dry_run:
            env = self._env()
            customize.write_custom_txt(release, env, log=self.log)
        self._collect(release, (".exe", ".msi"), "windows")

    def build_linux(self):
        self.log("\n=== Build Linux ===")
        self.setup_vcpkg("x64-linux")
        self.customize_for("linux")
        # base64 custom_.txt staged for build.py + bundle (SKILL.md §4.4)
        if not self.dry_run:
            env = self._env()
            customize.write_custom_txt(self.src_dir, env, log=self.log)
        self.run([self._py(), "build.py", "--flutter"], cwd=self.src_dir, check=False)
        # ensure it also reaches the flutter bundle (rpm/Arch package the bundle)
        for arch in ("x64", "arm64"):
            bundle = os.path.join(self.src_dir, "flutter", "build", "linux",
                                  arch, "release", "bundle")
            if os.path.isdir(bundle):
                customize.write_custom_txt(bundle, env, log=self.log)
        self._collect(self.src_dir, (".deb", ".rpm", ".AppImage", ".flatpak",
                                     ".pkg.tar.zst"), "linux")

    def build_android(self):
        self.log("\n=== Build Android ===")
        self.customize_for("android")
        env = self._env()
        # bundled asset (SKILL.md §4.2)
        if not self.dry_run:
            assets = os.path.join(self.src_dir, "flutter", "assets")
            customize.write_custom_txt(assets, env, log=self.log)

        archs = {
            "android-arm64": ("aarch64-linux-android", "android-arm64", "arm64-v8a", "ndk_arm64.sh"),
            "android-armv7": ("armv7-linux-androideabi", "android-arm", "armeabi-v7a", "ndk_arm.sh"),
            "android-x86_64": ("x86_64-linux-android", "android-x64", "x86_64", "ndk_x64.sh"),
        }
        wanted = [a for a in self.target_ids if a in archs]
        universal = "android-universal" in self.target_ids
        if universal and not wanted:
            wanted = list(archs.keys())  # universal needs all three arch libs

        for tid in wanted:
            target, ftarget, abi, ndk = archs[tid]
            self.log(f"\n-- Android {abi} --")
            self.run(["rustup", "target", "add", target], check=False)
            self.run(["cargo", "install", "cargo-ndk", "--version", "3.1.2", "--locked"],
                     check=False)
            script = f"./flutter/{ndk}"
            bash = self._bash()
            if bash or self.dry_run:
                self.run([bash or "bash", script], cwd=self.src_dir, check=False)
            else:
                self.log("  ! bash not found — RustDesk's NDK build scripts are shell "
                         "scripts. On Windows install Git Bash (bundled with Git for "
                         "Windows) so these can run.")
            jni = os.path.join(self.src_dir, "flutter", "android", "app", "src",
                               "main", "jniLibs", abi)
            os.makedirs(jni, exist_ok=True)
            if not universal:
                self.run(["flutter", "build", "apk", "--release",
                          "--target-platform", ftarget, "--split-per-abi"],
                         cwd=os.path.join(self.src_dir, "flutter"), check=False)
        if universal:
            self.log("\n-- Android universal (all ABIs) --")
            self.run(["flutter", "build", "apk", "--release"],
                     cwd=os.path.join(self.src_dir, "flutter"), check=False)
        apk_dir = os.path.join(self.src_dir, "flutter", "build", "app",
                               "outputs", "flutter-apk")
        self._collect(apk_dir, (".apk",), "android")

    def build_macos(self):
        self.log("\n=== Build macOS ===")
        self.customize_for("macos")
        self.run([self._py(), "build.py", "--flutter", "--hwcodec"],
                 cwd=self.src_dir, check=False)
        env = self._env()
        app_dir = os.path.join(self.src_dir, "flutter", "build", "macos",
                               "Build", "Products", "Release")
        if os.path.isdir(app_dir):
            customize.write_custom_txt(app_dir, env, log=self.log)
        self._collect(self.src_dir, (".dmg",), "macos")

    # ---- artifact collection ---------------------------------------------
    def _collect(self, root, exts, platform):
        os.makedirs(self.out_dir, exist_ok=True)
        if self.dry_run or not os.path.isdir(root):
            self.log(f"  (would collect {'/'.join(exts)} from {root})")
            return
        fname = self.config.get("exename", self.config.get("appname", "RustDesk"))
        found = 0
        for dp, _, files in os.walk(root):
            for f in files:
                if any(f.endswith(e) for e in exts):
                    src = os.path.join(dp, f)
                    dest = os.path.join(self.out_dir, f)
                    shutil.copy2(src, dest)
                    self.artifacts.append(dest)
                    self.log(f"  ✓ artifact: {dest}")
                    found += 1
        if not found:
            self.log(f"  ! no {'/'.join(exts)} artifacts found under {root}")

    # -- driver -------------------------------------------------------------
    def execute(self):
        start = time.time()
        try:
            self.log(f"Building RustDesk v{self.version} for: "
                     f"{', '.join(self.target_ids)}")
            self.log(f"Host: {self.host['os']} {self.host['arch']} · "
                     f"{self.host['cores_logical']} cores · {self.host['ram_gb']} GB RAM")
            if self.dry_run:
                self.log("** DRY RUN — commands are printed, nothing is executed **")

            self.checkout_source()
            self.generate_bridge()

            plats = self.platforms_needed()
            dispatch = {
                "windows": self.build_windows,
                "linux": self.build_linux,
                "android": self.build_android,
                "macos": self.build_macos,
            }
            for p in plats:
                self._check_cancel()
                dispatch[p]()

            elapsed = int(time.time() - start)
            self.log(f"\n=== DONE in {elapsed//60}m {elapsed%60}s ===")
            self.log(f"Artifacts ({len(self.artifacts)}):")
            for a in self.artifacts:
                self.log(f"  {a}")
            return {"ok": True, "artifacts": self.artifacts, "seconds": elapsed}
        except BuildCancelled:
            self.log("\n!! build cancelled by user")
            return {"ok": False, "cancelled": True, "artifacts": self.artifacts}
        except Exception as e:
            self.log(f"\n!! BUILD FAILED: {e}")
            return {"ok": False, "error": str(e), "artifacts": self.artifacts}


def preflight(target_ids, prereqs_status, host=None):
    """Return (ok, problems[]) — are the toolchains present for these targets?"""
    host = host or detect.host_info()
    problems = []
    matrix = {t["id"]: t for t in detect.TARGETS}
    for tid in target_ids:
        t = matrix.get(tid)
        if not t:
            problems.append(f"unknown target {tid}")
            continue
        if host["os"] not in t["host_os"]:
            problems.append(f"{t['label']}: needs a {' or '.join(t['host_os'])} host")
            continue
        for tool in detect.required_tools(t, host["os"]):
            st = prereqs_status.get(tool)
            if not st or not st.get("present"):
                problems.append(f"{t['label']}: missing {tool}")
    # de-dupe, preserve order
    seen, uniq = set(), []
    for p in problems:
        if p not in seen:
            seen.add(p); uniq.append(p)
    return (len(uniq) == 0, uniq)
