import { useState } from 'react';
import type { FormEvent } from 'react';
import { AppIcon } from './AppIcon';
import { ApiError, api } from './softline-api';
import { workspaceHref } from './use-operator-navigation';

export function OperatorLogin({ onSignedIn }: { onSignedIn: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = String(new FormData(event.currentTarget).get('token')).trim();
    setBusy(true);
    setError('');
    try {
      await api('/api/operator/session', { method: 'POST', headers: { Authorization: `Bearer ${token}` } });
      onSignedIn();
    } catch (error) {
      setError(error instanceof ApiError && error.status === 401
        ? 'Токен не подошёл. Проверьте его и повторите.' : 'Не удалось подключиться к кабинету.');
    } finally {
      setBusy(false);
    }
  }

  return <main className="stage stage--ascii stage--operator operator-login-page">
    <section className="operator-login" aria-labelledby="operator-login-title">
      <AppIcon name="mark" size={28} />
      <h1 id="operator-login-title">Кабинет менеджера</h1>
      <form className="operator-live-form" onSubmit={signIn}>
        <label>Токен доступа<input name="token" autoComplete="current-password" type="password" required /></label>
        <button className="operator-live-primary" disabled={busy} type="submit">{busy ? 'Входим…' : 'Войти'}</button>
        {error && <p className="chat-state-error" role="alert">{error}</p>}
      </form>
      <a href={workspaceHref({ view: 'chat' })}>Открыть клиентский чат <AppIcon name="chevron" size={14} /></a>
    </section>
  </main>;
}
