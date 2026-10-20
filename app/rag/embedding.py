"""임베딩 — 글을 벡터로 바꾼다. 모델: BGE-m3 (app/config.py 의 EMBEDDING_MODEL).

BGE-m3 는 한 번 계산으로 두 가지 벡터를 준다:
    dense  숫자 1024개 — 글 전체의 "뜻". 뜻이 비슷하면 가깝다 (말투가 달라도 잡힘)
    sparse {토큰 번호: 중요도} — 글에 나온 낱말(토큰)별 중요도. 키워드 일치용
           모델이 토큰마다 "이 낱말이 얼마나 중요한가"를 직접 매긴다.
           예) "급여관리자 지정 제외 대상은" → 급여 0.24, 관리 0.23, 지정 0.21, 제외 0.27, 은 0.0
           조사·어미는 0에 가깝게 나오므로 따로 걸러낼 필요가 없다.

sparse 계산법 (BGE-m3 논문/공식 구현과 같음):
    토큰별 중요도 = relu(토큰 출력 벡터 · w + b)   — w, b 는 모델 저장소의 sparse_linear.pt (몇 KB)
    같은 토큰이 여러 번 나오면 가장 큰 값, 특수 토큰(<s>, </s> 등)은 뺀다.
    두 글의 sparse 점수 = 겹치는 토큰들의 (중요도 × 중요도) 합

모델은 처음 쓸 때 한 번만 읽어 들이고 재사용한다 (읽는 데 수십 초 걸림).
처음 실행하면 HuggingFace 에서 모델 파일(약 2.3GB)을 내려받아 캐시에 둔다.
"""

from functools import lru_cache

from app.config import EMBEDDING_MODEL

BATCH_SIZE = 16  # 한 번에 모델에 넣는 글 수


@lru_cache(maxsize=1)  # 처음 부를 때만 실행, 그 뒤로는 같은 모델 객체를 돌려줌
def get_model():
    """BGE-m3 모델. 무거운 라이브러리라 실제로 쓸 때 import 한다 (서버·테스트 시작이 느려지지 않게)."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL, device="cpu")


@lru_cache(maxsize=1)
def get_sparse_head():
    """sparse 중요도를 계산하는 선형층 (w, b). 모델 저장소의 sparse_linear.pt."""
    import torch
    from huggingface_hub import hf_hub_download

    state = torch.load(hf_hub_download(EMBEDDING_MODEL, "sparse_linear.pt"), map_location="cpu")
    return state["weight"].float(), state["bias"].float()


def embed_with_sparse(texts: list[str]) -> tuple[list[list[float]], list[dict[int, float]]]:
    """글 목록 → (dense 벡터 목록, sparse 목록). 모델을 한 번만 돌려 둘 다 만든다."""
    import torch

    from tqdm import tqdm

    model = get_model()
    weight, bias = get_sparse_head()
    special_ids = set(model.tokenizer.all_special_ids)

    # model.encode(output_value=None) 는 여러 글을 한 번에 넣으면 오류가 나서 (sentence-transformers 6.1)
    # 배치를 직접 만들어 모델을 부른다. 출력: sentence_embedding(정규화된 dense), token_embeddings(토큰별)
    # 길이가 비슷한 글끼리 묶는다 — 배치 안의 글은 가장 긴 글 길이에 맞춰 계산되므로
    # 섞여 있으면 짧은 글도 긴 글만큼 시간이 든다. 결과는 마지막에 원래 순서로 되돌린다.
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    dense, sparse = [], []
    batches = range(0, len(texts), BATCH_SIZE)
    for start in tqdm(batches, disable=len(texts) <= BATCH_SIZE, desc="임베딩"):
        features = model.tokenize([texts[i] for i in order[start : start + BATCH_SIZE]])
        with torch.no_grad():
            out = model(features)
        token_weights = torch.relu(out["token_embeddings"].float() @ weight.T + bias).squeeze(-1)  # [글, 토큰]
        for i in range(len(features["input_ids"])):
            dense.append(out["sentence_embedding"][i].float().tolist())
            weights: dict[int, float] = {}
            ids = features["input_ids"][i].tolist()
            mask = features["attention_mask"][i].tolist()  # 0 = 길이를 맞추려고 채운 자리
            for token_id, m, w in zip(ids, mask, token_weights[i].tolist()):
                if not m or token_id in special_ids or w <= 0:
                    continue
                weights[token_id] = max(w, weights.get(token_id, 0.0))  # 같은 토큰은 가장 큰 값
            sparse.append(weights)

    # 정렬된 순서 → 원래 순서
    restored_dense, restored_sparse = [None] * len(texts), [None] * len(texts)
    for position, original in enumerate(order):
        restored_dense[original] = dense[position]
        restored_sparse[original] = sparse[position]
    return restored_dense, restored_sparse
