# LC Auto

LC Auto 是一个面向 [LeetCode 中文站](https://leetcode.cn/) 的本地自动化命令行工具。

它会连接你已经登录的 Chrome 浏览器，读取题目内容，调用 OpenAI-compatible Chat Completions 模型生成 Python3 解法，并把代码写入力扣编辑器。默认情况下，工具只会运行代码检查流程；只有你显式开启 `allow_real_submit` 后，才会进行真实提交。

> 当前项目仍是 MVP：只支持 `leetcode.cn`，只生成 Python3 解法，不处理验证码、风控、安全验证或任何反自动化绕过。

## 功能概览

- 连接本机已登录的 Chrome，而不是在容器中接管登录流程。
- 支持 OpenAI、DeepSeek 等兼容 `/chat/completions` 的模型接口。
- 支持按题号顺序运行，也支持指定题目 slug 运行。
- 支持 dry-run、真实提交、失败后自动修复重试。
- 自动保存题目状态、运行结果、代码产物和截图。
- 遇到会员题、缺失题号、SQL / Pandas 等非 Python3 题目时会跳过并记录状态。

## 使用前请注意

本工具只用于个人学习和本地自动化实验，请遵守 LeetCode 中文站的使用规则。

LC Auto 不会、也不应该用于：

- 绕过验证码、登录校验、安全验证或风控机制；
- 竞赛、考试、面试等不允许自动化辅助的场景；
- 高频、批量、异常模式的自动提交。

默认配置中：

```yaml
allow_real_submit: false
```

也就是说，工具默认不会真实提交。开启真实提交前，请先用 `doctor` 和 `dry-run` 确认环境正常。

## 快速开始：Docker 推荐方式

普通用户建议优先使用公共 Docker 镜像，不需要在本地配置 Python 环境。

### 1. 克隆项目

```powershell
git clone https://github.com/xieluyao60-coder/lc-auto.git
cd lc-auto
```

### 2. 拉取镜像并初始化配置

Windows PowerShell：

```powershell
docker pull ghcr.io/xieluyao60-coder/lc-auto:latest
if (!(Test-Path .env)) { Copy-Item .env.example .env }
docker compose -f docker-compose.ghcr.yml run --rm lc-auto init
```

macOS / Linux：

```bash
docker pull ghcr.io/xieluyao60-coder/lc-auto:latest
[ -f .env ] || cp .env.example .env
docker compose -f docker-compose.ghcr.yml run --rm lc-auto init
```

初始化后会生成：

```text
.env
docker-data/config.yaml
docker-data/problems.txt
```

其中：

- `.env`：保存模型 API 参数；
- `docker-data/config.yaml`：保存工具运行配置；
- `docker-data/`：保存状态数据库、运行产物和截图。

### 3. 填写模型配置

编辑 `.env`：

```env
LC_AUTO_MODEL_API_KEY=你的密钥
LC_AUTO_MODEL_BASE_URL=https://api.openai.com/v1
LC_AUTO_MODEL_NAME=你的模型名
```

如果使用 DeepSeek，可以写成类似下面这样：

```env
LC_AUTO_MODEL_API_KEY=你的密钥
LC_AUTO_MODEL_BASE_URL=https://api.deepseek.com
LC_AUTO_MODEL_NAME=deepseek-chat
```

只想测试命令流程、不消耗模型额度时，可以把 `docker-data/config.yaml` 中的模型提供方改为：

```yaml
model:
  provider: fake
```

`fake` 模型只适合 smoke test，不适合真实解题。

### 4. 启动带 CDP 端口的 Chrome

工具需要连接一个已经登录力扣的 Chrome。请先用下面命令启动 Chrome，然后在打开的浏览器里手动登录 `https://leetcode.cn/`。

Windows PowerShell：

```powershell
$chrome = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
if (!(Test-Path $chrome)) { $chrome = "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe" }

& $chrome --remote-debugging-port=9222 --user-data-dir="$PWD\.chrome-cdp-profile"
```

如果 Docker 容器无法连接到 Chrome，可以改用：

```powershell
& $chrome --remote-debugging-address=0.0.0.0 --remote-debugging-port=9222 --user-data-dir="$PWD\.chrome-cdp-profile"
```

macOS：

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$PWD/.chrome-cdp-profile"
```

Linux：

```bash
google-chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$PWD/.chrome-cdp-profile"
```

登录成功后，请保持这个 Chrome 窗口不要关闭。

### 5. 检查环境

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto doctor --config /data/config.yaml
```

重点确认下面几项为 `OK`：

- `model`
- `browser_cdp_url`
- `state_db_parent`

### 6. 运行

从第 1 题开始，最多运行 3 题：

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto run-seq --start 1 --reset-progress --limit 3 --config /data/config.yaml
```

继续上次顺序进度：

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto run-seq --limit 3 --config /data/config.yaml
```

运行指定题目：

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto run --problem two-sum --config /data/config.yaml
```

只测试单题流程，不真实提交：

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto dry-run --problem two-sum --config /data/config.yaml
```

## 开启真实提交

真实提交默认关闭。确认 dry-run 和 doctor 都正常后，再编辑 `docker-data/config.yaml`：

```yaml
allow_real_submit: true
```

第一次真实运行建议保守一些：

```yaml
allow_real_submit: true
max_questions_per_run: 1
max_repairs_per_problem: 3
min_delay_seconds: 60
max_delay_seconds: 180
```

真实提交需要同时满足：

- `allow_real_submit: true`；
- 使用 `run` 或 `run-seq`；
- 没有使用 `dry-run`。

## 常用命令

下面命令均以 Docker 方式为例。

### 查看运行状态

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto status --config /data/config.yaml
```

### 恢复未完成题目

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto resume --config /data/config.yaml
```

### 导出状态数据库

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto export --output /data/state_export.json --config /data/config.yaml
```

### 从指定题号重新开始

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto run-seq --start 175 --reset-progress --limit 3 --config /data/config.yaml
```

### 强制重跑已 AC 题目

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto run-seq --start 2 --reset-progress --rerun-accepted --limit 1 --config /data/config.yaml
```

### 更新镜像

```powershell
docker pull ghcr.io/xieluyao60-coder/lc-auto:latest
```

## 配置说明

主要配置在 `docker-data/config.yaml` 中。

| 配置项 | 作用 | 默认值 |
| --- | --- | --- |
| `site` | 目标站点，目前只支持 `leetcode.cn` | `leetcode.cn` |
| `language` | 生成代码语言，目前只支持 Python3 | `python3` |
| `allow_real_submit` | 是否允许真实提交 | `false` |
| `max_questions_per_run` | 单次最多运行题目数 | `3` |
| `max_repairs_per_problem` | 单题失败后最多修复次数 | `3` |
| `browser_cdp_url` | Chrome DevTools 地址 | Docker 通常为 `http://host.docker.internal:9222` |
| `state_db_path` | 状态数据库路径 | `./lc_auto.sqlite3` |
| `artifact_dir` | 运行产物目录 | `./artifacts` |
| `min_delay_seconds` / `max_delay_seconds` | 题目之间的等待区间 | `60` / `180` |
| `stop_on_security_challenge` | 遇到安全验证时停止 | `true` |
| `skip_accepted` | 是否跳过已记录 AC 的题 | `true` |

模型配置可以通过 `.env` 提供：

```env
LC_AUTO_MODEL_API_KEY=你的密钥
LC_AUTO_MODEL_BASE_URL=模型服务地址
LC_AUTO_MODEL_NAME=模型名称
```

## 运行数据保存位置

Docker 模式下，所有本地数据都保存在 `docker-data/`：

```text
docker-data/config.yaml        本地配置
docker-data/lc_auto.sqlite3    题目状态和顺序进度
docker-data/artifacts/         每题题面、代码、结果和截图
docker-data/problems.txt       题目 slug 列表
```

顺序刷题进度保存在 SQLite 的 `sequence_progress` 表中。只有真实提交并 AC 后，顺序进度才会推进。

## 本地 Python 运行方式

如果不想使用 Docker，也可以直接用 Python 运行。

### 1. 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
python -m playwright install chromium
python -m lc_auto init
```

### 2. 启动 Chrome

```powershell
$chrome = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
if (!(Test-Path $chrome)) { $chrome = "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe" }
& $chrome --remote-debugging-port=9222 --user-data-dir="$PWD\.chrome-cdp-profile"
```

### 3. 运行命令

```powershell
python -m lc_auto doctor --config config.yaml --cdp-url http://127.0.0.1:9222
python -m lc_auto run-seq --limit 3 --config config.yaml --cdp-url http://127.0.0.1:9222
```

也可以把 CDP 地址写入 `config.yaml`：

```yaml
browser_cdp_url: http://127.0.0.1:9222
```

写入后，命令中可以省略 `--cdp-url`。

## 常见问题

### doctor 提示 `browser_cdp_url` 不通

请确认 Chrome 是用 `--remote-debugging-port=9222` 启动的，并且没有关闭。

Docker 用户通常使用：

```yaml
browser_cdp_url: http://host.docker.internal:9222
```

本地 Python 用户通常使用：

```yaml
browser_cdp_url: http://127.0.0.1:9222
```

### 登录或安全验证过不去

请在普通 Chrome 中手动完成登录或验证。工具不会绕过验证码、安全验证或风控提示。

### 为什么没有真实提交？

请检查三件事：

1. `allow_real_submit` 是否为 `true`；
2. 是否运行的是 `run` 或 `run-seq`；
3. 是否误用了 `dry-run`。

### 为什么 SQL / Pandas 题会跳过？

当前版本只生成 Python3 解法。无法切换到 Python3 的题目会被记录为 `unsupported_language`，然后跳过。

### 如何降低运行风险？

建议第一次真实运行只跑 1 题，并保留较长延迟：

```yaml
allow_real_submit: true
max_questions_per_run: 1
min_delay_seconds: 60
max_delay_seconds: 180
```

确认流程稳定后，再逐步调整运行数量。

## 开发者命令

```powershell
python -m pytest
python -m compileall lc_auto
docker compose -f docker-compose.ghcr.yml config --quiet
```

## License

如果你计划公开复用或分发本项目，建议补充明确的开源许可证文件。
