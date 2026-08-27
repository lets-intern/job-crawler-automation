# 제공자 넷 조사 (Gemini · Claude · GPT · Qwen)

> 조사일: 2026-08-27
> 왜: `.claude/tasks/todo/tasks-llm-providers-push1.md` 의 1.1
> 규칙: 모델 ID 와 파라미터 모양은 기억으로 쓰지 않는다 (`.claude/rules/llm.md`)

## 무엇을 정하려고 조사했나

셋이다.

- **SDK 가 몇 개 필요한가.** Qwen 이 OpenAI 호환 엔드포인트를 주면 넷을 셋으로 덮는다
- **어느 제공자가 응답을 스키마로 강제할 수 있는가.** 못 하는 제공자는 분류에서 뺀다.
  분류의 판정 칸이 닫힌 목록을 지키는 것이 여기 걸려 있다 (`app/classify/schema.py`)
- **토큰 수와 오류를 어디서 꺼내는가.** `llm_calls` 에 남길 값이고, `Usage` 로 옮겨야 한다

## 조사 방법

한 가지로 하지 않았다. 문서만 읽으면 모델 ID 가 맞는지 알 수 없고, SDK 만 보면 제공자가
무엇을 보장하는지 알 수 없다.

| 방법 | 무엇을 확인했나 |
|---|---|
| 각 제공자 공식 문서 | 모델 ID, 스키마 제약 문법, 토큰 자리, 가격 |
| 설치한 SDK 를 열어 확인 | 예외 클래스와 메서드가 실제로 있는지 (`openai` 3.5.0, `anthropic` 1.1.0) |
| 키로 실제 호출 1회 | Gemini 와 Qwen 키가 지금 무엇을 돌려주는지 |

세 번째가 문서 두 개를 뒤집었다. 아래 "키를 눌러 본 결과" 에 적는다.

## 제공자별 요약

| | Gemini | Claude | GPT | Qwen |
|---|---|---|---|---|
| SDK | `google-genai` | `anthropic` | `openai` | `openai` (호환 엔드포인트) |
| 이 저장소의 키 이름 | `GEMINI_API_KEY` | `CLAUDE_API_KEY` | `GPT_API_KEY` | `QWEN_API_KEY` |
| 제공자 문서가 쓰는 키 이름 | `GEMINI_API_KEY` | `ANTHROPIC_API_KEY` | `OPENAI_API_KEY` | `DASHSCOPE_API_KEY` |
| 스키마 강제 | 가능 | 가능 | 가능 | 모델에 따라 가능 |
| 분류에 쓸 수 있나 | 쓸 수 있다 | 쓸 수 있다 | 쓸 수 있다 | 지원 모델에서만 |
| 비동기 | `client.aio.models.generate_content` | `AsyncAnthropic.messages` | `AsyncOpenAI.chat.completions` | 같음 |
| 오류 기반 클래스 | `google.genai.errors.APIError` | `anthropic.APIError` | `openai.APIError` | `openai.APIError` |

키 이름을 제공자 문서와 다르게 정한 이유는 아래 "정한 것" 에 적는다.

## SDK 는 셋이면 넷을 덮는다

Qwen(DashScope)은 OpenAI 호환 엔드포인트를 준다. `openai` SDK 에 `base_url` 만 바꿔 붙는다.

| 리전 | base_url |
|---|---|
| 싱가포르(국제) | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` |
| 베이징(중국) | `https://dashscope.aliyuncs.com/compatible-mode/v1` |

**문서가 지금 권하는 것은 위의 둘이 아니다.**
`https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1` 형태의 워크스페이스
전용 도메인으로 옮기라고 적고 있고, 위의 도메인은 "옮겨 오라" 는 문맥에서만 나온다. 다만 계속
동작한다고도 적혀 있다.

2026-08-27 에 싱가포르 쪽으로 실제로 요청을 보내 동작하는 것을 확인했다. `models.list()` 가
모델 목록을 돌려줬고, 없는 모델에는 404 를, 있는 모델에는 403 을 제대로 갈라 줬다.

전용 도메인은 콘솔에서 `WorkspaceId` 를 봐야 알 수 있어 기본값으로 둘 수 없다. 위의 것을
기본값으로 쓰고 `base_url` 을 설정으로 두어, 전용 도메인으로 옮길 때 운영자가 바꾼다.

출처: <https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope>

`AsyncOpenAI(base_url=...)` 는 설치한 SDK 의 생성자 인자로 실제로 있는 것을 확인했다.
그래서 필요한 SDK 는 `google-genai`, `openai`, `anthropic` 셋이다. 지금 깔린 것은 첫 번째뿐이다.

## 응답을 스키마로 강제하는 방법

이 Push 의 진짜 위험이 여기다. 넷이 같은 방식을 쓰지 않는다.

| 제공자 | 방법 | 문서가 쓰는 표현 | enum |
|---|---|---|---|
| Gemini | `config.response_schema` + `response_mime_type="application/json"` | 지금 코드가 이미 쓴다 | Pydantic `Literal` 이 그대로 JSON Schema `enum` 이 된다 |
| Claude | `messages.parse(output_format=...)` 또는 도구에 `strict: true` | Structured Outputs | 지원 |
| GPT | `response_format={"type":"json_schema","json_schema":{...,"strict":true}}` | "항상 스키마를 지키는 응답을 내게 한다(ensures)" | 지원 |
| Qwen | GPT 와 같은 문법 | "**권장**(recommended). 형식을 엄격히 따른다" | 타입 목록에 있다. 예제는 없다 |

**Qwen 만 문장의 세기가 다르다.** GPT 문서는 ensures 라고 쓰고, Qwen 문서는 recommended 라고
쓴다. 같은 문법이지만 같은 약속이 아니다.

GPT 문서에 guarantee 라는 낱말이 있는지는 확인하지 못했다. 지금 가이드 페이지가 쓰는 낱말은
ensures 다. 2024년 발표 글에 guarantees 가 있으나 그것은 다른 페이지라 근거로 쓰지 않는다.

### Qwen 은 어느 모델에서 되는가

지원 목록이 모델 시리즈로 한정된다.

| 판정 | 모델 |
|---|---|
| `json_schema` + `strict` 지원 | `Qwen3.7-Plus`, `Qwen3.7-Flash`, `Qwen3.7-Max`, `Qwen3.8-Flash`, `Qwen3.8-Max` 시리즈 |
| 지원 목록에 없음 | `qwen-turbo`, `qwen-plus`, `qwen-flash`, `qwen-max` 같은 버전 없는 별칭 |

별칭에서 되는 것은 `json_object` 뿐이다. 그것은 "JSON 이기는 하다" 이지 "이 칸에 이 값만
온다" 가 아니다. **분류에는 쓸 수 없다.** 판정 칸이 닫힌 목록을 지키는 것이 목적인데,
`json_object` 는 칸 이름도 값도 보장하지 않는다.

`Qwen3.7-Flash` 는 중국어판 문서에만 있고 영문판에는 없다. 두 판본에 모두 있는 것은
`Qwen3.8-Flash` 다. 기본값은 두 판본이 일치하는 쪽으로 둔다.

`qwen3.8-flash` 는 모델 목록 문서와 가격표 문서에는 없다. 대조하면서 걸린 것인데, 실제
엔드포인트의 `models.list()` 에는 있다(아래 "키를 눌러 본 결과"). 구조화 출력 문서가 지원
시리즈로 적은 것과 실제 목록이 일치하고, 어긋난 것은 모델 목록·가격표 쪽이다. 존재는 실제
목록을 믿고, 가격은 문서에 없으므로 미확인으로 둔다.

출처: <https://help.aliyun.com/zh/model-studio/qwen-structured-output>,
<https://help.aliyun.com/en/model-studio/qwen-structured-output>

조사 중에 `www.alibabacloud.com/help/en/model-studio/qwen-structured-output` 이
`.../structured-output` 으로 리다이렉트되는 것을 확인했다. 리다이렉트된 쪽은 `json_object` 를
설명하는 **다른 문서**이고 `json_schema` 라는 낱말이 없다. 두 미러가 갈린 것처럼 보였던 이유가
이것이다. 다시 확인할 때 이 URL 을 근거로 쓰지 않는다.

## 모델 ID

설정에 넣을 값이다. 소스에 박지 않는다 (`.claude/rules/llm.md`).

| 제공자 | 싼 쪽 | 정확한 쪽 | 가격 (입력/출력, $/1M) |
|---|---|---|---|
| Gemini | `gemini-3.5-flash` | `gemini-3.1-pro-preview` | 1.50/9.00, 2.00/12.00 |
| Gemini (더 싼 쪽) | `gemini-3.6-flash` | | 0.75/3.75 |
| Claude | `claude-haiku-4-5-20251001` | `claude-sonnet-5` | 1.00/5.00, 2.00/10.00 |
| GPT | `gpt-5.6-luna` | `gpt-5.6-terra` | 0.20/1.20, 2.00/12.00 |
| Qwen | `qwen3.8-flash` | `qwen3.7-plus` | 미확인, 0.4~1.2/1.6~4.8 |

**`qwen3.8-flash` 의 가격을 문서에서 찾지 못했다.** 가격표에 그 줄이 없다. 같은 flash 계열의
값은 `qwen-flash` 가 0.05~0.25/0.4~2, `qwen3.6-flash` 가 0.25~1/1.5~4 다. 여기서 유추하지
않는다 — 분류는 건당 약 4,918 토큰이고 270건이면 유추가 틀렸을 때 그만큼 틀린다. 계정을 풀 때
콘솔에서 확인한다.

Qwen 가격은 싱가포르 리전이고 컨텍스트 길이 구간에 따라 단가가 달라진다. 베이징 리전이 더
싸지만 키의 리전이 정해져 있어 고를 수 있는 값이 아니다.

출처: <https://ai.google.dev/gemini-api/docs/models>,
<https://ai.google.dev/gemini-api/docs/pricing>,
<https://platform.claude.com/docs/en/models/overview>,
<https://developers.openai.com/api/docs/pricing>,
<https://www.alibabacloud.com/help/en/model-studio/model-pricing>

지금 쓰는 `gemini-3.5-flash` 는 문서의 모델 목록에 그대로 있다. 이 Push 에서 바꾸지 않는다.

## 토큰 수를 돌려주는 자리

| 제공자 | 입력 | 출력 | 합 |
|---|---|---|---|
| Gemini | `usage_metadata.prompt_token_count` | `usage_metadata.candidates_token_count` | `usage_metadata.total_token_count` |
| Claude | `usage.input_tokens` | `usage.output_tokens` | 없다. 더해서 쓴다 |
| GPT | `usage.prompt_tokens` | `usage.completion_tokens` | `usage.total_tokens` |
| Qwen | GPT 와 같다 | 같다 | 같다 |

Claude 만 합계 칸이 없다. `Usage.total_tokens` 는 입력과 출력을 더해 채운다.

Gemini 에는 `interactions.create` 라는 새 API 가 있고 토큰 자리가
`usage.total_input_tokens` 로 다르다. 지금 코드는 `generate_content` 를 쓰고 있고 이 Push 에서
옮기지 않는다 — 옮기는 것은 이 작업의 범위가 아니다.

## 비동기 호출 모양

| 제공자 | 호출 |
|---|---|
| Gemini | `await client.aio.models.generate_content(model=, contents=, config=)` |
| Claude | `await client.messages.create(model=, messages=, max_tokens=)` |
| GPT · Qwen | `await client.chat.completions.create(model=, messages=)` |

Claude 는 `max_tokens` 가 필수다. 나머지 셋은 선택이다.

`anthropic.AsyncAnthropic().messages.parse` 와 `openai.AsyncOpenAI().chat.completions.parse`
가 설치한 SDK 에 실제로 있는 것을 확인했다. `parse` 는 Pydantic 클래스를 그대로 받는다.

## 오류 타입

| 상황 | Gemini | Claude · GPT · Qwen |
|---|---|---|
| 인증 실패 (401) | `errors.ClientError` (`code == 401`) | `AuthenticationError` |
| 한도 초과 (429) | `errors.ClientError` (`code == 429`) | `RateLimitError` |
| 크레딧 소진 | 429 로 온다. 전용 클래스 없음 | 429 로 온다. 전용 클래스 없음 |
| 권한 없음 (403) | `errors.ClientError` | `PermissionDeniedError` |
| 서버 오류 (5xx) | `errors.ServerError` | `InternalServerError` |
| 연결 실패 | | `APIConnectionError` |

**넷 다 크레딧 소진에 전용 예외가 없다.** 429 로 오고, 무엇 때문인지는 메시지에만 있다.
그래서 오류 메시지를 `llm_calls.error` 에 남기는 것이 필요하다 — 남기지 않으면 "분당 한도에
걸렸나, 돈이 떨어졌나" 를 나중에 가를 수 없다. 지금 코드가 이미 그렇게 한다.

`anthropic` 과 `openai` 의 위 클래스가 실제로 있는 것을 설치한 SDK 에서 확인했다.
`google.genai.errors` 의 `ClientError`/`ServerError` 는 400~499 / 500~599 로 갈릴 뿐 429
전용 클래스가 없다.

## 키를 눌러 본 결과 (2026-08-27)

문서만 읽고 넘어갔으면 놓쳤을 것이다. 실제 호출 1회씩이다.

| 키 | 결과 |
|---|---|
| `GEMINI_API_KEY` | 429 `Your prepayment credits are depleted.` PRD 가 적은 그대로다 |
| `QWEEN_API_KEY` (싱가포르) | 403 `AccessDenied.Unpurchased` — 모델 접근 권한이 없다 |
| `QWEEN_API_KEY` (베이징) | 401 `Incorrect API key provided` — 리전이 다르다 |
| `QWEEN_API_KEY` — `models.list()` | 성공. 모델 목록은 돌려준다 |
| `CLAUDE_API_KEY` | 키가 없다 |
| `GPT_API_KEY` | 키가 없다 |

읽을 것이 셋이다.

**Qwen 키는 싱가포르 리전 키다.** 베이징에서 401 이 나고 싱가포르에서 401 이 아닌 403 이
났다. 키 자체는 인정받았고 막힌 것은 모델 접근이다.

**Qwen 키로는 지금 어떤 모델도 부를 수 없다.** `qwen-flash`, `qwen3.7-flash`, `qwen-plus`,
`qwen-turbo` 넷 다 같은 403 이고, 스키마를 걸든 안 걸든 같다.

모델 이름을 잘못 쓴 것이 아닌지 갈라 봤다. 없는 이름을 넣으면 404 `does not exist` 가 오고,
있는 이름을 넣으면 403 `AccessDenied.Unpurchased` 가 온다. **403 은 이름 문제가 아니라 계정에
모델 이용 자격이 없다는 뜻이다.** 콘솔에서 Model Studio 를 활성화하거나 결제 수단을 등록해야
풀린다.

`models.list()` 는 자격 없이도 답한다. 그래서 모델 ID 대조는 이 상태에서도 할 수 있었다.

**지금 부를 수 있는 제공자가 하나도 없다.** Gemini 는 돈이 떨어졌고 Qwen 은 자격이 없고
Claude 와 GPT 는 키가 없다. 이 Push 의 1.8(실제 분류 실행)은 코드가 아니라 계정 상태에
막혀 있다.

덤으로 하나 더 확인됐다. `gemini-2.5-flash` 는 404 로 거절되며
`no longer available to new users` 와 함께 `gemini-3.6-flash` 를 쓰라고 답한다. 구세대 ID 를
기본값으로 두면 안 된다는 뜻이다.

## 정한 것

코드에 그대로 들어가는 결정이다.

| 결정 | 이유 |
|---|---|
| SDK 는 `google-genai`, `openai`, `anthropic` 셋 | Qwen 이 `openai` 에 `base_url` 로 붙는다 |
| 제공자 이름은 `gemini`, `claude`, `gpt`, `qwen` | `llm_calls.provider` 에 그대로 들어간다. PRD 가 쓰는 이름과 같다 |
| 키 이름은 `<제공자>_API_KEY` | 아래 참고 |
| Qwen 기본 모델은 `qwen3.8-flash` | 스키마 지원 목록에 있고 영문·중국어 문서가 일치한다 |
| Qwen 은 분류에 쓸 수 있다고 본다 | 단, 지원 목록의 모델일 때만. 별칭을 넣으면 보장이 사라진다 |

### 키 이름을 제공자 문서와 다르게 정한 이유

Claude 의 문서는 `ANTHROPIC_API_KEY`, GPT 는 `OPENAI_API_KEY`, Qwen 은 `DASHSCOPE_API_KEY`
를 쓴다. 이 저장소는 `CLAUDE_API_KEY`, `GPT_API_KEY`, `QWEN_API_KEY` 로 둔다.

둘 때문이다. 제공자 이름이 넷이고 화면(Push 2)이 그 이름으로 고르게 되므로, 키 이름이
`<제공자>_API_KEY` 로 기계적으로 따라오는 편이 표를 한 번 더 보지 않아도 된다. 그리고 SDK 는
키를 주지 않으면 `ANTHROPIC_API_KEY` 나 `OPENAI_API_KEY` 를 환경에서 스스로 읽는다 — 개발
기계에 이미 깔려 있는 남의 키로 조용히 호출이 나가는 길이고, 이름을 달리 두면 그 길이 막힌다.
키는 항상 설정에서 읽어 명시적으로 넘긴다.

### `QWEEN_API_KEY` 는 `QWEN_API_KEY` 로 고친다

지금 `.env` 에 `QWEEN_API_KEY` 로 적혀 있다. 철자가 틀렸다. 표준 철자는 Qwen 이다.

**둘 다 읽는 코드를 쓰지 않는다.** 오타를 코드가 받아 주면 오타가 규격이 되고, 다음 사람이
어느 쪽이 맞는지 알 길이 없어진다. `.env` 를 고치고 `.env.example` 에는 `QWEN_API_KEY` 만
적는다.

## 대조 결과 (1.1.V)

위 표의 모델 ID 와 파라미터 이름을 하나씩 되짚었다. 조사한 경로와 다른 경로로 맞춰 보는 것이
목적이라, 문서를 다시 읽는 것 말고 **실제 목록과 설치한 SDK** 를 같이 썼다.

| 대조한 것 | 방법 | 결과 |
|---|---|---|
| `gemini-3.5-flash`, `gemini-3.6-flash`, `gemini-3.1-pro-preview` | 실 API `models.list()` | 셋 다 있다 |
| `claude-haiku-4-5-20251001`, `claude-sonnet-5` | `anthropic` SDK 의 모델 목록 리터럴 | 둘 다 있다 |
| `gpt-5.6-luna`, `gpt-5.6-terra` | `openai` SDK 의 모델 목록 리터럴 | 둘 다 있다 |
| `qwen3.8-flash`, `qwen3.7-flash`, `qwen3.7-plus`, `qwen3.7-max`, `qwen3.8-max` | 실 엔드포인트 `models.list()` | 다섯 다 있다 |
| Claude·GPT 가격, Claude `max_tokens` 필수 여부 | 공식 문서 재대조 | 표와 같다 |
| 예외 클래스 이름 전부 | 설치한 SDK 에서 존재 확인 | 표와 같다 |
| `messages.parse(output_format=)`, `chat.completions.parse` | 설치한 SDK 의 시그니처 | 표와 같다 |
| `AsyncOpenAI(base_url=)` | 설치한 SDK 의 생성자 인자 | 있다 |

대조에서 네 자리가 틀렸고 고쳤다. 무엇이 틀렸는지 남겨 둔다 — 같은 자리를 다음에 또 틀린다.

| 틀린 것 | 무엇이 맞나 |
|---|---|
| GPT 문서가 `strict` 를 "보장(guarantee)" 이라고 쓴다고 적었다 | 지금 가이드가 쓰는 낱말은 ensures 다 |
| `qwen3.8-flash` 가격을 범위로 적었다 | 서로 다른 두 모델의 값을 섞은 것이었다. 문서에 그 줄이 없다 |
| Qwen base_url 을 현행 권장값처럼 적었다 | 문서는 워크스페이스 전용 도메인을 권한다. 쓰는 것은 구 도메인이고 동작은 확인했다 |
| GPT 의 `gpt-5.6` 이 구조화 출력을 지원한다고 읽힐 수 있게 적었다 | 지원 모델 표에 그 이름이 없다. 미확인이다 |

기억으로 쓴 값은 없다. 표의 모든 모델 ID 는 위의 목록 조회나 SDK 리터럴에 실제로 있는
문자열이고, 파라미터 이름은 설치한 SDK 의 시그니처에서 읽은 것이다.

## 스키마가 지금 스키마 그대로 나가는가

넷을 붙이기 전에 한 가지가 걸린다. 지금 응답 스키마인 `Classification` 과 `SelectorSet` 은
Gemini 에 맞춰져 있다. `app/classify/schema.py` 가 적어 둔 대로 **Gemini 는
`additionalProperties: false` 를 모르고 400 을 낸다.** 그런데 GPT 의 strict 모드는 그것을
요구한다.

두 SDK 의 변환 함수에 지금 클래스를 그대로 넣어 봤다.

| 클래스 | `openai` 변환 | `anthropic` 변환 |
|---|---|---|
| `Classification` | 성공. `additionalProperties: false`, 14칸 전부 required, enum 유지 | 성공 |
| `SelectorSet` | 성공. `$defs` 유지 | 성공 |

**클래스를 고치지 않아도 된다.** 각 SDK 가 자기 모양으로 바꿔 준다. 제공자마다 다른 것은
변환 함수 호출 한 줄이고, 그 줄은 제공자 항목 안에 있다.

## 확인하지 못한 것

추측으로 채우지 않은 자리다.

| 무엇 | 왜 못 했나 |
|---|---|
| GPT 의 `gpt-5.6` 계열이 Structured Outputs 를 지원하는지 | 지원 모델 표가 `gpt-4o-2024-08-06` 과 "and later" 까지만 적는다. `gpt-5.6` 이 그 뒤인 것은 맞지만 표에 이름이 없다. 키가 없어 눌러 볼 수도 없다 |
| `qwen3.8-flash` 의 가격 | 가격표 문서에 그 줄이 없다 |
| Claude 의 `output_format` 이 enum 을 어떻게 거절하는지 | 키가 없어 실제 응답을 못 봤다 |
| Qwen 의 `strict: true` 가 실제로 얼마나 지키는지 | 403 에 막혀 한 번도 부르지 못했다. 문서의 "권장" 이상은 모른다 |
| Qwen 워크스페이스 전용 도메인 문자열 | `WorkspaceId` 는 콘솔에서만 보인다 |
| Gemini `client.aio.interactions.create` | 문서에서 비동기 형태의 예제를 찾지 못했다. 이 Push 에서 쓰지 않는다 |

앞의 셋은 키가 생기면 한 번의 호출로 답이 난다. 그때까지는 문서가 적은 것을 적어 둔다.
