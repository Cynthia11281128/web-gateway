# Agent 网页开发与接入规范

更新日期：2026-10-31。网站最终必须通过 **`/apps/<site-id>/`**（含结尾 `/`）访问并登记到 Web Gateway，不要只交付本地端口或文件路径。用户只要求代码/方案时不要擅自发布，并说明未发布。

执行前从用户提供的本机环境确认 `WORKSPACE_ROOT`（工作区绝对路径）和 `GATEWAY_ROOT`（网关仓库绝对路径）。实际地址和目录从本机配置读取，不写回公开文档。以下命令使用这两个变量；常见布局为 `$WORKSPACE_ROOT/infra/web-gateway`，也可以使用其他仓库位置。

本工作区的网页项目统一放在 `$WORKSPACE_ROOT/webgateway_projects/<project-name>/`，项目代码、环境、构建产物和运行日志均保存在对应项目目录内。

## 红线

- 不手改网关代码、`runtime.json`、`sites.json`、`Caddyfile`、凭据、防火墙；发布/下线只走 CLI。
- 不覆盖、修改或下线其他项目的站点；所有站点 ID 按普通发布规则处理，网关不自动启动应用后端。
- 不输出密码、cookie、token；没有合法会话时不读 `secrets/password.txt`，也不要求用户贴密码。
- 不关闭登录/Origin 检查，不把后端改成对外监听来绕过网关。
- 网关为 HTTP，仅限受控环境，不能宣称满足生产安全要求。

## 流程

1. **查环境与站点**：运行 `bash "$GATEWAY_ROOT/scripts/status.sh"` 和 `bash "$GATEWAY_ROOT/scripts/web.sh" list`。选 site-id（1..40 字符，小写字母开头，其余为小写字母/数字/`_`/`-`），不与他人冲突；仅确认同名属于当前项目时才加 `--replace`。
2. **开发适配**：所有浏览器侧地址都带 `/apps/<site-id>/` 前缀——资源、构建 base、router basename、跳转、表单、fetch/XHR、WebSocket/SSE、`Location` 重定向、业务 cookie（名称专属，Path=`/apps/<site-id>/`）。禁止写死 `/assets/...`、`/api/...` 或浏览器侧 `127.0.0.1`，也不写死服务器 IP；用 `window.location.origin` + 前缀。`href="/"` 仅用于回网关列表。
3. **发布**（二选一）：

   静态站（`public/` 或 `dist/`，含 `index.html`，无 symlink/隐藏文件/密钥）：
   ```bash
   bash "$GATEWAY_ROOT/scripts/web.sh" publish-static my-page \
     --title "My Page" --dir "$WORKSPACE_ROOT/webgateway_projects/my-page/dist"
   ```
   SPA 在命令末尾加 `--spa`，且构建 base 要对，并测深层路径刷新。静态文件直接读目录，同路径重新构建无需重新发布。

   动态站（后端监听 `http://127.0.0.1:<端口>`，端口 1024..65535，不得为网关端口/控制端口或 2019、2375、2376、3306、5432、6379、8171、10250；先 `ss -ltnp` 查占用，不杀陌生进程；不写 `localhost`、路径、末尾 `/`）：
   ```bash
   curl --noproxy '*' --max-time 5 -i http://127.0.0.1:8201/   # 先确认后端可用
   bash "$GATEWAY_ROOT/scripts/web.sh" publish-service my-app \
     --title "My App" --upstream http://127.0.0.1:8201 --prefix-mode strip
   ```
   - `strip`（默认）：后端收到去掉前缀的路径；`preserve`：后端收到完整前缀，仅在后端已按该前缀挂载时使用。
   - 两种模式都不会改写 HTML/JS/重定向/cookie，需应用自己适配（可参考 `X-Forwarded-Prefix`，但不能假定框架自动使用）。
   - 后端须在终端关闭后存活，用正式运行方式，日志放项目自己的目录。
   - 网关登录不等于业务授权；网关不会把 `web_gateway_session` 转给后端，也会过滤遗留会话 cookie。不要让后端依赖网关会话 cookie。
4. **更新**：同名更新加 `--replace`，它整条替换，需重新传 `--title`、`--spa`、`--prefix-mode` 等。在线发布热更新，无需重启网关。
5. **网关未运行**：不擅自重启/重装；用户明确要求离线准备才加 `--offline`（网关运行中禁用），并说明未上线。
6. **下线**：仅在用户要求或清理自己的临时站点时，运行 `bash "$GATEWAY_ROOT/scripts/web.sh" unpublish <id>`（不删文件、不停后端）。
7. **同步网站列表**：每次新增或更新网站，都必须核对并按需同步 `$WORKSPACE_ROOT/webgateway_projects/weblist.md`，包括无需重新登记的原目录重新构建、后端代码更新及重启。同一网站维护原有条目，不重复添加；名称、URL 和分组未变化时无需修改文件，不追加更新描述。下线时同步移除访问链接。交付前核对列表与实际网关登记一致。

## 网站列表

- `weblist.md` 使用 Markdown 列表，条目格式为 `[网站名称](完整网关 URL)`，点击名称即可进入完整网站。
- 名称使用对应项目的文件夹名称，即 `$WORKSPACE_ROOT/webgateway_projects/<project-name>/` 中的 `<project-name>`，不使用展示名称或网关登记的 `title`。
- 保留“测试”“已发布”等当前分组，各分组内按项目文件夹名称的字母顺序（A–Z）排列。
- 列表只保留标题和网站链接条目（即当前格式）；不添加每次发布或更新的日期、变更描述、验收结果、资产数量、服务重启记录或历史日志。这些信息放在对应项目 README 或单独报告中。
- 完整 URL 必须通过 `bash "$GATEWAY_ROOT/scripts/web.sh" url <id>` 获取，保留 `/apps/<site-id>/` 和结尾 `/`，不猜测访问地址。

## 验收

用 `bash "$GATEWAY_ROOT/scripts/web.sh" url <id>` 得到真实 URL，不手猜 origin。

- 匿名访问页面应跳转登录，匿名 API 应返回 401（登录页的 200 不代表应用已验证）。
- 有合法会话时：登录后回到应用；资源加载正常、控制台无路径类 404/502/401/403；核心操作、API、上传下载、重定向、WebSocket/SSE 经网关可用；SPA 深层 URL 刷新正常。
- 没有会话时，完成匿名保护和后端本地检查，并明确写出“登录后的浏览器验收未完成”，不能声称未做的检查已通过。

## 交付

给用户简洁结果，并在项目 README 保留：site-id、类型、网关 URL、项目目录；静态构建命令或后端启动/停止/状态命令与日志位置；动态站的前缀模式；发布与重新发布命令；已做/未做的验收；临时开发服务器的用途与生命周期。

运行配置和使用限制见 [README](README.md)。遇到接入限制，应修正应用配置或报告阻塞原因，不扩大网关权限。
