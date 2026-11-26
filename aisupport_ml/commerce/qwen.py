"""Optional local Qwen retrieval. Model loading is explicit."""

from threading import Lock

from .retrieval import HybridSearch

EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
RERANKER_MODEL = "Qwen/Qwen3-Reranker-0.6B"


def qwen_search(*, rerank: bool = False, device: str = "cpu") -> HybridSearch:
    from sentence_transformers import CrossEncoder, SentenceTransformer

    embedding = SentenceTransformer(EMBEDDING_MODEL, device=device)
    embedding.max_seq_length = 512
    lock = Lock()

    def encode(items, *, is_query):
        prompt = {"prompt_name": "query"} if is_query else {}
        with lock:
            return embedding.encode(
                items, normalize_embeddings=True, show_progress_bar=False, **prompt,
            ).tolist()

    if not rerank:
        return HybridSearch(encode)

    ranking = CrossEncoder(RERANKER_MODEL, device=device, max_length=768)

    def score(pairs):
        with lock:
            return ranking.predict(pairs, show_progress_bar=False).tolist()

    return HybridSearch(encode, score)
