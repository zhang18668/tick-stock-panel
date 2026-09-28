# Authentik SSO 与多用户插件拆分设计

## 1. 背景与目标

`release/0.0.2` 当前把多用户认证、PostgreSQL 持久化、订阅与后台管理作为源码内扩展接入，但仍修改了 `backend/app/main.py`、`frontend/src/pages/Settings.tsx`、核心依赖声明和 `backend/uv.lock`。当 `main` 同时演进认证、开放 API、SSE 或设置页时，这些热点文件会反复产生合并冲突。

本设计将统一身份交给独立部署的 Authentik，将 Tick Stock Panel 的多用户业务能力拆成独立插件包。目标是：

- 多个业务系统共享 Authentik 登录态；
- Tick Stock Panel 核心只依赖稳定、小粒度的身份契约；
- standalone 模式不安装插件依赖也能保持现有行为；
- 多用户、数据库和 OIDC 依赖不再进入核心 `uv.lock`；
- 多用户页面不再直接修改核心 `Settings.tsx`；
- 后续合并上游时，产品专属代码不再持续修改 `main.py`。

本设计不把 Authentik 源码纳入仓库，也不把 Tick Stock Panel 的策略、自选、监控、回测、订阅或积分数据迁入身份服务。

## 2. 方案选择

采用“成熟 OIDC 身份平台 + Authentik 认证插件 + 多用户业务插件”的组合方案。

不采用以下方案：

- 自建 OIDC 服务：需要自行承担授权码、PKCE、密钥轮换、令牌撤销、MFA、审计及安全响应，长期成本过高。
- 仅使用统一认证网关注入用户头：信任边界脆弱，难以覆盖 API、桌面端和跨域场景。
- 把多用户依赖放入核心 optional extra：`uv` 仍会把 extra 依赖纳入核心锁文件，不能解决升级冲突。
- 把完整多用户业务拆成远程微服务：现有业务仓库与策略、回测等调用链耦合较深，首轮改造风险过高。

## 3. 总体架构

```text
用户浏览器
   │
   │ 访问任一业务系统
   ▼
业务系统自己的后端/BFF
   │  未登录时发起 OIDC Authorization Code + PKCE
   ▼
Authentik
   ├─ 统一登录与 MFA
   ├─ 用户、组织和 Group
   ├─ OIDC Token 与 JWKS
   └─ 每个业务系统使用独立 Client
   │
   │ authorization code
   ▼
业务系统后端
   ├─ 用 code 换取 Token
   ├─ 验证 issuer、audience、signature、state 与 nonce
   ├─ 建立本系统 HttpOnly Session Cookie
   └─ 将 issuer + subject 映射为本地用户
```

建议部署拓扑：

```text
Reverse Proxy / TLS
  ├─ auth.example.com  -> Authentik
  ├─ stock.example.com -> Tick Stock Panel + 两个插件
  └─ other.example.com -> 其他 OIDC Client

Tick Stock Panel multi-user plugin -> PostgreSQL
```

Authentik 是唯一身份源，但不是 Tick Stock Panel 的业务数据库。单点登录由 Authentik 会话实现；每个业务系统仍建立自己的安全会话并独立授权。

## 4. 仓库与包边界

目标结构：

```text
tick-stock-panel/
  backend/                         # 上游核心，保持 standalone 可运行
  frontend/                        # 核心前端和稳定扩展运行时
  extensions/
    authentik-auth/
      pyproject.toml
      uv.lock
      src/tsp_authentik/
      tests/
    multi-user/
      pyproject.toml
      uv.lock
      migrations/
      src/tsp_multi_user/
      tests/
  services/
    authentik/                     # Compose、配置模板和部署文档
```

`authentik-auth` 负责 OIDC 和本地会话；`multi-user` 负责本系统业务数据隔离、订阅、积分和管理后台。两者分别维护依赖与锁文件。

核心保留现有 `app.custom` 发现机制至少一个扩展 API 大版本，并新增标准 Python entry point：

```toml
[project.entry-points."tick_stock_panel.backend_extensions"]
authentik = "tsp_authentik.extension:extension"
multi_user = "tsp_multi_user.extension:extension"
```

entry point 与 `app.custom` 模块最终进入同一个注册、验证、冻结和生命周期流程，避免形成第二套扩展系统。

## 5. 核心身份契约

核心新增不可变身份对象和小粒度认证 Provider：

```python
@dataclass(frozen=True)
class Principal:
    subject: str
    user_id: str
    roles: frozenset[str]
    tenant_id: str | None
    auth_provider: str


class AuthProvider(Protocol):
    api_version: int

    async def authenticate(self, request: Request) -> Principal | None:
        """无凭据返回 None；无效凭据抛认证异常；成功返回已验证身份。"""
```

扩展通过 `register_auth_provider(implementation_id, provider)` 注册。契约要求：

- 同一部署只允许一个交互式 Auth Provider；重复注册拒绝对应扩展，不静默覆盖；
- Provider 只认证身份，不决定订阅、策略或业务资源权限；
- 认证成功后，运行时将 Principal 写入 `request.state.principal`；
- API 使用统一依赖读取 Principal；
- 无法可靠认证时 fail-closed；
- standalone 默认 Provider 保持现有本地密码和 Cookie 语义。

现有“完整 request handler”注册能力被 Auth Provider 和普通扩展路由替代。插件不得吞掉 CORS、全局异常处理或其他中间件。

## 6. 扩展生命周期与核心接线

扩展运行时统一处理：

- entry point 与源码内扩展发现；
- API 版本、ID、路由冲突和单一 Auth Provider 校验；
- 配置阶段原子注册，失败不保留半注册状态；
- 异步 `startup`；
- 逆序异步 `shutdown`；
- 注册表启动后冻结。

认证运行时从 `main.py` 移入独立核心模块。`main.py` 最终只保留稳定的一次性安装调用，例如 `install_extensions(app)`，以后 Authentik 或多用户业务演进不再修改该文件。

插件启动失败不得影响 standalone。多用户模式显式启用但 Auth Provider、数据库或必需配置无效时，应用应拒绝进入不安全的半工作状态，而不是回退为匿名或管理员。

## 7. Authentik OIDC 流程

采用 OIDC Authorization Code + PKCE。Auth 插件注册以下独立路由：

- `/api/auth/oidc/login`
- `/api/auth/oidc/callback`
- `/api/auth/logout`
- `/api/auth/logout-all`
- `/api/auth/me`

登录流程：

1. 后端生成并服务端保存 state、nonce 和 PKCE verifier。
2. 浏览器跳转 Authentik authorization endpoint。
3. callback 校验 state，用 code 换取 Token。
4. 验证 ID Token 的签名、issuer、audience、nonce 和过期时间。
5. 使用 `(issuer, subject)` 查找本地身份映射。
6. 建立不透明的本地 Session Cookie。
7. 仅跳转到经过白名单校验的站内目标，防止 Open Redirect。

正常 API 请求不实时访问 Authentik。JWT 使用缓存的 JWKS 本地验证；密钥 ID 未命中时进行一次受控刷新。Authentik 暂时不可用时，未过期的本地 Session 可继续使用至配置的刷新或绝对过期边界；新登录和续期明确失败。

## 8. 会话与 Secret

浏览器只保存随机、不透明的 Session ID。Cookie 在生产环境使用：

- `HttpOnly`；
- `Secure`；
- 默认 `SameSite=Lax`；
- 明确的 Path、空闲过期和绝对过期。

Access Token、Refresh Token 与 PKCE verifier 不写入 `localStorage` 或可被前端 JavaScript 读取的 Cookie。服务端 Session 保存：

- 本地用户 ID；
- issuer 与 subject；
- 角色快照；
- Access Token 到期时间；
- 加密后的 Refresh Token；
- 创建、最后访问和绝对过期时间。

Refresh Token 轮换失败、被撤销或用户被禁用时，本地 Session 失效。Token 加密密钥通过 Secret 或环境变量注入，不写入数据库或 Git。

“退出当前系统”删除本地 Session，并尽力撤销 Refresh Token。“退出所有系统”在此基础上跳转 Authentik `end_session_endpoint`。首版不实现复杂的 Front-channel Logout；确有秒级踢出需求后再增加 webhook 或 Back-channel Logout。

## 9. 身份映射与角色

身份主键为 `(issuer, subject)`，不能只用邮箱。新增映射表：

```text
external_identities
  id
  provider_id
  issuer
  subject
  local_user_id
  email_snapshot
  display_name_snapshot
  created_at
  last_login_at

unique(provider_id, issuer, subject)
```

首次登录时：

- 映射存在则更新显示快照和最后登录时间；
- 映射不存在且允许自动开户则创建本地业务用户和映射；
- 关闭自动开户时返回“账户尚未开通”；
- 不根据相同邮箱自动绑定旧账户，避免账户接管。

Authentik Group 通过显式配置映射为粗粒度应用角色：

```text
tsp-admin -> admin
tsp-user  -> user
```

未映射 Group 不获得权限。订阅等级、积分、策略购买和业务资源权限继续由 Tick Stock Panel 本地数据库决定，不能由普通 OIDC Claim 决定。首版一个用户只属于一个 Tick Stock Panel tenant，不实现组织切换。

## 10. 前端边界

OIDC 交互由后端完成，前端不引入 OIDC JavaScript SDK。核心前端只消费稳定能力：

- `/api/auth/mode` 决定显示本地登录或“使用统一身份登录”；
- `/api/auth/me` 返回当前 Principal 的可展示子集；
- 登录按钮跳转后端 login endpoint；
- 注销调用后端 logout endpoint。

多用户管理页面通过现有前端扩展路由和导航注册，不加入核心设置页。本轮删除 `Settings.tsx` 中未实际生效的 `adminOnly/visibleTabs` 分支，保留 main 的“开放接口”Tab。

插件前端首版只使用核心已有 React、Router 和 Query 依赖，不修改核心 `package.json` 或锁文件。暂不引入远程 Module Federation；插件以后确需独有依赖时，再设计独立静态构建产物。

## 11. 多用户业务插件

多用户插件拥有：

- PostgreSQL 业务仓库；
- 用户与外部身份映射；
- 自选、策略、监控、回测和用户偏好隔离；
- 订阅、积分、支付适配与管理后台；
- Alembic 迁移；
- 插件自己的依赖、锁文件和测试。

核心流程不得直接导入插件的 SQLAlchemy 模型或仓库。当前已有的直接分支逐步收敛到小粒度仓库或上下文契约；不继承或复制 `StrategyEngine`、`BacktestEngine`、`ScreenerService` 等大型编排服务。

如果某条调用链暂时无法在不改变业务语义的前提下迁出，保留最小兼容适配层并记录为升级复核点，不强行一次性重写。

## 12. 旧用户与数据迁移

现有本地用户以及策略、自选、监控、回测等业务表的 `user_id` 保持不变。迁移只增加外部身份映射。

提供幂等迁移命令：

- 列出未绑定旧用户；
- 默认 dry-run；
- 管理员明确提供 Authentik issuer 与 subject 后建立映射；
- 拒绝重复 subject、本地用户重复绑定和不存在的目标；
- 写入失败时事务回滚；
- 不删除或覆盖旧业务数据。

迁移期可保留一个默认关闭的本地管理员应急入口。启用时必须使用独立 Secret、限制来源并记录审计日志。长期不支持“本地密码或 Authentik 任意选择”的双登录模式。

## 13. 配置与部署

配置示例：

```env
APP_MODE=multi_user

OIDC_ISSUER=https://auth.example.com/application/o/tsp/
OIDC_CLIENT_ID=tick-stock-panel
OIDC_CLIENT_SECRET=<secret>
OIDC_REDIRECT_URI=https://stock.example.com/api/auth/oidc/callback
OIDC_SCOPES=openid profile email groups
OIDC_ROLE_GROUP_ADMIN=tsp-admin
OIDC_ROLE_GROUP_USER=tsp-user

SESSION_COOKIE_NAME=tsp_session
SESSION_IDLE_TTL=8h
SESSION_ABSOLUTE_TTL=7d
SESSION_ENCRYPTION_KEY=<secret>
OIDC_AUTO_PROVISION=false
```

开发、测试与生产分别使用独立 Authentik Client 和 Redirect URI。不同业务系统不得共享 Client Secret。仓库只保存无敏感值的 Compose、配置模板和部署说明。

## 14. 当前合并处理

当前仓库正处于把 `main` 合入 `release/0.0.2` 的未完成状态。先恢复一个可验证的合并结果，再进行架构迁移：

1. `main.py` 同时保留 main 的 API Token、SSE、OpenAPI 逻辑和二开分支当前必需的扩展生命周期。
2. 删除 `Settings.tsx` 中未生效的 `adminOnly/visibleTabs` 改动，保留 main 新增的“开放接口”Tab。
3. 根据合并后的依赖声明重新生成 `backend/uv.lock`，不手工拼接生成文件。
4. 在迁移完成并通过验证后，从核心依赖移除 PostgreSQL、多用户和认证专属依赖，再次生成精简锁文件。

不自动创建 merge commit，不提交、不推送，也不覆盖工作区其他已暂存或未跟踪修改。

## 15. 验证矩阵

扩展基础设施：

- 无插件时 standalone 行为不变；
- entry point 单插件、多插件、重复 ID和版本不兼容；
-配置原子性、加载失败隔离、异步启动和逆序关闭；
- 多个 Auth Provider 冲突时 fail-closed。

OIDC：

- Authorization Code + PKCE 正常流程；
- state、nonce、issuer、audience、签名和过期时间错误；
- JWKS 缓存、未知 key ID 和密钥轮换；
- Refresh Token 轮换、撤销和 Authentik 不可用；
- 当前系统登出和全局登出；
- Cookie 安全属性和 Open Redirect 防护。

身份与权限：

- 自动开户开启和关闭；
- `(issuer, subject)` 稳定映射；
- 相同邮箱不自动合并；
- admin、user 和未映射 Group；
- 用户禁用、角色撤销、tenant 与业务数据隔离。

迁移与项目回归：

- dry-run、幂等、subject 冲突和事务回滚；
- 既有策略、自选、监控和回测数据不被覆盖；
- 核心后端受影响测试、插件各自 pytest 与 Ruff；
- standalone 启动、多用户联调和前端构建；
- 所有锁文件一致性检查；
- `git diff --check` 和最终 `git status`。

## 16. 实施顺序

1. 安全解决当前三个冲突并恢复可验证状态。
2. 新增 Principal、Auth Provider、entry point 发现和统一生命周期。
3. 将核心认证中间件移出 `main.py`，保留 standalone 默认 Provider。
4. 创建 Authentik 认证插件及其测试和部署模板。
5. 创建多用户业务插件，移动持久化、迁移、订阅和管理能力。
6. 将核心中的多用户直接分支收敛到小粒度契约或最小兼容层。
7. 清理核心依赖与锁文件，删除设置页产品专属修改。
8. 执行验证矩阵并记录剩余兼容风险。

## 17. 非目标

首版明确不实现：

- 自研 OIDC 身份服务器；
- 多个交互式身份 Provider 同时启用；
- Authentik 用户与本地用户双向全量同步；
- 每个请求实时访问 Authentik；
- 由 OIDC Claim 直接决定付费和业务资源权限；
- 多组织实时切换；
- 远程 React Module Federation；
- 生产 Authentik、DNS、TLS 或真实用户的自动变更。

## 18. 完成标准

- standalone 未安装任何新插件依赖即可启动并通过现有认证回归；
- Authentik 登录可在测试环境完成标准 OIDC 流程；
- 第二个接入 Authentik 的业务系统无需再次输入凭据；
- 多用户业务数据仍按本地用户正确隔离；
- 核心 `pyproject.toml` 与 `uv.lock` 不含多用户或 OIDC 专属依赖；
- `main.py` 和 `Settings.tsx` 不含 Authentik 或多用户产品专属逻辑；
- 插件加载、认证失败和迁移失败均有明确的 fail-closed 行为；
- 定向测试、插件测试、前端构建、锁文件检查和 `git diff --check` 全部通过。
