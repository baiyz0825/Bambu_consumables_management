import { ApiError, apiBaseUrl, fetchJson } from "./api";

/**
 * 合盘模块（backend: app/api/routers/plate_merger.py）的客户端封装。
 *
 * 约定：所有输入文件必须先通过 `upload3mf` 上传，拿到服务端返回的 `path`
 * 后再传给 analyze / merge / probe —— 后端只接受上传目录内的路径。
 */

const PM = "/plate-merger";

/** 三档换盘码预设 */
export function listPresets() {
  return fetchJson(`${PM}/presets`);
}

/** 渲染指定预设的换盘 G-code 与时长估算 */
export function renderPreset(presetId) {
  return fetchJson(`${PM}/presets/${encodeURIComponent(presetId)}/render`, { method: "POST" });
}

/** 上传 3MF，返回 { path, name, size } */
export async function upload3mf(file, { timeoutMs = 300000 } = {}) {
  const form = new FormData();
  form.append("file", file);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${apiBaseUrl()}${PM}/upload`, {
      method: "POST",
      body: form,
      signal: controller.signal
    });
    if (!res.ok) {
      let detail = null;
      try {
        detail = (await res.json())?.detail ?? null;
      } catch {
        detail = null;
      }
      throw new ApiError(
        typeof detail === "string" ? detail : `上传失败（${res.status}）`,
        { status: res.status, detail }
      );
    }
    return await res.json();
  } catch (err) {
    if (err?.name === "AbortError") {
      throw new ApiError("上传超时，请检查网络或文件大小", { status: 0 });
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * 统计盘数 / 时长 / 耗材。
 * @param {{path: string, plate: number}[]} items
 */
export function analyze(items) {
  return fetchJson(`${PM}/analyze`, {
    method: "POST",
    body: JSON.stringify({ items })
  });
}

/**
 * 执行合盘。
 * @param {object} payload 见后端 MergeIn
 */
export function merge(payload) {
  return fetchJson(`${PM}/merge`, {
    method: "POST",
    body: JSON.stringify(payload),
    timeoutMs: 180000
  });
}

/** 已生成的产物列表（按时间倒序） */
export function listOutputs() {
  return fetchJson(`${PM}/outputs`);
}

/** 删除产物 */
export function deleteOutput(name) {
  return fetchJson(`${PM}/outputs/${encodeURIComponent(name)}`, { method: "DELETE" });
}

/** 产物的直链（可用于 <a download> 或 window.open） */
export function outputDownloadUrl(name) {
  return `${apiBaseUrl()}${PM}/download/${encodeURIComponent(name)}`;
}

/** 触发浏览器下载 */
export function downloadOutput(name) {
  if (typeof window === "undefined") return;
  const a = document.createElement("a");
  a.href = outputDownloadUrl(name);
  a.download = name;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/**
 * 合盘产物记录（可按打印机过滤）。
 * @param {{printerId?: string|null, limit?: number}} options
 */
export function listArtifacts({ printerId = null, limit = 20 } = {}) {
  const query = new URLSearchParams({ limit: String(limit) });
  if (printerId) query.set("printer_id", printerId);
  return fetchJson(`${PM}/artifacts?${query.toString()}`);
}

/**
 * 产物的逐层索引，供数字孪生推算喷嘴位置。
 * 返回 `{ count, bbox, out_of_bounds, layers: [[z, xMin, xMax, yMin, yMax], ...] }`
 */
export function getArtifactLayers(artifactId) {
  return fetchJson(`${PM}/artifacts/${encodeURIComponent(artifactId)}/layers`, {
    timeoutMs: 60000
  });
}

/** 版本指纹探测 */
export function probe(path) {
  return fetchJson(`${PM}/probe`, {
    method: "POST",
    body: JSON.stringify({ path })
  });
}

/** 两份切片的指纹差异 */
export function probeDiff(base, current) {
  return fetchJson(`${PM}/probe/diff`, {
    method: "POST",
    body: JSON.stringify({ base, current })
  });
}

/** 生成不加热、不耗料的换盘测试文件 */
export function makeTestFile(templatePath, cycles = 1, preset = "builtin:a1-conservative") {
  return fetchJson(`${PM}/test-file`, {
    method: "POST",
    body: JSON.stringify({ template: templatePath, cycles, preset }),
    timeoutMs: 120000
  });
}

/**
 * 自动分盘排产。
 * @param {{name: string, minutes: number, filament?: string[]}[]} jobs
 */
export function planPlates(jobs, { maxMinutes = null, maxPlates = 9 } = {}) {
  return fetchJson(`${PM}/plan`, {
    method: "POST",
    body: JSON.stringify({ jobs, max_minutes: maxMinutes, max_plates: maxPlates })
  });
}

/** 上传 + 下发打印 */
export function dispatch(payload) {
  return fetchJson(`${PM}/dispatch`, {
    method: "POST",
    body: JSON.stringify(payload),
    timeoutMs: 150000
  });
}

/** 把秒格式化为「x小时y分」 */
export function formatDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const h = Math.floor(total / 3600);
  const m = Math.round((total % 3600) / 60);
  if (h > 0) return `${h} 小时 ${m} 分`;
  return `${m} 分`;
}

/** 字节格式化 */
export function formatBytes(bytes) {
  const n = Number(bytes) || 0;
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}
