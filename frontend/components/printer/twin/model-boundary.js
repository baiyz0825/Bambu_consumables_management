"use client";

import { Component } from "react";

/**
 * GLB 加载失败时的兜底边界。
 *
 * `useGLTF` 在文件损坏、不是合法 glTF、或网络中断时会**抛错**。
 * 没有边界的话整个页面会被错误页替换——用户只是放错了一个文件，
 * 不应该把设备详情页搞挂。这里捕获后回退到参数化模型。
 */
export class ModelBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error) {
    // 只在控制台提示，不打断用户
    if (typeof console !== "undefined") {
      console.warn("[twin] GLB 模型加载失败，已回退到参数化模型：", error?.message || error);
    }
    // 通知父组件把「模型来源」标签同步改掉
    this.props.onError?.(error);
  }

  render() {
    if (this.state.failed) return this.props.fallback ?? null;
    return this.props.children;
  }
}
