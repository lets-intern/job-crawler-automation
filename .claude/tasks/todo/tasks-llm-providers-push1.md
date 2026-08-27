# Tasks: llm-providers - Push 1

> PRD: `.claude/tasks/todo/prd-llm-providers.md`
> Push 범위: 호출 자리를 제공자에서 떼어내고 네 제공자를 붙인다. 화면은 건드리지 않는다
> 상태: 진행 중

## 왜 이 순서인가

키를 화면에서 바꾸는 것(Push 2)은 **바꿀 대상이 여러 개일 때만 의미가 있다.** 제공자가 하나뿐인
상태에서 화면부터 만들면 고를 것이 없는 선택 상자를 만드는 셈이다. 그래서 호출 자리를 먼저
넓히고, 그다음에 화면을 붙인다.

이 Push 가 끝나면 **환경변수만으로** 네 제공자를 쓸 수 있다. 화면 없이도 배포 한 번으로
Qwen 분류가 가능해진다는 뜻이고, 크레딧이 막힌 지금 상태를 이 Push 만으로 풀 수 있다.

## 관련 파일

- `app/llm/gemini.py` - 지금 유일한 호출 자리. `build_client()` · `call_model()` · `PROVIDER`
- `app/llm/log.py` - 호출 기록. `PROVIDER` 를 gemini.py 에서 가져다 박고 있다
- `app/config.py` - `gemini_api_key` · `gemini_model` 두 줄만 있다
- `app/selector/generator.py` - 셀렉터 생성 호출 (`build_gemini_client` · `call_gemini`)
- `app/selector/repair.py` - 셀렉터 수정 호출. `resolved.gemini_model` 을 직접 읽는다 (301줄)
- `app/classify/classifier.py` - 분류 호출 (202줄에서 `resolved.gemini_model`)
- `app/classify/batch.py` - 분류 배치. 실패 기록에 모델 이름을 쓴다 (197줄)
- `app/api/crawlers.py` - `record_call` 을 부른다 (53줄)
- `migrations/0013_llm_calls.sql` - `provider` 칸이 **이미 있다**. 값만 gemini 로 박혀 있다
- `.env.example` - 키 이름만 적는 곳

## 선행 조건

- 없음. PRD 의 미결정 사항(키 저장 위치)은 2026-08-27 에 정해졌다
- **모델 ID 와 파라미터 모양은 각 제공자의 현재 문서를 확인하고 쓴다.** 기억으로 쓰지 않는다
  (`.claude/rules/llm.md`)

## 알아 둘 것

**`llm_calls.provider` 칸은 이미 있다.** 마이그레이션을 새로 만들지 않는다. `app/llm/log.py`
가 `from app.llm.gemini import PROVIDER` 로 상수를 가져다 박고 있는 것이 문제이고, 그 줄만
고치면 된다.

**SDK 는 셋이면 넷을 덮는다.** Qwen(DashScope)이 OpenAI 호환 엔드포인트를 준다. `openai` SDK 에
`base_url` 만 바꿔 GPT 와 Qwen 을 같이 태울 수 있는지 문서로 확인하고, 되면 그렇게 한다.
`anthropic` 은 따로 필요하다. 지금 깔린 것은 `google-genai` 하나뿐이다.

**`guard-direct-fetch.sh` 는 `httpx`·`requests` 직접 호출에만 경고한다.** 공식 SDK 를 쓰면
걸리지 않는다. 훅에 예외를 더할 일이 생겼다면 SDK 대신 `httpx` 를 쓰려는 것이므로, 그 선택을
먼저 다시 본다.

**응답 스키마 제약이 이 Push 의 진짜 위험이다.** 지금 코드는 Gemini 의 `response_schema` 에
기대고 있고, 분류가 닫힌 목록을 지키는 것이 거기에 걸려 있다. 제공자마다 같은 보장을 어떻게
얻는지 문서로 확인하고, **얻을 수 없는 제공자는 분류에서 뺀다.** 프롬프트로 부탁하는 것은
보장이 아니다 (`.claude/rules/llm.md`).

## 작업

- [ ] 1.0 호출 자리를 제공자에서 떼어내고 넷을 붙인다

    - [x] 1.1 네 제공자의 현재 문서를 확인하고 조사 결과를 적는다
        - 확인할 것: 모델 ID, 응답을 JSON 스키마로 제약하는 방법, 토큰 수를 돌려주는 자리,
          비동기 호출 모양, 오류 타입
        - Qwen 이 OpenAI 호환 엔드포인트로 되는지 여기서 판정한다
        - **스키마 제약을 못 얻는 제공자를 명시한다.** 그 제공자는 분류에서 뺀다
        - 결과는 `.claude/tasks/memos/llm-provider-조사.md` 에 표로 적는다
        - [x] 1.1.V 검증: 표의 모든 모델 ID 와 파라미터 이름이 각 제공자 공식 문서에 있는
              값인지 대조한다. 기억으로 쓴 값이 하나도 없어야 한다

    - [x] 1.2 `app/llm/` 에 제공자 항목과 공통 타입을 만든다
        - `LlmCallError` · `Usage` · `PROVIDER` 를 제공자 중립인 자리로 옮긴다
          (`app/llm/base.py` 등). `app/llm/gemini.py` 는 Gemini 항목만 남긴다
        - 제공자 항목 하나가 적는 것: 이름, SDK, 모델 설정 키, 토큰 세는 법, 스키마 제약 지원
          여부. **그 외 어디에서도 제공자로 분기하지 않는다**
        - 기존 import 경로(`from app.llm.gemini import ...`)를 쓰는 다섯 파일을 같이 고친다
        - [x] 1.2.V 검증: `mypy app` 통과, 기존 pytest 전체 통과. 이 작업은 동작을 바꾸지
              않으므로 **테스트가 하나도 수정되지 않아야 한다** — 수정이 필요했다면 옮기다
              동작이 바뀐 것이다

    - [x] 1.3 Qwen 항목을 붙인다
        - 1.1 에서 정한 SDK 와 모델 ID 를 쓴다
        - 키가 없으면 `LlmCallError("no_api_key", ...)` 로 서고, **다른 제공자로 넘어가지
          않는다** (`.claude/rules/llm.md`)
        - 실행 중 정한 것: 제공자별 키·모델 설정은 1.5 가 아니라 **그 제공자를 붙이는
          작업에서** 같이 더한다. 설정이 없는 항목은 그 커밋에서 임포트조차 되지 않아,
          미루면 중간 커밋이 깨진 채로 남는다. 1.5 는 기능별 선택과 빈 문자열 처리,
          `.env.example` 을 맡는다
        - [x] 1.3.V 검증: 응답을 가짜로 만든 픽스처 기반 pytest 를 쓴다 —
              토큰 수가 `Usage` 에 옮겨지는지, 오류가 `LlmCallError` 로 바뀌는지,
              키가 비었을 때 `no_api_key` 인지. 실제 호출은 하지 않는다

    - [x] 1.4 Claude 와 GPT 항목을 붙인다
        - 1.3 과 같은 모양. 스키마 제약을 못 얻는 제공자는 그 사실을 항목에 적는다
        - [x] 1.4.V 검증: 1.3 과 같은 픽스처 pytest 를 제공자별로 쓴다.
              **스키마 제약을 못 얻는 제공자를 분류에 지정하면 거절되는지**까지 확인한다

    - [x] 1.5 기능마다 제공자와 모델을 환경변수로 고른다
        - `app/config.py` 에 제공자별 키와 기능별 선택을 더한다
          (셀렉터 생성 / 셀렉터 수정 / 본문 분류)
        - **빈 문자열을 값으로 취급하지 않는다.** compose 의 `""` 가 키가 있는 것처럼 보이면
          호출이 401 로 죽는다. `ADMIN_PASSWORD` 와 `CRAWL_USER_AGENT` 에서 같은 것에
          두 번 걸렸다
        - `.env.example` 에 **이름만** 적는다. 값은 적지 않는다
        - 실행 중 정한 것: Qwen 키 이름을 `QWEN_API_KEY` 로 정하고 `.env` 의 오타
          `QWEEN_API_KEY` 를 고쳤다. 둘 다 읽는 코드를 쓰지 않는다 — 오타를 코드가 받아 주면
          오타가 규격이 되고 다음 사람이 어느 쪽이 맞는지 알 길이 없어진다.
          Claude·GPT 도 제공자 이름을 따라 `CLAUDE_API_KEY`·`GPT_API_KEY` 로 둔다.
          제공자 문서의 이름(`ANTHROPIC_API_KEY`·`OPENAI_API_KEY`)을 쓰지 않는 것은,
          SDK 가 그 이름을 환경에서 스스로 읽어 설정한 적 없는 남의 키로 호출이 나가는 길을
          막기 위해서다 (`.claude/tasks/memos/llm-provider-조사.md`)
        - [x] 1.5.V 검증: `tests/test_config.py` 에 기본값과 빈 문자열 처리를 더한다.
              기능별 선택이 비었을 때 어떤 제공자로 떨어지는지도 잠근다

    - [x] 1.6 세 호출 자리가 고른 제공자를 쓰게 한다
        - `app/selector/generator.py` · `app/selector/repair.py` · `app/classify/classifier.py`
        - 셋 다 `resolved.gemini_model` 을 직접 읽고 있다. 기능에 맞는 설정을 읽도록 바꾼다
        - `app/classify/batch.py` 197줄의 실패 기록도 같이 본다
        - 같이 고친 것: `app/api/ui.py` 의 `no_api_key` 안내가 `GEMINI_API_KEY` 를 못박고
          있었다. 제공자를 고를 수 있게 된 뒤로는 틀린 문장이라 제공자 중립으로 바꾸고,
          새 사유 `unknown_provider`·`no_schema_support` 의 다음 수를 같이 적었다
        - [x] 1.6.V 검증: 기존 셀렉터·분류 pytest 가 전부 통과하는지 본다. 여기에 더해
              **기능마다 다른 제공자를 지정했을 때 각자 그것을 부르는지** 픽스처로 확인한다

    - [ ] 1.7 호출 기록에 실제 제공자가 남는다
        - `app/llm/log.py` 가 `from app.llm.gemini import PROVIDER` 로 상수를 박고 있다.
          호출한 제공자를 넘겨받도록 고친다
        - **마이그레이션은 만들지 않는다.** `llm_calls.provider` 칸은 0013 에 이미 있다
        - [ ] 1.7.V 검증: `tests/test_llm_calls.py` 를 고쳐, 서로 다른 제공자로 두 번 기록한 뒤
              `provider` 로 갈라 세었을 때 각각 맞게 나오는지 확인한다

    - [ ] 1.8 Qwen 으로 실제 분류를 돌린다
        - 미분류 270건 중 **먼저 3건만** 돌린다 (`POST /api/classify?limit=3`)
        - 채워진 값이 본문에 실제로 있는지, 판정 칸이 정해진 목록 안의 값인지 눈으로 본다
        - 괜찮으면 나머지를 돌린다
        - [ ] 1.8.V 검증: `job_classifications` 가 270건 늘고, `llm_calls` 에 `provider='qwen'`
              행이 남고, 표본 3건의 값이 본문과 맞는지 확인한다. **미분류가 0 이 되는 것이
              PRD 8번 조건이다**

## 이 Push 가 끝나면

환경변수에 Qwen 키를 넣고 배포하면 분류가 돈다. 화면은 아직 없다 — Push 2 다.
