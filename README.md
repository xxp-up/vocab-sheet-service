# Vocab Sheet Service

基于 FastAPI 的教材抽词与词表回填服务。

当前服务流程：
1. 上传教材文件 `PDF` / `DOCX`
2. 识别教材中的重点英文词
3. 可选结合音频识别结果和手工补词
4. 用本地免费词典补全音标、词性、中文释义
5. 从教材正文中定位例句
6. 回填到固定模板 `template/单词表模板.xlsx`
7. 返回生成后的 `.xlsx`

## 环境要求
- 运行机器必须预先安装 **Python 3.12**
- `pyproject.toml` 已限制为 `>=3.12,<3.13`
- Windows 下推荐安装官方 Python 3.12，并勾选加入 `PATH`
- 首次执行 `setup.ps1` 需要联网安装依赖
- 首次处理词典或音频时，服务仍会联网下载运行时资源

## 快速开始

### Windows 用户

1. 先确认本机已安装 Python 3.12
2. 在项目根目录执行：

```powershell
.\setup.ps1
```

3. 编辑 `.env`，填写：

```env
VISION_API_KEY=你的密钥
```

4. 启动服务：

```powershell
.\start.ps1 -NoReload
```

5. 浏览器打开 `http://127.0.0.1:8000/`

### 开发者模式

如果你需要运行测试或继续开发，推荐直接安装开发依赖：

```powershell
.\setup.ps1 -Dev
```

这会在项目根目录创建或复用 `.venv/`，并安装 `.[dev]`。

### macOS / Linux

本仓库提供的 `setup.ps1` 主要面向 Windows。macOS / Linux 请手动执行：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -e .[dev]
cp .env.example .env
```

然后填写：

```env
VISION_API_KEY=你的密钥
```

## 安装脚本说明

### `setup.ps1`

作用：

- 检查本机是否可用 Python 3.12
- 创建 `.venv/`
- 安装项目依赖
- 在缺少 `.env` 时自动从 `.env.example` 复制

常用命令：

```powershell
.\setup.ps1
.\setup.ps1 -Dev
```

说明：

- `.\setup.ps1` 安装运行依赖
- `.\setup.ps1 -Dev` 额外安装测试开发依赖
- 如果已有的 `.venv` 不是 Python 3.12，或是旧版内置环境残留导致缺少 `pip`，脚本会自动重建

## 启动服务

### 前台启动

```powershell
.\start.ps1 -NoReload
```

说明：

- 前台模式下，接口访问日志和应用处理日志会直接打印到当前控制台
- 启动脚本会优先使用 `.venv\Scripts\python.exe`
- 如果 `.venv` 不存在，会尝试使用本机安装的 Python 3.12
- 如果当前 Python 3.12 环境里缺少依赖，启动前检查会提示先执行 `.\setup.ps1`

### 后台启动并实时看日志

```powershell
.\start.ps1 -Background -NoReload -TailLogs
```

说明：

- 服务在后台运行
- 当前窗口会持续追踪 `.runtime/logs/uvicorn.stderr.log` 和 `.runtime/logs/uvicorn.stdout.log`
- 按 `Ctrl+C` 只会停止“看日志”，不会停掉后台服务

### 常见启动方式

```powershell
.\start.ps1
.\start.ps1 -Port 8001
.\start.ps1 -HostAddress 0.0.0.0 -Port 8000 -NoReload
.\start.ps1 -Background
.\start.ps1 -Background -NoReload -TailLogs
```

参数说明：

- `-NoReload`：关闭热重载，适合稳定运行或分发后使用
- `-Background`：后台启动
- `-TailLogs`：后台启动后在当前窗口实时追踪日志

## 配置说明

复制配置模板：

```powershell
copy .env.example .env
```

支持的环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `REQUEST_TIMEOUT_SECONDS` | `90` | 通用下载超时时间 |
| `RUNTIME_ROOT` | `.runtime` | 运行时缓存目录 |
| `VISION_API_KEY` | 空 | 必填，视觉模型接口密钥 |
| `VISION_BASE_URL` | `https://api.siliconflow.cn/v1` | 硅基流动兼容接口地址 |
| `VISION_MODEL` | `Qwen/Qwen3-VL-32B-Instruct` | 视觉模型 ID |
| `VISION_TIMEOUT_SECONDS` | `90` | 视觉模型调用超时时间 |

当前安全策略：

- 代码里不再硬编码第三方 Key
- 分享给别人时，推荐使用 `windows-share` 包，不带 `.env`
- 内部直接用时，可使用 `windows-internal` 包，打包脚本会在本地存在 `.env` 时一起带上

## 打包给别人使用

执行：

```powershell
.\package-windows.ps1
```

脚本会生成：

```text
dist/
├─ windows-share/
└─ windows-internal/
```

### 新的分发约定

- **两个包都不再携带 `.python312`**
- **接收方必须本机安装 Python 3.12**
- **接收方首次使用前必须先执行 `.\setup.ps1`**

### `windows-share`

适合发给外部或其他同事：

- 不带 `.env`
- 接收方需要自行填写 `VISION_API_KEY`
- 接收方需要先安装 Python 3.12，再执行安装脚本

接收方操作：

1. 确认本机已安装 Python 3.12
2. 执行 `.\setup.ps1`
3. 把 `.env.example` 复制成 `.env`
4. 填好 `VISION_API_KEY`
5. 执行 `.\start.ps1 -NoReload`
6. 打开 `http://127.0.0.1:8000/`

### `windows-internal`

适合内部直接使用：

- 如果你本机有 `.env`，打包时会一起复制进去
- 接收方仍然需要先安装 Python 3.12
- 第一次运行前仍然要先执行 `.\setup.ps1`

### 分发包里默认包含什么

- `app/`
- `template/`
- `pyproject.toml`
- `setup.ps1`
- `start.ps1`
- `clean-generated.ps1`
- `README.md`
- `.env.example`

默认不包含：

- `.python312/`
- `.runtime/bootstrap/`
- `tests/`
- `.venv/`
- 私有 `.env`（仅 `windows-internal` 在本地存在 `.env` 时才会带）

## 首次运行会下载什么

首次处理词典或音频时，服务会自动下载并缓存到 `RUNTIME_ROOT`：

- `cmudict`
- `cedict`
- `Vosk` 英文小模型
- 本地语音识别依赖 wheel

默认缓存位置：

```text
.runtime/bootstrap/
```

这意味着：

- 第一次执行 `setup.ps1` 需要联网安装 Python 依赖
- 第一次业务请求可能更慢
- 第一次运行仍需要能访问外网下载运行时资源
- 下载完成后会复用本地缓存

## 哪些目录和文件是干嘛的

### 需要保留的核心内容

| 路径 | 作用 | 是否建议保留 |
| --- | --- | --- |
| `app/` | 服务源码 | 是 |
| `template/` | 固定 Excel 模板 | 是 |
| `tests/` | 自动化测试 | 开发时保留 |
| `pyproject.toml` | 依赖与 Python 版本约束 | 是 |
| `setup.ps1` | Windows 安装脚本 | 是 |
| `start.ps1` | 主启动脚本 | 是 |
| `clean-generated.ps1` | 清理生成物脚本 | 建议保留 |
| `package-windows.ps1` | 生成 Windows 分发包 | 打包时保留 |
| `.env.example` | 配置模板 | 是 |
| `README.md` | 使用说明 | 是 |

### 常见生成物，可以删除

| 路径 | 来源 | 是否可删 |
| --- | --- | --- |
| `pytest-cache-files-*` | `pytest` 创建缓存目录失败后遗留的临时目录 | 可以 |
| `tmp*` | 临时目录 | 可以 |
| `__pycache__/` | Python 字节码缓存 | 可以 |
| `vocab_sheet_service.egg-info/` | `pip install -e .` 生成的包元数据 | 可以 |
| `.pytest_cache/` | pytest 缓存 | 可以 |
| `.runtime/logs/` | 运行日志 | 可以 |
| `dist/` | 打包输出目录 | 可以 |

可以直接执行：

```powershell
.\clean-generated.ps1
```

如果连首次下载的词典/语音资源也想一起清掉：

```powershell
.\clean-generated.ps1 -IncludeRuntimeBootstrap
```

### 本地运行环境相关目录

| 路径 | 作用 | 说明 |
| --- | --- | --- |
| `.venv/` | 本地虚拟环境 | 由 `setup.ps1` 或手工 `venv` 创建，可删后重建 |
| `.runtime/bootstrap/` | 运行时自动下载的词典、Vosk 模型、wheel 缓存 | 可删，但下次会重新下载 |

## HTTP 接口

### `GET /health`

健康检查：

```json
{
  "status": "ok"
}
```

### `GET /`

返回本地调试用上传页面。

### `POST /v1/vocab/fill`

使用 `multipart/form-data` 上传教材并生成词表。

请求字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `teaching_file` | 是 | 教材文件，支持 `.pdf` / `.docx` |
| `audio_file` | 否 | 音频文件，辅助提词 |
| `words_text` | 否 | 手工补充单词文本 |

成功时直接返回 `.xlsx` 文件流，下载文件名规则：

```text
{teaching_file.stem}.xlsx
```

响应头：

- `X-Words-Written`
- `X-Words-Skipped`
- `X-Skipped-Reasons`

`curl` 示例：

```bash
curl.exe -X POST "http://127.0.0.1:8000/v1/vocab/fill" ^
  -F "teaching_file=@lesson.pdf" ^
  -F "audio_file=@lesson.mp3" ^
  -F "words_text=apple, improve, watch"
```

## 开发与测试

推荐先执行：

```powershell
.\setup.ps1 -Dev
```

然后运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

如果你已经手动激活了 Python 3.12 虚拟环境，也可以：

```powershell
python -m pytest -q
```

当前测试覆盖：

- 视觉接口 JSON 解析、超时和上游错误
- 练习题句子还原
- PDF / DOCX 解析
- 固定模板写入
- 路由错误映射
- pipeline 在无词和全跳过场景下的行为
- 运行时资源下载重试

## 常见问题

### 1. 启动时报 `Python 3.12 interpreter not found`

说明当前机器没有可用的 Python 3.12。请先安装 Python 3.12，再执行：

```powershell
.\setup.ps1
```

### 2. 启动时报缺少依赖或 `ModuleNotFoundError`

说明当前 Python 3.12 环境还没有安装项目依赖。执行：

```powershell
.\setup.ps1
```

如果你是开发者：

```powershell
.\setup.ps1 -Dev
```

### 3. 启动时报 `缺少 VISION_API_KEY`

处理方法：

1. 复制 `.env.example` 为 `.env`
2. 填写 `VISION_API_KEY`
3. 重新执行 `.\start.ps1 -NoReload`

### 4. 能启动，但第一次处理很慢

正常。首次会下载词典和语音模型资源。

### 5. 为什么控制台没日志

- 前台启动请用 `.\start.ps1 -NoReload`
- 后台启动请用 `.\start.ps1 -Background -NoReload -TailLogs`
- 也可以直接看 `.runtime/logs/uvicorn.stderr.log`

### 6. `.venv` 不是 Python 3.12，或旧环境没有 `pip` 怎么办

直接重新执行：

```powershell
.\setup.ps1
```

脚本会自动用本机 Python 3.12 重建 `.venv/`。

## 项目结构

```text
vocab-sheet-service/
├─ app/
│  ├─ api/
│  ├─ models/
│  ├─ services/
│  └─ utils/
├─ template/
│  └─ 单词表模板.xlsx
├─ tests/
├─ .env.example
├─ README.md
├─ clean-generated.ps1
├─ package-windows.ps1
├─ pyproject.toml
├─ setup.ps1
└─ start.ps1
```
