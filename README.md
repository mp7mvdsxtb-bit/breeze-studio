# Breeze Studio

本地 Breeze-TTS-2 英语配音工作台：声音设计、声音克隆、声音指导，长文分段、持久化批量队列、声音库、配方、音频导出、中文声音描述本地翻译。

声音库中的“删除声音”会确认后移除该条目及参考音频，已生成的配音保留。排队、运行或正在取消的任务引用该声音时禁止删除；旧任务的参考已删除后无法直接重试，需要重新选择声音新建任务。

长文音色：声音设计先生成首段，后续段落统一克隆首段音色，不再逐段独立设计。克隆和声音指导始终复用选定参考。重试会继续使用同一首段；旧版独立生成的后续分段会保留备份并重生成。此机制可减少换声感，模型仍可能产生轻微语调和音色波动。若需要多条独立文案也保持相同声音，先将满意的短音频保存到声音库，再选择声音克隆模式批量生成。

发声事件：英语支持 `(laugh)`、`(sigh)`、`(cough)`、`(clears throat)`，中文对应 `[笑]`、`[叹气]`、`[咳嗽]`、`[清嗓子]`。建议放在句首或完整句子之间。出现标记时增加明确的非语言声音指导，音色限制仅约束正常说话，不抑制叹气所需的呼吸声。后续分段和克隆仍保留同一参考，但含事件的段落使用参考音色加事件指导，不再纯克隆无指令。未标记的段落不受影响。事件由生成模型执行，无法保证每次成功或精确控制时长；这不是固定音效播放功能。

## Windows 一键安装（推荐）

安装 Git 后，在 PowerShell 执行：

```powershell
git clone https://github.com/mp7mvdsxtb-bit/breeze-studio.git D:\breeze-studio
cd D:\breeze-studio
.\一键安装.bat
```

也可以在 GitHub 点击 Code → Download ZIP，解压后双击 `一键安装.bat`。安装完成后双击 `启动语音工作室.bat`。

脚本支持 Windows 10/11 x64、NVIDIA 显卡及可用驱动。建议至少 8GB 显存、16GB 内存，首次安装前预留 25GB 磁盘空间，并保证能访问 python.org、PyPI、PyTorch 和 Hugging Face。驱动需要自行安装，脚本不会更改显卡驱动。

自动检查 Python 3.12 x64；缺少时从 python.org 下载带有效官方签名的 3.12.10 安装程序，按当前用户安装到 `tools/python312`，不改系统 PATH。随后建立独立 `venv`、安装 CUDA 12.8 PyTorch 和依赖，再验证 GPU。无需单独安装 CUDA Toolkit。

语音模型约 7.68GB，翻译模型约 0.32GB；连同 PyTorch 等首次下载约 11GB。固定官方模型版本，逐文件验证 SHA256 或 Git blob 哈希；网络中断后重跑可续传，已验证文件会跳过。权重保存于代码目录上一级的 `models/Breeze-TTS-2`，翻译模型保存在代码目录 `translation-model`。失败时窗口会保留错误信息，解决后重跑即可。

只检查、不安装或下载：`powershell -NoProfile -ExecutionPolicy Bypass -File webui/setup.ps1 -VerifyOnly`。

从 v1.0.0 升级需手动运行一次安装 BAT，因为旧依赖表包含本机绝对路径；自动更新会按设计拦截依赖变化。

## Windows 手动运行

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
