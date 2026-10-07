"""
customize.py — apply every source customization the GitHub Actions workflows do,
but in Python, against a checked-out RustDesk source tree.

This is a faithful port of the "Apply customizations" steps in:
  build-windows.yml · build-linux.yml · build-android.yml

Two categories (SKILL.md §3):
  (A) compiled into the binary  — server/key/api/appname/company patched in source
  (B) read at runtime           — the base64 custom_.txt written next to the binary,
                                   plus (Android only) embedded into native code.

Everything routes through `apply(...)`, which takes the source dir, the target
platform, the CUSTOM_* env dict, and a `log` callback for streaming progress.
"""

import os
import re
import subprocess
import sys


# ---------------------------------------------------------------------------
# small helpers (sed / patch equivalents)
# ---------------------------------------------------------------------------

def _read(path):
    with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
        return f.read()


def _write(path, text):
    with open(path, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write(text)


def sed(src_dir, rel, old, new, log=None, required=False, count=0):
    """Literal string replace in a file (like `sed -i 's|old|new|'`)."""
    path = os.path.join(src_dir, rel)
    if not os.path.exists(path):
        if required and log:
            log(f"    ! missing (skipped): {rel}")
        return False
    text = _read(path)
    if old not in text:
        return False
    text = text.replace(old, new, count if count else -1)
    _write(path, text)
    if log:
        log(f"    · {rel}: {_short(old)} -> {_short(new)}")
    return True


def sed_regex(src_dir, rel, pattern, repl, log=None, flags=0):
    path = os.path.join(src_dir, rel)
    if not os.path.exists(path):
        return False
    text = _read(path)
    new_text, n = re.subn(pattern, repl, text, flags=flags)
    if n:
        _write(path, new_text)
        if log:
            log(f"    · {rel}: {n}× /{_short(pattern)}/")
    return bool(n)


def find_files(src_dir, subdir, suffix):
    root = os.path.join(src_dir, subdir)
    hits = []
    for dp, _, files in os.walk(root):
        for fn in files:
            if fn.endswith(suffix):
                hits.append(os.path.join(dp, fn))
    return hits


def git_apply(src_dir, patch_path, log=None):
    try:
        subprocess.run(["git", "apply", patch_path], cwd=src_dir,
                       check=True, capture_output=True, text=True)
        if log:
            log(f"    · applied patch {os.path.basename(patch_path)}")
        return True
    except subprocess.CalledProcessError as e:
        if log:
            log(f"    ! patch skipped ({os.path.basename(patch_path)}): "
                f"{(e.stderr or '').strip()[:120]}")
        return False


def _short(s, n=42):
    s = str(s).replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


# ---------------------------------------------------------------------------
# shared category-A customizations (server/key/api/appname/company/urls/flags)
# ---------------------------------------------------------------------------

def _apply_server_key_api(src, env, log):
    log("  Server + key + API")
    sed(src, "libs/hbb_common/src/config.rs", "rs-ny.rustdesk.com", env["CUSTOM_SERVER"], log)
    sed(src, "libs/hbb_common/src/config.rs",
        "OeVuKk5nlHiXp+APNn0Y3pC1Iwpwn44JGqrQCsWqmBw=", env["CUSTOM_KEY"], log)
    sed(src, "src/common.rs", "https://admin.rustdesk.com", env["CUSTOM_API_SERVER"], log)


def _apply_allow_custom(src, patches_dir, log):
    """Strip the signature check on custom_.txt and rename custom.txt->custom_.txt."""
    log("  Allow custom_.txt (strip signature check)")
    # reuse the upstream allowCustom.py by running it in the source dir
    script = os.path.join(os.path.abspath(patches_dir), "allowCustom.py")
    common = os.path.join(src, "src", "common.rs")
    if os.path.exists(script) and os.path.exists(common):
        try:
            # 用当前解释器而非 "python3"——Windows 上 python3 常是坏的商店 stub
            subprocess.run([sys.executable, script], cwd=src, check=True,
                           capture_output=True, text=True)
            log("    · allowCustom.py applied")
        except subprocess.CalledProcessError as e:
            log(f"    ! allowCustom.py failed: {(e.stderr or '').strip()[:120]}")
    else:
        # fallback: inline sed like the Android job does
        _strip_signature_inline(src, log)


def _strip_signature_inline(src, log):
    """Android-style inline strip: remove const KEY block and verify block."""
    path = os.path.join(src, "src", "common.rs")
    if not os.path.exists(path):
        return
    text = _read(path)
    # remove `const KEY: &str = ...;` through matching `};` (the get_rs_pk block)
    text = re.sub(r"const KEY:.*?\n(?:.*?\n)*?\s*};\n", "", text, count=1)
    # remove the `if let Ok(data) = sign::verify(&data, &pk)` block up to `};`
    text = re.sub(r"let Ok\(data\) = sign::verify\(&data, &pk\).*?\n(?:.*?\n)*?\s*};\n",
                  "", text, count=1)
    text = text.replace("custom.txt", "custom_.txt")
    _write(path, text)
    log("    · signature check stripped (inline)")


def _apply_appname(src, env, platform, log):
    app = env["CUSTOM_APPNAME"]
    if app.lower() == "rustdesk":
        return
    log(f"  App name -> {app}")
    for rs in find_files(src, "src/lang", ".rs"):
        rel = os.path.relpath(rs, src)
        sed(src, rel, "RustDesk", app)
    if platform == "windows":
        sed(src, "Cargo.toml", 'description = "RustDesk Remote Desktop"',
            f'description = "{app}"', log)
        sed(src, "flutter/windows/runner/Runner.rc", '"RustDesk Remote Desktop"',
            f'"{app}"', log)
        sed(src, "flutter/windows/runner/Runner.rc",
            'VALUE "InternalName", "rustdesk"',
            f'VALUE "InternalName", "{app}"', log)
    if platform == "android":
        sed(src, "Cargo.toml", 'description = "RustDesk Remote Desktop"', f'description = "{app}"', log)
        sed(src, "Cargo.toml", 'name = "RustDesk"', f'name = "{app}"', log)
        sed(src, "flutter/android/app/src/main/res/values/strings.xml", "RustDesk", app, log)
        sed(src, "flutter/lib/main.dart", "title: 'RustDesk'", f"title: '{app}'", log)
        amanifest = "flutter/android/app/src/main/AndroidManifest.xml"
        sed(src, amanifest, 'android:label="RustDesk"', f'android:label="{app}"', log)
        sed(src, amanifest, 'android:label="RustDesk Input"', f'android:label="{app} Input"', log)
        kt = "flutter/android/app/src/main/kotlin/com/carriez/flutter_hbb"
        sed(src, f"{kt}/BootReceiver.kt", "RustDesk is Open", f"{app} is Open", log)
        sed(src, f"{kt}/FloatingWindowService.kt", "Show Rustdesk", f"Show {app}", log)
        sed(src, f"{kt}/MainService.kt", '"RustDesk"', f'"{app}"', log)
        sed(src, f"{kt}/MainService.kt", '"RustDesk Service', f'"{app} Service', log)
        sed(src, "flutter/lib/main.dart", "RustDesk", app, log)
        sed(src, "libs/hbb_common/src/config.rs", '"RustDesk"', f'"{app}"', log)


def _apply_company(src, env, log):
    comp = env["CUSTOM_COMPNAME"]
    if not comp or comp == "Purslane Ltd":
        return
    log(f"  Company name -> {comp}")
    files = ["Cargo.toml", "libs/portable/Cargo.toml", "src/main.rs",
             "flutter/lib/desktop/pages/desktop_setting_page.dart",
             "flutter/windows/runner/Runner.rc", "res/msi/preprocess.py"]
    for rel in files:
        sed(src, rel, "Purslane Tech Pte. Ltd.", comp)
        sed(src, rel, "Purslane Ltd", comp)
    sed(src, "res/msi/preprocess.py", "PURSLANE", comp)


def _apply_urls(src, env, log):
    url = env["CUSTOM_URL_LINK"]
    dl = env["CUSTOM_DOWNLOAD_LINK"]
    if url and url != "https://rustdesk.com":
        log(f"  URL link -> {url}")
        for rel in ["flutter/lib/common.dart",
                    "flutter/lib/desktop/pages/desktop_setting_page.dart",
                    "flutter/lib/mobile/pages/settings_page.dart"]:
            sed(src, rel, "https://rustdesk.com", url)
    if dl and dl != "https://rustdesk.com/download":
        for rel in ["flutter/lib/desktop/pages/desktop_home_page.dart",
                    "flutter/lib/mobile/pages/connection_page.dart"]:
            sed(src, rel, "https://rustdesk.com/download", dl)


def _apply_flags(src, env, patches_dir, log):
    log("  Feature flags")
    if env["CUSTOM_DELAY_FIX"] == "true":
        if sed(src, "src/client.rs", "!key.is_empty()", "false"):
            log("    · delay fix")
    if env["CUSTOM_X_OFFLINE"] == "true":
        git_apply(src, os.path.join(patches_dir, "xoffline.diff"), log)
    if env["CUSTOM_HIDE_CM"] == "true":
        git_apply(src, os.path.join(patches_dir, "hidecm.diff"), log)
    if env["CUSTOM_REMOVE_NEW_VERSION_NOTIF"] == "true":
        if sed(src, "flutter/lib/desktop/pages/desktop_home_page.dart",
               "updateUrl.isNotEmpty", "false"):
            log("    · removeNewVersionNotif")


def _apply_gpu_texture_fix(src, log):
    # needed so tagged releases resolve flutter_gpu_texture_renderer
    for rel in ["flutter/pubspec.lock", "flutter/pubspec.yaml"]:
        sed(src, rel, "2ded7f146437a761ffe6981e2f742038f85ca68d",
            "08a471bb8ceccdd50483c81cdfa8b81b07b14b87")


# ---------------------------------------------------------------------------
# Android-only: embed the base64 config into native code (SKILL.md §4.2)
# ---------------------------------------------------------------------------

def _apply_android_embed(src, env, log):
    log("  Embed custom config into native code (Android)")
    b64 = env["CUSTOM_B64"]
    kt = os.path.join("flutter", "android", "app", "src", "main", "kotlin",
                      "com", "carriez", "flutter_hbb", "MainService.kt")
    dart = os.path.join("flutter", "lib", "models", "native_model.dart")
    ok1 = sed(src, kt, 'FFI.startServer(configPath, "")',
              f'FFI.startServer(configPath, "{b64}")', log)
    ok2 = sed(src, dart, "customClientConfig: '',",
              f"customClientConfig: '{b64}',", log)
    if not (ok1 and ok2):
        log("    ! WARNING: one of the Android embed points was not found — "
            "password may not preset (see SKILL.md §4.2)")
    # app id
    app_id = env.get("CUSTOM_ANDROID_APP_ID", "")
    if app_id:
        sed(src, "flutter/android/app/build.gradle", "com.carriez.flutter_hbb", app_id, log)
    # remove android scam warning
    sed_regex(src, "flutter/lib/mobile/pages/server_page.dart",
              r'bind\.mainGetLocalOption\(key:\s*"show-scam-warning"\)', '"N"', log)


def write_custom_txt(dest_dir, env, log=None, filename="custom_.txt"):
    """Write the base64 payload next to the binary (category B)."""
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(env["CUSTOM_B64"])       # base64, NOT raw JSON — SKILL.md §4.1
    if log:
        log(f"  wrote {filename} (base64) -> {path}")
    return path


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------

def apply(src_dir, platform, env, patches_dir, log=print):
    """
    Apply all customizations for `platform` in-place on `src_dir`.
    platform: 'windows' | 'linux' | 'macos' | 'android'
    """
    log(f"Applying customizations for {platform} …")
    # allowCustom.py runs with cwd=src_dir, and git apply needs a real path,
    # so patches_dir must be absolute.
    patches_dir = os.path.abspath(patches_dir)
    src_dir = os.path.abspath(src_dir)
    _apply_server_key_api(src_dir, env, log)
    _apply_allow_custom(src_dir, patches_dir, log)
    git_apply(src_dir, os.path.join(patches_dir, "removeSetupServerTip.diff"), log)
    _apply_appname(src_dir, env, platform, log)
    _apply_company(src_dir, env, log)
    _apply_flags(src_dir, env, patches_dir, log)
    _apply_gpu_texture_fix(src_dir, log)
    _apply_urls(src_dir, env, log)
    if platform == "android":
        _apply_android_embed(src_dir, env, log)
    log("Customizations complete.")
