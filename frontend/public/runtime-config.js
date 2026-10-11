/**
 * 运行时配置占位文件。
 *
 * 预编译镜像场景由容器启动脚本（docker-entrypoint.sh）覆盖本文件，注入
 * NEXT_PUBLIC_API_BASE_URL 等变量。本地/源码部署时保持空实现，避免 404。
 */
window.__RUNTIME_CONFIG__ = window.__RUNTIME_CONFIG__ || {};
