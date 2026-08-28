# 결과보고서: tasks-llm-providers-push1.md

> 완료일: 2026-08-27
> Push 범위: 호출 자리를 제공자에서 떼어내고 네 제공자를 붙인다. 화면은 건드리지 않는다
> 상태: 여덟 중 일곱 완료. 1.8(실제 분류 실행)은 계정과 데이터에 막혀 남았다

## 구현 요약

| 작업 | 상태 | 커밋 |
|---|---|---|
| 1.1 네 제공자의 현재 문서를 확인하고 조사 결과를 적는다 | 완료 | `5517c37` |
| 1.2 `app/llm/` 에 제공자 항목과 공통 타입을 만든다 | 완료 | `2842267` |
| 1.3 Qwen 항목을 붙인다 | 완료 | `1681a0d` |
| 1.4 Claude 와 GPT 항목을 붙인다 | 완료 | `41c1a28` |
| 1.5 기능마다 제공자와 모델을 환경변수로 고른다 | 완료 | `367c5f5` |
| 1.6 세 호출 자리가 고른 제공자를 쓰게 한다 | 완료 | `680f75f` |
| 1.7 호출 기록에 실제 제공자가 남는다 | 완료 | `9185d69` |
| 1.8 Qwen 으로 실제 분류를 돌린다 | 미완료 | 없음 |

## 생성·수정 파일

새로 만든 것.

- `app/llm/base.py` - 제공자와 무관한 것만. `LlmCallError`, `Usage`, `Provider`, 로그 형식
- `app/llm/providers.py` - 이름을 항목으로 바꾸는 자리. 기능별 선택과 스키마 강제 판정
- `app/llm/openai_compat.py` - OpenAI SDK 로 부르는 제공자들. Qwen 과 GPT
- `app/llm/claude.py` - Claude 항목
- `tests/test_llm_qwen.py`, `tests/test_llm_claude_gpt.py`, `tests/test_llm_feature_provider.py`
- `.claude/tasks/memos/llm-provider-조사.md` - 1.1 의 산출물

고친 것.

- `app/llm/gemini.py` - Gemini 항목만 남기고 공통 타입을 `base.py` 로 보냈다
- `app/llm/log.py` - `from app.llm.gemini import PROVIDER` 를 지웠다. `usage.provider` 를 쓴다
- `app/config.py` - 제공자별 키·모델·주소, 기능별 선택, 빈 문자열 처리
- `app/selector/generator.py` · `app/selector/repair.py` · `app/classify/classifier.py` -
  `resolved.gemini_model` 을 직접 읽던 자리를 기능 이름으로 바꿨다
- `app/classify/batch.py` - 실패한 호출도 제공자와 모델을 남긴다
- `app/api/crawlers.py` - 두 번 부른 생성의 비용을 합칠 때 제공자를 잃지 않는다
- `app/api/ui.py` - `no_api_key` 안내가 `GEMINI_API_KEY` 를 못박고 있었다
- `.env.example` · `pyproject.toml` (`openai`, `anthropic`)
- `Usage` 를 만드는 테스트 여덟 곳

## 검증 결과

| 대상 | 검증 | 결과 |
|---|---|---|
| 1.1 모델 ID·파라미터 | 공식 문서 + 실 API 모델 목록 + 설치 SDK 대조 | 네 자리 틀렸고 고쳤다 |
| 1.2 공통 타입 이동 | `mypy app`, 기존 pytest 전체 | 통과. **테스트 수정 0건** |
| 1.3 Qwen 항목 | 픽스처 pytest | 17건 통과 |
| 1.4 Claude·GPT 항목 | 픽스처 pytest | 18건 통과 |
| 1.5 설정 | `tests/test_config.py` | 34건 통과 |
| 1.6 기능별 제공자 | 픽스처 pytest | 10건 통과 |
| 1.7 호출 기록 | `tests/test_llm_calls.py` | 7건 통과 |
| 전체 | `pytest -m "not live"` | 1436건 통과 (시작 시 1359건) |
| 전체 | `mypy app` | 74파일 오류 0 |
| 전체 | `ruff check` | 새 오류 0. 남은 5건은 손대지 않은 파일의 기존 것 |

커밋마다 이 검사를 돌렸고, 통과한 뒤에만 체크했다.

### 1.1 을 어떻게 대조했나

문서만 읽으면 모델 ID 가 지금도 있는지 알 수 없어서 경로를 셋으로 나눴다.

| 대조한 것 | 방법 |
|---|---|
| Gemini 모델 ID 3개 | 실 API `models.list()` |
| Claude·GPT 모델 ID 4개 | 설치한 SDK 의 모델 리터럴 목록 |
| Qwen 모델 ID 5개, base_url | 실 엔드포인트 `models.list()` |
| 예외 클래스, 메서드 시그니처 | 설치한 SDK |

대조에서 틀린 네 자리는 메모의 "대조 결과 (1.1.V)" 에 남겼다.

## 이슈 및 특이사항

### 1.8 이 막힌 이유 — 코드가 아니다

둘 다 이 저장소에서 풀 수 있는 것이 아니다.

| 막은 것 | 확인한 방법 |
|---|---|
| Qwen 계정에 모델 이용 자격이 없다 | 실제 호출이 403 `AccessDenied.Unpurchased` |
| 이 기계에 운영 데이터가 없다 | `./data/jobs.db` 가 0바이트이고 표가 하나도 없다 |

403 이 모델 이름 문제인지 갈라 봤다. 없는 이름은 404 `does not exist` 로 오고 있는 이름은
403 으로 온다. **이름 문제가 아니라 계정 문제다.** 콘솔에서 Model Studio 를 활성화하거나
결제 수단을 등록해야 풀린다.

Gemini 로 대신 돌릴 수도 없다. 429 `Your prepayment credits are depleted` 로, PRD 가 적은
그대로다. Claude 와 GPT 는 키가 없다. **지금 부를 수 있는 제공자가 하나도 없다.**

배선은 확인했다. 실제 키로 `classify_body()` 를 한 번 불러 설정에서 고른 제공자가 Qwen
항목으로 이어지고, DashScope 에 실제 요청이 나가고, 그 실패가
`ClassifyError("api_error", "Qwen 호출 실패(403): ...")` 로 돌아오는 것까지 봤다.
**남은 것은 자격과 데이터뿐이다.**

### `.env` 의 `QWEEN_API_KEY` 를 고쳤다

철자가 틀려 있었다. `QWEN_API_KEY` 로 고쳤고 값은 그대로다. **둘 다 읽는 코드를 쓰지
않았다** — 오타를 코드가 받아 주면 오타가 규격이 되고, 다음 사람이 어느 쪽이 맞는지 알 길이
없어진다.

Claude 와 GPT 의 키 이름도 제공자 이름을 따라 `CLAUDE_API_KEY`·`GPT_API_KEY` 로 뒀다.
제공자 문서의 이름(`ANTHROPIC_API_KEY`·`OPENAI_API_KEY`)을 쓰지 않은 것은, SDK 가 그 이름을
환경에서 스스로 읽어 이 서비스가 설정한 적 없는 남의 키로 호출이 나가는 길을 막기 위해서다.

### Qwen 은 아무 모델에서나 분류에 쓸 수 없다

`json_schema` + `strict` 가 되는 것은 `qwen3.7-plus`·`qwen3.7-flash`·`qwen3.7-max`·
`qwen3.8-flash`·`qwen3.8-max` 시리즈뿐이다. `qwen-turbo`·`qwen-plus`·`qwen-flash` 같은
별칭에서 되는 것은 `json_object` 이고, 그것은 칸 이름도 값도 보장하지 않는다.

그래서 별칭을 분류에 지정하면 `no_schema_support` 로 선다. 기본 모델도 별칭이 아닌
`qwen3.8-flash` 로 뒀다.

### 구현하면서 정한 것 둘

**제공자별 키·모델 설정을 1.5 가 아니라 그 제공자를 붙이는 작업에서 같이 더했다.**
설정이 없으면 그 항목은 임포트조차 되지 않아, 미루면 중간 커밋이 깨진 채로 남는다.

**제공자 이름을 `record_call` 의 인자가 아니라 `Usage` 에 실었다.** 답한 제공자만이 그 값을
안다. 기록하는 쪽에서 설정을 다시 읽어 알아내면 호출과 기록 사이에 설정이 바뀌었을 때 기록이
거짓이 된다. `Usage` 를 만드는 테스트 여덟 곳이 같이 바뀐 것이 대가다.

## 하지 않은 것 — 사용자 판단이 필요하다

### compose 가 새 환경변수를 컨테이너에 넘기지 않는다

task 파일이 1.5 의 대상으로 `.env.example` 만 적었고 `관련 파일` 에도 compose 가 없어서
건드리지 않았다. 그런데 **이 Push 의 "끝나면" 문장이 여기에 걸린다.**

`docker-compose.yml` 과 `docker-compose.coolify.yml` 은 변수를 이름으로 하나씩 나열해
넘긴다. `QWEN_API_KEY`·`CLAUDE_API_KEY`·`GPT_API_KEY`·모델 넷·기능별 선택 셋이 그 목록에
없어서, **지금 배포하면 키를 넣어도 컨테이너 안까지 가지 않는다.** 자격이 풀린 뒤 배포로
분류를 돌리려면 이 줄들이 먼저 필요하다.

한 줄씩 더하면 되는 일이지만 배포 설정이라 임의로 넓히지 않았다.

### `.claude/tasks/memos/README.md` 와 새 메모가 어긋난다

그 README 는 "여기 있는 것은 작업 대상이 아니다. 보류한 구상을 둔다" 고 적고 있다.
1.1 이 만든 `llm-provider-조사.md` 는 보류한 구상이 아니라 지금 쓰는 조사 결과다.
표에도 올리지 않았다. 폴더의 뜻을 바꾸는 판단이라 손대지 않았다.

### 확인하지 못한 채 남긴 값

메모의 "확인하지 못한 것" 에 다섯 줄로 적었다. 키가 생기면 한 번의 호출로 답이 나는 것이
셋이다.

- GPT 의 `gpt-5.6` 계열이 Structured Outputs 지원 모델 표에 이름이 없다. "그 이후" 에
  드는 것은 맞지만 표에 적혀 있지는 않다
- `qwen3.8-flash` 의 가격이 가격표 문서에 없다. 유추하지 않고 미확인으로 뒀다
- GPT 에 `temperature=0.0` 을 그대로 보낸다. 최신 모델이 기본값 외의 값을 거절하는지
  확인하지 못했고, 키가 없어 눌러 볼 수도 없었다. 거절한다면 첫 호출이 `api_error` 로
  서고 메시지에 이유가 남는다
