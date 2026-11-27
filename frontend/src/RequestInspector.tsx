import { AppIcon } from './AppIcon';
import type { IconName } from './AppIcon';
import { AnimatePresence, motion } from 'motion/react';
import { useState } from 'react';
import type { AgentResponse, Product } from './agent-types';
import type { OperatorRequest } from './operator-types';

const tabs = [
  { id: 'actions', label: 'Действия' },
  { id: 'products', label: 'Подбор' },
  { id: 'sources', label: 'Источники' },
] as const;

export type InspectorTab = (typeof tabs)[number]['id'];

function InspectorEmpty({ icon, size = 17, children }: { icon: IconName; size?: number; children: string }) {
  return <p className="inspector-empty"><AppIcon name={icon} size={size} />{` ${children}`}</p>;
}

function IssueCard({ issue }: { issue: NonNullable<OperatorRequest['issue']> }) {
  return (
    <article className="result-card issue-card">
      <div className="result-card-meta">
        <AppIcon name="review" size={15} />
        <span>Требует внимания</span>
      </div>
      <h3>{issue.label}</h3>
      <p>{issue.detail}</p>
    </article>
  );
}

function ProductResult({ product, index }: { product: Product; index: number }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <article className={`result-card result-card--${index % 3}`}>
      <div className="result-card-meta">
        <span>{product.recommended ? 'Рекомендация' : 'Альтернатива'}{product.version && ` · ${product.version}`}</span>
        {product.url && (
          <a className="result-link" href={product.url} target="_blank" rel="noreferrer" aria-label={`Открыть ${product.name} в каталоге`}>
            <AppIcon name="external" size={16} />
          </a>
        )}
      </div>
      <h3>{product.name}</h3>
      <p>{product.summary}</p>
      {product.detail && (
        <>
          <button type="button" className="result-detail" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>
            {expanded ? 'Свернуть' : 'Подробнее'}
          </button>
          {expanded && <p className="result-extra">{product.detail}</p>}
        </>
      )}
    </article>
  );
}

export function RequestConditions({ requirements }: { requirements: AgentResponse['requirements'] }) {
  return (
    <section className="request-conditions">
      <h3>Условия клиента</h3>
      <dl>
        {requirements.map(({ label, value }, index) => (
          <div key={`${label}-${index}`}><dt>{label}</dt><dd>{value}</dd></div>
        ))}
      </dl>
    </section>
  );
}

function RequestTrace({ trace }: { trace: AgentResponse['trace'] }) {
  return (
    <section className="trace-panel">
      <h3>Ход работы</h3>
      <ol className="trace-list" role="list">
        {trace.map((step, index) => (
          <li key={`${step.label}-${index}`} className="trace-step">
            <span className="trace-node" aria-hidden="true">{index + 1}</span>
            {step.detail ? (
              <details open={index === trace.length - 1}>
                <summary>{step.label}</summary>
                <p>{step.detail}</p>
              </details>
            ) : <span className="trace-step-label">{step.label}</span>}
          </li>
        ))}
      </ol>
    </section>
  );
}

export function RequestContext({ response: { requirements, trace }, showConditions = true }: {
  response: AgentResponse;
  showConditions?: boolean;
}) {
  return (
    <>
      {showConditions && requirements.length > 0 && <RequestConditions requirements={requirements} />}
      {trace.length > 0 && <RequestTrace trace={trace} />}
    </>
  );
}

function ProductResults({ products }: { products: AgentResponse['products'] }) {
  if (!products.length) {
    return <InspectorEmpty icon="products" size={18}>Рекомендации пока отсутствуют.</InspectorEmpty>;
  }

  return [...products]
    .sort((first, second) => Number(second.recommended) - Number(first.recommended))
    .map((product, index) => <ProductResult key={product.id} product={product} index={index} />);
}

function SourceResults({ sources }: { sources: AgentResponse['sources'] }) {
  if (!sources.length) {
    return <InspectorEmpty icon="sources" size={18}>Источники в ответе отсутствуют.</InspectorEmpty>;
  }

  return (
    <ul className="source-list">
      {sources.map((source, index) => (
        <li key={`${source.url}-${index}`}>
          <a href={source.url} target="_blank" rel="noreferrer">
            <AppIcon name="sources" size={17} /><span>{source.title}{source.label && <small>{source.label}</small>}</span>
            <AppIcon name="external" size={15} />
          </a>
        </li>
      ))}
    </ul>
  );
}

export function RequestTabContent({ response, tab }: {
  response: AgentResponse;
  tab: Exclude<InspectorTab, 'actions'>;
}) {
  return tab === 'products'
    ? <ProductResults products={response.products} />
    : <SourceResults sources={response.sources} />;
}

export function RequestInspector({ request, tab, onTab, onTest }: {
  request?: OperatorRequest;
  tab: InspectorTab;
  onTab: (tab: InspectorTab) => void;
  onTest?: () => void;
}) {
  const response = request?.response;

  return (
    <aside className="inspector" id="inspector" aria-labelledby="inspector-title" tabIndex={-1}>
      <header className="inspector-header">
        <div className="inspector-title">
          <h2 id="inspector-title">Работа агента</h2>
        </div>
        <div className="inspector-tabs" role="group" aria-label="Разделы работы агента">
          {tabs.map(item => (
            <button type="button" key={item.id} aria-pressed={tab === item.id} onClick={() => onTab(item.id)}>
              {tab === item.id && <motion.span className="inspector-tab-active" layoutId="inspector-tab" />}
              <AppIcon name={item.id} size={15} />
              {item.label}
            </button>
          ))}
        </div>
      </header>
      <motion.div className="inspector-body" layoutScroll>
        {request && response ? (
          <>
            {request.issue && <IssueCard issue={request.issue} />}
            <AnimatePresence initial={false} mode="popLayout">
              <motion.div
                key={`${request.id}-${tab}`}
                className="inspector-view"
                initial={{ opacity: 0, y: 13 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -7, transition: { duration: 0.12 } }}
                transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
              >
                {tab === 'actions' ? (
                  <>
                    <RequestContext response={response} />
                    {!response.trace.length && <InspectorEmpty icon="actions">Действия пока отсутствуют.</InspectorEmpty>}
                  </>
                ) : <RequestTabContent response={response} tab={tab} />}
              </motion.div>
            </AnimatePresence>
          </>
        ) : <InspectorEmpty icon="journal">Выберите запрос в журнале.</InspectorEmpty>}
      </motion.div>
      {onTest && (
        <footer className="inspector-utilities">
          <button type="button" onClick={onTest}><AppIcon name="test" size={17} /> Тест агента</button>
        </footer>
      )}
    </aside>
  );
}
