export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(`/api${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...options?.headers }, signal: controller.signal });
    if (!response.ok) {
      let detail = `Request failed (${response.status}).`;
      try { const body = await response.json(); detail = typeof body.detail === 'string' ? body.detail : Array.isArray(body.detail) ? body.detail.map((item: { loc?: string[]; msg?: string }) => `${item.loc?.slice(1).join('.') || 'Input'}: ${item.msg || 'Invalid value'}`).join(' ') : body.detail?.message || (typeof body.error === 'string' ? body.error : detail); } catch { /* Response can be empty. */ }
      throw new Error(detail);
    }
    return await response.json() as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw new Error('The server took too long to respond. Your saved work is safe; please try again.');
    if (error instanceof TypeError) throw new Error('Cannot reach the Reflex server. Start the backend on port 8000, then reconnect.');
    throw error;
  } finally { window.clearTimeout(timer); }
}
export const post = <T>(path: string, body: unknown) => api<T>(path, { method: 'POST', body: JSON.stringify(body) });
