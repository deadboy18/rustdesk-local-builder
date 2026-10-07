"use strict";
/* Minimal bilingual dictionary (EN / 中文) for the builder UI.
   Static markup carries data-i18n / data-i18n-ph / data-i18n-title keys;
   dynamic strings in app.js call t("key"). The chosen language is kept in
   localStorage and defaults to the browser language. */

const I18N = {
  en: {
    "app.title": "RustDesk Local Builder",
    "brand.sub": "Local Builder",
    "rig.machine": "This machine",
    "rig.reading": "reading hardware…",
    "rig.toolchain": "Toolchain",
    "rig.installMissing": "install missing",
    "rig.installMissing.title": "Download missing toolchains into a local folder",
    "rig.recheck": "re-scan",
    "rig.recheck.title": "Re-scan toolchains",
    "rig.checking": "checking…",
    "rig.installing": "installing…",
    "rig.cancel": "cancel",
    "rig.foot": "No GitHub. Everything runs on this device.",

    "tab.targets": "Targets",
    "tab.config": "Config",
    "tab.console": "Build",

    "targets.h1": "What can this machine build?",
    "targets.lede": "Lit cells are ready to build right now. Outlined cells need a toolchain. Hatched cells need a different host OS.",
    "targets.ledeDynamic": "This {os} machine can build {n} target(s); {ready} ready to go right now.",
    "targets.legendReady": "◉ ready",
    "targets.legendNeed": "⚠ needs a tool (installable)",
    "targets.legendBlocked": "▨ wrong host OS",
    "targets.loading": "building capability map…",
    "targets.selected": "selected",
    "targets.dryRun": "Dry run (print commands only)",
    "targets.previewPlan": "Preview plan",
    "targets.startBuild": "Start build",
    "targets.installFirst": "⚠ install first: {tools}",

    "config.h1": "Baked-in config",
    "config.lede": "These values are compiled into the client and written to custom_.txt. The password and permissions live in the base64 payload.",
    "config.server": "Server",
    "config.serverAddr": "Server address",
    "config.pubkey": "Public key",
    "config.apiServer": "API server",
    "config.identity": "Identity",
    "config.appname": "App name",
    "config.exename": "File name",
    "config.compname": "Company",
    "config.androidid": "Android app id",
    "config.access": "Access",
    "config.password": "Permanent password",
    "config.approval": "Approval mode",
    "config.approval.pc": "password-click (password AND on-screen accept)",
    "config.approval.p": "password only",
    "config.approval.c": "click only",
    "config.permissions": "Permissions",
    "config.tweaks": "Tweaks",
    "config.save": "Save config",
    "config.saved": "saved ✓",
    "config.saveError": "error: ",
    "config.preview": "custom_.txt preview",
    "config.previewNote": "Written next to the binary as base64 — never raw JSON. Decoded for readability here.",
    "config.compiled": "Compiled-in values",

    "build.h1": "Build",
    "build.lede": "Runs the same steps as the GitHub Actions workflow, on this machine.",
    "build.version": "RustDesk version",
    "build.idle": "idle",
    "build.running": "running",
    "build.done": "done",
    "build.failed": "failed",
    "build.copyLog": "copy log",
    "build.copyLog.title": "Copy the full build log",
    "build.copied": "copied ✓",
    "build.cancel": "Cancel",
    "build.hint": "Select targets, then Start build. Output streams here.",
    "build.preflight": "! preflight found missing toolchains:",
    "build.preflightFix": "  (fix these in the Toolchain panel, or use Dry run to preview)",
    "build.couldNotStart": "could not start",

    "spec.host": "host", "spec.os": "os", "spec.arch": "arch", "spec.distro": "distro",
    "spec.cpu": "cpu", "spec.cores": "cores", "spec.ram": "ram", "spec.disk": "disk",
    "spec.gbFree": " GB free",

    "tool.install": "install",
    "tool.ok": "ok",
    "tool.notFound": "not found",
    "tool.localTitle": "installed locally",
    "tool.removeTitle": "remove local copy",
    "tool.localFoot": "local toolchains: ",
    "tool.vsConfirm": "Install Build Tools for Visual Studio (C++)?\n\nThis is Microsoft's official installer (~4–6 GB, several minutes) and will show a UAC prompt. It provides the MSVC linker (link.exe) that Rust needs plus MSBuild. Continue?",
    "tool.installingX": "installing {ids}…",
    "tool.finished": "install finished — re-scanning",
    "tool.done": "done. tools wired into this session.",
    "tool.removeConfirm": "Remove the locally-installed {id}{size}? You can reinstall it anytime.",

    "rescanning": "re-scanning…",

    "perm.enableKeyboard": "Keyboard", "perm.enableClipboard": "Clipboard",
    "perm.enableFileTransfer": "File transfer", "perm.enableAudio": "Audio",
    "perm.enableTCP": "TCP tunnel", "perm.enableRemoteRestart": "Remote restart",
    "perm.enableRecording": "Recording", "perm.enableBlockingInput": "Block input",
    "perm.enableRemoteModi": "Remote config edit", "perm.enablePrinter": "Printer",
    "perm.enableCamera": "Camera", "perm.enableTerminal": "Terminal",
    "flag.delayFix": "Fix connection delay", "flag.hidecm": "Hide connection window",
    "flag.xOffline": "Show ‘X’ when offline", "flag.removeNewVersionNotif": "Hide update notice",
    "flag.removeWallpaper": "Allow wallpaper removal", "flag.denyLan": "Disable LAN discovery",
    "flag.enableDirectIP": "Direct IP access", "flag.autoClose": "Auto-disconnect idle",

    "ph.host": "host.example.com",
    "ph.api": "https://host.example.com/",
    "ph.appname": "RustDesk = no rename",
    "ph.exename": "RustDesk",
    "ph.androidid": "blank = default",
  },

  zh: {
    "app.title": "RustDesk 本地构建器",
    "brand.sub": "本地构建器",
    "rig.machine": "本机信息",
    "rig.reading": "正在读取硬件信息…",
    "rig.toolchain": "工具链",
    "rig.installMissing": "安装缺失项",
    "rig.installMissing.title": "把缺失的工具链下载到本地目录",
    "rig.recheck": "重新检测",
    "rig.recheck.title": "重新扫描工具链",
    "rig.checking": "检测中…",
    "rig.installing": "安装中…",
    "rig.cancel": "取消",
    "rig.foot": "不走 GitHub，一切都在本机完成。",

    "tab.targets": "构建目标",
    "tab.config": "配置",
    "tab.console": "构建",

    "targets.h1": "这台机器能构建什么？",
    "targets.lede": "亮起的卡片现在就能构建；描边卡片缺点工具链；斜纹卡片需要换操作系统。",
    "targets.ledeDynamic": "这台 {os} 机器可构建 {n} 个目标，其中 {ready} 个现在就能开跑。",
    "targets.legendReady": "◉ 就绪",
    "targets.legendNeed": "⚠ 缺工具（可安装）",
    "targets.legendBlocked": "▨ 系统不符",
    "targets.loading": "正在生成能力图…",
    "targets.selected": "已选",
    "targets.dryRun": "试运行（只打印命令）",
    "targets.previewPlan": "预览计划",
    "targets.startBuild": "开始构建",
    "targets.installFirst": "⚠ 请先安装：{tools}",

    "config.h1": "内嵌配置",
    "config.lede": "这些值会编译进客户端并写入 custom_.txt；密码与权限存放在 base64 载荷里。",
    "config.server": "服务器",
    "config.serverAddr": "服务器地址",
    "config.pubkey": "公钥",
    "config.apiServer": "API 服务器",
    "config.identity": "身份标识",
    "config.appname": "应用名",
    "config.exename": "文件名",
    "config.compname": "公司名",
    "config.androidid": "Android 包名",
    "config.access": "访问控制",
    "config.password": "固定密码",
    "config.approval": "确认方式",
    "config.approval.pc": "密码+点击（密码且屏幕确认）",
    "config.approval.p": "仅密码",
    "config.approval.c": "仅点击",
    "config.permissions": "权限",
    "config.tweaks": "微调项",
    "config.save": "保存配置",
    "config.saved": "已保存 ✓",
    "config.saveError": "错误：",
    "config.preview": "custom_.txt 预览",
    "config.previewNote": "以 base64 写在程序旁（不是明文 JSON），这里解码展示便于阅读。",
    "config.compiled": "编译期内嵌值",

    "build.h1": "构建",
    "build.lede": "与 GitHub Actions 流水线相同的步骤，在本机执行。",
    "build.version": "RustDesk 版本",
    "build.idle": "空闲",
    "build.running": "构建中",
    "build.done": "完成",
    "build.failed": "失败",
    "build.copyLog": "复制日志",
    "build.copyLog.title": "复制完整构建日志",
    "build.copied": "已复制 ✓",
    "build.cancel": "取消",
    "build.hint": "先选目标，再点“开始构建”，日志将实时显示在这里。",
    "build.preflight": "! 预检发现缺少工具链：",
    "build.preflightFix": "  （可在左侧“工具链”面板补齐，或用试运行预览）",
    "build.couldNotStart": "无法启动",

    "spec.host": "主机", "spec.os": "系统", "spec.arch": "架构", "spec.distro": "发行版",
    "spec.cpu": "处理器", "spec.cores": "核心", "spec.ram": "内存", "spec.disk": "磁盘",
    "spec.gbFree": " GB 可用",

    "tool.install": "安装",
    "tool.ok": "正常",
    "tool.notFound": "未找到",
    "tool.localTitle": "本地已装",
    "tool.removeTitle": "删除本地副本",
    "tool.localFoot": "本地工具链：",
    "tool.vsConfirm": "安装 Visual Studio Build Tools（C++）吗？\n\n这是微软官方安装器（约 4–6 GB，需几分钟），会弹出 UAC 提权提示。它提供 Rust 需要的 MSVC 链接器（link.exe）和 MSBuild。继续吗？",
    "tool.installingX": "正在安装 {ids}…",
    "tool.finished": "安装完成 — 重新扫描中",
    "tool.done": "完成，工具已接入当前会话。",
    "tool.removeConfirm": "删除本地安装的 {id}{size}？以后随时可以重新安装。",

    "rescanning": "重新扫描中…",

    "perm.enableKeyboard": "键盘", "perm.enableClipboard": "剪贴板",
    "perm.enableFileTransfer": "文件传输", "perm.enableAudio": "音频",
    "perm.enableTCP": "TCP 隧道", "perm.enableRemoteRestart": "远程重启",
    "perm.enableRecording": "录屏", "perm.enableBlockingInput": "锁定输入",
    "perm.enableRemoteModi": "远程改配置", "perm.enablePrinter": "打印机",
    "perm.enableCamera": "摄像头", "perm.enableTerminal": "终端",
    "flag.delayFix": "修复连接延迟", "flag.hidecm": "隐藏连接窗口",
    "flag.xOffline": "离线时显示「X」", "flag.removeNewVersionNotif": "隐藏升级提示",
    "flag.removeWallpaper": "允许移除壁纸", "flag.denyLan": "禁用局域网发现",
    "flag.enableDirectIP": "允许直连 IP", "flag.autoClose": "空闲自动断开",

    "ph.host": "主机.示例.com",
    "ph.api": "https://主机.示例.com/",
    "ph.appname": "RustDesk = 不改名",
    "ph.exename": "RustDesk",
    "ph.androidid": "留空 = 默认",
  },
};

let LANG = localStorage.getItem("rdlb_lang");
if (!LANG) LANG = (navigator.language || "").toLowerCase().startsWith("zh") ? "zh" : "en";

function t(key, vars) {
  let s = (I18N[LANG] && I18N[LANG][key]) ?? I18N.en[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll("{" + k + "}", v);
  return s;
}

function applyLang() {
  document.documentElement.lang = LANG === "zh" ? "zh-CN" : "en";
  document.title = t("app.title");
  for (const el of document.querySelectorAll("[data-i18n]")) el.textContent = t(el.dataset.i18n);
  for (const el of document.querySelectorAll("[data-i18n-ph]")) el.placeholder = t(el.dataset.i18nPh);
  for (const el of document.querySelectorAll("[data-i18n-title]")) el.title = t(el.dataset.i18nTitle);
  const btn = document.getElementById("lang-toggle");
  if (btn) btn.textContent = LANG === "zh" ? "EN" : "中文";
}

function setLang(l) {
  LANG = l;
  localStorage.setItem("rdlb_lang", l);
  applyLang();
  if (window.__i18nRerender) window.__i18nRerender();
}

document.addEventListener("DOMContentLoaded", () => {
  applyLang();
  const btn = document.getElementById("lang-toggle");
  if (btn) btn.addEventListener("click", () => setLang(LANG === "zh" ? "en" : "zh"));
});
