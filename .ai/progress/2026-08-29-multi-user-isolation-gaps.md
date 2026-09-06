# 多用户隔离缺口（P1，2026-08-29）

> 本迭代已完成：主题绑定 ACL、浏览器 `geo:*` / 敏感 `cgda.*` 按用户命名空间、导入任务 `owner_user_id` 列表与读写过滤。
> 下列项仍为**单机构共享资源池**，open 模式下知 ID 可访问；建议非 admin 主题使用 **whitelist**。

| 缺口 | 现状 | 建议后续 |
|------|------|----------|
| `imported-*` overlay | 无 owner；open ACL 默认放行 | 落盘 meta 加 `owner_user_id`；list/tile 过滤 |
| 用户工作流定义 | 共享用户定义目录，`author="user"` | 按 `user_id` / `theme_id` 分目录或元数据过滤 |
| `data_source` ACL | 可配置，热路径未 `check_resource_access` | 远程下载 / provider 列表接线 |
| Agent LLM 配置 | 部署级单文件 | 按主题或用户分密钥（若主题不可共享模型） |

运维建议：演示/课题主题默认 `whitelist` + 主题默认 allow 列表；主入口 SGFS 可保持 `open` 供 admin。
