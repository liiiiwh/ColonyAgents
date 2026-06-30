/** 把内部 thread_key 渲染成人类可读标签——绝不暴露裸 uuid。
 *
 * 用于没有后端解析名（agent name）的场合（如记忆压缩分支摘要）。有解析名的场合
 * （线程列表/头部）优先用后端 title。
 * - main → 主线；health → 健康自检
 * - worker:{super_id}:{worker_id} → Worker · {worker_id 前 8 位}
 * - 其它 → 原样
 */
export function cleanThreadKey(threadKey: string): string {
  if (!threadKey) return threadKey;
  if (threadKey === 'main') return '主线';
  if (threadKey === 'health') return '健康自检';
  if (threadKey.startsWith('worker:')) {
    const parts = threadKey.split(':');
    const wid = parts[2];
    if (wid) return `Worker · ${wid.slice(0, 8)}`;
  }
  return threadKey;
}
