/**
 * 统一从未知错误里抽人类可读消息。
 *
 * 前端到处是 `catch (e: any) { setErr(e?.response?.data?.detail || e.message) }` —— axios 错误把
 * 后端 detail 塞在 response.data.detail，普通错误用 message。集中到一处，catch 块就能写 `unknown`。
 */
export function errMessage(e: unknown, fallback = 'Unknown error'): string {
  if (typeof e === 'object' && e !== null) {
    const resp = (e as { response?: { data?: { detail?: unknown } } }).response;
    const detail = resp?.data?.detail;
    if (typeof detail === 'string' && detail) return detail;
    const msg = (e as { message?: unknown }).message;
    if (typeof msg === 'string' && msg) return msg;
  }
  if (typeof e === 'string' && e) return e;
  return fallback;
}
