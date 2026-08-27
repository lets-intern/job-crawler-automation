# Tasks: job-crawler - Push 14

> PRD: `.claude/tasks/done/job-crawler/prd-job-crawler.md`
> Push 범위: 상세 링크가 `href` 가 아닌 사이트 — 링크 추출 방식을 넓힌다
> 상태: 진행 중

## 무엇이 막혔나

Push 11 이 Playwright 를 넣어 렌더는 성공했다. 한화 3자 → 441,363자, 현대자동차 13자 →
1,331,820자로 목록이 실제로 채워졌다. 그런데 두 사이트 다 등록에 실패했다.

렌더된 HTML 에 셀렉터를 적용한 결과다.

| 사이트 | item | title | date | link 노드 | href 있음 | 따라갈 수 있는 href |
|---|---|---|---|---|---|---|
| 한화 | 20 | 20 | 20 | 20 | 0 | 0 |
| 현대자동차 | 20 | 20 | 20 | 20 | 20 | 0 |

**목록은 다 읽었고 상세로 가는 길만 없다.**

- 한화: 목록 항목 20개 안에 `a` 태그가 0개다. Vue 라우터로 이동하고 `rtSeq` 는 렌더된 DOM
  어디에도 없다
- 현대자동차: `href` 가 전부 `javascript:void(0)` 이고 상세 파라미터는 `li` 의
  `data-recuyy`, `data-recutype`, `data-recucls` 에 들어 있다. 실행이 `javascript:;` 를 상세 URL 로
  넘겼고 공용 클라이언트가 http(s) 가 아니라며 거절했다

`seeds/sample-sites.json` 이 삼성에 적어 둔 `detail_link_absent` 와 같은 종류다.
현재 셀렉터 스키마는 `list.link` 가 `href` 를 준다고 전제하는데, 그 전제가 이 사이트들에서 깨진다.

## 함께 드러난 검증 결함

생성 시점 자체 검증이 `list.link` 를 **노드 수로만** 판정한다. 한화에서 모델이 `list.link` 로
`h4.recruit-title` 을 골랐는데 20/20 매칭으로 통과했다. 링크가 아닌 요소를 골라도 성공으로 보인다.

Push 12 의 12.4·12.5 와 같은 계열이다 — 숫자만 세고 쓸 수 있는 값인지 보지 않는다.

## 관련 파일

- `app/selector/schema.py` - 링크 추출 방식
- `app/selector/verify.py` - href 유무 판정
- `app/selector/generator.py` - 프롬프트
- `app/crawler/parser.py` - 상세 URL 조립
- `.claude/site-recipes/www-hanwhain-com.md`, `talent-hyundai-com.md`

## 선행 조건

- Push 11 완료 (렌더가 돼야 이 문제가 드러난다)

## 작업

- [x] 14.0 상세 링크 추출 (Push 범위)

    - [x] 14.1 자체 검증이 href 유무를 본다
        - `list.link` 는 노드 수가 아니라 **따라갈 수 있는 URL 이 나오는지**로 판정한다
        - `href` 가 없거나 `javascript:`, `#` 뿐이면 실패다. 노드가 20개여도 실패다
        - 이것부터 하는 이유는, 지금은 못 쓰는 셀렉터가 성공으로 보이기 때문이다
        - [x] 14.1.V 검증: 픽스처 기반 pytest 작성 및 통과 — `a` 없는 요소를 고른 셀렉터, `href` 가
          `javascript:void(0)` 인 셀렉터가 각각 실패로 판정되고, 정상 `href` 는 성공인지 단언

    - [x] 14.2 링크 추출 방식을 넓힌다
        - `list.link` 가 두 가지를 받게 한다
          1. 지금처럼 `href` 를 읽는 방식 (기본)
          2. **속성값 + URL 템플릿** — 항목에서 지정한 속성들을 읽어 템플릿에 끼운다
        - 현대자동차 예: `data-recuyy`·`data-recutype`·`data-recucls` 를
          `https://talent.hyundai.com/apply/applyView.hc?recuYy={recuYy}&recuType={recuType}&recuCls={recuCls}` 에 끼운다
        - 기존에 저장된 셀렉터 JSON 이 깨지면 안 된다. 방식을 적지 않으면 `href` 로 본다
        - 조립된 URL 도 공용 fetch 클라이언트를 지난다. http(s) 가 아니면 거절한다
        - 한화처럼 상세 파라미터가 DOM 에 아예 없는 경우는 이 방식으로도 안 된다.
          **그 사실을 실패 사유에 적는다.** 억지로 만들지 않는다
        - [x] 14.2.V 검증: 픽스처 기반 pytest 작성 및 통과 — 속성 세 개로 조립한 URL 이 기대값과 일치하고,
          속성이 없는 항목은 실패로 기록되며, 방식을 적지 않은 기존 셀렉터가 그대로 동작하는지 단언

    - [x] 14.3 실사이트 확인
        - **현대자동차 한 곳만** 확인한다. 속성 + 템플릿으로 실제 상세를 따라갈 수 있어야 한다
        - 한화는 이 Push 로 풀리지 않는다. 확인하지 말고 레시피에 남은 이유를 적는다
        - [x] 14.3.V 검증: 실사이트 1회 실행 후 `crawl_runs` 행과 `raw_jobs` 적재 건수를 숫자로 확인.
          실패하면 원인을 적고 통과시키지 말 것

    - [x] 14.4 실사이트 확인 중 나온 간헐적 렌더 미스를 기록한다
        - 14.3 확인 도중 현대자동차 실행 3회 중 1회(run 5)가 `selector_miss` 로 실패했다.
          같은 URL·같은 셀렉터로 1분 뒤 run 6, run 7 은 20건을 잡았다
        - 셀렉터를 넓혀서 고칠 문제가 아니다. `selector_miss` 는 재시도 대상이 아니므로
          (`.claude/rules/crawling.md`) 코드를 고치지 않고 사실만 레시피에 남긴다
        - [x] 14.4.V 검증: `.claude/site-recipes/talent-hyundai-com.md` 에 run 번호와 함께
          기록되어 있는지 확인
