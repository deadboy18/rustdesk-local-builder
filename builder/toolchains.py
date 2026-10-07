"""
toolchains.py — optionally auto-download the build toolchains into a local
`.toolchains/` folder next to the app, with **no admin rights and no system
changes**. We extract portable archives, then record the env vars (PATH
additions, LIBCLANG_PATH, VCPKG_ROOT, ANDROID_NDK_HOME, JAVA_HOME) to
`.toolchains/env.json`. `app.py` loads that file on startup and applies it, so
detection immediately sees the freshly-installed tools.

What can be auto-installed (portable, deterministic):
    flutter · llvm · vcpkg · android_ndk · java · rust(add 1.75 via rustup)

What can't (needs a real system installer / elevation) stays a guided hint:
    msbuild / the Visual Studio C++ workload, Xcode.

NOTE: the download URLs are the official ones but versions/paths do drift —
if a download 404s, update the registry below. Everything writes under
`.toolchains/`; delete that folder to start clean.
"""

import json
import os
import platform
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile


PINNED = {"flutter": "3.24.5", "llvm": "15.0.6", "ndk": "r28c",
          "rust": "1.75", "vcpkg": "120deac3062162151622ca4860575a33844ba10b"}

# rough download / on-disk footprint, shown in the UI so people know what a tool
# costs before installing and what deleting it will free.
SIZE_HINTS = {
    "flutter":     {"download": "~1.1 GB", "disk": "~2.8 GB", "version": "3.24.5"},
    "llvm":        {"download": "~30 MB", "disk": "~90 MB", "version": "15/16"},
    "android_ndk": {"download": "~700 MB", "disk": "~2.6 GB", "version": "r28c"},
    "java":        {"download": "~190 MB", "disk": "~330 MB", "version": "17 (Temurin)"},
    "vcpkg":       {"download": "~10 MB",  "disk": "~600 MB", "version": "pinned"},
    "rust":        {"download": "~250 MB", "disk": "~800 MB", "version": "1.75"},
    "vs_buildtools": {"download": "~4 MB", "disk": "~4-6 GB", "version": "2022 (C++)"},
}

WIN = platform.system() == "Windows"
EXE = ".exe" if WIN else ""


def _system():
    return {"Darwin": "macOS"}.get(platform.system(), platform.system())


def _arch():
    m = platform.machine().lower()
    if m in ("x86_64", "amd64", "x64"):
        return "x86_64"
    if m in ("arm64", "aarch64"):
        return "aarch64"
    return m


# ---------------------------------------------------------------------------
# tool registry: url per (os, arch), archive kind, and how to wire env after
# ---------------------------------------------------------------------------
# Flutter SDK download base. Override with RDLB_FLUTTER_BASE to use a mirror
# (e.g. https://storage.flutter-io.cn/flutter_infra_release/releases/stable,
# which is path-compatible with the Google storage URL) when the default host
# is slow or unreachable from your network.
FLUTTER_BASE = os.environ.get(
    "RDLB_FLUTTER_BASE",
    "https://storage.googleapis.com/flutter_infra_release/releases/stable",
)
LLVM_REL = "https://github.com/llvm/llvm-project/releases/download/llvmorg-15.0.6"
NDK_BASE = "https://dl.google.com/android/repository"
ADOPTIUM = "https://api.adoptium.net/v3/binary/latest/17/ga"

TOOLS = {
    "flutter": {
        "label": "Flutter SDK 3.24.5",
        "kind": "archive",
        "urls": {
            ("Windows", "x86_64"): (f"{FLUTTER_BASE}/windows/flutter_windows_3.24.5-stable.zip", "zip"),
            ("Linux", "x86_64"):   (f"{FLUTTER_BASE}/linux/flutter_linux_3.24.5-stable.tar.xz", "tar"),
            ("macOS", "x86_64"):   (f"{FLUTTER_BASE}/macos/flutter_macos_3.24.5-stable.zip", "zip"),
            ("macOS", "aarch64"):    (f"{FLUTTER_BASE}/macos/flutter_macos_arm64_3.24.5-stable.zip", "zip"),
        },
        "marker": os.path.join("bin", "flutter.bat" if WIN else "flutter"),
    },
    "llvm": {
        "label": "LLVM / libclang 15",
        "kind": "archive",
        "urls": {
            # Windows: the official LLVM installer needs admin and is flaky, so we
            # fetch just libclang (all bindgen needs) via pip — no admin, reliable.
            ("Windows", "x86_64"): ("libclang==16.0.6", "pip"),
            ("Linux", "x86_64"):   (f"{LLVM_REL}/clang+llvm-15.0.6-x86_64-linux-gnu-ubuntu-18.04.tar.xz", "tar"),
            ("Linux", "aarch64"):    (f"{LLVM_REL}/clang+llvm-15.0.6-aarch64-linux-gnu.tar.xz", "tar"),
            ("macOS", "x86_64"):   (f"{LLVM_REL}/clang+llvm-15.0.6-x86_64-apple-darwin.tar.xz", "tar"),
            ("macOS", "aarch64"):    (f"{LLVM_REL}/clang+llvm-15.0.6-arm64-apple-darwin22.0.tar.xz", "tar"),
        },
        "marker": os.path.join("bin", "clang" + EXE),
    },
    "android_ndk": {
        "label": "Android NDK r28c",
        "kind": "archive",
        "urls": {
            ("Windows", "x86_64"): (f"{NDK_BASE}/android-ndk-r28c-windows.zip", "zip"),
            ("Linux", "x86_64"):   (f"{NDK_BASE}/android-ndk-r28c-linux.zip", "zip"),
            ("macOS", "x86_64"):   (f"{NDK_BASE}/android-ndk-r28c-darwin.dmg", "dmg"),
            ("macOS", "aarch64"):    (f"{NDK_BASE}/android-ndk-r28c-darwin.dmg", "dmg"),
        },
        "marker": "source.properties",
    },
    "java": {
        "label": "JDK 17 (Temurin)",
        "kind": "archive",
        "urls": {
            ("Windows", "x86_64"): (f"{ADOPTIUM}/windows/x64/jdk/hotspot/normal/eclipse", "zip"),
            ("Linux", "x86_64"):   (f"{ADOPTIUM}/linux/x64/jdk/hotspot/normal/eclipse", "tar"),
            ("Linux", "aarch64"):    (f"{ADOPTIUM}/linux/aarch64/jdk/hotspot/normal/eclipse", "tar"),
            ("macOS", "x86_64"):   (f"{ADOPTIUM}/mac/x64/jdk/hotspot/normal/eclipse", "tar"),
            ("macOS", "aarch64"):    (f"{ADOPTIUM}/mac/aarch64/jdk/hotspot/normal/eclipse", "tar"),
        },
        "marker": os.path.join("bin", "java" + EXE),
    },
    "vcpkg": {
        "label": "vcpkg (native deps)",
        "kind": "git",
        "repo": "https://github.com/microsoft/vcpkg",
        "marker": "bootstrap-vcpkg." + ("bat" if WIN else "sh"),
    },
    "rust": {
        "label": "Rust 1.75 (via rustup)",
        "kind": "rust",
        "urls": {
            ("Windows", "x86_64"): ("https://win.rustup.rs/x86_64", "rustup-init.exe"),
            ("Linux", "x86_64"):   ("https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init", "rustup-init"),
            ("Linux", "aarch64"):    ("https://static.rust-lang.org/rustup/dist/aarch64-unknown-linux-gnu/rustup-init", "rustup-init"),
            ("macOS", "x86_64"):   ("https://static.rust-lang.org/rustup/dist/x86_64-apple-darwin/rustup-init", "rustup-init"),
            ("macOS", "aarch64"):    ("https://static.rust-lang.org/rustup/dist/aarch64-apple-darwin/rustup-init", "rustup-init"),
        },
    },
    # Build Tools for Visual Studio — the command-line-only subset of VS (no IDE).
    # Provides the MSVC linker (link.exe) that Rust needs on Windows, plus MSBuild
    # for the .msi. Windows only; large (~3-5 GB) and needs one UAC prompt.
    "vs_buildtools": {
        "label": "VS Build Tools (C++ / MSVC linker + MSBuild)",
        "kind": "vs",
        "urls": {
            ("Windows", "x86_64"): ("https://aka.ms/vs/17/release/vs_BuildTools.exe", "vs"),
        },
    },
}

# which detection id each tool satisfies (prereqs.py ids)
SATISFIES = {"flutter": "flutter", "llvm": "llvm", "android_ndk": "android_ndk",
             "java": "java", "vcpkg": "vcpkg", "rust": "rust",
             "vs_buildtools": "msbuild"}


def tools_dir(root):
    return os.path.join(root, ".toolchains")


def dir_size(path):
    """Total bytes under a directory (best-effort)."""
    total = 0
    for dp, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit != "GB" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def installed_info(root):
    """Which tools are present in the local .toolchains folder, and their size."""
    base = tools_dir(root)
    out = {}
    total = 0
    for tid in TOOLS:
        home = os.path.join(base, tid)
        if os.path.isdir(home):
            sz = dir_size(home)
            total += sz
            out[tid] = {"local": True, "bytes": sz, "size": human_size(sz)}
        else:
            out[tid] = {"local": False, "bytes": 0, "size": ""}
    out["_total"] = {"bytes": total, "size": human_size(total)}
    return out


def remove_tool(tid, root, log=lambda m: None):
    """Delete a locally-installed toolchain and drop its env entries."""
    home = os.path.join(tools_dir(root), tid)
    freed = 0
    if os.path.isdir(home):
        freed = dir_size(home)
        shutil.rmtree(home, ignore_errors=True)
        log(f"removed {tid} ({human_size(freed)})")
    else:
        log(f"{tid} was not installed locally")
    # rewrite env.json without paths/vars pointing at the removed home
    d = _load_env(root)
    d["path"] = [p for p in d.get("path", []) if home not in p]
    d["vars"] = {k: v for k, v in d.get("vars", {}).items() if home not in str(v)}
    os.makedirs(tools_dir(root), exist_ok=True)
    with open(env_path(root), "w") as f:
        json.dump(d, f, indent=2)
    return {"removed": tid, "freed": freed, "freed_human": human_size(freed)}


def installable(host_os=None, host_arch=None):
    """Return {id: {label, ok, reason}} for every tool, on this host."""
    host_os = host_os or _system()
    host_arch = host_arch or _arch()
    out = {}
    for tid, spec in TOOLS.items():
        ok, reason = True, ""
        if spec["kind"] == "archive":
            if (host_os, host_arch) not in spec["urls"]:
                ok, reason = False, f"no portable {spec['label']} for {host_os}/{host_arch}"
        elif spec["kind"] == "git":
            if not shutil.which("git"):
                ok, reason = False, "git is required to fetch vcpkg"
        elif spec["kind"] == "rust":
            if (host_os, host_arch) not in spec["urls"]:
                ok, reason = False, f"no rustup-init for {host_os}/{host_arch}"
        elif spec["kind"] == "vs":
            if host_os != "Windows":
                ok, reason = False, "Visual Studio Build Tools are Windows-only"
        out[tid] = {"label": spec["label"], "ok": ok, "reason": reason}
    return out


# ---------------------------------------------------------------------------
# download + extract
# ---------------------------------------------------------------------------

def _human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def _download(url, dest, log):
    log(f"  ↓ {url}")
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "rustdesk-local-builder"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length", 0))
        got = 0
        last = 0.0
        while True:
            chunk = r.read(262144)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            now = time.time()
            if now - last > 0.5:
                last = now
                if total:
                    pct = got * 100 // total
                    log(f"    {pct:3d}%  {_human(got)} / {_human(total)}")
                else:
                    log(f"    {_human(got)}")
    log(f"  ✓ downloaded {_human(os.path.getsize(dest))}")


def _extract(archive, kind, dest, log):
    log(f"  extracting → {dest}")
    os.makedirs(dest, exist_ok=True)
    if kind == "zip":
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    elif kind == "dmg":
        _extract_dmg(archive, dest, log)
    else:  # tar.* (xz/gz auto-detected by mode 'r:*')
        with tarfile.open(archive, "r:*") as t:
            t.extractall(dest)


def _extract_dmg(dmg, dest, log):
    """macOS only: mount the .dmg, copy its contents out, then detach."""
    mnt = tempfile.mkdtemp(prefix="rdlb-dmg-")
    log("  mounting dmg (hdiutil)")
    subprocess.check_call(["hdiutil", "attach", "-nobrowse", "-quiet",
                           "-mountpoint", mnt, dmg])
    try:
        for name in os.listdir(mnt):
            src = os.path.join(mnt, name)
            dst = os.path.join(dest, name)
            if os.path.isdir(src):
                shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
    finally:
        subprocess.call(["hdiutil", "detach", "-quiet", mnt])
        shutil.rmtree(mnt, ignore_errors=True)


def _locate(base, marker, log):
    """Find the tool home under `base` — the dir that contains `marker`."""
    # common case: base itself, or a single top-level child
    if os.path.exists(os.path.join(base, marker)):
        return base
    for child in sorted(os.listdir(base)):
        p = os.path.join(base, child)
        if os.path.isdir(p) and os.path.exists(os.path.join(p, marker)):
            return p
    # deeper walk (NDK zip nests android-ndk-r28c/; some tars nest bin/)
    for dirpath, _dirs, _files in os.walk(base):
        if os.path.exists(os.path.join(dirpath, marker)):
            return dirpath
    log(f"  ! could not find marker '{marker}' under {base}")
    return base


def _llvm_env(home):
    """LIBCLANG_PATH = the dir that actually contains libclang.(dll|so|dylib).
    Handles both the pip layout (clang/native/) and the tarball layout (lib/)."""
    for dp, _dirs, files in os.walk(home):
        for f in files:
            if f.startswith("libclang") and any(e in f for e in (".dll", ".so", ".dylib")):
                return {"vars": {"LIBCLANG_PATH": dp}, "path": [dp]}
    # fall back to the conventional tarball location
    lib = os.path.join(home, "lib")
    return {"vars": {"LIBCLANG_PATH": lib}, "path": [os.path.join(home, "bin")]}


def _env_for(tid, home):
    """Env vars + PATH additions a tool needs, given its install home."""
    bindir = os.path.join(home, "bin")
    if tid == "flutter":
        return {"vars": {}, "path": [bindir]}
    if tid == "llvm":
        return _llvm_env(home)
    if tid == "java":
        # macOS Temurin nests Contents/Home
        mac_home = os.path.join(home, "Contents", "Home")
        jhome = mac_home if os.path.isdir(mac_home) else home
        return {"vars": {"JAVA_HOME": jhome}, "path": [os.path.join(jhome, "bin")]}
    if tid == "android_ndk":
        return {"vars": {"ANDROID_NDK_HOME": home, "ANDROID_NDK_ROOT": home}, "path": []}
    if tid == "vcpkg":
        return {"vars": {"VCPKG_ROOT": home}, "path": [home]}
    return {"vars": {}, "path": []}


# ---------------------------------------------------------------------------
# per-tool install
# ---------------------------------------------------------------------------

def install_one(tid, root, log, cancelled=lambda: False):
    spec = TOOLS[tid]
    host_os, host_arch = _system(), _arch()
    base = tools_dir(root)
    os.makedirs(base, exist_ok=True)
    home_target = os.path.join(base, tid)

    log(f"\n=== Installing {spec['label']} ===")

    if spec["kind"] == "rust":
        # Download rustup-init and install 1.75 per-user (~/.cargo, ~/.rustup).
        # No admin needed. --no-modify-path: we manage PATH via env.json instead.
        url, _label = spec["urls"][(host_os, host_arch)]
        with tempfile.TemporaryDirectory() as tmp:
            init = os.path.join(tmp, "rustup-init" + (".exe" if WIN else ""))
            _download(url, init, log)
            if not WIN:
                os.chmod(init, 0o755)
            log("  installing Rust 1.75 (rustup-init -y, minimal profile)")
            # (no --no-modify-path: let rustup add ~/.cargo/bin to PATH for the
            #  user, so cargo works in any new terminal too. We also wire it into
            #  our own env.json for this app.)
            rc = subprocess.call([init, "-y", "--default-toolchain", PINNED["rust"],
                                  "--profile", "minimal"])
            if rc != 0:
                raise RuntimeError("rustup-init failed")
        cargo_bin = os.path.join(os.path.expanduser("~"), ".cargo", "bin")
        log(f"  ✓ Rust installed; cargo bin: {cargo_bin}")
        # home stays "" (rust lives in ~/.cargo, not .toolchains) but we DO wire PATH
        return {"tool": tid, "home": "", "env": {"vars": {}, "path": [cargo_bin]}}

    if spec["kind"] == "vs":
        # Build Tools for Visual Studio (C++). Bootstrapper self-elevates; we run
        # it elevated and wait. Installs the MSVC toolset (link.exe) + Windows SDK
        # + MSBuild to Program Files. cargo/rustc then find link.exe via vswhere,
        # no PATH wiring needed. Large download handled by the installer itself.
        url, _ = spec["urls"][(host_os, host_arch)]
        with tempfile.TemporaryDirectory() as tmp:
            boot = os.path.join(tmp, "vs_BuildTools.exe")
            _download(url, boot, log)
            if cancelled():
                raise RuntimeError("cancelled")
            log("  launching the Visual Studio Build Tools installer.")
            log("  → Accept the UAC prompt. This installs the C++ MSVC toolset")
            log("    (link.exe) + Windows SDK + MSBuild — a few GB, several minutes.")
            args = ("--quiet --wait --norestart --nocache "
                    "--add Microsoft.VisualStudio.Workload.VCTools "
                    "--includeRecommended")
            ps = (f"$p = Start-Process -FilePath '{boot}' -ArgumentList "
                  f"'{args}' -Verb RunAs -Wait -PassThru; exit $p.ExitCode")
            rc = subprocess.call(["powershell", "-NoProfile", "-ExecutionPolicy",
                                  "Bypass", "-Command", ps])
            # VS bootstrapper returns 3010 for "success, reboot recommended"
            if rc not in (0, 3010):
                raise RuntimeError(
                    f"VS Build Tools installer exited with code {rc}. If UAC was "
                    "declined, try again; otherwise install 'Desktop development "
                    "with C++' from https://aka.ms/vs/17/release/vs_BuildTools.exe")
        log("  ✓ VS Build Tools install finished. Click re-scan; cargo will now "
            "find link.exe.")
        # lives in Program Files, not .toolchains — no env wiring here.
        return {"tool": tid, "home": "", "env": {"vars": {}, "path": []}}

    if spec["kind"] == "git":
        if os.path.isdir(home_target):
            log("  already present, updating")
        else:
            log(f"  git clone {spec['repo']}")
            rc = subprocess.call(["git", "clone", "--depth", "1", spec["repo"], home_target])
            if rc != 0:
                raise RuntimeError("git clone failed")
        # bootstrap so the vcpkg binary exists
        boot = os.path.join(home_target, "bootstrap-vcpkg." + ("bat" if WIN else "sh"))
        log("  bootstrapping vcpkg")
        subprocess.call([boot] if WIN else ["bash", boot])
        env = _env_for(tid, home_target)
        return {"tool": tid, "home": home_target, "env": env}

    # archive
    url, arch_kind = spec["urls"][(host_os, host_arch)]
    if cancelled():
        raise RuntimeError("cancelled")

    if arch_kind == "pip":
        # Fetch just libclang (bindgen only needs libclang.dll) via pip into a
        # local dir. No admin, no NSIS. `url` holds the pip requirement string.
        if os.path.isdir(home_target):
            shutil.rmtree(home_target, ignore_errors=True)
        os.makedirs(home_target, exist_ok=True)
        log(f"  pip install {url} → {home_target}")
        rc = subprocess.call([sys.executable, "-m", "pip", "install",
                              "--no-input", "--target", home_target, url])
        if rc != 0:
            raise RuntimeError("pip install libclang failed")
        env = _llvm_env(home_target)
        libdir = env["vars"].get("LIBCLANG_PATH", "")
        if libdir and any(f.startswith("libclang") for f in os.listdir(libdir)):
            log(f"  ✓ libclang at {libdir}")
        else:
            log("  ! libclang not found after pip install")
        return {"tool": tid, "home": home_target, "env": env}

    if arch_kind == "nsis":
        # The official LLVM Windows installer is requireAdministrator, so a plain
        # silent /S install fails with WinError 740 (needs elevation). We run it
        # elevated through one UAC prompt. A temp .bat carries the /D path so
        # spaces in it survive (NSIS /D must be the unquoted rest of the line).
        with tempfile.TemporaryDirectory() as tmp:
            exe = os.path.join(tmp, tid + "-setup.exe")
            _download(url, exe, log)
            if cancelled():
                raise RuntimeError("cancelled")
            if os.path.isdir(home_target):
                shutil.rmtree(home_target, ignore_errors=True)
            os.makedirs(home_target, exist_ok=True)
            bat = os.path.join(tmp, "install_llvm.bat")
            with open(bat, "w") as f:
                f.write("@echo off\r\n")
                f.write(f'"{exe}" /S /D={home_target}\r\n')
            log("  LLVM's Windows installer needs admin — a UAC prompt will appear.")
            log("  (LLVM is only needed for Windows desktop builds, not Android.)")
            ps = (f"$p = Start-Process -FilePath '{bat}' -Verb RunAs -Wait -PassThru; "
                  f"exit $p.ExitCode")
            rc = subprocess.call(["powershell", "-NoProfile", "-ExecutionPolicy",
                                  "Bypass", "-Command", ps])
            if rc != 0:
                raise RuntimeError(
                    "elevated LLVM install did not complete (UAC declined or failed). "
                    "You can install LLVM 15 manually and set LIBCLANG_PATH, or skip "
                    "it — it's only needed for Windows desktop builds.")
        home = _locate(home_target, spec["marker"], log)
        env = _env_for(tid, home)
        if os.path.exists(os.path.join(home, spec["marker"])):
            log(f"  ✓ installed at {home}")
        else:
            log(f"  ! installer finished but clang not found under {home_target}")
        return {"tool": tid, "home": home, "env": env}

    ext = {"zip": ".zip", "dmg": ".dmg"}.get(arch_kind, ".tar")
    with tempfile.TemporaryDirectory() as tmp:
        fname = os.path.join(tmp, tid + ext)
        _download(url, fname, log)
        if cancelled():
            raise RuntimeError("cancelled")
        # clean prior install
        if os.path.isdir(home_target):
            shutil.rmtree(home_target, ignore_errors=True)
        _extract(fname, arch_kind, home_target, log)
    home = _locate(home_target, spec["marker"], log)
    env = _env_for(tid, home)
    # sanity
    if not os.path.exists(os.path.join(home, spec["marker"])):
        log(f"  ! warning: marker missing after extract ({spec['marker']})")
    else:
        log(f"  ✓ installed at {home}")
    return {"tool": tid, "home": home, "env": env}


def install_many(ids, root, log, cancelled=lambda: False):
    results, errors = [], []
    for tid in ids:
        if cancelled():
            log("\n[cancelled]")
            break
        if tid not in TOOLS:
            errors.append((tid, "unknown tool"))
            continue
        try:
            results.append(install_one(tid, root, log, cancelled))
        except Exception as e:  # noqa: BLE001
            log(f"  ✗ {tid} failed: {e}")
            errors.append((tid, str(e)))
    if results:
        merge_env(root, results, log)
    log("\n" + ("done." if not errors else f"done with {len(errors)} error(s)."))
    return {"installed": [r["tool"] for r in results], "errors": errors}


# ---------------------------------------------------------------------------
# persisted env — written after install, applied at app startup
# ---------------------------------------------------------------------------

def env_path(root):
    return os.path.join(tools_dir(root), "env.json")


def merge_env(root, results, log):
    data = _load_env(root)
    for r in results:
        for k, v in r["env"]["vars"].items():
            data["vars"][k] = v
        for p in r["env"]["path"]:
            if p and p not in data["path"]:
                data["path"].insert(0, p)
    os.makedirs(tools_dir(root), exist_ok=True)
    with open(env_path(root), "w") as f:
        json.dump(data, f, indent=2)
    log(f"  wrote {env_path(root)}")


def _load_env(root):
    try:
        with open(env_path(root)) as f:
            d = json.load(f)
            d.setdefault("vars", {})
            d.setdefault("path", [])
            return d
    except Exception:
        return {"vars": {}, "path": []}


def apply_persisted_env(root):
    """Call at startup: set vars + prepend PATH so detection sees local tools."""
    d = _load_env(root)
    for k, v in d.get("vars", {}).items():
        os.environ[k] = v
    if d.get("path"):
        sep = os.pathsep
        existing = os.environ.get("PATH", "")
        prepend = sep.join(p for p in d["path"] if os.path.isdir(p))
        if prepend:
            os.environ["PATH"] = prepend + sep + existing
    return d


if __name__ == "__main__":
    import sys
    r = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print(json.dumps(installable(), indent=2))
    if len(sys.argv) > 1:
        install_many(sys.argv[1:], r, print)
