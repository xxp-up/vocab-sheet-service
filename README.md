# Vocab Sheet Service

基于 FastAPI 的教材抽词与词表回填服务。

当前服务流程：

1. 上传教材文件 `PDF` / `DOCX`
2. 识别教材中的重点英文词
3. 可选结合音频识别结果和手工补词
4. 用本地免费词典补全音标、词性、中文释义
5. 从教材正文中定位例句
6. 回填到固定模板 `template/test 6单词表模板.xlsx`
7. 返回生成后的 `.xlsx`

## 先看你属于哪种用法

### 1. Windows 用户，没有 Python 环境

优先使用“便携包模式”：

1. 拿到打包后的 `windows-share` 或 `windows-internal` 目录
2. 如果目录里没有 `.env`，就把 `.env.example` 复制成 `.env`
3. 在 `.env` 里填写 `VISION_API_KEY`
4. 双击 `start.bat`
5. 浏览器打开 `http://127.0.0.1:8000/`

特点：

- 不需要自己装 Python，只要包里带了 `.python312`
- 日志直接显示在启动控制台
- 关闭控制台或按 `Ctrl+C` 就会停止前台服务

### 2. 开发者，或需要跨平台扩展

使用“源码安装模式”。

Windows：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\activate
pip install -e .[dev]
copy .env.example .env
```

macOS / Linux：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
```

然后编辑 `.env`：

```env
VISION_API_KEY=你的密钥
```

## 傻瓜式启动

### 前台启动，日志直接看控制台

推荐命令：

```powershell
.\start.ps1 -NoReload
```

最简单的 Windows 双击启动：

```text
start.bat
```

说明：

- 前台模式下，接口访问日志和应用处理日志会直接打印到当前控制台
- 启动脚本会先做预检查：缺少 `VISION_API_KEY` 或缺依赖时，会直接报清晰错误并退出

### 后台启动，同时在当前控制台实时看日志

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

- `-NoReload`：关闭热重载，适合稳定运行或打包后使用
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
- 内部直接用时，可使用 `windows-internal` 包，脚本会在本地存在 `.env` 时一起带上

## 哪些目录和文件是干嘛的

### 需要保留的核心内容

| 路径 | 作用 | 是否建议保留 |
| --- | --- | --- |
| `app/` | 服务源码 | 是 |
| `template/` | 固定 Excel 模板 | 是 |
| `tests/` | 自动化测试 | 开发时保留 |
| `start.ps1` | 主启动脚本 | 是 |
| `start.bat` | Windows 一键启动入口 | Windows 推荐保留 |
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

注意：

- 你截图里的 `pytest-cache-files-*` 就是 pytest 的生成物，不是业务代码
- 安全删除前提是：当前没有在跑测试，也没有服务正在占用这些目录
- 可以直接执行：

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
| `.venv/` | 你自己创建的虚拟环境 | 开发专用，可删后重建 |
| `.python312/` | 便携 Python 运行时 | 便携包模式会用到 |
| `.runtime/bootstrap/` | 运行时自动下载的词典、Vosk 模型、wheel 缓存 | 可删，但下次会重新下载 |
| `python-3.12.9-amd64.exe` | Windows Python 安装包 | 只是安装器，不是业务必须文件 |

结论：

- 如果你只做开发，`.venv/` 比 `.python312/` 更常用
- 如果你要“打包给没有 Python 环境的人”，`.python312/` 最有用
- `python-3.12.9-amd64.exe` 不是运行必须文件，不需要时可以删

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

### `windows-share`

适合发给外部或其他同事：

- 不带 `.env`
- 默认要求接收方自己填写 `VISION_API_KEY`
- 如果包内带 `.python312`，接收方不需要自己装 Python

接收方操作：

1. 把 `.env.example` 复制成 `.env`
2. 填好 `VISION_API_KEY`
3. 双击 `start.bat`
4. 打开 `http://127.0.0.1:8000/`

### `windows-internal`

适合内部直接用：

- 如果你本机有 `.env`，打包时会一起复制进去
- 接收方通常直接双击 `start.bat` 即可

### 便携包里默认包含什么

- `app/`
- `template/`
- `start.ps1`
- `start.bat`
- `clean-generated.ps1`
- `README.md`
- `.env.example`
- `.python312/`（如果本地存在）

默认不包含：

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

- 第一次请求可能更慢
- 第一次运行需要能访问外网
- 下载完成后会复用本地缓存

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
{teaching_file.stem}_filled.xlsx
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

如果仓库里有便携解释器：

```powershell
.\.python312\python.exe -m pytest -q
```

如果你走 `.venv`：

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

### 1. 启动时报 `缺少 VISION_API_KEY`

处理方法：

1. 复制 `.env.example` 为 `.env`
2. 填写 `VISION_API_KEY`
3. 重新执行 `.\start.ps1 -NoReload` 或双击 `start.bat`

### 2. 能启动，但第一次处理很慢

正常。首次会下载词典和语音模型资源。

### 3. 为什么控制台没日志

- 前台启动请用 `.\start.ps1 -NoReload`
- 后台启动请用 `.\start.ps1 -Background -NoReload -TailLogs`
- 也可以直接看 `.runtime/logs/uvicorn.stderr.log`

### 4. `pytest-cache-files-*` 能不能删

可以。它们是 pytest 生成物，不是业务代码。停掉测试和服务后删最稳妥，或直接运行：

```powershell
.\clean-generated.ps1
```

## 项目结构

```text
vocab-sheet-service/
├─ app/
│  ├─ api/
│  ├─ models/
│  ├─ services/
│  └─ utils/
├─ template/
│  └─ test 6单词表模板.xlsx
├─ tests/
├─ .env.example
├─ README.md
├─ clean-generated.ps1
├─ package-windows.ps1
├─ start.bat
└─ start.ps1
```
