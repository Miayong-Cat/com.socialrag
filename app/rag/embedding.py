"""임베딩 — 글을 벡터(숫자 1024개)로 바꾼다. 모델: BGE-m3 (app/config.py 의 EMBEDDING_MODEL).

모델은 처음 쓸 때 한 번만 읽어 들이고 재사용한다 (읽는 데 수십 초 걸림).
처음 실행하면 HuggingFace 에서 모델 파일(약 2.3GB)을 내려받아 캐시에 둔다.

벡터를 정규화(길이 1)해 두므로 "코사인 거리"로 비교하면 된다 (app/rag/retriever.py).
"""

from functools import lru_cache

from app.config import EMBEDDING_MODEL


@lru_cache(maxsize=1)  # 처음 부를 때만 실행, 그 뒤로는 같은 모델 객체를 돌려줌
def get_model():
    """BGE-m3 모델. 무거운 라이브러리라 실제로 쓸 때 import 한다 (서버·테스트 시작이 느려지지 않게)."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL, device="cpu")


def embed(texts: list[str]) -> list[list[float]]:
    """글 목록 → 벡터 목록 (순서 같음)."""
    vectors = get_model().encode(
        texts,
        normalize_embeddings=True,   # 길이 1로 맞춤 → 코사인 거리 비교
        batch_size=16,
        show_progress_bar=len(texts) > 16,
    )
    return vectors.tolist()
