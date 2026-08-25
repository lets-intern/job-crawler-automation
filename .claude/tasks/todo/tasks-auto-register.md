# Tasks: 목록 URL 하나로 자동 등록

> 브랜치: `feat/auto-register` (기준 `main` `122ff3f`)
> 상태: 진행 중

## 목표

**운영자가 목록 URL 하나만 넣으면 등록이 끝난다.** 정적이냐 렌더냐를 고르지 않는다.
판정은 등록 과정이 한다.

## 지금 무엇이 있나

`app/selector/discovery.py` 의 `discover_detail_path()` 가 이미 순서를 담고 있다.

1. 목록을 `httpx` 로 받아 항목과 상세 주소가 다 있으면 끝 (브라우저 안 띄움)
2. 모자라면 렌더
3. 그래도 없으면 항목을 클릭해 그 순간 나간 요청을 줍는다
4. 줍은 요청을 `httpx` 로 다시 불러 확인한 뒤 채택

`app/api/crawlers.py` 의 `create_crawler` 가 이것을 부르고 `api_config_json` 까지 저장한다.
`Discovery` 에 `evidence`(근거 문장)·`reason`·`failure`·`list_count` 가 있다.

**빠진 것은 두 가지다.** 등록 화면이 아직 렌더 모드를 묻고, 판정이 **상세 경로만** 찾는다.

## 새 사이트 다섯 곳 (2026-08-25 실측)

| 사이트 | 목록 URL | 정적 | 목록 API |
|---|---|---|---|
| 두산 | `https://career.doosan.com/dsp/sa/RecList.jsp` | **`a.list-tit` 29건** | 없음 |
| 네이버 | `https://recruit.navercorp.com/rcrt/list.do` | **`ul.card_list > li` 10건** | 없음 |
| 토스 | `https://toss.im/career/jobs` | 안 잡힘 | `GET https://api-public.toss.im/api-public/v3/ipd-thor/api/v1/workspaces/13/posts?page=1` |
| 카카오 | `https://careers.kakao.com/jobs?part=BUSINESS_SERVICES&company=KAKAO&page=1` | 껍데기 1,553B | `GET https://careers.kakao.com/public/api/job-list?skillSet=&part=BUSINESS_SERVICES&company=KAKAO&keyword=&employeeType=&page=1` |
| 우아한형제들 | `https://career.woowayouths.com/recruitment/` | 반복 없음 | `GET https://career.woowayouths.com/w1/recruits?category=jobGroupCodes%3ABA005010&...` |

응답 구조는 이렇다. 셋 다 `referer` 만 있으면 브라우저 없이 200 이다.

- 토스: `.success.results` 20건. `id`(52443), `title`, `category`(계열사 — 토스뱅크 등), `series`
- 카카오: `.jobList` 11건. `realId`(`P-14503`, 상세 URL 과 같다), `jobOfferTitle`, `endDate`, `closeFlag`
- 우아한형제들: 항목 `a.title` 의 `href` 가 `/recruitment/R2607031/detail?category=...` 로 바로 나온다

상세 URL 형식:
`recruit.navercorp.com/rcrt/view.do?annoId=30005276` /
`toss.im/career/job-detail?job_id=7665307003` /
`careers.kakao.com/jobs/P-14503`

**네이버에 함정이 있다.** `li.item` 이 144건 잡히는데 실제 공고는 `ul.card_list > li` 10건이다.
넓은 쪽을 집으면 네비게이션을 공고로 센다.

### 2026-08-25 재측정에서 달라진 것

토스 `.../workspaces/13/posts` 는 공고 목록이 아니라 커리어 아티클 목록이다(`title` 이
"토스뱅크 Server Chapter와 Server Platform Team이 일하는 방식" 같은 글 제목). `toss.im/career/jobs`
를 렌더하는 동안 나간 JSON 요청은 푸터·배너·헤더뿐이고 공고 배열을 담은 응답이 없다. 공고
263건은 초기 HTML 안에 `href="/career/job-detail?job_id=..."` 로 이미 들어 있다. 그래서 토스는
목록 API 가 아니라 렌더 경로로 등록된다. 1.1.V 의 "후보가 없는 응답" 검증에 이 세 응답을 쓴다.

우아한형제들 목록 API 응답은 `data.list` 8건이고 항목의 `recruitNumber`(`R2607031`)가 렌더된
항목의 `href` 에 그대로 들어 있다. 카카오는 `jobList` 11건, `realId`(`P-14503`)가 같은 자리다.

## 작업

- [ ] 1.0 목록 URL 하나로 등록이 끝나게 한다
    - [x] 1.1 판정이 목록 API 도 찾는다
        - 지금 `discover_detail_path()` 는 상세 경로만 찾는다. 토스·카카오·우아한형제들은
          **목록 자체가 API** 라 이것이 없으면 자동 등록이 안 된다
        - 렌더 중 관찰한 응답(`app/crawler/playwright.py` 의 요청 관찰) 중 항목 배열을 담은
          것을 목록 API 후보로 잡는다. 렌더된 항목 수와 비슷한 길이가 단서다
        - 찾으면 `ApiListConfig` 로 저장하고 `httpx` 로 다시 불러 확인한 뒤 채택한다
        - [x] 1.1.V 검증: 픽스처 기반 pytest — 토스·카카오 응답으로 목록 API 를 집어내고,
              후보가 없는 응답에서는 빈 결과가 나오는지
    - [x] 1.2 등록 화면에서 렌더 모드 선택을 없앤다
        - [x] 1.2.1 (추가) 정적으로 목록이 안 잡히면 등록이 스스로 렌더로 올려 생성한다
            - 지금은 정적 HTML 에 목록이 없으면 `list_not_found` 로 등록을 거절한다. 운영자가
              모드를 고르지 않게 하려면 거절하는 대신 등록이 렌더로 한 번 더 시도해야 한다
            - 카카오 목록은 정적으로 껍데기 1,553B 라 이것이 없으면 1.2 가 등록을 막는다
            - [x] 1.2.1.V 검증: 정적은 껍데기, 렌더는 항목이 있는 가짜 소스로 pytest
        - [x] 1.2.2 (추가) 항목 셀렉터가 넓게 잡히면 제목이 있는 반복 요소로 좁힌다
            - 네이버 함정이다. `li.item` 144건과 `ul.card_list > li` 10건 중 넓은 쪽을 집으면
              네비게이션을 공고로 센다
            - 제목 셀렉터가 잡은 노드를 하나씩만 품는 가장 가까운 반복 조상으로 좁힌다.
              **넓히지 않는다** — 좁힐 후보가 없으면 모델이 낸 것을 그대로 둔다
            - [x] 1.2.2.V 검증: 네이버 목록 픽스처로 pytest
        - `app/api/ui_crawlers.py` 의 폼에서 `render_mode` 입력을 뺀다
        - 대신 **판정 결과와 근거 문장**을 보인다. `Discovery.evidence` 가 그 값이다
        - 판정이 실패하면 사유와 다음 행동을 보이고, 상세 URL 을 손으로 넣는 길은 남긴다
        - 운영자가 나중에 바꾼 것을 판정이 덮어쓰지 않는다
        - [x] 1.2.V 검증: 로컬에서 등록 화면을 열어 모드 선택칸이 없고 판정 근거가 뜨는지
              (운영 DB 사본을 8140 에 띄워 확인. `name="render_mode"` 0건)
    - [x] 1.3 안내 문구를 고친다
        - 지금 문구는 운영자가 모드를 고른다는 전제로 쓰여 있다
        - "목록 URL 하나만 넣으면 나머지는 등록이 알아서 한다" 는 것이 읽히게 한다
        - 이모지·아이콘 금지. 상태는 글자로 (`.claude/rules/writing.md`)
        - [x] 1.3.V 검증: 로컬에서 화면을 열어 문구가 실제 동작과 맞는지 읽어 확인
    - [ ] 1.3.1 (추가) 항목에 상세 주소가 없으면 클릭으로 주소 형식을 알아낸다
        - 두산과 네이버는 항목의 `href` 가 `javascript:` 이고 공고 번호가 `onclick` 인자에만
          있다. 클릭으로 알아낸 주소 하나를 저장하면 공고가 몇 건이든 같은 상세를 가져온다
        - 알아낸 주소 안의 항목 값을 `{onclick|arg1}` 같은 자리표시자로 바꿔
          `list.link_template` 에 저장한다. 폼 POST 로 나간 요청은 GET 주소로 옮겨 본다
        - **두 항목의 주소를 실제로 열어 제목을 확인한 것만 채택한다**
        - [x] 1.3.1.V 검증: 두산·네이버 픽스처로 pytest, 두 번째 항목이 같은 페이지면 거절
    - [ ] 1.4 다섯 사이트를 등록한다
        - **목록 URL 만 넣어 등록되는지가 이 작업의 시험이다.** 손으로 보태야 하면 왜인지 적는다
        - 네이버는 항목 셀렉터가 `ul.card_list > li` 로 좁게 잡히는지 확인한다
        - [ ] 1.4.V 검증: 다섯 크롤러를 테스트 실행해 필드별 매칭 개수와 본문이 채워지는지 확인
    - [ ] 1.5 사이트 레시피를 쓴다
        - `.claude/site-recipes/` 에 다섯 파일. 목록·상세 경로와 확인 날짜를 적는다
        - 문서에 적는 주소는 코드나 설정에서 복사한다
        - [ ] 1.5.V 검증: 문서에 적힌 엔드포인트와 DB 설정값을 대조

## 하지 않는 것

- 본문을 13개 항목으로 나누는 것
- AI 제공자 넷 고르기
