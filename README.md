# 力扣自动化刷题工具

本项目是一个本地 Python 命令行工具，用 Playwright 控制 `leetcode.cn` 的已登录浏览器会话，完成指定题目的自动化闭环：

`获取题目 -> 调用大模型生成 Python3 解法 -> 填入编辑器 -> 提交 -> 根据提交结果修正 -> 记录状态与产物`

当前默认流程是直接提交：`获取题目 -> 调用大模型生成答案 -> 填入编辑器 -> 提交`。如果提交失败，工具会把提交结果反馈给模型修正后再次提交。默认不再先点击“运行代码”。

重要边界：

- 默认不会真实提交，`allow_real_submit` 默认为 `false`。
- 不绕过验证码、风控、登录校验或反自动化机制。
- 不做代理池、指纹伪装、批量账号或竞赛自动提交。
- 遇到验证码、登录失效、页面安全验证、频繁访问提示或页面结构无法识别时会停止。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
python -m playwright install chromium
```

## Docker 分发

可以打包成 Docker 镜像，但推荐的运行方式是：容器里只运行 CLI 和 Playwright 客户端，浏览器仍使用宿主机上已经登录的 Chrome，并通过 CDP 连接。这样不会把浏览器登录态、模型密钥和运行状态打进镜像，也能避开容器内图形浏览器登录困难的问题。

### 使用公共镜像

项目发布的公共镜像地址：

```text
ghcr.io/xieluyao60-coder/leetcode-automatic:latest
```

用户不需要本地构建，克隆仓库后直接拉取镜像：

```powershell
git clone https://github.com/xieluyao60-coder/leetcode-automatic.git
cd leetcode-automatic

docker pull ghcr.io/xieluyao60-coder/leetcode-automatic:latest
if (!(Test-Path .env)) { Copy-Item .env.example .env }
docker compose -f docker-compose.ghcr.yml run --rm lc-auto init
```

后续命令都使用 `docker-compose.ghcr.yml`：

```powershell
docker compose -f docker-compose.ghcr.yml run --rm lc-auto doctor --config /data/config.yaml
docker compose -f docker-compose.ghcr.yml run --rm lc-auto run-seq --limit 3 --config /data/config.yaml
```

### 本地构建镜像

开发者也可以自己构建镜像：

```powershell
docker build -t leetcode-automatic:latest .
# 或者
docker compose build
```

第一次准备运行目录：

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
docker compose run --rm lc-auto init
```

然后编辑 `.env` 填入模型参数，编辑 `docker-data/config.yaml` 确认配置。Docker 专用配置默认使用：

```yaml
browser_cdp_url: http://host.docker.internal:9222
state_db_path: /data/lc_auto.sqlite3
artifact_dir: /data/artifacts
```

在宿主机启动可被容器连接的 Chrome：

```powershell
$chrome = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
if (!(Test-Path $chrome)) { $chrome = "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe" }
& $chrome --remote-debugging-port=9222 --user-data-dir="$PWD\.chrome-cdp-profile"
```

在这个 Chrome 中手动登录 `https://leetcode.cn/`，保持浏览器不关闭，然后从容器运行：

```powershell
docker compose run --rm lc-auto doctor --config /data/config.yaml
docker compose run --rm lc-auto run-seq --limit 3 --config /data/config.yaml
```

不用 compose 也可以直接运行：

```powershell
docker run --rm -it --env-file .env -v "${PWD}\docker-data:/data" leetcode-automatic:latest doctor --config /data/config.yaml
```

Linux 上如果容器无法解析 `host.docker.internal`，额外加上：

```powershell
--add-host host.docker.internal:host-gateway
```

镜像不会包含 `.env`、`config.yaml`、SQLite 状态库、浏览器 profile 或运行产物；这些都通过 `docker-data/` 和本地 `.env` 管理。

初始化本地配置：

```powershell
python -m lc_auto init
```

然后在 `.env` 中填写模型服务配置：

```env
LC_AUTO_MODEL_API_KEY=你的密钥
LC_AUTO_MODEL_BASE_URL=https://api.openai.com/v1
LC_AUTO_MODEL_NAME=你的模型名
```

如果只想验证流程、不消耗模型额度，可以把 `config.yaml` 中的模型改成：

```yaml
model:
  provider: fake
```

也可以直接使用仓库里的 `config.fake.yaml`。fake 模型只适合 smoke test，默认返回 Two Sum 的示例解法；使用 `config.fake.yaml` 时 `.env` 里的真实模型参数不会被读取。

## 诊断

```powershell
python -m lc_auto doctor --config config.yaml
```

它会检查 Python 版本、依赖、Playwright 包、配置文件、模型环境变量、本地状态库目录和浏览器 profile 目录。

## 登录

```powershell
python -m lc_auto login --config config.yaml
```

浏览器打开后手动登录力扣。登录态会保存在 `.browser-profile/`。

如果 Playwright 自带 Chromium 登录时一直卡在安全验证，改用“外部 Chrome 连接模式”。这个模式不会绕过验证码，只是复用你自己打开的普通 Chrome：

```powershell
$chrome = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
if (!(Test-Path $chrome)) { $chrome = "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe" }
& $chrome --remote-debugging-port=9222 --user-data-dir="$PWD\.chrome-cdp-profile"
```

在弹出的 Chrome 里手动打开并登录 `https://leetcode.cn/`。登录成功后保持这个 Chrome 不要关闭，然后在另一个终端运行：

```powershell
python -m lc_auto doctor --config config.fake.yaml --cdp-url http://127.0.0.1:9222
python -m lc_auto login --config config.fake.yaml --cdp-url http://127.0.0.1:9222
```

后续命令同样加上 `--cdp-url`：

```powershell
python -m lc_auto dry-run --problem two-sum --config config.fake.yaml --cdp-url http://127.0.0.1:9222
```

也可以把它写进 `config.yaml`：

```yaml
browser_cdp_url: http://127.0.0.1:9222
```

## 单题 dry-run

dry-run 会生成代码、填入编辑器并点击“运行代码”，但不会点击“提交”。

```powershell
python -m lc_auto dry-run --problem two-sum --config config.yaml
```

如果要真实提交并继续下一题，不要用 `dry-run`，要使用 `run`，并在 `config.yaml` 中显式设置 `allow_real_submit: true`。

fake 模型 smoke test：

```powershell
python -m lc_auto dry-run --problem two-sum --config config.fake.yaml
```

## 发现题目

从题库页收集当前可见题目 slug，并写入 `problems.txt`：

```powershell
python -m lc_auto discover --limit 20 --output problems.txt --config config.yaml
```

追加模式：

```powershell
python -m lc_auto discover --limit 20 --append --config config.yaml
```

## 批量运行

按 `problems.txt` 顺序运行：

```powershell
python -m lc_auto run --problems problems.txt --config config.yaml
```

运行一个题目：

```powershell
python -m lc_auto run --problem two-sum --config config.yaml
```

运行 `discover` 保存过的题目：

```powershell
python -m lc_auto run --from-discovered --limit 3 --config config.yaml
```

不准备题目列表，直接从当前浏览器题目页开始，并在 AC 后点击页面顶部“下一题”按钮继续：

```powershell
python -m lc_auto run --current --next-in-page --limit 3 --config config.yaml --cdp-url http://127.0.0.1:9222
```

从指定题开始，然后 AC 后点击页面“下一题”继续：

```powershell
python -m lc_auto run --problem two-sum --next-in-page --limit 3 --config config.yaml --cdp-url http://127.0.0.1:9222
```

真实提交必须同时满足：

- `config.yaml` 中 `allow_real_submit: true`
- 使用 `run` 命令，而不是 `dry-run`
- 页面下一题模式也必须使用 `run --next-in-page`，`dry-run` 不会点击下一题

建议第一次真实提交时设置：

```yaml
max_questions_per_run: 1
max_repairs_per_problem: 3
allow_real_submit: true
```

## 按题号顺序运行

如果不想维护 `problems.txt`，可以直接按力扣前端题号 `1, 2, 3...` 顺序做。工具会自动把题号解析成题目 slug，并把下次要做的题号记录到 SQLite。

第一次从第 1 题开始：

```powershell
python -m lc_auto run-seq --start 1 --reset-progress --limit 3 --config config.yaml --cdp-url http://127.0.0.1:9222
```

之后继续上次进度：

```powershell
python -m lc_auto run-seq --limit 3 --config config.yaml --cdp-url http://127.0.0.1:9222
```

如果某题曾被错误记录为 accepted，可以从该题重新开始并强制重跑：

```powershell
python -m lc_auto run-seq --start 2 --reset-progress --rerun-accepted --limit 1 --config config.yaml --cdp-url http://127.0.0.1:9222
```

顺序进度保存在 `sequence_progress` 表里。只有真实提交 AC 后，`next_frontend_id` 才会推进到下一题；`dry-run` 通过不会推进进度。遇到会员题或不存在的编号会自动跳过并记录。
如果遇到数据库题、Pandas 题等无法切换到 Python3 的题目，工具会记录为 `unsupported_language` 并跳过，然后继续处理下一题；这类题不会调用模型、不会填代码、不会提交，也不会被 `resume` 反复恢复。

## 恢复、状态与导出

恢复未完成题目：

```powershell
python -m lc_auto resume --config config.yaml
```

查看最近状态：

```powershell
python -m lc_auto status --config config.yaml
```

导出 SQLite 状态到 JSON：

```powershell
python -m lc_auto export --output state_export.json --config config.yaml
```

状态默认保存在 `lc_auto.sqlite3`。每题运行产物默认保存在 `artifacts/<slug>/`，包括题面、初始模板、每次尝试代码、判题结果、模型原始输出、失败截图和最终结果。

## 常用配置

```yaml
allow_real_submit: false
run_before_submit: false
max_questions_per_run: 3
max_repairs_per_problem: 3
skip_accepted: true
continue_on_problem_error: false
artifact_dir: ./artifacts
save_screenshots: true
save_page_html: false
min_delay_seconds: 60
max_delay_seconds: 180
```

`run_before_submit: false` 表示写入代码后直接提交；改成 `true` 才会恢复“先运行测试用例，通过后再提交”的旧流程。

如果开启 `continue_on_problem_error: true`，普通页面解析错误会跳过当前题继续；登录失效和安全/风控提示仍会立即停止。

## 测试

```powershell
python -m pytest
python -m compileall lc_auto
```
