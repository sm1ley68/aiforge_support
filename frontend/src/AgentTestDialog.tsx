import { AppIcon } from './AppIcon';
import { useEffect, useLayoutEffect, useRef } from 'react';
import { useConsultation } from './use-consultation';

export function AgentTestDialog({ onClose }: { onClose: () => void }) {
  const { response, messages, draft, setDraft, pending, error, send } = useConsultation();
  const dialog = useRef<HTMLDialogElement>(null);
  const transcript = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);

  useLayoutEffect(() => {
    const element = transcript.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [messages, pending]);

  return (
    <dialog
      ref={dialog}
      className="test-dialog"
      aria-labelledby="test-title"
      onCancel={event => { event.preventDefault(); onClose(); }}
      onClick={event => { if (event.target === event.currentTarget) onClose(); }}
    >
      <div className="test-view">
        <header>
          <div><h2 id="test-title">Тест агента</h2></div>
          <button type="button" className="close-test" onClick={onClose} aria-label="Закрыть"><AppIcon name="close" size={20} /></button>
        </header>
        <div ref={transcript} className="test-transcript" role="log" aria-label="Тестовый диалог">
          {messages.length === 0 && <p className="test-prompt">Введите пример обращения клиента.</p>}
          {messages.map((message, index) => <p className={`test-message test-message--${message.role}`} key={index}>{message.content}</p>)}
          {pending && <p className="test-prompt">Агент готовит ответ…</p>}
          {response.sources.length > 0 && (
            <ul className="test-sources">
              {response.sources.map(source => (
                <li key={source.url}><a href={source.url} target="_blank" rel="noreferrer">{source.title} <AppIcon name="external" size={14} /></a></li>
              ))}
            </ul>
          )}
        </div>
        {error && <p className="test-error" role="alert">{error}</p>}
        <form onSubmit={event => { event.preventDefault(); void send(); }}>
          <input aria-label="Текст тестового запроса" placeholder="Например, «Нужна Astra Linux»" value={draft} onChange={event => setDraft(event.currentTarget.value)} />
          <button type="submit" aria-label="Запустить тест" disabled={!draft.trim() || pending}>
            {pending ? <AppIcon name="loading" className="spinner" size={19} /> : <AppIcon name="send" size={20} />}
          </button>
        </form>
      </div>
    </dialog>
  );
}
