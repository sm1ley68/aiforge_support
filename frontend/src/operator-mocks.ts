import { demoConversation } from '../mock-agent.mjs';
import type { AgentResponse, Message, Product } from './agent-types';
import type { OperatorRequest } from './operator-types';

const r7Office: Product = {
  id: 'r7-office-business',
  name: 'Р7-Офис для бизнеса',
  summary: 'Редакторы документов, таблиц и презентаций для организаций.',
  url: 'https://store.softline.ru/novcommtech/ao-r7-dlya-biznesa/',
  recommended: true,
};

const astraWorkstation: Product = {
  ...demoConversation.products[0],
  recommended: true,
};

type ConversationDetails = Pick<AgentResponse, 'reply' | 'requirements' | 'trace'> &
  Partial<Pick<AgentResponse, 'products' | 'suggestedReplies'>> & { history: Message[] };

function conversation(conversationId: string, {
  history, reply, requirements, trace, products = [], suggestedReplies = [],
}: ConversationDetails): AgentResponse {
  return {
    conversationId,
    messages: [...history, { role: 'assistant', content: reply }],
    reply,
    requirements,
    products,
    sources: products.map(({ name, url }) => ({ title: name, url, label: 'Карточка Softline Store' })),
    trace,
    suggestedReplies,
  };
}

export const mockRequests: OperatorRequest[] = [
  {
    id: 'SL-1048',
    title: 'Astra Linux для 80 рабочих станций',
    customer: 'АО «Северная приборостроительная компания»',
    updatedAt: '2026-11-26T11:56:00+03:00',
    scenario: 'known',
    status: 'review',
    issue: {
      label: 'Коммерческие условия',
      detail: 'Подтвердить тип лицензии для 80 ПК и состав услуг по переносу профилей. В карточке каталога условий миграции нет.',
      checks: ['Тип лицензии на 80 ПК', 'Услуги по переносу профилей'],
    },
    comparison: {
      productId: astraWorkstation.id,
      rows: [
        {
          label: 'Уровень защиты', value: 'Усиленный', result: 'Совпадает по уровню защиты', state: 'match',
          detail: 'В данных подбора «Воронеж» указан как редакция с усиленным уровнем защиты.',
          sourceUrl: astraWorkstation.url,
        },
        {
          label: 'Развёртывание', value: 'Физические ПК', result: 'Редакция для рабочих станций', state: 'match',
          detail: 'Вариант рассчитан на рабочие станции. Совместимость с конкретными ПК нужно уточнить по параметрам проекта.',
          sourceUrl: astraWorkstation.url,
        },
        {
          label: 'Рабочие места', value: 'Около 80', result: 'Уточнить тип лицензии', state: 'review',
          detail: 'Пример поставки в каталоге описывает электронную лицензию на 12 месяцев. Тип лицензии для проекта на 80 ПК нужно подтвердить.',
          sourceUrl: astraWorkstation.url,
        },
        {
          label: 'Услуги', value: 'Поддержка и миграция рассматриваются', result: 'В каталоге нет условий миграции', state: 'missing',
          detail: 'Нужно уточнить состав услуг по переносу профилей.',
        },
      ],
    },
    response: demoConversation,
  },
  {
    id: 'SL-1047',
    title: 'Редакция Astra Linux для защищённого контура',
    customer: 'ООО «Невские системы»',
    updatedAt: '2026-11-26T11:39:00+03:00',
    scenario: 'known',
    status: 'review',
    issue: {
      label: 'Конфликт требований',
      detail: 'В заявке указан усиленный уровень защиты, а в требованиях службы ИБ — максимальный. Нужна действующая версия требований для 24 рабочих станций.',
      checks: ['Обязательный уровень защиты для 24 ПК'],
    },
    response: conversation('SL-1047', {
      history: [
        { role: 'user', content: 'Нужна Astra Linux на 24 рабочих места. В заявке записали усиленный уровень, но ИБ вчера прислала требования к максимальному.' },
      ],
      reply: 'Зафиксировал оба требования. Перед выбором редакции нужно подтвердить, какой уровень защиты обязателен для этих рабочих мест.',
      requirements: [
        { label: 'Рабочие места', value: '24 ПК' },
        { label: 'Уровень защиты', value: 'Усиленный по заявке, максимальный по требованиям ИБ' },
      ],
      trace: [
        { label: 'Зафиксированы требования', detail: 'Уровни защиты из заявки и сообщения ИБ расходятся.' },
        { label: 'Выбор отложен', detail: 'Редакция зависит от действующих требований ИБ.' },
      ],
      suggestedReplies: ['Подтвердить уровень защиты'],
    }),
  },
  {
    id: 'SL-1046',
    title: 'Цена и срок поставки 30 лицензий Astra Linux',
    customer: 'ГК «Уралкомплект»',
    updatedAt: '2026-11-26T11:17:00+03:00',
    scenario: 'question',
    status: 'review',
    issue: {
      label: 'Коммерческие условия',
      detail: 'Нужны цена партии из 30 электронных лицензий и подтверждение поставки в Екатеринбург до 4 декабря.',
      checks: ['Цена 30 электронных лицензий', 'Поставка в Екатеринбург до 4 декабря'],
    },
    response: conversation('SL-1046', {
      history: [
        { role: 'user', content: 'Сколько будут стоить 30 электронных лицензий Astra Linux «Воронеж»? Нужны в Екатеринбурге до 4 декабря.' },
      ],
      reply: 'Нашёл карточку «Воронеж». Для КП нужно подтвердить цену на 30 лицензий и возможность поставки до 4 декабря.',
      requirements: [
        { label: 'Количество', value: '30 электронных лицензий' },
        { label: 'Регион', value: 'Екатеринбург' },
        { label: 'Желаемый срок', value: 'До 4 декабря' },
      ],
      trace: [
        { label: 'Найдена карточка', detail: 'Издание «Воронеж» сопоставлено с запросом.' },
        { label: 'Нужна проверка', detail: 'Цена партии и срок поставки требуют подтверждения.' },
      ],
      products: [{ ...astraWorkstation, recommended: false }],
    }),
  },
  {
    id: 'SL-1045',
    title: 'Офисные приложения для проектной команды',
    customer: 'ООО «ГородПроект»',
    updatedAt: '2026-11-26T10:48:00+03:00',
    scenario: 'discovery',
    status: 'waiting',
    response: conversation('SL-1045', {
      history: [
        { role: 'user', content: 'Ищем офисное ПО для 45 сотрудников. Часть работает в филиале.' },
        { role: 'assistant', content: 'Какие приложения нужны и где должны храниться документы?' },
        { role: 'user', content: 'Точно нужны таблицы и текстовые документы. По хранению жду ответа от ИТ.' },
      ],
      reply: 'Зафиксировал 45 сотрудников, документы и таблицы. Для подбора уточните, можно ли хранить документы в облаке и требуется ли совместное редактирование между офисами.',
      requirements: [
        { label: 'Пользователи', value: '45 сотрудников' },
        { label: 'Приложения', value: 'Документы и таблицы' },
        { label: 'Размещение данных', value: 'Клиент уточняет у ИТ' },
      ],
      trace: [
        { label: 'Собраны требования', detail: 'Известны число пользователей и набор редакторов.' },
        { label: 'Ожидается ответ клиента', detail: 'Способ хранения и совместная работа определяют вариант поставки.' },
      ],
      suggestedReplies: ['Данные только на нашем сервере', 'Облачное хранение допустимо'],
    }),
  },
  {
    id: 'SL-1044',
    title: 'Поддержка макросов в Р7-Офис',
    customer: 'ООО «Балтийская логистика»',
    updatedAt: '2026-11-26T10:26:00+03:00',
    scenario: 'question',
    status: 'review',
    issue: {
      label: 'Нет подтверждающего источника',
      detail: 'Карточка Р7-Офис не подтверждает запуск XLSM с VBA, который обращается к локальной базе Access через ACE OLE DB.',
      checks: ['Запуск VBA в XLSM с подключением к Access'],
    },
    response: conversation('SL-1044', {
      history: [
        { role: 'user', content: 'Можно ли открыть в Р7-Офис нашу XLSM и выполнить макрос? Он тянет данные из Access через ACE OLE DB.' },
      ],
      reply: 'Карточка Р7-Офис не подтверждает совместимость этого макроса и подключения к Access. Для ответа нужна документация производителя по подключению или проверка на обезличенной копии файла.',
      requirements: [
        { label: 'Формат файла', value: 'XLSM с VBA' },
        { label: 'Источник данных', value: 'Access через ACE OLE DB' },
      ],
      trace: [
        { label: 'Проверена карточка', detail: 'Есть сведения об офисных редакторах.' },
        { label: 'Источник отсутствует', detail: 'Поддержка указанного подключения к Access не подтверждена.' },
      ],
      products: [{ ...r7Office, recommended: false }],
    }),
  },
  {
    id: 'SL-1043',
    title: 'Кандидат для пилота офисных редакторов',
    customer: 'АНО «Учебный центр Профиль»',
    updatedAt: '2026-11-26T10:02:00+03:00',
    scenario: 'discovery',
    status: 'resolved',
    response: conversation('SL-1043', {
      history: [
        { role: 'user', content: 'Что посмотреть для пилота на 12 человек? Редактируем документы, таблицы и презентации.' },
        { role: 'assistant', content: 'Нужны ли на пилоте почта или интеграции с другими системами?' },
        { role: 'user', content: 'Нет, решили начать с редакторов. Достаточно ссылки на продукт.' },
      ],
      reply: 'Для пилота с документами, таблицами и презентациями рассмотрите Р7-Офис для бизнеса. Прикладываю карточку продукта.',
      requirements: [
        { label: 'Пользователи', value: '12 участников пилота' },
        { label: 'Приложения', value: 'Документы, таблицы и презентации' },
      ],
      trace: [
        { label: 'Уточнён объём пилота', detail: 'На первом этапе нужны только офисные редакторы.' },
        { label: 'Подобран продукт', detail: 'Приложена карточка Р7-Офис для бизнеса из каталога.' },
      ],
      products: [r7Office],
    }),
  },
  {
    id: 'SL-1042',
    title: 'Astra Linux для нового филиала',
    customer: 'ООО «Точка снабжения»',
    updatedAt: '2026-11-26T09:42:00+03:00',
    scenario: 'known',
    status: 'waiting',
    response: conversation('SL-1042', {
      history: [
        { role: 'user', content: 'Планируем Astra Linux для нового филиала. Пока есть только предварительный список оборудования.' },
      ],
      reply: 'Уточните, пожалуйста, какие устройства нужно лицензировать: рабочие станции, серверы или оба типа. Для подбора также нужны число устройств каждого типа и требования ИБ.',
      requirements: [{ label: 'Продукт', value: 'Astra Linux' }],
      trace: [
        { label: 'Требования запрошены', detail: 'Пока не подтверждены типы устройств, их количество и требования ИБ.' },
      ],
      suggestedReplies: ['Указать число рабочих станций', 'Добавить сведения о серверах'],
    }),
  },
  {
    id: 'SL-1041',
    title: 'Карточка Astra Linux SE «Воронеж»',
    customer: 'АО «РегионСвязьПроект»',
    updatedAt: '2026-11-26T09:18:00+03:00',
    scenario: 'question',
    status: 'resolved',
    response: conversation('SL-1041', {
      history: [
        { role: 'user', content: 'Пришлите ссылку на «Воронеж» для x86-64 на 12 месяцев. Нужно приложить к перечню вариантов для ИБ.' },
      ],
      reply: 'Прикладываю карточку Astra Linux SE «Воронеж» с электронной лицензией x86-64 на 12 месяцев.',
      requirements: [
        { label: 'Редакция', value: 'Astra Linux SE «Воронеж»' },
        { label: 'Лицензия', value: 'Электронная, x86-64, 12 месяцев' },
      ],
      trace: [
        { label: 'Сверены параметры', detail: 'Редакция, архитектура и срок совпадают с запросом.' },
        { label: 'Источник приложен', detail: 'Добавлена карточка Softline Store для согласования.' },
      ],
      products: [astraWorkstation],
    }),
  },
];
