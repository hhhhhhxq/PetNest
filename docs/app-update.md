# PetNest 应用安装包更新

## 用户侧入口

应用安装包更新与资源更新分开处理：

- 托盘中的“立即检查资源更新”只检查光标、倒计时和其他远程资源。
- Windows 用户在“设置”窗口底部的“检查程序更新…”中检查安装包更新。
- 启动后约 2.5 秒会进行一次后台检查；后台检查与上次成功/失败检查间隔至少 24 小时。
- 设置页手动点击会强制检查，不受 24 小时节流影响。检查、下载都在后台进行，重复点击不会创建第二个任务。

发现新版本后，用户可以查看版本说明并选择下载。安装包下载到用户临时目录，只有大小和 SHA-256 都匹配后才会交给独立的 `PetNestUpdater.exe`。updater 等待 PetNest 退出，再启动 Inno Setup；网络失败、校验失败、取消或安装器启动失败都保留当前已安装版本。

macOS 不显示此入口，也不会启动 Windows updater。之后接入 Sparkle 等 macOS 更新方案时，可以复用相同的检查结果和 UI 状态，而不改变当前资源更新流程。

## GitHub Release 发布文件

主项目公开仓库的每个 Release 上传：

1. `PetNest-Setup-<version>.exe`
2. `app-update.json`

示例（版本号应与安装器的 `AppVersion` 一致）：

```json
{
  "schema_version": 1,
  "version": "0.2.0",
  "platform": "windows-x64",
  "asset": {
    "url": "https://github.com/qinxiaohui-qq/PetNest/releases/download/v0.2.0/PetNest-Setup-0.2.0.exe",
    "size": 12345678,
    "sha256": "<64 个十六进制字符>"
  },
  "release_notes": "本版本修复了……"
}
```

客户端只接受 HTTPS 的 GitHub Release 地址、严格的新版本号、最大 512 MiB 的安装包和 64 位 SHA-256。元数据格式以后可以增加签名字段；在签名校验实现前，不应在 JSON 中声称已有签名保护。

## Windows 构建

运行 `build_windows.bat` 会生成：

- `dist/PetNest/`：主程序 onedir 包；
- `dist/PetNestUpdater.exe`：不依赖 Qt 的独立等待/启动程序；
- `dist/installer/PetNest-Setup.exe`：Inno Setup 安装包。

发布前应计算安装包 SHA-256，将大小和摘要写入 `app-update.json`，再把两个文件一起上传到同一个 GitHub Release。安装器升级使用相同的 `AppId`，因此会覆盖程序文件但不会删除用户宠物库。

可以直接使用仓库内脚本生成元数据，避免手工抄写摘要：

```powershell
python tools/create_app_update_manifest.py `
  --version 0.2.0 `
  --installer dist/installer/PetNest-Setup.exe `
  --url https://github.com/qinxiaohui-qq/PetNest/releases/download/v0.2.0/PetNest-Setup-0.2.0.exe `
  --notes "本版本修复了……"
```
