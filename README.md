# Breeze Studio

本地 Breeze-TTS-2 英语配音工作台：声音设计、声音克隆、声音指导，长文分段、持久化批量队列、声音库、配方、音频导出、中文声音描述本地翻译。

## Windows 运行

需要 Python 3.12、支持 CUDA 的 NVIDIA GPU；当前环境为 RTX 5060 8GB，低显存串行推理。其他硬件需自行验证。代码目录下的 `venv`、`translation-model`、`outputs` 均为本机数据，不提交。

1. 将 Breeze-TTS-2 官方模型下载到代码目录的上一级 `models/Breeze-TTS-2`。权重不包含在仓库或更新包中。
2. 在代码根目录执行 `py -3.12 -m venv venv`，然后 `venv\Scripts\python -m pip install -r requirements-lock.txt --extra-index-url https://download.pytorch.org/whl/cu128`。
3. 用 PowerShell 执行 `webui/download_translation.ps1` 下载本地中英翻译模型。
4. 双击 `启动语音工作室.bat`，访问本机 7861 端口。停止时使用 `停止语音工作室.bat`。

## 私有仓库自动更新

安装 GitHub CLI，运行 `gh auth login` 登录拥有仓库读取权限的账号。本机也支持 `tools/github-cli/bin/gh.exe`。认证由 GitHub CLI 管理，不在网页填写令牌。

`version.json` 中的 `repository` 设置为实际的 `OWNER/breeze-studio`。私有仓库创建和首个 Release 发布后更新才会可用。页面底部可检查新版本、关闭自动更新。

启动脚本在服务停止时从该仓库读取最新正式 Release，校验 SHA256、文件清单、版本号、每个文件哈希和 Python 语法，再安装代码。更新不处理模型、生成音频、声音库、浏览器配方、环境或本地设置。复制失败会恢复已替换的文件；旧代码保存在 `.update-backups`。断电、进程被强制终止和新版本的逻辑错误仍可能需要从备份手动恢复，不能保证更新免故障。已经运行的工作室不会热替换代码。

运行环境依赖有变化时阻止自动安装，先按版本说明更新环境。自动更新是启动时检查；浏览器“检查更新”只查询版本，不重启服务。

## 开发与发布

测试：`venv\Scripts\python -m pytest webui -q`。打包：`venv\Scripts\python webui/release.py dist`。只从明确的源码目录选择文件，发布 `breeze-studio-update.zip` 和 `breeze-studio-update.sha256`。正式标签格式 `v1.0.0`，必须与 `version.json` 一致。发布前审查变更，不上传本地工作目录的全部内容。

## 许可

上游推理源码见 `app/LICENSE`（Apache 2.0），来源 https://github.com/breezeblue-ai/breeze-tts 。Breeze-TTS-2 权重适用其官方研究与非商业许可；本项目 UI 不会改变模型许可。中文翻译使用 Helsinki-NLP/opus-mt-zh-en，模型许可 CC-BY-4.0，来源 https://huggingface.co/Helsinki-NLP/opus-mt-zh-en 。用于商业配音前须另行确认模型授权。
