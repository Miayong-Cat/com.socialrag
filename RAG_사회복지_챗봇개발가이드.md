# 자바 개발자를 위한 파이썬 RAG 챗봇 프로젝트 완전 가이드 (v2)

> **프로젝트명(가칭)**: 복지제도 판정 AI 챗봇 (WELFARE AI)
> **대상 독자**: 자바 CRUD 경험은 있으나 파이썬/AI 스택은 처음인 개발자
> **목표**: 순수 개인 포트폴리오. 특정 채용공고나 마감일에 종속되지 않음
> **v2 변경 요약**: "검색해서 보여주기"에서 "실제로 자격을 판정하기"로 핵심을 바꿈. LangGraph를 형식이 아니라 필수 요소(조건 분기·판정·재확인 루프)로 편입. Spring Boot는 선택 확장으로 뒤로 미룸.

---

## 목차

1. [이 문서를 읽는 법](#1-이-문서를-읽는-법)
2. [프로젝트 개요 — 검색에서 판정으로](#2-프로젝트-개요--검색에서-판정으로)
3. [자바 → 파이썬 개념 매핑](#3-자바--파이썬-개념-매핑)
4. [파이썬 문법 최소 지식](#4-파이썬-문법-최소-지식)
5. [RAG + 판정 로직 — 검색만으론 안 되는 이유](#5-rag--판정-로직--검색만으론-안-되는-이유)
6. [LangGraph — 왜 필수인가](#6-langgraph--왜-필수인가)
7. [기술 스택 선정과 이유](#7-기술-스택-선정과-이유)
8. [아키텍처 설계](#8-아키텍처-설계)
9. [데이터 수집 전략과 첫 스파이크](#9-데이터-수집-전략과-첫-스파이크)
10. [개발 로드맵 (단계별, 데드라인 없음)](#10-개발-로드맵-단계별-데드라인-없음)
11. [학습 리소스](#11-학습-리소스)
12. [윈도우 환경 트러블슈팅](#12-윈도우-환경-트러블슈팅)
13. [포트폴리오 어필 포인트](#13-포트폴리오-어필-포인트)
14. [부록 A: Spring Boot 확장 (선택, 나중에)](#14-부록-a-spring-boot-확장-선택-나중에)
15. [부록 B: 첫 스파이크 체크리스트](#15-부록-b-첫-스파이크-체크리스트)

---

## 1. 이 문서를 읽는 법

이 문서는 **순서대로 읽되, 3~6장은 개념 이해용이고 8장부터가 실제 작업**입니다.

가장 중요한 원칙 하나: **환경 세팅 → 문서 작성 → 설계 → 개발 순서로 가지 않습니다.** 이 프로젝트에서 가장 불확실한 지점(복지 지침서의 표를 구조화된 데이터로 뽑아낼 수 있는가)을 가장 먼저 작게 찔러보고, 그 결과에 따라 나머지 계획을 조정합니다. 이걸 **스파이크(spike)**라고 부릅니다. 9장과 부록 B가 이 스파이크를 다룹니다.

**추천 읽기 순서**
- 1회차: 1~2장 → 9장 스파이크 먼저 실행 (표 파싱이 되는지부터 확인)
- 2회차: 3~4장 (파이썬 문법), 스파이크 결과를 보며 7~8장
- 3회차: 5~6장 (RAG+판정, LangGraph) → 10장 로드맵대로 개발 시작

마감일이 없다는 것이 "천천히 해도 된다"는 뜻은 아닙니다. 오히려 데드라인이 없을 때 스코프가 끝없이 늘어나다 아무것도 완성 못 하는 게 가장 흔한 실패 패턴입니다. **판정 기능이 되는 최소 버전을 먼저 끝까지 완성**하는 것을 최우선 원칙으로 삼으세요.

---

## 2. 프로젝트 개요 — 검색에서 판정으로

### 2.1 무엇을 만드는가

사용자가 자연어로 자기 상황을 설명하면, **받을 수 있는 복지제도를 찾아주고, 실제로 자격이 되는지 계산해서 판정하고, 신청 방법까지 안내**하는 챗봇입니다.

```
사용자: "70세인데 혼자 살고 있고 월 소득이 80만원 정도예요.
         받을 수 있는 지원이 뭐가 있을까요?"

챗봇:   [조건 파악] 연령 70세 / 1인 가구 / 월소득 80만원
        [제도 매칭] 기초연금, 기초생활보장(생계급여) 대상 가능성
        [판정]     소득인정액 산정 → 1인 가구 생계급여 선정기준(중위소득 32%) 대비 계산
                   → "생계급여: 충족 / 기초연금: 충족 (소득 산정 방식 상이, 확인 필요 사유 명시)"
        [근거]     ... 2026년 기초연금 사업안내 p.23, 기준 중위소득 고시
        [다음]     "주거 형태가 자가인가요, 임차인가요? (재산 산정에 필요)"
```

**v1과의 결정적 차이**: v1은 검색 유사도를 "추천도 94%"처럼 보여주는 데 그쳤습니다. 이건 판정이 아니라 정보 검색입니다. v2는 소득인정액 등을 실제로 계산해 **충족 / 미충족 / 확인 필요**로 답합니다. "확인 필요"는 계산에 필요한 정보(재산, 부양의무자 등)가 아직 부족할 때만 쓰고, 최대한 실제 계산으로 좁힙니다.

### 2.2 왜 이 방향인가

| 관점 | 이유 |
|---|---|
| **도메인 강점** | 복지 지식이 있는 개발자는 드묾. 기술만 있는 지원자와 차별화 |
| **판정 로직의 기술적 깊이** | 단순 RAG는 이제 흔한 포트폴리오 소재. 소득인정액 계산 + 규칙 기반 판정 + LLM 설명 결합이 차별점 |
| **데이터 확보** | 복지로, 보건복지부 지침서 등 공개 자료가 풍부 |
| **문제 정의 명확** | "복지제도가 너무 복잡해서 대상자가 몰라서 못 받는다"는 실제 사회 문제 |
| **기술 난이도 적절** | 조건 기반 필터링 + 정형 판정 로직 + 멀티턴 대화로 RAG의 고급 기법을 자연스럽게 씀 |

### 2.3 핵심 기능 (MVP 기준)

1. **멀티턴 조건 수집** — 연령·가구원수·소득·재산·거주형태 등을 대화로 파악
2. **제도 검색 및 매칭** — 수집한 조건에 맞는 제도를 벡터DB에서 검색
3. **자격 판정** — 정형화된 기준(`welfare_services` 테이블)과 계산 로직으로 충족/미충족을 실제로 계산. RAG 검색 결과가 아니라 이 판정 결과가 최종 답의 핵심
4. **근거 인용 답변** — 어떤 문서 몇 페이지에서 나온 내용인지, 어떤 계산식을 썼는지 표시 (환각 방지)
5. **위기 신호 감지** — 자살·학대·긴급 상황 키워드 감지 시 별도 안내 흐름으로 분기
6. **신청 절차 안내** — 필요 서류, 신청 기관, 문의처
7. **검색/판정 로그 적재** — 질문, 검색 문서 수, 응답 시간, 판정 결과를 쌓아 나중에 정량적으로 성능을 설명할 수 있게 함 (7장·8장 참고)

> **범위 제한이 중요합니다.** 처음부터 모든 복지제도를 다루려 하면 절대 못 끝냅니다.
> **1차 목표는 판정 로직까지 확실히 되는 2~3개 제도(예: 기초생활보장 + 긴급복지지원 + 기초연금)만 깊게** 하세요. 제도 개수를 늘리는 것보다 "판정이 진짜로 맞는가"를 검증하는 게 훨씬 중요합니다.

### 2.4 사용자 포지셔닝

이 챗봇은 **당사자(복지가 필요한 사람)와 실무자(사회복지사·상담원) 양쪽에 다 쓸모 있게** 설계합니다. 당사자에게는 "내가 받을 수 있는지"를, 실무자에게는 "이 사람이 어떤 근거로 대상자가 되는지"를 빠르게 계산해 보여주는 도구입니다. 둘은 배타적이지 않습니다 — 판정 로직 하나면 양쪽 다 채워집니다.

단, 법적 책임 문제 때문에 **"AI는 참고용 1차 판정이며, 최종 확정은 관할 기관 담당자가 한다"**는 문구를 UI와 답변에 명시적으로 넣습니다.

---

## 3. 자바 → 파이썬 개념 매핑

당신이 이미 아는 개념이 파이썬에서 뭐라고 불리는지만 알면 됩니다.

### 3.1 프레임워크 / 도구

| 자바 | 파이썬 | 비고 |
|---|---|---|
| Spring Boot | **FastAPI** | 훨씬 가볍고 코드량 적음 |
| `@RestController` | `APIRouter` | |
| `@GetMapping("/x")` | `@router.get("/x")` | 데코레이터 = 어노테이션 |
| DTO + `@Valid` | **Pydantic** `BaseModel` | 타입 선언만으로 검증 자동 |
| Service 클래스 | 그냥 클래스 또는 함수 모듈 | 강제 계층 없음 |
| Repository | SQLAlchemy 또는 그냥 함수 | |
| JPA / Hibernate | **SQLAlchemy** | ORM |
| Maven / Gradle | **pip** + `requirements.txt` | 최근엔 `uv`, `poetry`도 씀 |
| `pom.xml` | `requirements.txt` | |
| `application.yml` | `.env` + `pydantic-settings` | |
| Swagger 설정 | **자동 생성** (`/docs`) | 설정 불필요 |
| Tomcat | **Uvicorn** | ASGI 서버 |
| JUnit | **pytest** | |
| Lombok `@Getter` | 불필요 (기본 public) | |
| `interface` | `ABC` (추상 클래스) 또는 `Protocol` | 잘 안 씀 |
| `null` | `None` | |
| `List<String>` | `list[str]` | |
| `Map<String, Object>` | `dict[str, Any]` | |
| `Optional<T>` | `T \| None` | |

> Spring Boot를 아예 안 쓰는 게 아니라 **뒤로 미루는 것**입니다. 14장(부록 A)에서 나중에 어떻게, 왜 붙일지 다룹니다.

### 3.2 같은 CRUD를 두 언어로

**자바 (Spring Boot)**

```java
@RestController
@RequestMapping("/api/welfare")
public class WelfareController {

    private final WelfareService service;

    public WelfareController(WelfareService service) {
        this.service = service;
    }

    @GetMapping("/{id}")
    public WelfareResponse getWelfare(@PathVariable Long id) {
        return service.findById(id);
    }

    @PostMapping
    public WelfareResponse create(@RequestBody @Valid WelfareRequest request) {
        return service.create(request);
    }
}
```

**파이썬 (FastAPI)**

```python
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/api/welfare")


@router.get("/{welfare_id}", response_model=WelfareResponse)
def get_welfare(welfare_id: int, service: WelfareService = Depends(get_service)):
    return service.find_by_id(welfare_id)


@router.post("", response_model=WelfareResponse)
def create(request: WelfareRequest, service: WelfareService = Depends(get_service)):
    return service.create(request)
```

**차이점 요약**
- 세미콜론 없음, 중괄호 대신 **들여쓰기(4칸)**
- 타입은 `변수: 타입` 형태로 뒤에 붙음
- `Depends()`가 스프링의 DI 역할
- Pydantic 모델을 `response_model`에 지정하면 응답 검증 + Swagger 문서화 자동

### 3.3 DTO 비교

**자바**

```java
public class WelfareRequest {
    @NotBlank
    private String name;

    @Min(0)
    private int minAge;

    // getter, setter, 생성자...
}
```

**파이썬**

```python
from pydantic import BaseModel, Field


class WelfareRequest(BaseModel):
    name: str = Field(min_length=1)
    min_age: int = Field(ge=0)
```

끝입니다. getter/setter/생성자 전부 불필요합니다.

---

## 4. 파이썬 문법 최소 지식

이 프로젝트를 하는 데 필요한 것만 추렸습니다.

### 4.1 타입 힌트

파이썬은 타입을 안 써도 되지만, **반드시 쓰세요.** 자바 하던 사람에겐 오히려 안 쓰는 게 더 불편합니다.

```python
def find_welfare(age: int, income: int) -> list[str]:
    ...

name: str = "기초연금"
scores: dict[str, float] = {"정확도": 0.87}
maybe_value: str | None = None  # Optional<String>
```

### 4.2 자료구조

```python
# 리스트 (= ArrayList)
items = ["기초연금", "생계급여"]
items.append("의료급여")
first = items[0]

# 딕셔너리 (= HashMap)
person = {"age": 70, "income": 800000}
age = person["age"]
age = person.get("age", 0)   # 기본값

# 리스트 컴프리헨션 (= Stream.map/filter)
# 자바: list.stream().filter(x -> x.age > 65).map(x -> x.name).toList()
names = [x.name for x in people if x.age > 65]
```

### 4.3 클래스

```python
class WelfareService:
    def __init__(self, repository: WelfareRepository):  # 생성자
        self.repository = repository                     # this.repository

    def find_by_id(self, welfare_id: int) -> Welfare:    # self = this (필수 첫 인자)
        return self.repository.find(welfare_id)
```

**주의**: 메서드 첫 인자에 `self`를 반드시 써야 합니다. 자바의 `this`가 명시적으로 드러난 형태입니다.

### 4.4 async / await

LangChain과 FastAPI에서 자주 나옵니다.

```python
async def generate_answer(question: str) -> str:
    result = await llm.ainvoke(question)   # await = 결과 나올 때까지 대기
    return result.content
```

**초보 때 원칙**
- 일단 **동기(sync) 코드로 짜고**, 나중에 필요하면 비동기로 전환하세요.
- LangChain은 대부분 `invoke()`(동기)와 `ainvoke()`(비동기) 둘 다 제공합니다. `invoke()`부터 쓰세요.
- 단, `async def` 함수 안에서만 `await`을 쓸 수 있습니다.

### 4.5 f-string

```python
name = "기초연금"
message = f"{name} 제도를 안내합니다. 나이는 {age}세입니다."
```

### 4.6 경로 처리 (윈도우 필수)

```python
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "raw"        # 역슬래시 문제 없음

for pdf in DATA_DIR.glob("*.pdf"):
    print(pdf.name)
```

문자열로 `"data\\raw\\file.pdf"` 이렇게 붙이지 마세요. `pathlib`을 쓰면 OS 차이를 신경 쓸 필요가 없습니다.

---

## 5. RAG + 판정 로직 — 검색만으론 안 되는 이유

### 5.1 한 문장 정의

> **RAG(Retrieval-Augmented Generation)** = "LLM이 답하기 전에, 관련 문서를 먼저 찾아서 같이 던져주는 기법"

### 5.2 RAG가 못 하는 것 — 왜 판정 로직이 따로 필요한가

RAG는 "관련 문서를 찾아서 그럴듯하게 답하는" 기술입니다. 그런데 "이 사람이 생계급여 대상인가?"는 그럴듯한 문장이 아니라 **정확한 계산**이 필요한 질문입니다.

```
소득인정액 = 소득평가액 + 재산의 소득환산액
생계급여 선정기준 = 기준 중위소득 × 32% (2026년 기준, 가구원수별로 다름)

판정 = 소득인정액 ≤ 선정기준  →  True/False
```

이건 LLM에게 "계산해줘"라고 맡길 문제가 아닙니다. LLM은 산수를 틀리기도 하고, 매번 다른 답을 낼 수도 있습니다. **판정은 결정론적 코드로 계산하고, LLM은 그 결과를 사람이 이해할 말로 설명하는 역할만 맡깁니다.**

```
질문 → [조건 수집] → [판정 엔진: 코드로 계산] → [RAG: 근거 문서 검색] → [LLM: 계산 결과 + 근거를 설명으로 조립] → 답변
```

이 구조가 v1(순수 RAG)과 v2의 가장 큰 차이입니다. RAG는 "왜 그런지 근거를 붙이는 역할"로 격하되고, 판정의 정확성은 별도 계산 엔진이 책임집니다.

### 5.3 RAG 파이프라인 6단계 (근거 검색 부분)

```
[사전 준비: Indexing]
1. Load     PDF/HWP 문서 읽기
2. Split    문서를 적당한 크기로 쪼개기 (청킹)
3. Embed    각 조각을 벡터(숫자 배열)로 변환
4. Store    벡터DB에 저장

[실행 시: Retrieval & Generation]
5. Retrieve 질문을 벡터로 바꿔서 유사한 조각 검색
6. Generate 찾은 조각 + 판정 결과를 LLM에 전달해 설명 생성
```

### 5.4 각 단계에서 중요한 것

**2단계 청킹(Chunking)이 RAG 품질의 절반을 결정합니다.**

| 방식 | 설명 | 복지 문서 적합도 |
|---|---|---|
| 고정 크기 | 1000자씩 자르기 | 낮음 (문맥 끊김) |
| RecursiveCharacterTextSplitter | 문단→문장 순으로 자름 | 중간 (기본값으로 무난) |
| 구조 기반 | "제1조", "가. 나. 다." 등 조항 단위로 자름 | **높음** (지침서는 조항 구조가 명확) |

복지 지침서는 조항·항목 구조가 뚜렷해서 **구조 기반 청킹**이 잘 먹힙니다.

**표(기준 중위소득표, 재산기준표 등)는 벡터DB에 넣지 않습니다.** 표는 청킹하면 숫자와 항목이 깨져서 검색이 무의미해집니다. 대신 `welfare_services` 같은 정형 테이블로 뽑아서 **SQL로 정확 조회**합니다. 이게 8장·9장의 핵심 주제입니다.

**5단계 검색 품질 개선 기법 (근거 문서 검색에 한정)**

| 기법 | 설명 | 우선순위 |
|---|---|---|
| 하이브리드 검색 | 벡터 검색 + 키워드(BM25) 검색 결합 | 높음 — 한국어 제도명은 정확 일치가 중요 |
| 메타데이터 필터링 | 연도·제도유형으로 먼저 걸러내고 검색 | 높음 |
| 리랭킹(Rerank) | 검색된 20개를 재정렬해 상위 5개만 사용 | 중간 |
| 쿼리 재작성 | 사용자 질문을 검색에 유리하게 다시 씀 | 중간 |

---

## 6. LangGraph — 왜 필수인가

### 6.1 단순 체인으로는 안 되는 이유

v1 설계는 "질문 → 검색 → Rerank → LLM → 답변"의 단방향 파이프라인이었습니다. 이건 LangChain 체인(Chain)만으로 충분히 구현되고, **되돌아오는 화살표도 조건 분기도 없습니다.** 문제는 이 프로젝트의 핵심 기능들이 전부 분기와 반복을 필요로 한다는 겁니다.

- 위기 신호가 감지되면 검색 흐름 자체를 건너뛰고 별도 대응으로 가야 함 (분기)
- 판정에 필요한 조건(재산, 부양의무자 등)이 부족하면 되물어야 함 (반복 루프)
- 판정이 "확인 필요"로 나오면 부족한 정보를 다시 물어서 재판정해야 함 (조건부 재진입)

이건 체인이 아니라 **상태 머신**입니다. LangGraph가 정확히 이 문제를 위한 도구입니다. "LangGraph를 왜 쓰셨나요?"라는 질문에 "조건 수집과 판정 재확인에 되묻기 루프가 필요해서, 단방향 체인으로는 표현이 안 됐습니다"라고 구체적으로 답할 수 있어야 합니다.

### 6.2 LangGraph 핵심 개념 3가지

**① State (상태)** — 대화 전체에서 공유되는 데이터 보관함

```python
from typing import TypedDict


class ChatState(TypedDict):
    messages: list                 # 대화 기록
    user_age: int | None           # 수집된 조건
    household_size: int | None
    monthly_income: int | None
    assets: int | None             # 재산 (판정에 필요)
    housing_type: str | None       # 자가/임차 등
    retrieved_docs: list           # 검색된 근거 문서
    eligibility_result: dict       # {"생계급여": "충족", "기초연금": "확인 필요"}
    missing_fields: list           # 판정에 아직 부족한 조건
    is_crisis: bool                # 위기 신호 여부
    answer: str
```

자바로 치면 세션에 담아두는 DTO 같은 겁니다. v1과 달리 `eligibility_result`, `missing_fields`가 추가된 게 핵심입니다.

**② Node (노드)** — 상태를 받아 수정해서 돌려주는 함수

```python
def eligibility_check_node(state: ChatState) -> ChatState:
    required = ["user_age", "household_size", "monthly_income", "assets"]
    missing = [f for f in required if state.get(f) is None]
    if missing:
        return {"missing_fields": missing}

    result = calculate_eligibility(
        age=state["user_age"],
        household_size=state["household_size"],
        income=state["monthly_income"],
        assets=state["assets"],
    )
    return {"eligibility_result": result, "missing_fields": []}
```

`calculate_eligibility`는 LLM 호출이 아니라 **결정론적 계산 함수**입니다. 5.2절에서 다룬 소득인정액 계산이 여기 들어갑니다.

**③ Edge (엣지)** — 노드 간 연결. 조건부 분기가 핵심

```python
def route_after_eligibility(state: ChatState) -> str:
    if state["missing_fields"]:
        return "ask_condition"       # 부족한 조건 되묻기
    return "retrieve"                # 판정 끝났으면 근거 문서 검색으로
```

### 6.3 이 프로젝트의 그래프 설계

```
            [START]
               │
               ▼
      ┌─── crisis_check ───┐              위기 키워드 감지
      │                    │
   (위기)                (정상)
      │                    ▼
      ▼             condition_check       필요한 조건이 다 모였나?
 crisis_handler            │
      │            ┌───────┴───────┐
      │         (부족)           (충분)
      │            │               │
      │            ▼               ▼
      │      ask_condition   eligibility_check   소득인정액 등 실제 판정 계산
      │            │               │
      │            │        ┌──────┴──────┐
      │            │     (부족)          (완료)
      │            │        │               │
      │            └────────┘               ▼
      │            (되묻기 루프)          retrieve         근거 문서 검색
      │                                     │
      │                                     ▼
      │                                  rerank            상위 문서 재정렬
      │                                     │
      │                                     ▼
      │                                  generate          판정결과 + 근거로 답변 생성
      │                                     │
      └─────────────────────────────────────┘
                        ▼
                      [END]
```

v1 대비 달라진 점: `eligibility_check` 노드가 추가되고, 조건이 부족하면 `ask_condition`으로 되돌아가는 루프가 생겼습니다. 이 되묻기 루프가 v1에는 없던, LangGraph를 실제로 필요로 하게 만드는 부분입니다.

---

## 7. 기술 스택 선정과 이유

### 7.1 최종 스택 (Python 단일 스택)

| 영역 | 선택 | 이유 | 대안 |
|---|---|---|---|
| 언어 | Python 3.11+ | AI 생태계 표준 (3.13 아님, 라이브러리 호환성 문제 있음) | — |
| 웹 프레임워크 | **FastAPI** | Spring Boot와 구조 유사, Swagger 자동 | Flask, Django |
| AI 오케스트레이션 | **LangChain + LangGraph** | 6장 참고 — 되묻기/판정 루프에 필수 | LlamaIndex |
| LLM | **OpenAI GPT-4o-mini** 또는 **Claude** | 한국어 성능, 비용 | Solar, HyperCLOVA X |
| 임베딩 | **BGE-m3** (로컬, 무료) | 한국어 무료·강력, API 비용 없음 | OpenAI text-embedding-3 |
| 벡터DB | **Chroma**(초기) → **pgvector**(확장) | 조건 필터링 + 벡터검색 동시 필요 | Qdrant, Weaviate |
| 정형 데이터 | **PostgreSQL** (`welfare_services`, `ai_search_logs`) | 판정 로직은 SQL 정확 조회, pgvector와 통합 | SQLite(초기) |
| 프론트엔드 | **Streamlit**(초기) → React(선택) | 빠른 검증 후 필요시 교체 | Gradio |
| 평가 | **RAGAS** | 정량 지표 제시용 | 자체 테스트셋 |
| 배포 | Docker + 클라우드 | 완성도 어필 | Railway, Render |
| 형상관리 | Git / GitHub | — | — |

**Spring Boot/Java는 이 표에 없습니다.** 14장(부록 A)에서 핵심 기능 완성 후 선택적으로 붙이는 방법을 다룹니다.

### 7.2 주요 선택의 근거 (면접·포트폴리오 설명용)

**왜 판정을 LLM이 아니라 코드로 계산하는가?**
> 소득인정액 계산은 법령에 정해진 결정론적 산식입니다. LLM에 맡기면 같은 입력에도 다른 답이 나올 수 있고, 계산 실수를 검증할 방법이 없습니다. 판정은 순수 함수로 계산하고, LLM은 그 결과를 자연어로 설명하는 역할만 맡깁니다. 이게 "환각 방지"의 가장 확실한 형태입니다.

**왜 pgvector인가?**
> 이 프로젝트는 "70세, 1인가구, 소득 80만원" 같은 **정형 조건 필터링**과 **의미 기반 검색**을 동시에 해야 합니다. pgvector는 PostgreSQL이라 `WHERE age_min <= 70 AND household = 1` 같은 SQL 조건과 벡터 유사도 검색을 한 쿼리로 처리할 수 있습니다.

**왜 BGE-m3인가?**
> 한국어 임베딩 성능이 우수하고, 로컬에서 무료로 돌릴 수 있어 API 비용이 안 듭니다. 또 dense/sparse 벡터를 동시에 생성해 하이브리드 검색 구현이 쉽습니다.

**왜 Streamlit부터인가?**
> 핵심 가치는 판정 정확도와 RAG 품질이지 UI가 아닙니다. Streamlit으로 데모를 빠르게 만들어 검증하고, 여유가 있으면 React로 교체하는 게 합리적입니다.

**ai_search_logs는 왜 필요한가?**
> "성능 병목이 어디였나요?" 같은 질문에 감으로 답하지 않고 데이터로 답하기 위해서입니다. 질문·검색 문서 수·응답 시간·판정 결과를 쌓아두면 어느 단계가 느린지, 어떤 질문 유형에서 판정이 자주 "확인 필요"로 빠지는지를 나중에 분석할 수 있습니다.

### 7.3 초기 설치 패키지

```bash
# 웹 프레임워크
pip install fastapi uvicorn[standard] python-dotenv pydantic-settings

# LangChain 계열
pip install langchain langchain-community langchain-openai langgraph

# 문서 처리 / 벡터DB
pip install pypdf pdfplumber chromadb

# 한국어 임베딩
pip install sentence-transformers

# DB
pip install sqlalchemy psycopg2-binary

# 프론트
pip install streamlit

# 개발 도구
pip install pytest ruff

pip freeze > requirements.txt
```

> **한 번에 다 깔지 마세요.** 단계별로 필요할 때 추가하는 게 의존성 충돌을 줄입니다. 특히 `pdfplumber`는 9장 스파이크에서만 먼저 설치하면 됩니다.

---

## 8. 아키텍처 설계

### 8.1 헥사고날/클린 아키텍처를 써야 하나?

**결론: 쓰지 마세요.** 대신 **관심사 분리**라는 핵심 원칙만 가져오세요.

| | 헥사고날 풀 적용 | 권장(레이어드 + 부분 추상화) |
|---|---|---|
| 파일 수 | 3~4배 증가 | 적정 |
| 개발 속도 | 느림 | 빠름 |
| 포트폴리오 인상 | "왜 이렇게 복잡하게?" | "구조를 이해하고 있네" |
| 확장성 | 높음 | 필요한 만큼 충분 |

**단, 이것만은 추상화하세요**: LLM 제공자와 벡터DB. 나중에 교체 가능성이 실제로 있고, "확장성을 고려했다"는 스토리를 만들 수 있습니다.

```python
from abc import ABC, abstractmethod


class VectorStorePort(ABC):
    @abstractmethod
    def search(self, query: str, filters: dict, k: int) -> list[Document]:
        ...


class ChromaAdapter(VectorStorePort): ...
class PgVectorAdapter(VectorStorePort): ...
```

자바의 인터페이스 + 구현체와 동일한 패턴입니다.

### 8.2 시스템 아키텍처

```
┌─────────────────┐
│   Streamlit UI  │  사용자 대화 화면
└────────┬────────┘
         │ HTTP (SSE 스트리밍)
         ▼
┌─────────────────────────────────────────┐
│           FastAPI Backend                │
│  ┌────────────────────────────────────┐ │
│  │  API Layer  (라우터, 요청/응답)      │ │
│  ├────────────────────────────────────┤ │
│  │  Graph Layer (LangGraph 워크플로)    │ │
│  │   crisis_check → condition_check →  │ │
│  │   eligibility_check → retrieve →    │ │
│  │   rerank → generate                 │ │
│  ├────────────────────────────────────┤ │
│  │  판정 엔진 (결정론적 계산, LLM 아님)  │ │
│  ├────────────────────────────────────┤ │
│  │  RAG Layer  (검색, 리랭킹, 프롬프트)  │ │
│  ├────────────────────────────────────┤ │
│  │  Port/Adapter (VectorStore, LLM)    │ │
│  └────────────────────────────────────┘ │
└──────┬─────────────┬─────────────────────┘
       │             │
       ▼             ▼
┌─────────────┐  ┌──────────────┐
│  VectorDB   │  │   LLM API    │
│ Chroma/pgv  │  │ OpenAI/Claude│
└─────────────┘  └──────────────┘
       ▲
       │
┌──────┴─────────────────────────────┐
│   PostgreSQL (정형 데이터)           │
│   welfare_services (판정 기준표)     │
│   ai_search_logs   (검색/판정 로그)  │
└──────────────────────────────────────┘
       ▲
       │ (오프라인 배치)
┌──────┴───────────────────────────┐
│      Ingestion Pipeline           │
│  PDF 로드 → 청킹 → 임베딩 → 저장   │
│  표 파싱 → welfare_services 적재   │
└───────────────────────────────────┘
```

**중요**: Ingestion(문서 적재)은 **서버와 분리된 별도 스크립트**입니다. 서버 실행 시마다 임베딩하면 안 됩니다.

### 8.3 폴더 구조

```
welfare-rag-chatbot/
├── .env                      # API 키 (절대 커밋 금지)
├── .env.example               # 키 없는 템플릿 (커밋 O)
├── .gitignore
├── README.md
├── requirements.txt
├── docker-compose.yml
│
├── app/
│   ├── __init__.py
│   ├── main.py                # FastAPI 진입점
│   │
│   ├── core/                  # 설정, 공통
│   │   ├── config.py          # 환경변수 (pydantic-settings)
│   │   ├── logging.py
│   │   └── exceptions.py
│   │
│   ├── api/                   # = Controller 계층
│   │   ├── deps.py            # 의존성 주입
│   │   └── routes/
│   │       ├── chat.py        # POST /api/chat
│   │       └── health.py
│   │
│   ├── schemas/                # = DTO
│   │   ├── chat.py
│   │   └── welfare.py
│   │
│   ├── graph/                  # LangGraph 워크플로
│   │   ├── state.py            # ChatState 정의
│   │   ├── builder.py          # 그래프 조립
│   │   └── nodes/
│   │       ├── crisis_check.py
│   │       ├── condition_check.py
│   │       ├── eligibility_check.py   # 판정 노드 (신규)
│   │       ├── retrieve.py
│   │       ├── rerank.py
│   │       └── generate.py
│   │
│   ├── eligibility/             # 판정 엔진 (신규, LLM 미개입)
│   │   ├── income_calculator.py # 소득인정액 계산
│   │   └── rules.py             # 제도별 선정기준 규칙
│   │
│   ├── rag/                     # 검색 로직
│   │   ├── retriever.py         # 하이브리드 검색
│   │   ├── reranker.py
│   │   └── prompts/
│   │       ├── system.py
│   │       └── answer.py
│   │
│   ├── adapters/                # 외부 시스템 연결
│   │   ├── vectorstore/
│   │   │   ├── base.py          # 추상 인터페이스
│   │   │   ├── chroma.py
│   │   │   └── pgvector.py
│   │   └── llm/
│   │       ├── base.py
│   │       └── openai.py
│   │
│   └── services/                 # = Service 계층
│       ├── chat_service.py
│       └── log_service.py        # ai_search_logs 적재
│
├── ingestion/                    # 문서 적재 (독립 실행)
│   ├── loaders.py                # PDF/HWP 로드
│   ├── splitters.py              # 구조 기반 청킹
│   ├── embedder.py
│   ├── table_extractor.py        # 표 → welfare_services 적재
│   └── run_ingest.py             # python -m ingestion.run_ingest
│
├── spike/                        # 스파이크 스크립트 (9장)
│   └── table_scout.py            # 표 파싱 가능성 정찰
│
├── data/
│   ├── raw/                      # 원본 PDF (gitignore)
│   └── processed/                # 정제 결과
│
├── evaluation/                   # 성능 평가
│   ├── testset.json              # 질문-정답 쌍 50개
│   └── run_eval.py               # RAGAS 실행
│
├── frontend/
│   └── streamlit_app.py
│
└── tests/
    ├── test_retriever.py
    ├── test_eligibility.py       # 판정 로직 단위 테스트 (핵심)
    └── test_nodes.py
```

### 8.4 .gitignore (최우선 작업)

```gitignore
# 환경
venv/
.venv/
.env

# 파이썬
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/

# 벡터DB
.chroma/
chroma_db/
*.sqlite3

# 데이터
data/raw/
data/processed/

# IDE
.idea/
.vscode/
```

> `.env`를 실수로 커밋하면 API 키가 유출됩니다. **첫 커밋 전에 반드시 설정하세요.**

### 8.5 데이터 모델

**welfare_services — 판정 기준 정형 테이블 (신규 핵심)**

표를 벡터DB 청크로 두지 않고, 판정에 바로 쓸 수 있는 필드로 구조화합니다.

```python
class WelfareProgram(BaseModel):
    program_id: str
    name: str                        # "기초연금"
    category: str                    # "노인"
    min_age: int | None              # 65
    max_age: int | None
    max_income_ratio: float | None   # 중위소득 대비 % (선정기준)
    max_asset_amount: int | None     # 재산 기준액
    household_types: list[str]       # ["1인", "2인"]
    source_document: str             # "2026 기초연금 사업안내"
    source_page: int
    updated_year: int                # 2026
```

이 테이블이 있으면 `updated_year == 2026 AND min_age <= 70 AND max_income_ratio >= (소득인정액/중위소득*100)` 같은 SQL로 **직접 판정**할 수 있습니다. RAG 검색은 이 판정에 근거 문서를 붙이는 보조 역할입니다.

**ai_search_logs — 검색/판정 로그 (신규)**

```python
class SearchLog(BaseModel):
    log_id: str
    question: str
    retrieved_doc_count: int
    response_time_ms: int
    eligibility_result: dict | None   # 판정 결과 요약
    missing_fields_count: int         # "확인 필요"로 빠진 조건 개수
    created_at: datetime
```

이 로그를 쌓아두면 "평균 응답 시간이 얼마인가", "어떤 질문 유형에서 판정이 자주 막히는가" 같은 걸 나중에 집계 쿼리로 answer할 수 있습니다. 성능 개선을 "그냥 빨라진 것 같다"가 아니라 수치로 보여주는 근거가 됩니다.

---

## 9. 데이터 수집 전략과 첫 스파이크

### 9.1 왜 표 파싱부터 확인하는가

판정 기능(2.1절, 5.2절)의 전제는 "지침서의 기준표를 구조화된 데이터로 뽑아낼 수 있다"입니다. 이게 안 되면 판정 자체가 성립하지 않고, 이 프로젝트의 가장 큰 차별점이 사라집니다. 반대로 이게 되면 나머지(청킹, LangGraph, UI)는 전부 "하면 되는" 일들입니다.

그래서 **가장 먼저** 표를 뽑을 수 있는지부터 스파이크로 확인합니다. 환경을 다 세팅하고 나서 3주차에 "표가 안 뽑히네?"를 발견하면 이미 늦습니다.

### 9.2 스파이크 실행

`spike/table_scout.py` — PDF 안에 표가 몇 개 있고, 어떤 형태(병합셀 여부, 페이지 걸침 여부, 빈 셀 비율)인지 정찰하는 스크립트입니다.

```bash
pip install pdfplumber
python spike/table_scout.py "국민기초생활보장_사업안내.pdf" --pages 1-50
```

- 마음에 드는 표를 찾으면 `--dump 23` 으로 그 페이지 표를 JSON으로 뽑아 실제 내용을 확인합니다.
- 결과에 따라 다음 갈림길이 갈립니다:

| 스파이크 결과 | 다음 행동 |
|---|---|
| 표가 잘 뽑힘 (병합셀 적음) | 계획대로 `pdfplumber` 기반 파이프라인 진행 |
| 병합셀이 많아 지저분함 | `law.go.kr` HTML 경로로 전환 (오히려 더 쉬울 수 있음) |
| 표를 아예 못 찾음 | 스캔본 PDF일 가능성 — OCR 필요하거나 다른 출처 탐색 |

어느 쪽이든 **이 단계에서 알아야** 나머지 계획을 정확히 세울 수 있습니다.

### 9.3 공개 데이터 소스

| 출처 | 내용 | 형식 | 키 필요 여부 |
|---|---|---|---|
| **복지로** (bokjiro.go.kr) | 전체 복지서비스 목록, 자격요건 | 웹, API | - |
| **보건복지부** → 사업안내 지침서 | 판정 기준의 핵심 자료 | PDF, HWP | 불필요, 로그인 후 다운로드 |
| **공공데이터포털** 파일데이터 | 사업안내 PDF | PDF | **불필요** — 로그인만 하면 다운로드 |
| **공공데이터포털** OpenAPI | 복지서비스 메타데이터(제도명·소관부처 등) | JSON/XML | **필요** — 활용신청 후 발급(1~2일 소요), `welfare_services` 보강용이라 급하지 않음 |
| 지자체 홈페이지 | 지역 특화 복지 | PDF, 웹 | - |

핵심 자료(사업안내 PDF)는 키 없이 바로 받을 수 있습니다. OpenAPI 키는 나중에 메타데이터를 보강할 때만 필요하므로 스파이크를 막지 않습니다.

### 9.4 수집 시 주의사항

1. **HWP 파일 처리** — 정부 문서는 HWP가 많습니다. `pyhwp` 라이브러리를 쓰거나, 수동으로 PDF 변환 후 처리하는 게 실무적으로 빠릅니다.
2. **연도 정보 필수** — 복지 기준은 매년 바뀝니다. 모든 청크와 `welfare_services` 레코드에 `updated_year` 메타데이터를 반드시 넣으세요.
3. **표(Table) 처리** — 소득 기준표 같은 표가 많은데, 일반 PDF 파서는 표를 망가뜨립니다. `pdfplumber`로 표만 따로 추출해 `welfare_services`로 구조화합니다 (5.4절, 8.5절 참고).
4. **저작권** — 공공저작물은 대체로 자유 이용이지만, 출처 표시는 하세요.

### 9.5 청킹 전략 (근거 문서용, 표 제외)

복지 지침서는 이런 구조입니다.

```
Ⅱ. 급여의 종류
  1. 생계급여
    가. 지원대상
      1) 소득인정액 기준
      2) 부양의무자 기준
    나. 지원내용
```

**구조 기반 청킹 접근**
- `Ⅱ.`, `1.`, `가.`, `1)` 패턴을 정규식으로 감지해 계층 파싱
- 청크마다 상위 계층 정보를 헤더로 붙임 → 문맥 유지
- 청크가 너무 크면 그 안에서만 재분할
- **단, 숫자로 된 기준표는 이 청킹 대상에서 제외**하고 9.2절 스파이크로 별도 추출합니다.

```python
# 청크 예시 (본문 서술 부분만)
"""
[출처] 2026 국민기초생활보장 사업안내 > Ⅱ. 급여의 종류 > 1. 생계급여 > 가. 지원대상

소득인정액이 기준 중위소득의 32% 이하인 가구 ...
"""
```

이 헤더 방식(Contextual Chunking)은 검색 정확도를 눈에 띄게 올려줍니다.

---

## 10. 개발 로드맵 (단계별, 데드라인 없음)

마감일이 없는 만큼 "몇 주"는 강제 일정이 아니라 **권장 페이스**입니다. 다만 순서는 그대로 지키세요 — 스파이크(0단계)를 건너뛰고 바로 환경 세팅과 UI로 가는 게 가장 흔한 실패 패턴입니다.

각 단계 끝에 **반드시 커밋하고 README를 갱신**하세요. 커밋 히스토리 자체가 포트폴리오입니다.

### 0단계 — 스파이크 (표 파싱 가능성 확인)

- [ ] Python 3.11 설치
- [ ] 국민기초생활보장 사업안내 PDF 다운로드 (공공데이터포털, 키 불필요)
- [ ] PDF를 눈으로 훑어 표가 단순 격자인지, 병합셀이 있는지, 페이지를 넘어가는지 확인
- [ ] `spike/table_scout.py` 실행해 결과 확인
- **산출물**: "표가 뽑히는가"에 대한 결론 + 다음 단계 방향 확정

### 1단계 — 파이썬 + FastAPI 적응

- [ ] 파이썬 문법 훑기 (4장 내용)
- [ ] FastAPI로 CRUD API 만들기 — **복지제도 목록 CRUD**로 연습
- [ ] `/docs` Swagger 확인
- [ ] Pydantic 모델로 요청/응답 검증
- [ ] SQLite(또는 PostgreSQL) + SQLAlchemy 연동
- **산출물**: 동작하는 CRUD API + 첫 커밋

> 자바에서 하던 걸 그대로 재현하는 게 최고의 적응법입니다. 새로운 걸 배우려 하지 말고 **아는 걸 옮겨보세요.**

### 2단계 — 데이터 수집 및 정형화

- [ ] 대상 제도 2~3개 확정
- [ ] 지침서 PDF 다운로드 → `data/raw/`
- [ ] `pypdf`로 본문 텍스트 추출, `pdfplumber`로 표 추출 (0단계 결과 기반)
- [ ] 표를 `welfare_services` 테이블로 적재
- [ ] 추출 품질 눈으로 확인 (깨진 텍스트, 표 붕괴 체크)
- **산출물**: 정제된 텍스트 + `welfare_services` 초기 데이터

### 3단계 — 판정 엔진 (신규, 최우선 핵심)

- [ ] 소득인정액 계산 함수 구현 (`income_calculator.py`)
- [ ] 제도별 선정기준 규칙 구현 (`rules.py`)
- [ ] 단위 테스트로 계산이 지침서 예시와 일치하는지 검증 (`test_eligibility.py`)
- **산출물**: 입력(연령·소득·재산 등)을 넣으면 충족/미충족을 정확히 반환하는 순수 함수

> **여기가 이 프로젝트의 진짜 핵심입니다.** RAG보다 이 판정 엔진의 정확도가 훨씬 중요합니다.

### 4단계 — 기본 RAG 파이프라인

- [ ] 청킹 구현 (본문 서술 부분, 표 제외)
- [ ] 임베딩 → Chroma 저장
- [ ] 간단한 검색 테스트: "생계급여 소득 기준" 검색해서 관련 문서 나오는지
- [ ] LLM 연결해 근거 인용 답변 생성
- **산출물**: 질문하면 근거와 함께 답하는 최소 RAG (CLI로 충분)

### 5단계 — 검색 품질 개선

- [ ] 구조 기반 청킹으로 교체
- [ ] 메타데이터 추가 (연도, 제도명, 페이지)
- [ ] 하이브리드 검색 (BM25 + 벡터) 적용
- [ ] Before/After 비교 기록 ← **포트폴리오 자산**
- **산출물**: 개선 전후 비교표

### 6단계 — LangGraph 도입 (판정 엔진과 결합)

- [ ] `ChatState` 설계 (`eligibility_result`, `missing_fields` 포함)
- [ ] 노드 구현: `condition_check`, `eligibility_check`, `retrieve`, `generate`
- [ ] 조건 부족 시 `ask_condition`으로 되돌아가는 루프 구현
- [ ] 멀티턴 대화 (체크포인터로 대화 기록 유지)
- **산출물**: 조건을 되묻고, 실제로 판정까지 하는 대화형 챗봇

### 7단계 — 도메인 특화 기능

- [ ] 위기 신호 감지 노드 (자살/학대/긴급 키워드 → 별도 분기)
- [ ] 출처 인용 표시 (문서명 + 페이지 + 계산 근거)
- [ ] 답변 불가 시 정직하게 "모른다" 답하기 (환각 방지 프롬프트)
- [ ] 면책 안내 문구 ("AI는 참고용 1차 판정이며, 최종 확인은 관할 기관에")
- [ ] `ai_search_logs` 적재 연결
- **산출물**: 도메인 전문성이 드러나는 기능

### 8단계 — 평가 및 UI

- [ ] 테스트셋 50문항 작성 (질문 + 정답 판정 + 근거 문서)
- [ ] RAGAS로 측정: Faithfulness, Answer Relevancy, Context Precision
- [ ] `ai_search_logs` 집계로 응답 시간·판정 성공률 리포트
- [ ] Streamlit UI 구현 (대화창 + 판정 결과 + 출처 표시 + 스트리밍)
- **산출물**: 정량 지표가 있는 데모

### 9단계 — 배포 및 문서화

- [ ] Dockerfile + docker-compose
- [ ] 클라우드 배포 (Railway/Render/EC2 중 택1)
- [ ] README 작성 (아래 참고)
- [ ] 데모 영상 2분 녹화
- **산출물**: 링크 하나로 보여줄 수 있는 완성품

### (선택) 10단계 — Spring Boot 확장

핵심 기능이 전부 끝난 뒤, 여유가 있을 때만 진행합니다. 14장(부록 A) 참고.

### README에 반드시 넣을 것

```markdown
1. 문제 정의 — 왜 이걸 만들었는가 (복지 사각지대 문제)
2. 데모 — GIF 또는 배포 링크
3. 아키텍처 다이어그램
4. LangGraph 플로우 다이어그램 (되묻기 루프 포함)
5. 판정 로직 설명 — 소득인정액 계산을 왜 LLM이 아니라 코드로 했는가
6. 기술 선택 이유 — 왜 pgvector? 왜 하이브리드 검색?
7. 성능 개선 기록 — 청킹 전략 변경 전후 정확도 비교, ai_search_logs 기반 지표
8. 평가 결과 — RAGAS 점수
9. 한계와 개선 방향 — 솔직하게
10. 실행 방법
```

**5번과 7번이 다른 포트폴리오와 갈리는 지점입니다.** "검색해서 보여줬다"가 아니라 "실제로 계산해서 판정했고, 그걸 측정했다"를 보여주세요.

---

## 11. 학습 리소스

### 11.1 파이썬

- **점프 투 파이썬** (wikidocs.net/book/1) — 무료, 한국어, 기본 문법
- **FastAPI 공식 튜토리얼** — 한국어 번역 있음. Spring 경험자는 하루면 훑습니다
- 자바 개발자용 팁: 문법책을 처음부터 읽지 말고, **CRUD 만들면서 필요한 것만 찾아보세요**

### 11.2 LangChain / LangGraph

- **LangChain 공식 문서** (python.langchain.com) — 반드시 공식 기준으로
- **LangGraph 공식 튜토리얼** — 특히 "Build a chatbot" 시리즈, 조건부 엣지(conditional edge) 부분을 중점적으로
- **테디노트 유튜브/위키독스** — 한국어 LangChain 자료 중 가장 충실

> ⚠️ **버전 주의**: LangChain은 변화가 빨라서 블로그 코드가 자주 안 돌아갑니다. `langchain.chains`에서 `langchain.` 임포트 경로가 여러 번 바뀌었습니다. 에러 나면 **공식 문서의 현재 버전 코드**를 확인하세요.

### 11.3 RAG / 판정 로직 심화

- **RAG 논문** (Lewis et al., 2020) — 개념만 훑어도 충분
- **Pinecone Learning Center** — 벡터 검색 개념 정리 잘 되어 있음
- **RAGAS 공식 문서** — 평가 지표 이해
- **국민기초생활보장 사업안내** 내 소득인정액 산정 관련 조항 — 판정 로직 구현의 1차 근거 자료

### 11.4 학습 원칙

**절대 하지 말 것**: 강의를 다 듣고 시작하려는 것. 스파이크(0단계)까지 못 갑니다.

**할 것**: 0단계 스파이크와 3단계 판정 엔진을 먼저 달성하고, 막힐 때마다 그 부분만 공부하세요.

---

## 12. 윈도우 환경 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `chromadb` 설치 시 빌드 에러 | C++ 컴파일러 없음 | **Visual Studio Build Tools** 설치 (C++ 빌드 도구 워크로드) |
| 한글 파일 읽을 때 `UnicodeDecodeError` | 윈도우 기본 인코딩 cp949 | `open(path, encoding="utf-8")` 명시 |
| 경로 에러 `\U` 등 | 역슬래시가 이스케이프로 해석 | `pathlib.Path` 사용 |
| `pip install` 매우 느림 | — | `pip install --upgrade pip` 후 재시도 |
| `pdfplumber`로 표 추출 시 셀이 깨짐 | 병합셀/스캔본 PDF | 9.2절 스파이크에서 미리 판별. 병합셀 많으면 HTML 소스로 전환 |
| Docker 실행 안 됨 | WSL2 미설치 | Docker Desktop + WSL2 백엔드 설치 |
| 한국어 임베딩 모델 다운로드 느림 | HuggingFace 다운로드 | 최초 1회만 걸림. 캐시됨 |
| venv 활성화 스크립트 실행 정책 오류 | PowerShell 실행 정책 | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |

**개발 편의 도구 추천**
- **VS Code** + Python 확장 + Pylance (자바의 IntelliJ 역할)
- **Ruff** — 린터 겸 포매터. `pip install ruff` 후 저장 시 자동 정렬
- **Windows Terminal** — 기본 cmd보다 훨씬 편함

---

## 13. 포트폴리오 어필 포인트

### 13.1 예상 질문과 답변 준비

| 질문 | 준비할 답변 방향 |
|---|---|
| 이 챗봇이 다른 RAG 프로젝트와 뭐가 다른가요? | 검색 유사도가 아니라 소득인정액을 실제로 계산해 충족/미충족을 판정. RAG는 근거 인용 보조 역할 |
| 판정을 왜 LLM이 아니라 코드로 했나요? | 법령 기반 결정론적 계산이라 재현성과 검증이 필요. LLM은 설명 조립만 담당 |
| LangGraph를 왜 썼나요? | 단순 체인으로는 조건 부족 시 되묻는 루프와 위기 분기를 표현할 수 없어서 |
| 청킹 전략을 왜 그렇게 했나요? | 복지 지침서의 조항 구조 → 구조 기반 청킹, 표는 별도 정형 테이블로 분리 |
| 검색 정확도를 어떻게 개선했나요? | 하이브리드 검색 도입 근거(제도명 정확 매칭 필요) + Before/After |
| 환각은 어떻게 막았나요? | 판정은 코드 계산으로 확정, 근거 인용 강제, 근거 없으면 "모른다" 응답, Faithfulness 측정 |
| 성능 병목은 어떻게 파악했나요? | `ai_search_logs`에 질문·검색문서수·응답시간을 쌓아 집계 분석 |
| 자바 하다가 파이썬으로 바꾼 이유는? | AI 스택 필요성 + 백엔드 기본기는 언어 무관하다는 점 |
| Spring Boot는 왜 안 쓰셨나요? (혹은 어떻게 쓸 계획인가요?) | 핵심 차별점(판정 로직, LangGraph)은 전부 Python/AI 레이어에 있어 먼저 완성. 이후 API 게이트웨이 등으로 확장 가능(14장) |

### 13.2 차별화되는 요소

1. **판정의 정확성** — 검색 유사도가 아니라 실제 계산에 기반한 충족/미충족 판정
2. **도메인 전문성** — 복지 실무를 아는 사람만 설계할 수 있는 조건 수집 흐름과 위기 감지 기능
3. **정량 측정** — RAGAS 점수 + `ai_search_logs` 기반 개선 기록. 대부분의 포트폴리오에는 없습니다
4. **아키텍처적 판단 근거** — LangGraph, pgvector, 판정/검색 분리 등 모든 선택에 "왜"가 설명됨

---

## 14. 부록 A: Spring Boot 확장 (선택, 나중에)

이 섹션은 **핵심 기능(판정 엔진 + RAG + LangGraph)이 전부 완성된 이후에만** 참고하세요. 처음부터 같이 진행하면 작업량이 1.5~2배로 늘고, 판정 로직처럼 실제 차별점이 되는 부분이 늦어집니다.

### 14.1 왜 나중에 붙이는 게 의미가 있는가

실무에서는 Java 기반 시스템(특히 금융·보험권)에 Python AI 서버를 붙이는 구조가 흔합니다. "Java 백엔드 경험 위에 Python AI 서버를 통합해봤다"는 서사는 이미 Java 경험이 있는 개발자에게 자연스럽고 실무적으로도 설득력이 있습니다.

### 14.2 붙이는 방법 (예시)

- **API 게이트웨이 방식**: Spring Boot가 사용자 인증·요청 라우팅을 맡고, 내부적으로 FastAPI(Python AI 서버)를 호출
- **관리자 백오피스 방식**: `welfare_services` 데이터 관리, 통계 대시보드 등 CRUD 성격이 강한 부분을 Spring Boot로 별도 구현하고 AI 챗봇 자체는 Python 유지

```
┌──────────────┐      ┌───────────────────┐
│ React/Thymeleaf│ →  │  Spring Boot        │  인증, 라우팅, 관리자 기능
│  (관리자 UI)   │      │  (Java)             │
└──────────────┘      └─────────┬───────────┘
                                 │ REST 호출
                                 ▼
                       ┌───────────────────┐
                       │  FastAPI (Python)  │  RAG + LangGraph + 판정 엔진
                       └───────────────────┘
```

### 14.3 착수 전 체크

- [ ] 판정 엔진 단위 테스트 통과
- [ ] LangGraph 되묻기 루프 정상 동작
- [ ] RAGAS 평가 지표 확보
- [ ] 위 세 가지가 전부 끝났는가? → 그렇다면 진행해도 좋습니다

---

## 15. 부록 B: 첫 스파이크 체크리스트

10장 0단계와 동일한 내용을 실행 순서대로 정리한 것입니다.

- [ ] 공공데이터포털(data.go.kr) 가입 — 파일데이터는 키 불필요, 로그인만 하면 다운로드
- [ ] Python 3.11 설치 (3.13 아님)
- [ ] 국민기초생활보장 사업안내 PDF 다운로드 → `data/raw/`
- [ ] PDF를 열어 표 구조를 눈으로 확인 (격자 단순한지, 병합셀 있는지, 페이지 걸치는지)
- [ ] `pip install pdfplumber`
- [ ] `python spike/table_scout.py "국민기초생활보장_사업안내.pdf" --pages 1-50` 실행
- [ ] 결과 확인: 표 개수, 병합셀 여부, 빈 셀 비율 → 9.2절 표에 따라 다음 경로 결정
- [ ] 마음에 드는 표는 `--dump <페이지번호>` 로 JSON 덤프해서 실제 값 확인
- [ ] (선택, 나중에) OpenAI 또는 Anthropic API 키 발급 + 사용 한도(예: 월 $10) 설정
- [ ] (선택, W2 이후) 공공데이터포털 OpenAPI 활용신청 — 중앙부처·지자체 복지서비스 목록

```python
# app/main.py — 스파이크 이후 1단계에서 만들 최소 헬스체크
from fastapi import FastAPI

app = FastAPI(title="복지제도 판정 챗봇 API")


@app.get("/health")
def health_check():
    return {"status": "ok"}
```

`uvicorn app.main:app --reload` 실행 → `localhost:8000/docs`가 뜨면 1단계 시작 준비 완료입니다.

첫 커밋 메시지 예시: `chore: 프로젝트 초기 구조 설정`

---

*이 문서는 진행하면서 계속 갱신하세요. 특히 10장 로드맵의 체크박스와 13장 포트폴리오 답변은 개발하면서 채워나가는 것이 핵심입니다.*
