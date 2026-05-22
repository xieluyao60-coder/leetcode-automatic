# LC Auto

一个用于 `leetcode.cn` 的本地自动化命令行工具。

它会控制你已经登录的 Chrome 浏览器，按题号顺序打开题目，调用 OpenAI-compatible 大模型生成 Python3 解法并写入编辑器。开启真实提交后，它会自动提交；提交失败时会把错误信息交给模型修正后重试。遇到 SQL、Pandas 等无法切换到 Python3 的题会自动跳过。

## 先看结论

推荐普通用户使用公共 Docker 镜像，不需要本地安装 Python：

下面命令默认使用 Windows PowerShell。macOS/Linux 用户把 `Copy-Item .env.example .env` 换成 `cp .env.example .env` 即可。

```powershell
git clone https://github.com/xieluyao60-coder/lc-auto.git
cd lc-auto

docker pull ghcr.io/xieluyao60-coder/lc-auto:latest
if (!(Test-Path .env)) { Copy-Item .env.example .env }
docker compose -f docker-compose.ghcr.yml run --rm lc-auto init
```

然后做三件事：

1. 编辑 `.env`，填你的模型 API 参数。
2. 编辑 `docker-data/config.yaml`，确认是否开启真实提交。
3. 启动一个带 CDP 端口的 Chrome，手动登录力扣。

最后运行：

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto doctor --config /data/config.yaml
docker compose -f docker-compose.ghcr.yml run --rm lc-auto run-seq --limit 3 --config /data/config.yaml
```

## 重要边界

- 本工具不绕过验证码、安全验证、风控、登录校验或反自动化机制。
- 默认不会真实提交，`allow_real_submit` 默认为 `false`。
- 真实提交必须由用户手动改配置开启。
- 遇到验证码、登录失效、风控提示、页面结构无法识别时会停止。
- 遇到无法使用 Python3 的题会记录为 `unsupported_language` 并跳过。
- 不建议在竞赛、考试、面试等不允许自动化辅助的场景使用。

## 准备条件

你需要：

- Docker Desktop
- Git
- Google Chrome
- 一个 OpenAI-compatible Chat Completions API

模型接口需要兼容 `/chat/completions`。例如 OpenAI、DeepSeek 或其他兼容服务都可以。

## 第一步：获取项目

```powershell
git clone https://github.com/xieluyao60-coder/lc-auto.git
cd lc-auto
```

如果你已经有项目目录，直接进入该目录即可。

## 第二步：初始化 Docker 运行目录

拉取公共镜像：

```powershell
docker pull ghcr.io/xieluyao60-coder/lc-auto:latest
```

生成本地配置：

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
docker compose -f docker-compose.ghcr.yml run --rm lc-auto init
```

初始化后会出现：

```text
.env
docker-data/config.yaml
docker-data/problems.txt
```

其中 `.env` 保存模型密钥，`docker-data/` 保存运行状态、配置和产物。它们不会被提交到 Git。

## 第三步：填写模型配置

编辑 `.env`：

```env
LC_AUTO_MODEL_API_KEY=你的密钥
LC_AUTO_MODEL_BASE_URL=https://api.openai.com/v1
LC_AUTO_MODEL_NAME=你的模型名
```

如果使用 DeepSeek，通常类似：

```env
LC_AUTO_MODEL_API_KEY=你的密钥
LC_AUTO_MODEL_BASE_URL=https://api.deepseek.com
LC_AUTO_MODEL_NAME=deepseek-chat
```

只想测试流程、不消耗模型额度时，可以把 `docker-data/config.yaml` 里的模型配置改成：

```yaml
model:
  provider: fake
```

fake 模型只适合 smoke test，不适合真实刷题。

## 第四步：启动 Chrome 并登录力扣

工具推荐连接宿主机 Chrome，而不是在容器里打开浏览器。这样登录、安全验证和验证码都由你自己在正常 Chrome 中完成。

Windows PowerShell：

```powershell
$chrome = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
if (!(Test-Path $chrome)) { $chrome = "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe" }

& $chrome --remote-debugging-port=9222 --user-data-dir="$PWD\.chrome-cdp-profile"
```

如果容器里提示连不上 Chrome，可以改成：

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

Chrome 打开后，手动访问并登录：

```text
https://leetcode.cn/
```

登录成功后保持这个 Chrome 不要关闭。

## 第五步：检查环境

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto doctor --config /data/config.yaml
```

看到关键项都是 `OK` 后再运行。尤其要确认：

- `model` 是 OK
- `browser_cdp_url` 是 OK
- `state_db_parent` 是 OK

## 第六步：开始运行

### 按题号顺序运行

第一次从第 1 题开始：

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto run-seq --start 1 --reset-progress --limit 3 --config /data/config.yaml
```

以后继续上次进度：

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto run-seq --limit 3 --config /data/config.yaml
```

从指定题号重新开始：

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto run-seq --start 175 --reset-progress --limit 3 --config /data/config.yaml
```

### 跑指定题目

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto run --problem two-sum --config /data/config.yaml
```

### dry-run 单题测试

dry-run 不会真实提交：

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto dry-run --problem two-sum --config /data/config.yaml
```

## 开启真实提交

默认配置不会真实提交。要开启真实提交，编辑 `docker-data/config.yaml`：

```yaml
allow_real_submit: true
```

建议第一次真实提交时先保守设置：

```yaml
allow_real_submit: true
max_questions_per_run: 1
max_repairs_per_problem: 3
min_delay_seconds: 60
max_delay_seconds: 180
```

真实提交必须同时满足：

- `allow_real_submit: true`
- 使用 `run` 或 `run-seq`
- 不使用 `dry-run`

## 常用命令

查看最近运行状态：

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto status --config /data/config.yaml
```

恢复未完成题目：

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto resume --config /data/config.yaml
```

导出状态：

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto export --output /data/state_export.json --config /data/config.yaml
```

强制重跑已经记录为 accepted 的题：

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto run-seq --start 2 --reset-progress --rerun-accepted --limit 1 --config /data/config.yaml
```

## 运行状态保存在哪里

Docker 模式下，所有运行数据都在 `docker-data/`：

```text
docker-data/config.yaml        本地配置
docker-data/lc_auto.sqlite3    题目状态和顺序进度
docker-data/artifacts/         每题题面、代码、结果和截图
```

顺序刷题进度保存在 SQLite 的 `sequence_progress` 表里。只有真实提交并 AC 后，下一题进度才会推进。会员题、缺失题号、无法切换到 Python3 的题会跳过并记录。

## 更新镜像

```powershell
docker pull ghcr.io/xieluyao60-coder/lc-auto:latest
```

如果你用的是旧仓库名或旧镜像名，请改成：

```text
https://github.com/xieluyao60-coder/lc-auto
ghcr.io/xieluyao60-coder/lc-auto:latest
```

## 本地 Python 运行方式

如果你不想用 Docker，可以本地安装：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
python -m playwright install chromium
python -m lc_auto init
```

编辑 `.env` 和 `config.yaml` 后，启动 Chrome CDP：

```powershell
$chrome = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
if (!(Test-Path $chrome)) { $chrome = "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe" }
& $chrome --remote-debugging-port=9222 --user-data-dir="$PWD\.chrome-cdp-profile"
```

本地运行：

```powershell
python -m lc_auto doctor --config config.yaml --cdp-url http://127.0.0.1:9222
python -m lc_auto run-seq --limit 3 --config config.yaml --cdp-url http://127.0.0.1:9222
```

也可以把 CDP 地址写入 `config.yaml`：

```yaml
browser_cdp_url: http://127.0.0.1:9222
```

写入后命令可以省略 `--cdp-url`。

## 常见问题

### doctor 提示 browser_cdp_url 不通

确认 Chrome 是用 `--remote-debugging-port=9222` 启动的，并且这个 Chrome 没有关闭。

Docker 用户的 `docker-data/config.yaml` 应该是：

```yaml
browser_cdp_url: http://host.docker.internal:9222
```

本地 Python 用户通常是：

```yaml
browser_cdp_url: http://127.0.0.1:9222
```

### 登录时安全验证过不了

不要用工具尝试绕过验证。使用普通 Chrome 手动登录，再让工具连接这个 Chrome。登录成功后保持 Chrome 不关闭。

### 为什么没有提交

检查 `docker-data/config.yaml` 或 `config.yaml`：

```yaml
allow_real_submit: true
```

同时确认你运行的是 `run` 或 `run-seq`，不是 `dry-run`。

### 为什么遇到 SQL 题会跳过

当前版本只生成 Python3 解法。SQL、Pandas 或其他无法切换到 Python3 的题会记录为 `unsupported_language` 并跳到下一题。

### 如何降低风险

第一次真实运行建议：

```yaml
allow_real_submit: true
max_questions_per_run: 1
min_delay_seconds: 60
max_delay_seconds: 180
```

先只跑 1 题，确认流程正常后再提高 `max_questions_per_run`。

## 开发者检查

```powershell
python -m pytest
python -m compileall lc_auto
docker compose -f docker-compose.ghcr.yml config --quiet
```
