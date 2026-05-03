# 分发安装包：macOS（签名 / 公证 / DMG）与 Windows（Inno Setup / MSIX）

本文假设你已用 PyInstaller 打出产物（见仓库根目录 [`README.md`](../README.md) → **快速开始** 第 7 节「打包桌面 GUI」；英文版见 [`README.en.md`](../README.en.md) 对应小节）。

---

## 一、macOS：给 `.app` 签名 → 公证 → 可选做 DMG

### 1. 准备条件

- 加入 **Apple Developer Program**（付费），在 [Certificates, Identifiers & Profiles](https://developer.apple.com/account/resources/certificates/list) 创建 **Developer ID Application** 证书，并在本机 Keychain 安装好。
- 在 Apple ID 上开启 **App 专用密码**（用于 `notarytool`），见 [Apple 支持：App 专用密码](https://support.apple.com/zh-cn/102654)。
- Xcode 命令行工具：`xcode-select --install`（通常已装）。

### 2. 对 `.app` 做代码签名（ hardened runtime）

将 `DouyinDownloaderGui.app` 换成你的实际路径（一般在 `dist/` 下）。

```bash
APP="dist/DouyinDownloaderGui.app"
IDENTITY="Developer ID Application: 你的团队名 (XXXXXXXXXX)"   # 在钥匙串或 security find-identity -v -p codesigning 里查看

# 先签内部二进制与框架（--deep），并启用 runtime（公证要求）
codesign --deep --force --options runtime --timestamp \
  --sign "$IDENTITY" \
  "$APP"

# 自检
codesign --verify --verbose "$APP"
spctl -a -vv "$APP"
```

若 `.app` 内还有未签名的 dylib，需按报错逐个 `codesign` 后再签外层 `.app`。

### 3. 提交公证（notarytool）

```bash
ZIP="DouyinDownloaderGui.zip"
ditto -c -k --keepParent "$APP" "$ZIP"

xcrun notarytool submit "$ZIP" \
  --apple-id "你的AppleID邮箱" \
  --team-id "XXXXXXXXXX" \
  --password "xxxx-xxxx-xxxx-xxxx" \
  --wait
```

`--password` 使用 **App 专用密码**，不要填 Apple ID 登录密码。

查询历史：`xcrun notarytool history --apple-id ... --team-id ... --password ...`

### 4. 装订票据（staple）

公证通过后：

```bash
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"
```

### 5. 制作 DMG（可选，便于用户拖拽安装）

**方式 A：`hdiutil`（系统自带）**

```bash
hdiutil create -volname "Douyin Downloader" -srcfolder "$APP" -ov -format UDZO "DouyinDownloaderGui.dmg"
```

**方式 B：** 使用 [create-dmg](https://github.com/create-dmg/create-dmg) 做带背景/Applications 快捷方式的 DMG（自行安装该工具后按其 README 调用）。

### 6. 常见坑

- **Gatekeeper**：未签名或未公证的 `.app`，用户首次打开可能被拦截；签名+公证+staple 可显著改善。
- **公证失败**：Apple 返回的日志里会写明哪个二进制缺 hardened runtime 或 entitlements；按日志修后再提交。
- **官方文档**：[Notarizing macOS software before distribution](https://developer.apple.com/documentation/security/notarizing_macos_software_before_distribution)

---

## 二、Windows：Inno Setup（经典 `.exe` 安装向导）

### 1. 安装工具

下载并安装 [Inno Setup](https://jrsoftware.org/isinfo.php)（免费）。

### 2. 思路

PyInstaller 产物是一个文件夹，例如 `dist\DouyinDownloaderGui\`，里面有 `DouyinDownloaderGui.exe` 和 `_internal\` 等。**整个目录**都要打进安装包，安装时解压到 `{app}`。

### 3. 最小 `.iss` 示例（按你的路径改 `Source`）

```iss
[Setup]
AppName=Douyin Downloader
AppVersion=2.0.0
DefaultDirName={autopf}\DouyinDownloaderGui
OutputDir=.\installer_out
OutputBaseFilename=DouyinDownloaderGui_Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "dist\DouyinDownloaderGui\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Douyin Downloader"; Filename: "{app}\DouyinDownloaderGui.exe"
Name: "{autodesktop}\Douyin Downloader"; Filename: "{app}\DouyinDownloaderGui.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked

[Run]
Filename: "{app}\DouyinDownloaderGui.exe"; Description: "运行 Douyin Downloader"; Flags: nowait postinstall skipifsilent
```

在 Inno Setup 编译器中 **Build → Compile**，得到 `installer_out\DouyinDownloaderGui_Setup.exe`。

### 4. 代码签名（可选）

购买 **Authenticode 证书**，用 `signtool`（Windows SDK）对 `Setup.exe` 签名，减少 SmartScreen 警告。详见 [Microsoft：SignTool](https://learn.microsoft.com/windows/win32/seccrypto/signtool)。

---

## 三、Windows：MSIX（商店 / 企业分发风格）

MSIX 步骤较长，需 **应用程序标识（Package Identity）**、**manifest**、资产（图标、启动图）等。

### 1. 官方入口

- [MSIX 打包概述](https://learn.microsoft.com/zh-cn/windows/msix/packaging-tool/create-app-package-with-composer)

### 2. 常见做法

1. 安装 **MSIX Packaging Tool**（Microsoft Store）或 **Windows SDK** 里的相关工具。  
2. 用 **Packaging Tool** 对「已安装好的」应用目录做一次捕获，生成 `.msix`；或手写 `AppxManifest.xml` + `MakeAppx.exe` 打包。  
3. 若上架 Microsoft Store，还要在 Partner Center 配置；若仅企业内部分发，可考虑 **未上架签名包** + 受信证书。

MSIX 比 Inno Setup **门槛高**，适合已有商店/合规需求时使用。

---

## 四、和本仓库 PyInstaller 的关系

| 步骤 | 本仓库已提供 | 需你本机完成 |
|------|----------------|--------------|
| 打 `.app` / `exe` + 依赖目录 | `packaging/DouyinDownloaderGui.spec`、构建脚本 | 运行脚本 |
| Apple 签名 / 公证 / DMG | 否 | 按上文 **一** |
| Windows 安装包 / 商店包 | 否 | 按上文 **二、三** |

政策与界面以 Apple / Microsoft 当前文档为准；若命令报错，请对照官方文档调整参数版本。
