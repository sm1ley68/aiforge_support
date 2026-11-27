import { useEffect, useState } from 'react';
import { AppIcon } from './AppIcon';
import { DemoNotice } from './DemoNotice';
import { LiveStoreAdvisor } from './LiveStoreAdvisor';
import { ApiError, formatCatalogDate, formatPrice, json, safeLink } from './softline-api';
import type { CatalogCard } from './softline-api';
import './product-entry.css';

const facts = {
  license_type: 'Тип лицензии',
  term: 'Срок',
  platform: 'Платформа',
  operating_system: 'Операционная система',
} as const;

export function ProductEntry({ offerId, openChat }: { offerId: string; openChat: boolean }) {
  const [card, setCard] = useState<CatalogCard>();
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void json<CatalogCard>(`/api/catalog/offers/${encodeURIComponent(offerId)}`, { signal: controller.signal })
      .then(card => { if (!controller.signal.aborted) setCard(card); })
      .catch(error => {
        if (!controller.signal.aborted) setError(error instanceof ApiError && [404, 422].includes(error.status)
          ? 'Товар с таким ID отсутствует в каталоге.'
          : 'Каталог временно недоступен.');
      });
    return () => controller.abort();
  }, [offerId, attempt]);

  if (openChat && card) return <LiveStoreAdvisor selectedOffer={card} />;

  const source = card && safeLink(card.url);
  const offerFacts = card?.verified_facts.filter(fact => Object.hasOwn(facts, fact.field)) ?? [];
  return <main className="product-entry">
    <article className="product-sheet">
      <DemoNotice />
      {card ? (
        <>
          <header className="product-sheet-heading">
            <span>ПО и лицензии</span>
            <h1>{card.title}</h1>
          </header>
          <div className="product-sheet-details">
            <dl>
              {card.sku && <div><dt>Артикул</dt><dd>{card.sku}</dd></div>}
              {offerFacts.map(fact => <div key={fact.field}>
                <dt>{facts[fact.field as keyof typeof facts]}</dt><dd>{fact.value}</dd>
              </div>)}
            </dl>
            <section className="product-purchase" aria-label="Цена и наличие">
              <span>Цена по фиду</span>
              <strong>{card.price_amount && card.currency ? formatPrice(card.price_amount, card.currency) : 'Цена не указана'}</strong>
              <p>{card.availability === true ? 'В наличии по фиду' : card.availability === false
                ? 'Поставка требует подтверждения' : 'Наличие не указано'}</p>
              <a className="product-chat-link" href={`?view=chat&offer=${encodeURIComponent(card.offer_id)}`}>
                <AppIcon name="agent" size={18} /> Спросить о товаре
              </a>
            </section>
          </div>
          <footer className="product-sheet-source">
            <span>Снимок каталога от <time dateTime={card.snapshot_at}>{formatCatalogDate(card.snapshot_at)}</time></span>
            {source && <a href={source} target="_blank" rel="noreferrer">Источник в Softline Store <AppIcon name="external" size={14} /></a>}
          </footer>
        </>
      ) : <>
        <h1>Карточка товара</h1>
        {error ? <p role="alert">{error}</p> : <p role="status">Загружаем данные из каталога…</p>}
        <div className="product-entry-actions">
          {error && <button type="button" onClick={() => { setError(''); setAttempt(value => value + 1); }}>Повторить</button>}
          <a href="?view=chat">Открыть чат</a>
        </div>
      </>}
    </article>
  </main>;
}
