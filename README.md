# Web Gateway

带统一登录的多网站发布入口。将工作区内的静态目录或已经运行的回环 HTTP 服务登记到 `/apps/<id>/`，客户端通过浏览器访问，无需安装客户端程序或为每个站点配置 SSH 转发。

实现位于 `server/src/web_gateway/`，运行与发布脚本位于 `scripts/`，非秘密配置模板位于 `deploy/`。

让 agent 开发并接入网页时，先阅读并遵循：[Agent 网页开发与接入规范](AGENT_WEB_PUBLISHING.md)。

Python 包名为 `web_gateway`。仓库可以放在工作区内的任意目录，不依赖特定用户名、服务器 IP 或目录层级。

当前实现只提供明文 HTTP，适用于受控环境，不提供原生 TLS、SSO 或站点安全隔离。模板使用 `127.0.0.1`，不是远程浏览器可访问的部署地址。

## 准备

在仓库根目录设置路径；实际值只保存在本机配置，不写入公开文档：

```bash
export GATEWAY_ROOT="$PWD"
# 替换为自己的工作区绝对路径，须包含网关目录及待发布目录。
export WORKSPACE_ROOT="/absolute/path/to/workspace"

# Linux amd64，Python >=3.11；需要 uv、curl、awk、sha512sum 和 tar。
bash "$GATEWAY_ROOT/scripts/bootstrap.sh"
```

默认使用 `python3` 创建虚拟环境，可用 `WEB_GATEWAY_PYTHON` 指定其他解释器。已有虚拟环境会继续使用，不会因修改该变量而重建。

启动前必须准备本机 `var/runtime.json`、`secrets/login.json`、`var/internal-token`，再离线发布站点生成 Caddy 配置。参考 [配置模板](deploy/runtime.json.example)，将工作区、状态目录和认证文件路径替换为本机实际绝对路径；远程访问时，监听 IP 和公开 origin 必须一起改为服务器实际可达地址。

首次部署可交互创建密码哈希并生成内部 token；以下命令不覆盖已有凭据，不输出秘密：

```bash
mkdir -p "$GATEWAY_ROOT/var" "$GATEWAY_ROOT/secrets"
chmod 700 "$GATEWAY_ROOT/var" "$GATEWAY_ROOT/secrets"
bash "$GATEWAY_ROOT/scripts/python.sh" -m web_gateway.auth \
  --file "$GATEWAY_ROOT/secrets/login.json"
bash "$GATEWAY_ROOT/scripts/python.sh" -c '
import os
from pathlib import Path
import secrets

path = Path(os.environ["GATEWAY_ROOT"]) / "var/internal-token"
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="ascii") as stream:
    stream.write(secrets.token_urlsafe(32) + "\n")
'
```

首次登记时，在下方发布命令末尾加 `--offline`，然后按管理部分启动。运行中发布不使用 `--offline`。启动脚本不自动创建配置或凭据。

## 发布

以下命令要求网关已运行，并已设置 `GATEWAY_ROOT`、`WORKSPACE_ROOT`：

```bash
# 静态站：工作区内专用 public/ 或 dist/，必须有 index.html
bash "$GATEWAY_ROOT/scripts/web.sh" publish-static my-report \
  --dir "$WORKSPACE_ROOT/projects/my-report/public"

# 动态站：先启动应用，监听此回环地址；应用须适配 /apps/my-app/
bash "$GATEWAY_ROOT/scripts/web.sh" publish-service my-app \
  --upstream http://127.0.0.1:8201 --prefix-mode strip

bash "$GATEWAY_ROOT/scripts/web.sh" list
bash "$GATEWAY_ROOT/scripts/web.sh" url my-app
bash "$GATEWAY_ROOT/scripts/web.sh" unpublish my-app
```

发布成功输出可访问 URL，并热更新入口。更新登记用 `--replace`；下线不删除源文件、不停止自有后端。静态站直接服务该目录，内容修改后刷新可见；不是文件快照。发布不负责启动任意应用。

后端页面、资源、API、WebSocket、重定向和 cookie 必须适配 `/apps/<id>/`。`strip` 仅在转发时删除前缀，不能修复网页中写死的 `/api`、`/assets` 等根路径。`preserve` 保留完整路径。SPA 可用 `--spa`，但构建资源路径仍要正确。

## 管理

```bash
bash "$GATEWAY_ROOT/scripts/status.sh"
bash "$GATEWAY_ROOT/scripts/stop.sh"
# 确认没有运行中的 supervisor 后再启动。
setsid --fork bash "$GATEWAY_ROOT/scripts/start.sh" \
  >> "$GATEWAY_ROOT/var/supervisor.log" 2>&1 < /dev/null
```

本地 supervisor 只管理 Caddy 和登录控制服务，子进程故障有有限重试。所有应用后端由各自项目管理，不按站点 ID 自动启动。整机/任务重启恢复、supervisor 自身故障恢复未配置；`status` 检查进程存活，不等于网页健康。

配置和运行文件在 `var/`，凭据在 `secrets/`；这两个目录不提交 Git。密码通过交互命令创建哈希，程序不自动保存明文密码。登录控制服务重启后需要重新登录。

所有网站共用一个 origin 和登录，仅用于自己信任的代码，不提供站点安全隔离。静态目录注册时拒绝隐藏文件和 symlink，运行时必须保持可信，不能后来加入 symlink 或秘密文件。

## 发布源码

`.gitignore` 排除本机凭据、运行状态、环境、日志和未确认公开授权的本地模型报告。保留的配置模板只含示例值；不要把实际 IP、个人路径、密码、token 或会话写回模板。

本地文件在被忽略后仍然存在，正在运行的站点不受影响。已被 Git 跟踪的文件不会因为加入忽略规则而自动移除，提交前必须检查暂存区和历史。
