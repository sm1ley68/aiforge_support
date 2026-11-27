import asyncio
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import InvalidOperation
from hashlib import sha256
from sqlite3 import DatabaseError
from time import monotonic

from ..contracts import IntentModel, TemporaryReadError
from .catalog import CatalogOffer, SoftlineCatalog
from .contracts import (
    CartLine, Customer, Document, Handoff, Message, ModelCall, OrderRecord,
    PendingConsultation, PendingProduct, Product, Seller, Source, State, Trace, TurnResult,
)
from .documents import build_document
from .edo import edo_answer
from .extraction import (
    PROMPT_VERSION, RANK_SCHEMA, RANK_SYSTEM, SCHEMA, SYSTEM, Extraction, LineChange, parse_extraction,
)
from .indexed_chat import (
    INDEXED_PROMPT_VERSION, INDEXED_SCHEMA, INDEXED_SYSTEM, CatalogInput, backup_input, context_fact, decide,
    desktop_input, direct_sku, fallback_input, is_origin_follow_up, last_offer_sources, parse_catalog_input,
    requests_catalog_name, verified_named_input,
)
from .offer_evidence import OfferCardEvidence
from .retrieval import KnowledgeBase, expand_exceptions, fuzzy_candidates, normalize
from .routing import explicit_handoff_requested, requests_product_selection
from .support_answers import CHECKOUT_QUESTION, SUPPORT_ANSWERS, checkout_help, support_request

SPECIAL_CONDITION = re.compile(
    r"постоплат\w*|предоплат\w*|отсроч\w*|рассроч\w*|скид\w*|без\s+ндс|индивидуальн\w+\s+(?:цен\w*|услов\w*)",
    re.IGNORECASE,
)
CONFIRMATION = re.compile(
    r"^(?:да|подтверждаю|согласен|согласна|подходит|устраивает)(?=$|[\s,.!—])", re.IGNORECASE
)
NUMBERED_CHOICE = re.compile(
    r"^(?:вариант\s+)?([1-5])(?:[, ]+\s*(?:нужно\s+)?([1-9]\d{0,5})\s*(?:лицензи\w*|штук\w*)?)?[.!]?$",
    re.IGNORECASE,
)
GENERAL_DOCUMENT_QUESTION = re.compile(r"\b(?:как|где)\b.*\b(?:скачать|найти|посмотреть)\b", re.IGNORECASE)
SIMPLE_CATALOG_QUESTION = re.compile(
    r"^(сколько стоит|когда поставите|есть ли в наличии)\s+([\w -]+)[?.!]?$",
    re.IGNORECASE,
)
EXPLICIT_INVOICE_COMMANDS = {
    "выставьте счет", "теперь выставьте счет", "выставьте счет пожалуйста", "выставить счет",
}
EXPLICIT_REPRICE_CONFIRMATION = {
    "да", "подтверждаю", "да согласен на новую цену", "да согласна на новую цену", "согласен на новую цену",
    "согласна на новую цену", "подтверждаю новую цену",
}
CUSTOMER_ORDER_REFERENCE = re.compile(r"\b(?:мо[йяеию]|наш\w*|покупк\w*|заказ\w*|номер)\b", re.IGNORECASE)
DECLINE = re.compile(r"\b(?:нет|не\s+соглас\w*|не\s+подходит|не\s+устраивает)\b", re.IGNORECASE)
INDEXED_MANAGER_TERMS = re.compile(r"\b(?:постоплат\w*\s+\d+|(?:дайте|сделайте|нужна)\s+(?:нам\s+)?скидк\w*|"
                                  r"(?:подготовьте|сделайте|оформите)\s+(?:кп|коммерческое предложение))\b", re.I)
CATALOG_NAME_QUESTION = "Не нашёл товар по этому названию. Проверьте написание или пришлите артикул."

SELECTION_QUESTION = (
    "Какую задачу нужно решить? Если товар уже выбран, укажите его название или артикул."
)
SELECTION_EXAMPLES = (
    "Что ближе к вашей задаче: защита почты и файлов, резервное копирование, "
    "редактирование PDF или планирование проектов? "
    "Если нужно что-то другое, опишите, что сотрудники хотят делать."
)


def effect_id(kind: str, conversation_id: str, message_id: str) -> str:
    digest = sha256(json.dumps([conversation_id, message_id]).encode()).hexdigest()[:16]
    return f"{kind}-{digest}"


class CommerceAgent:
    def __init__(
        self, model: IntentModel, *, products: Sequence[Product] = (), knowledge: KnowledgeBase,
        orders: Sequence[OrderRecord] = (), conditions: Sequence[Source] = (),
        seller: Seller | None = None, search: Callable | None = None, model_timeout: float = 18,
        catalog_index: SoftlineCatalog | None = None,
        card_lookup: Callable[[CatalogOffer], OfferCardEvidence | None] | None = None,
    ):
        self.model = model
        if catalog_index is not None and products:
            raise ValueError("Use either the indexed catalog or in-memory products")
        self.catalog_index = catalog_index
        self.card_lookup = card_lookup
        self.products = {product.sku: product for product in products}
        if len(self.products) != len(products):
            raise ValueError("Duplicate catalog SKU")
        self.knowledge = knowledge
        self.orders = tuple(orders)
        self.conditions = tuple(conditions)
        self.seller = seller
        self.model_name = getattr(model, "model", type(model).__name__)
        self.search = search
        self.model_timeout = model_timeout

    async def reply(
        self, conversation_id: str, message_id: str, text: str, *, state: State = State(),
        history: tuple[Message, ...] = (), customer: Customer | None = None,
        now: datetime | None = None,
    ) -> TurnResult:
        """Process one turn. The caller provides trusted, conversation-scoped state."""
        now = now if now is not None else datetime.now(timezone.utc)
        if not conversation_id or not message_id or not text.strip() or len(text) > 8_000:
            raise ValueError("Expected IDs and a non-empty message of at most 8000 characters")
        if now.utcoffset() is None:
            raise ValueError("now must have a timezone")
        turn = _Turn(self, conversation_id, message_id, text.strip(), state, history, customer, now)
        started = monotonic()
        result = await turn.run()
        return replace(result, trace=Trace(
            self.model_name, INDEXED_PROMPT_VERSION if self.catalog_index is not None else PROMPT_VERSION,
            round((monotonic() - started) * 1000),
            tuple(turn.calls),
        ))


class _Turn:
    def __init__(self, agent, conversation_id, message_id, text, state, history, customer, now):
        self.agent = agent
        self.conversation_id = conversation_id
        self.message_id = message_id
        self.text = text
        self.state = state
        self.customer = customer
        self.customer_id = customer.id if customer else None
        self.history = (*history, Message("customer", text))
        self.now = now
        self.calls = []
        self.catalog = {
            sku: product for sku, product in agent.products.items()
            if product.source.active(now, self.customer_id)
        }

    async def model_call(self, step, system, data, schema):
        started = monotonic()
        try:
            async with asyncio.timeout(self.agent.model_timeout):
                output, usage = await self.agent.model.complete(
                    system, json.dumps(data, ensure_ascii=False), schema
                )
        except (TemporaryReadError, ValueError, TimeoutError) as error:
            self.calls.append(ModelCall(step, round((monotonic() - started) * 1000), error=type(error).__name__))
            raise
        self.calls.append(ModelCall(step, round((monotonic() - started) * 1000),
                                    usage.input_tokens, usage.output_tokens))
        return output

    def clarification(self, text):
        return TurnResult("clarify", text, self.state)

    def handoff(self, reason, question, sources=()):
        summary = " ".join(self.text.split())
        if len(summary) > 240:
            summary = summary[:239] + "…"
        return TurnResult(
            "handoff", "Передаю вопрос менеджеру вместе с контекстом обращения.", self.state, sources,
            handoff=Handoff(effect_id("handoff", self.conversation_id, self.message_id), reason,
                            summary, question, self.state.cart, self.history, sources, self.state.catalog_context),
        )

    def product_match(self, reference):
        key = normalize(reference)
        choices = [(sku, (sku, product.name, *product.aliases)) for sku, product in self.catalog.items()]
        exact = [sku for sku, names in choices if any(key == normalize(name) for name in names)]
        return exact, [] if exact else fuzzy_candidates(reference, choices)

    def ask_product(self, skus, quantity=None, *, remember=False):
        skus = tuple(sku for sku in skus[:5] if sku in self.catalog)
        if not skus:
            return self.clarification("Не нашёл позицию. Уточните название, редакцию или артикул.")
        if remember:
            self.state = replace(self.state, pending=PendingProduct(skus, quantity))
        choices = "\n".join(
            f"{index}. {self.catalog[sku].name} ({sku})" for index, sku in enumerate(skus, 1)
        )
        return self.clarification(f"Уточните позицию по номеру варианта или артикулу.\n{choices}")

    async def run(self):
        if not explicit_handoff_requested(self.text) and (answer := edo_answer(self.text)):
            text, sources = answer
            return TurnResult("answer", text, self.state, sources)
        if self.agent.catalog_index is not None:
            return await self.run_indexed(self.agent.catalog_index)
        pending_consult = self.state.consultation
        if pending_consult:
            picked = NUMBERED_CHOICE.fullmatch(self.text)
            if picked and not picked[2] and int(picked[1]) <= len(pending_consult.skus):
                sku = pending_consult.skus[int(picked[1]) - 1]
            else:
                exact, _ = self.product_match(self.text)
                sku = exact[0] if len(exact) == 1 else None
            self.state = replace(self.state, consultation=None)
            if sku in self.catalog:
                lookup = Extraction(
                    pending_consult.kind, (), sku, pending_consult.fact, None,
                    pending_consult.special_terms, None, False, False,
                )
                return await self.consult(lookup, question=pending_consult.question)
        # Numbered choices are generated by the service, so resolve explicit picks directly.
        pick = NUMBERED_CHOICE.fullmatch(self.text) if self.state.pending else None
        if pick:
            choice = int(pick[1])
            updates = (LineChange("upsert", None, int(pick[2])),) if pick[2] else ()
            return self.document_turn(Extraction("continue", updates, None, None, None, None, choice, False, False))

        command = normalize(self.text)
        if self.state.cart and command in EXPLICIT_INVOICE_COMMANDS:
            return self.document_turn(Extraction("invoice", (), None, None, None, None, None, False, False))
        if self.state.awaiting_price_confirmation and command in EXPLICIT_REPRICE_CONFIRMATION:
            return self.document_turn(Extraction("continue", (), None, None, None, None, None, False, True))
        if not SPECIAL_CONDITION.search(self.text):
            direct = self.agent.knowledge.direct(self.text, self.now, customer_id=self.customer_id)
            if direct:
                return self.knowledge_answer(direct)
        simple_product = SIMPLE_CATALOG_QUESTION.fullmatch(self.text)
        if simple_product and self.product_match(simple_product[2].strip())[0]:
            fact = "price" if simple_product[1].casefold() == "сколько стоит" else "availability"
            return await self.consult(Extraction(
                "catalog", (), simple_product[2].strip(), fact, None, None, None, False, False,
            ))
        context = {
            "message": self.text,
            "document_intent": self.state.intent,
            "cart": [asdict(line) for line in self.state.cart],
            "pending_choices": list(self.state.pending.skus) if self.state.pending else [],
            "awaiting_price_confirmation": self.state.awaiting_price_confirmation,
            "has_special_terms": bool(self.state.requested_terms),
        }
        try:
            raw = await self.model_call("extract", SYSTEM, context, SCHEMA)
            extraction = parse_extraction(raw, self.text)
        except (TemporaryReadError, ValueError, TimeoutError):
            return self.handoff("extraction_unavailable", "Уточнить, что нужно клиенту, и обработать запрос.")
        if extraction.kind == "handoff":
            return self.handoff("manager_requested", "Разобрать запрос клиента.")
        if extraction.kind == "order":
            if (not extraction.order_id and GENERAL_DOCUMENT_QUESTION.search(self.text)
                    and not CUSTOMER_ORDER_REFERENCE.search(self.text)):
                return await self.consult(replace(extraction, kind="knowledge"))
            return self.answer_order(extraction.order_id)
        if extraction.kind in ("catalog", "knowledge"):
            return await self.consult(extraction)
        return self.document_turn(extraction)

    async def run_indexed(self, index: SoftlineCatalog) -> TurnResult:
        context = self.state.catalog_context
        if explicit_handoff_requested(self.text) or INDEXED_MANAGER_TERMS.search(self.text):
            try:
                sources = await asyncio.to_thread(last_offer_sources, index, context)
            except (DatabaseError, OSError):
                sources = ()
            return self.handoff("manager_requested", "Уточнить условия и проверить выбранные позиции.", sources)

        if normalize(self.text) in {"спасибо", "спасибо большое", "большое спасибо", "благодарю"}:
            return TurnResult("answer", "Пожалуйста! Если появится ещё вопрос, напишите.", self.state)

        topic, escalate = support_request(self.text, self.state.support_topic)
        self.state = replace(self.state, support_topic=None)
        eligible = self.agent.knowledge.eligible(self.now, None, self.customer_id)
        support = eligible.get(SUPPORT_ANSWERS[topic].id) if topic else None
        if escalate and topic is None:
            return self.handoff("support_follow_up", "Проверить статус или состав заказа.")
        if support is not None:
            if escalate:
                sources = expand_exceptions((support,), eligible, limit=5)
                return self.handoff("support_follow_up", f"Проверить обращение по теме «{support.title.lower()}».", sources)
            self.state = replace(self.state, support_topic=topic)
            article = self.agent.knowledge.prefer_article(support, eligible)
            return self.knowledge_answer(expand_exceptions((article,), eligible, limit=5))
        faq = self.agent.knowledge.match_faq(self.text, self.now, customer_id=self.customer_id)
        if faq:
            return self.knowledge_answer(faq)
        previous = self.history[-2] if len(self.history) > 1 else None
        after_checkout_question = previous == Message("agent", CHECKOUT_QUESTION)
        if checkout := checkout_help(self.text, after_question=after_checkout_question):
            if checkout == CHECKOUT_QUESTION:
                return self.clarification(checkout)
            return self.handoff("support_follow_up", checkout)
        try:
            if (sku := direct_sku(self.text)) is not None:
                patch = sku
            elif (fact := context_fact(self.text)) is not None:
                patch = CatalogInput("fact", fact=fact)
            elif context is not None and is_origin_follow_up(self.text):
                patch = CatalogInput("continue")
            elif (desktop := desktop_input(self.text, context)) is not None:
                patch = desktop
            elif (backup := backup_input(self.text, context)) is not None:
                patch = backup
            elif (named := await asyncio.to_thread(verified_named_input, index, self.text, context)) is not None:
                patch = named
            else:
                raw = await self.model_call("extract_catalog", INDEXED_SYSTEM, {
                    "message": self.text, "selection": asdict(context) if context else None,
                }, INDEXED_SCHEMA)
                patch = parse_catalog_input(raw, self.text)
        except (TemporaryReadError, ValueError, TimeoutError):
            patch = fallback_input(self.text, context)
        except (DatabaseError, OSError):
            return self.handoff("catalog_unavailable", "Перепроверить запрос по актуальному каталогу.")
        if patch is None or patch.action == "other":
            if previous == Message("agent", SELECTION_QUESTION):
                return self.clarification(SELECTION_EXAMPLES)
            if previous == Message("agent", SELECTION_EXAMPLES):
                return self.handoff("insufficient_requirements", "Уточнить задачу клиента и продолжить подбор.")
            if requests_product_selection(self.text):
                return self.clarification(SELECTION_QUESTION)
            if requests_catalog_name(self.text):
                if previous == Message("agent", CATALOG_NAME_QUESTION):
                    return self.handoff("insufficient_requirements", "Уточнить наименование товара или артикул.")
                return self.clarification(CATALOG_NAME_QUESTION)
            if patch is None:
                return self.handoff("extraction_unavailable", "Проверить запрос клиента и продолжить подбор.")
        try:
            decision = await asyncio.to_thread(decide, index, context, patch, self.text, self.agent.card_lookup)
        except (DatabaseError, OSError):
            return self.handoff("catalog_unavailable", "Перепроверить запрос по актуальному каталогу.")
        self.state = replace(self.state, catalog_context=decision.context)
        if decision.disputed_fact:
            return self.handoff("conflicting_sources", decision.disputed_fact, decision.sources)
        return TurnResult(decision.outcome, decision.text, self.state, decision.sources, products=decision.products,
                          recommendations=decision.recommendations)

    def answer_order(self, order_id):
        if not order_id:
            return self.clarification("Укажите номер покупки, которую нужно найти.")
        order = next((record for record in self.agent.orders if (
            self.customer_id is not None and record.customer_id == self.customer_id
            and normalize(record.id) == normalize(order_id) and record.source.active(self.now, self.customer_id)
        )), None)
        if order is None:
            return self.handoff("order_unavailable", "Проверить доступ клиента к указанной покупке.")
        return TurnResult("answer", order.source.text, self.state, (order.source,))

    async def consult(self, extraction, *, question=None):
        question = question or self.text
        product = None
        if extraction.product:
            exact, candidates = self.product_match(extraction.product)
            if len(exact) != 1:
                choices = tuple((exact or candidates)[:5])
                self.state = replace(self.state, consultation=PendingConsultation(
                    question, extraction.kind, extraction.catalog_fact, extraction.special_terms, choices,
                ))
                return self.ask_product(choices)
            product = self.catalog[exact[0]]
        elif len(self.state.cart) == 1:
            product = self.catalog.get(self.state.cart[0].sku)
        requested = self.special_request(extraction.special_terms, question)
        if requested:
            rules = self.match_conditions(requested,
                                          (product.sku,) if product else ())
            if len(rules) != 1:
                return self.handoff("special_terms_unconfirmed", "Проверить запрошенные клиентом особые условия.")
            return TurnResult("answer", rules[0].text, self.state, rules)
        if extraction.kind == "catalog":
            if product is None:
                self.state = replace(self.state, consultation=PendingConsultation(
                    question, extraction.kind, extraction.catalog_fact, extraction.special_terms, (),
                ))
                return self.clarification("Уточните название продукта или артикул.")
            if extraction.catalog_fact == "availability":
                if not product.availability:
                    return self.handoff("availability_unknown", "Уточнить наличие и срок поставки.", (product.source,))
                answer = product.availability
            elif extraction.catalog_fact == "product":
                answer = product.source.text
            else:
                if not product.price.is_finite() or product.price < 0:
                    return self.handoff("catalog_price_invalid", "Проверить цену позиции.", (product.source,))
                answer = f"{product.price:.2f} {product.currency}"
            return TurnResult("answer", f"{product.name} ({product.sku}) — {answer}", self.state, (product.source,))
        sku = product.sku if product else None
        if self.agent.search is None:
            ranked = self.agent.knowledge.search(question, self.now, sku, self.customer_id)
        else:
            eligible = self.agent.knowledge.eligible(self.now, sku, self.customer_id)
            try:
                ranked = await asyncio.to_thread(self.agent.search, question, eligible)
            except (OSError, RuntimeError, ValueError):
                ranked = self.agent.knowledge.search(question, self.now, sku, self.customer_id)
        if not ranked:
            return self.handoff("knowledge_missing", "Найти подтверждённый ответ на вопрос клиента.")
        excerpts = [{"id": src.id, "title": src.title, "text": src.text[:1800]} for src in ranked]
        try:
            result = await self.model_call(
                "select_evidence", RANK_SYSTEM, {"question": question, "sources": excerpts}, RANK_SCHEMA,
            )
        except (TemporaryReadError, ValueError, TimeoutError):
            return self.handoff("knowledge_unverified", "Проверить найденные материалы.", ranked)
        ids = result.get("ids") if isinstance(result, dict) else None
        lookup = {source.id: source for source in ranked}
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 3
                or any(not isinstance(source_id, str) or source_id not in lookup for source_id in ids)):
            return self.handoff("knowledge_unverified", "Проверить, какие материалы применимы.", ranked)
        selected = dict.fromkeys(
            self.agent.knowledge.prefer_article(lookup[key], lookup).id for key in ids
        )
        parents = {reference for source_id in selected for reference in lookup[source_id].exceptions}
        if len(selected.keys() - parents) > 1:
            return self.handoff("knowledge_unverified", "Сопоставить несколько применимых материалов.", ranked)
        # Exceptions are included even if the model selects only their parent section.
        sources = expand_exceptions((lookup[key] for key in selected), lookup, limit=len(ranked))
        if not sources:
            return self.handoff("knowledge_unverified", "Проверить ограничения найденных правил.", ranked)
        return self.knowledge_answer(sources)

    def knowledge_answer(self, sources):
        update = self.agent.knowledge.learn(sources[0], self.now, multi_source=len(sources) != 1)
        reply = "\n\n".join(f"{source.title}\n{source.text}" for source in sources)
        return TurnResult("answer", reply, self.state, sources, knowledge_update=update)

    def literal_product(self):
        # Recover a single unambiguous literal mention when extraction omits a line.
        # Overlapping aliases for the same mention prefer the longest literal span.
        aliases = {name for product in self.catalog.values()
                   for name in (product.sku, product.name, *product.aliases)}
        spans = set()
        for name in aliases:
            spans.update(match.span() for match in re.finditer(
                rf"(?<![\w-]){re.escape(name)}(?![\w-])", self.text, re.IGNORECASE
            ))
        spans = [span for span in spans if not any(
            other != span and other[0] <= span[0] and span[1] <= other[1] for other in spans
        )]
        if len(spans) == 1:
            start, end = spans[0]
            return self.text[start:end]
        return None

    def update_cart(self, extraction):
        updates = extraction.lines
        if not updates and extraction.kind in ("quote", "invoice"):
            product = extraction.product or self.literal_product()
            if product:
                updates = (LineChange("upsert", product, None),)
        pending = self.state.pending
        cart = {line.sku: line.quantity for line in self.state.cart}
        if extraction.choice is not None:
            if not pending or extraction.choice > len(pending.skus):
                return self.clarification("Укажите артикул или номер из предложенного списка.")
            sku = pending.skus[extraction.choice - 1]
            if sku not in self.catalog:
                self.state = replace(self.state, pending=None)
                return self.clarification("Выбранная позиция больше недоступна. Укажите другой артикул.")
            if not updates:
                cart[sku] = pending.quantity
            pending = None
        else:
            sku = None
        for change in updates:
            candidate = sku
            quantity = change.quantity
            if change.reference:
                exact, fuzzy = self.product_match(change.reference)
                if len(exact) != 1:
                    if len(updates) > 1:
                        return self.clarification("Укажите точные артикулы и количество для каждой позиции.")
                    return self.ask_product(exact or fuzzy, quantity, remember=True)
                candidate = exact[0]
                if pending and candidate in pending.skus:
                    quantity = quantity if quantity is not None else pending.quantity
                    pending = None
            elif candidate is None:
                if pending:
                    return self.ask_product(pending.skus, quantity if quantity is not None else pending.quantity,
                                            remember=True)
                if len(cart) != 1:
                    return self.clarification("Уточните, к какому товару относится изменение.")
                candidate, = cart
            if change.op == "remove":
                cart.pop(candidate, None)
            elif change.op == "add":
                if not quantity or not cart.get(candidate):
                    return self.clarification("Укажите итоговое количество по этой позиции.")
                cart[candidate] += quantity
            elif quantity is not None or candidate not in cart:
                cart[candidate] = quantity if quantity is not None else self.state.pending.quantity if sku else None
        self.state = replace(self.state, cart=tuple(CartLine(*item) for item in cart.items()), pending=pending)
        return None

    def document_turn(self, extraction):
        if extraction.kind in ("quote", "invoice"):
            self.state = replace(self.state, intent=extraction.kind)
        confirmed = bool(CONFIRMATION.search(self.text) and not DECLINE.search(self.text))
        requested = self.special_request(extraction.special_terms, self.text)
        if requested:
            self.state = replace(self.state, requested_terms=requested)
        elif extraction.accept_standard and confirmed:
            self.state = replace(self.state, requested_terms=None)
        issue = self.update_cart(extraction)
        if issue:
            return issue
        if not self.state.intent:
            return self.clarification("Что подготовить по выбранным позициям — КП или счёт?")
        if self.state.pending:
            return self.ask_product(self.state.pending.skus, self.state.pending.quantity, remember=True)
        if not self.state.cart:
            return self.clarification("Укажите продукт и количество лицензий.")
        if any(line.quantity is None for line in self.state.cart):
            missing = ", ".join(line.sku for line in self.state.cart if line.quantity is None)
            return self.clarification(f"Сколько лицензий нужно по позициям {missing}?")
        if any(not 1 <= line.quantity <= 100_000 for line in self.state.cart):
            return self.clarification("Укажите количество от 1 до 100 000 для каждой позиции.")
        if any(line.sku not in self.catalog for line in self.state.cart):
            return self.handoff("catalog_unavailable", "Перепроверить доступность позиций в каталоге.")
        sources = tuple(self.catalog[line.sku].source for line in self.state.cart)
        conditions = self.approved_conditions()
        if conditions is None:
            return self.handoff("special_terms_unconfirmed", "Подтвердить запрошенные особые условия.", sources)
        kind = self.state.intent
        if kind == "invoice":
            seller = self.agent.seller
            if seller is None or not all(value.strip() for value in asdict(seller).values()):
                return self.handoff("seller_details_missing", "Проверить реквизиты поставщика для счёта.", sources)
            if not self.customer or not self.customer.company.strip() or not self.customer.tax_id.strip():
                return self.handoff("billing_details_missing", "Проверить реквизиты покупателя для счёта.", sources)
        try:
            document = self.document(kind, conditions)
        except (ValueError, InvalidOperation):
            return self.handoff("catalog_price_invalid", "Проверить цены и валюту позиций.", sources)
        previous_quote = self.state.last_quote
        if kind == "invoice" and previous_quote and self.terms_of(document) != self.terms_of(previous_quote):
            quote = self.document("quote", conditions)
            self.state = replace(self.state, last_quote=quote, awaiting_price_confirmation=True)
            return TurnResult("quote_ready", "Условия изменились. Подтвердите обновлённое КП, чтобы получить счёт.",
                              self.state, (*sources, *conditions), document=quote)
        if kind == "invoice" and self.state.awaiting_price_confirmation:
            if not (extraction.confirm_price and confirmed):
                return self.clarification("Подтвердите условия обновлённого КП для выставления счёта.")
        if kind == "quote":
            self.state = replace(self.state, last_quote=document)
        self.state = replace(self.state, intent="quote" if kind == "quote" else None,
                             awaiting_price_confirmation=False)
        label = "Готово коммерческое предложение" if kind == "quote" else "Готов счёт"
        return TurnResult(f"{kind}_ready", f"{label} на {document.total} {document.currency}.", self.state,
                          (*sources, *conditions), document=document)

    def approved_conditions(self):
        requested = self.state.requested_terms
        if requested is None:
            return ()
        rules = self.match_conditions(requested, tuple(line.sku for line in self.state.cart))
        return rules if len(rules) == 1 else None

    @staticmethod
    def special_request(extracted, text):
        mentioned = {match.group().casefold() for match in SPECIAL_CONDITION.finditer(text)}
        if mentioned and (not extracted or any(word not in extracted.casefold() for word in mentioned)):
            return text
        return extracted

    def match_conditions(self, requested, skus):
        key = normalize(requested)
        return tuple(rule for rule in self.agent.conditions if (
            rule.active(self.now, self.customer_id)
            and key in {normalize(alias) for alias in rule.aliases}
            and (rule.sku is None or skus and all(sku == rule.sku for sku in skus))
        ))

    def document(self, kind, conditions) -> Document:
        return build_document(
            effect_id(kind, self.conversation_id, self.message_id),
            kind, self.customer, self.state.cart, self.catalog, conditions, self.agent.seller,
        )

    @staticmethod
    def terms_of(document):
        return (
            document.currency,
            sorted((line.sku, line.quantity, line.unit_price) for line in document.lines),
            tuple((rule.id, rule.version, rule.text) for rule in document.conditions),
        )
