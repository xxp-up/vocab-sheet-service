# Vocab Sheet Service

基于 FastAPI 的教学材料处理工具，当前聚焦两类一线工作：

1. `教材提词`
   从带明显标注的 `PDF` / `DOCX` 教材中提取重点英文词或词组，
   自动补全音标、词性、中文意思和例句，并回填到固定 Excel 模板。
2. `课后反馈`
   根据课堂音频、逐字稿或补充笔记，生成可编辑、可复制的课后反馈草稿。

日常分发以 `Windows 单文件 EXE` 为主。
最终使用者不需要自行安装 Python，也不需要在页面里维护配置。
当前 Web 工作台中的 `系统配置` 模块已经隐藏；
如需更换 `VISION_API_KEY` 或模型参数，请由维护者修改 `.env` 后重新打包。

## 目录

- [文档导航](#文档导航)
- [项目现状](#项目现状)
- [教材提词输出规则](#教材提词输出规则)
- [快速开始](#快速开始)
- [配置维护](#配置维护)
- [Windows 打包与分发](#windows-打包与分发)
- [源码运行](#源码运行)
- [清理生成物](#清理生成物)
- [HTTP 接口](#http-接口)
- [开发与测试](#开发与测试)
- [常见问题](#常见问题)
- [项目结构](#项目结构)

## 文档导航

- [用户操作手册](docs/用户操作手册.md)
  面向老师、教务和运营同事，重点说明页面操作和结果解读。
- `README.md`
  面向维护者和开发者，重点说明配置、打包、清理和接口。

## 项目现状

### 当前对外使用方式

- 维护者在本仓库内维护 `.env`
- 维护者执行 `package-windows.ps1`
- 脚本生成单文件 `exe`
- 使用者双击 `exe` 即可启动

### 当前页面行为

- 用户可见标签页只有 `教材提词` 和 `课后反馈`
- `系统配置` 面板仍保留在代码中，但前端已隐藏
- 后端的 `/v1/settings` 相关接口仍保留，供维护或调试使用

### 当前运行时资源策略

- 源码模式下，首次处理词典或音频时会准备运行时资源
- 打包模式下，`package-windows.ps1` 会预载词典、Vosk 模型和相关 wheel
- 单文件 `exe` 启动后，会把这些资源恢复到同目录下的 `.runtime/bootstrap/`

## 教材提词输出规则

### 词条补全

教材提词会把教材标注词、手工补词和音频补词合并去重后写入 Excel。
每个词条会尽量补全以下字段：

| 字段 | 规则 |
| --- | --- |
| 音标 | 优先使用本地免费词典资源 |
| 词性 | 使用本地词典解析，常见短语标为 `phr.` |
| 中文意思 | 优先使用本地词典；常见教材短语有内置兜底释义 |
| 例句 | 优先定位教材正文中的原句；找不到时自动生成语义贴合的例句 |
| 页数 | 只有使用教材原句时填写页码；自动生成例句时保持为空 |

### 例句高亮

生成的 Excel 和页面预览都会在例句中突出目标词：

- 目标词或词组会加粗
- 字号会在原字号基础上放大一点，便于检查
- 匹配时区分完整单词边界，避免把 `apple` 错标到 `pineapple` 中
- 词组会按连续短语匹配，例如 `in the future`

### 找不到教材例句时的造句策略

当教材正文中无法定位到某个词条的例句时，系统不会再留空，
而是生成一条更贴合词义和词性的英文例句。页数字段保持为空，
方便人工区分“教材原句”和“系统生成例句”。

示例：

| 词条 | 生成例句 |
| --- | --- |
| `afraid` | `My brother was afraid of it, but it didn't come anywhere near us.` |
| `upset` | `She was upset because she lost her favorite notebook.` |
| `several` | `Several students stayed after class to ask questions.` |
| `yet` | `I haven't finished my homework yet.` |

## 快速开始

### 给最终使用者

把下面两个文件发给对方即可：

- `dist/vocab-sheet-service.exe`
- `dist/vocab-sheet-service.sha256.txt`

使用者操作：

1. 双击 `vocab-sheet-service.exe`
2. 等浏览器自动打开 `http://127.0.0.1:8000/`
3. 在页面中使用 `教材提词` 或 `课后反馈`

说明：

- 不需要安装 Python
- 不需要手动配置密钥
- 默认会自动打开浏览器
- 如需自定义端口，可命令行执行：

```powershell
.\vocab-sheet-service.exe --host 127.0.0.1 --port 18080 --no-browser
```

### 给维护者

首次进入项目时先准备本地开发环境：

```powershell
.\setup.ps1 -Dev
```

然后根据工作需要：

- 本地源码运行：`.\start.ps1 -NoReload`
- 打包单文件 EXE：`powershell -NoProfile -ExecutionPolicy Bypass -File .\package-windows.ps1`

## 配置维护

### 配置文件位置

项目默认读取根目录 `.env`：

```env
REQUEST_TIMEOUT_SECONDS=90
RUNTIME_ROOT=.runtime
VISION_API_KEY=
VISION_BASE_URL=https://api.siliconflow.cn/v1
VISION_MODEL=Qwen/Qwen3-VL-32B-Instruct
VISION_TIMEOUT_SECONDS=90
```

如果本地缺少 `.env`，可先复制模板：

```powershell
Copy-Item .env.example .env
```

### 维护原则

- 日常使用者不再通过页面修改配置
- 如需更换 `VISION_API_KEY`、模型地址或超时参数，请直接修改 `.env`
- 修改 `.env` 后，如要发给别人继续使用，请重新执行打包脚本生成新的 `exe`

### 主要配置项

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `REQUEST_TIMEOUT_SECONDS` | `90` | 通用请求超时时间 |
| `RUNTIME_ROOT` | `.runtime` | 运行时缓存目录 |
| `VISION_API_KEY` | 空 | 必填，视觉模型接口密钥 |
| `VISION_BASE_URL` | `https://api.siliconflow.cn/v1` | 视觉模型兼容接口地址 |
| `VISION_MODEL` | `Qwen/Qwen3-VL-32B-Instruct` | 视觉模型 ID |
| `VISION_TIMEOUT_SECONDS` | `90` | 视觉模型请求超时时间 |

## Windows 打包与分发

### 打包命令

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\package-windows.ps1
```

### 打包产物

脚本会生成：

```text
dist/
├─ vocab-sheet-service.exe
└─ vocab-sheet-service.sha256.txt
```

### 当前打包行为

- 自动校验本地 `.env` 是否存在
- 自动安装或复用 `.venv` 中的 `PyInstaller`
- 自动把当前 `.env` 打进 `exe`
- 自动预载本地词典、Vosk 模型和相关 wheel
- 生成 SHA256 校验文件，便于分发后验包

### 使用建议

- 给外部使用者分发前，先确认 `.env` 中的密钥和模型参数就是要交付的版本
- 如担心文件损坏，可让对方校验 `SHA256`
- 如配置变更，重新打包，不建议让一线用户手动维护 `.env`

## 源码运行

### Windows

安装依赖：

```powershell
.\setup.ps1
```

开发环境安装：

```powershell
.\setup.ps1 -Dev
```

启动服务：

```powershell
.\start.ps1 -NoReload
```

后台启动并追日志：

```powershell
.\start.ps1 -Background -NoReload -TailLogs
```

### macOS / Linux

仓库自带的 PowerShell 脚本主要面向 Windows。
如需手动运行，可参考：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -e .[dev]
cp .env.example .env
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 清理生成物

### 推荐清理命令

```powershell
.\clean-generated.ps1
```

如果连运行时资源缓存也一起清掉：

```powershell
.\clean-generated.ps1 -IncludeRuntimeBootstrap
```

### 默认清理范围

- `build/`
- `dist/`
- `.pytest_cache/`
- `vocab_sheet_service.egg-info/`
- `.runtime/` 下除 `bootstrap/` 外的临时目录、测试目录、日志和任务输出
- `app/`、`tests/` 下的 `__pycache__/`
- 根目录里的 `tmp*`、`pytest-cache-files-*`、`*.egg-info`

### 说明

- 默认保留 `.runtime/bootstrap/`，避免下次重新下载大体积资源
- 打包产物位于 `dist/`，如果还要发给别人，请先备份后再执行清理

## HTTP 接口

### 基础接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查 |
| `GET` | `/` | Web 工作台页面 |
| `GET` | `/v1/vocab/template` | 返回固定模板说明 |

### 教材提词

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/v1/vocab/fill` | 同步生成词表并直接返回 Excel |
| `POST` | `/v1/vocab/jobs` | 创建异步教材提词任务 |
| `GET` | `/v1/vocab/jobs/{job_id}` | 查询异步任务状态 |
| `GET` | `/v1/vocab/jobs/{job_id}/download` | 下载异步任务生成的 Excel |

`POST /v1/vocab/fill` 请求字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `teaching_file` | 是 | 教材文件，支持 `.pdf` / `.docx` |
| `audio_file` | 否 | 音频文件，辅助提词 |
| `words_text` | 否 | 手工补充单词文本 |

### 课后反馈

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/v1/feedback/jobs` | 创建课后反馈任务 |
| `GET` | `/v1/feedback/jobs/{job_id}` | 查询反馈任务状态 |
| `POST` | `/v1/feedback/jobs/{job_id}/sections/{section_key}/regenerate` | 重新生成某一个反馈模块 |

`POST /v1/feedback/jobs` 请求字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `lesson_date` | 是 | 上课日期，如 `2026-04-29` |
| `lesson_index` | 是 | 节次，从 `1` 开始 |
| `class_name` | 否 | 班级或课程名 |
| `transcript_text` | 否 | 逐字稿或补充笔记 |
| `audio_file` | 否 | 课堂音频 |

说明：

- `audio_file` 和 `transcript_text` 至少提供一个
- 两者同时提供时，系统会合并内容后生成反馈草稿

### 维护接口

以下接口仍保留，但默认页面已隐藏对应入口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/v1/settings` | 读取当前配置 |
| `PUT` | `/v1/settings` | 保存配置 |
| `POST` | `/v1/settings/validate` | 校验配置连通性 |
| `POST` | `/v1/audio/transcribe` | 音频转文本并返回候选单词 |

## 开发与测试

推荐先执行：

```powershell
.\setup.ps1 -Dev
```

运行测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

当前测试覆盖重点包括：

- PDF / DOCX 解析
- 固定模板写入
- 词典与语音运行时资源准备
- 路由错误映射
- 配置读写与校验
- 课后反馈生成链路

## 常见问题

### 1. 双击 EXE 没反应或启动失败

先尝试在 PowerShell 中直接运行：

```powershell
.\vocab-sheet-service.exe --host 127.0.0.1 --port 18080 --no-browser
```

再观察控制台报错信息。

### 2. 想改 Key，但页面里看不到“系统配置”

这是当前设计。
请由维护者修改项目根目录 `.env`，然后重新打包 `exe`。

### 3. 第一次业务处理为什么还是稍慢

虽然打包时已预载资源，但单文件 `exe` 首次启动仍需要解包，
并把内置资源恢复到同目录下的 `.runtime/`。

### 4. 源码模式启动时报 `缺少 VISION_API_KEY`

说明当前 `.env` 没有填好。
请复制 `.env.example` 到 `.env` 并补齐密钥。

### 5. 是否必须保留 `dist/`

不是。
`dist/` 只是打包输出目录，随时可以删除并通过打包脚本重新生成。

## 项目结构

```text
vocab-sheet-service/
├─ app/
│  ├─ api/
│  ├─ models/
│  ├─ services/
│  ├─ utils/
│  ├─ web/
│  └─ portable_entry.py
├─ docs/
│  └─ 用户操作手册.md
├─ template/
│  └─ 单词表模板.xlsx
├─ tests/
├─ .env.example
├─ README.md
├─ clean-generated.ps1
├─ package-windows.ps1
├─ pyproject.toml
├─ setup.ps1
├─ start.ps1
└─ vocab-sheet-service.spec
```
