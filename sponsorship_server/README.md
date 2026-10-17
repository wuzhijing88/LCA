# LCA 赞助服务

独立部署的赞助网页与 ZPAY 页面支付服务。桌面应用只用浏览器打开网页，支付配置只保存在服务器。

页面改编自 MIT 许可的 [shadcn-landing-page](https://github.com/leoMirandaa/shadcn-landing-page)，采用双栏首屏、赞助金额快捷选择和卡片式感谢墙；设计来源、固定源版本和许可保留在 `THIRD_PARTY_NOTICES.md` 与分发的主题 CSS 中。所有网页配色和外观集中在 `themes/sponsorship.css`，跟随系统亮暗模式，不加载远程字体、头像或界面组件。

## 当前部署

- 网站：<https://www.lcaa.top/>；`lcaa.top` 和 HTTP 访问统一跳转到该地址。
- 服务器目录：`/opt/lca-sponsorship`；运行配置为 `sponsorship_server/.env`，权限 `0600`。真实密钥只保存在服务器，不在源码或桌面程序中。
- Nginx 站点：`/etc/nginx/sites-available/lca-sponsorship`，配置对应本目录的 `nginx.conf.example`。
- 证书：`/etc/letsencrypt/live/lca-sponsorship/`，由 `certbot.timer` 自动续期；部署钩子在续期后检查并重载 Nginx。
- 桌面关闭弹窗已配置该网址；修改桌面源码后需要重新构建发行包才能更新已安装程序。
- 当前商户已验证支付宝收银台可用。微信接口返回“商户尚未开通或开启微信支付渠道”，因此生产环境只启用 `ZPAY_PAYMENT_TYPES=alipay`；商户后台开通微信并重新验收后再加入 `wxpay`。
- 已验证 HTTPS、域名跳转、非法通知拒绝、支付宝二维码收银台及证书模拟续期。尚未操作支付账号完成真实付款，首次实付后仍需核对到账和赞助墙记录。

常用管理命令：

```sh
cd /opt/lca-sponsorship
docker compose -f sponsorship_server/compose.yaml ps
docker compose -f sponsorship_server/compose.yaml logs --tail 100
docker compose -f sponsorship_server/compose.yaml up -d --build --wait
certbot renew --cert-name lca-sponsorship --dry-run --no-random-sleep-on-renew --run-deploy-hooks
```

## 已实现的流程

网页填写金额、昵称、留言 → ZPAY 收银台 → 验签及主动查单确认到账 → 感谢页面与赞助墙。

- 支付协议采用 [ZPAY 官方文档](https://zpayz.cn/doc.html) 的 `submit.php` 页面支付、GET 支付通知及 `api.php?act=order` 查单。只支持该现行协议；其它版本需要明确修改后接入。
- 单笔 1～5000 元，人民币，整数分存储。可用支付宝、微信支付，由 `ZPAY_PAYMENT_TYPES` 限定实际开通的通道。
- 同一表单重复提交只创建一个订单。浏览器同步返回和异步通知都必须验签，再核对商户、订单、金额、支付方式、商品名与支付流水；待支付订单必须主动查单确认，未知或失败不会显示到账。
- 重复成功通知不重复记账，同一支付流水不能关联两个订单。仅已确认到账的订单进入感谢墙，每页 24 条。昵称是用户自填信息，不表示已验证身份。
- 未勾选公开展示时不保存昵称和留言；感谢墙用“匿名赞助者”展示金额与协调世界时日期。不采集支付账号、联系方式或头像。
- 页面内容自动转义；表单带有效期为一小时的来源校验与签名令牌。网页样式统一放在 `themes/sponsorship.css`，跟随系统亮暗主题。
- 不创建后台轮询任务或无界内存缓存。数据库连接逐次关闭，HTTP 客户端在服务停止时关闭。订单历史保留在持久化 SQLite 中，不自动删除财务记录。

## Linux + Docker Compose 部署

1. 将本仓库的 `sponsorship_server/`、`themes/sponsorship.css`、`resources/icon.ico` 和仓库根 `.dockerignore` 上传到服务器相同目录结构中。网页标识和浏览器标签页图标共用项目原始 `resources/icon.ico`，不单独维护另一份图标。
2. 复制 `sponsorship_server/.env.example` 为同目录 `.env`，填写独立域名、商户 ID、商户密钥、随机表单密钥与支付通道。必须全部有效，缺少配置时服务启动直接失败。设置 `.env` 权限为仅部署账号可读。
3. 在仓库根执行：

   ```sh
   docker compose -f sponsorship_server/compose.yaml up -d --build
   ```

4. 参照 `nginx.conf.example` 配置域名、HTTPS 证书和反向代理。域名根路径指向本服务，8080 端口只监听服务器本机。`SPONSOR_PUBLIC_URL` 必须与浏览器访问的 HTTPS 域名完全一致。
5. 在 ZPAY 商户后台核对网关域名、实际开通通道和站点设置，确保平台能访问 `https://你的域名/notify`。回调与收银台地址由服务端公开地址生成，不依赖客户端 Host 或代理头。

`.env` 不进入 Git，也不会进入 Docker 构建上下文。不要把 PID、密钥填入客户端。生产命令禁用 HTTP 访问日志，避免通知签名落入访问日志；不要启用 HTTP 客户端调试日志。Nginx 中订单入口有限流；若在 CDN 后部署，需先正确配置可信来源的真实 IP。

## 不使用 Docker

服务器安装 Python 3.10，在独立虚拟环境安装 `sponsorship_server/requirements.txt`，将 `.env.example` 中变量配置到服务进程环境（`.env` 文件不会被 Python 自动读取）。`SPONSOR_DATABASE` 使用该服务器上的绝对路径，目录须可写。

从仓库根启动并用服务器进程管理器管理：

```sh
python -m uvicorn sponsorship_server.app:create_app --factory --host 127.0.0.1 --port 8080 --no-access-log --no-proxy-headers
```

仍需 HTTPS 反向代理和订单入口限流。不要将开发环境的测试商户替代真实配置上线。

## 上线核实与维护

上线后用真实商户小额付款一次，核对 ZPAY 后台、感谢页与赞助墙金额；随后重放同一通知应仍返回 `success` 且只有一条记录。真实付款需要操作商户和支付账号，本仓库测试不会发起扣款。

数据库保存在 Docker 的 `sponsorship_data` 命名卷；升级保留该卷，不使用 `down -v`。备份应停服务后复制数据库，或使用 SQLite 在线备份接口，备份同时妥善保护服务器环境密钥。退款与不当留言由运营方核对 ZPAY 后台并维护订单记录；本版不提供管理后台或自动退款同步。

自动测试使用项目解释器，命令及规范见 `docs/TESTING.md`；赞助相关用例位于 `tests/test_sponsorship_*.py`，覆盖协议、网页闭环、并发通知与客户端窗口资源释放。真实商户支付跳转和真实付款到账是两项独立验收；收银台成功显示二维码不表示已经通过实付验收。
