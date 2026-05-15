/** Заголовок Authorization для JWT из localStorage (вход «Войти»). */
export function bearerAuthHeaders() {
  try {
    const t = localStorage.getItem('user_token')
    return t ? { Authorization: `Bearer ${t}` } : {}
  } catch {
    return {}
  }
}
