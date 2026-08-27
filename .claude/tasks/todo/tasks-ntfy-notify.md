# Tasks: 새 공고가 들어오면 알린다 (ntfy)

> 브랜치: `feat/auto-register` (자동 등록 작업과 같은 브랜치, 파일이 겹치지 않는다)
> 상태: 완료

## 목표

새 공고가 적재되면 ntfy 로 알림을 보낸다. 보낼지 말지와 어디로 보낼지는 운영 설정 화면에서
정한다.

## 확인된 것 (2026-08-25)

대상 `https://ntfy.supabin.com/job` 이 200 을 준다. 한글·마크다운·태그 전부 받는다.

```
curl -H "Title: 연결 확인" -H "Priority: low" -H "Tags: white_check_mark" \
     -H "Markdown: yes" -d "..." https://ntfy.supabin.com/job
-> 200 {"id":"...","topic":"job","priority":2,...}
```

ntfy 가 받는 헤더 (공식 문서 확인):

| 무엇 | 헤더 | 값 |
|---|---|---|
| 제목 | `X-Title` | 글자 |
| 우선순위 | `X-Priority` | `1`~`5` (`min`·`low`·`default`·`high`·`urgent`) |
| 태그 | `X-Tags` | 쉼표로 나눔. 이모지 단축이름과 맞으면 아이콘으로 그려진다 |
| 마크다운 | `X-Markdown` | `yes` |
| 눌렀을 때 열 주소 | `X-Click` | URL |
| 단추 | `X-Actions` | 최대 3개 |

## 결정해 둔 것

**한 공고마다 보내지 않는다. 실행 하나에 한 번 보낸다.** SK 는 한 번에 104건이 들어온다.
공고마다 보내면 알림이 104개 온다.

**태그는 쓰고 본문은 글자로 쓴다.** `.claude/rules/writing.md` 의 이모지 금지는 문서에 대한
것이고 휴대폰 알림은 문서가 아니다. 태그는 ntfy 가 상태를 한눈에 보이게 하는 자리라 쓰되,
본문 문장에는 그림문자를 넣지 않는다.

**보내는 것은 `httpx` 로 한다.** 사용자가 "curl 로" 라고 한 것은 방식을 말한 것이고, 파이썬에서
`subprocess` 로 curl 을 부르는 것은 더 나쁘다. 같은 HTTP POST 다.

**공용 fetch 클라이언트를 쓰지 않는다.** `.claude/rules/crawling.md` 의 그 클라이언트는 크롤링
대상 사이트를 보호하는 장치다(robots 확인, 호스트별 딜레이). 우리 알림 서버에 robots 를 묻는
것은 뜻이 없다. **대신 `.claude/rules/crawling.md` 와 `.claude/rules/core.md` 의 "모든 외부
요청" 문구를 "크롤링 대상에 대한 모든 요청" 으로 고쳐 이 예외를 규칙에 적는다.** 규칙을 두고
코드만 예외를 두면 다음에 또 충돌한다.

## 관련 파일

- `app/api/ui_settings.py` - 운영 설정 화면
- `app/templates/fragments/settings_form.html`
- `app/settings.py`, `app_settings` 표 - 키·값 설정이 이미 있다. **새 표를 만들지 않는다**
- `app/crawler/runner.py` - 실행이 끝나는 자리(`_finish_run`, `RunResult`)
- `app/api/ui.py` - `as_time` 필터, `NEXT_STEPS`
- `app/templates/macros.html` - 실패·빈 상태 공통 매크로

## 다른 작업과 겹치지 않게

같은 브랜치에서 **자동 등록 작업**이 동시에 돕니다. 그쪽이 쓰는 파일을 건드리지 마세요.

- `app/selector/discovery.py`, `app/selector/api_schema.py`
- `app/api/crawlers.py`, `app/api/ui_crawlers.py`
- `app/templates/fragments/crawler_*.html`
- `.claude/site-recipes/`

`git add` 는 반드시 경로를 지정해서 하세요.

## 작업

- [x] 1.0 새 공고를 알린다
    - [x] 1.1 알림 보내는 자리를 만든다
        - 새 모듈(`app/notify/ntfy.py` 등). 서버 URL·토픽·우선순위를 받아 POST 한다
        - 실패해도 **실행을 실패로 만들지 않는다.** 알림이 안 갔다고 수집이 실패한 것은 아니다.
          사유는 로그에 남긴다
        - 타임아웃을 둔다. 알림 서버가 응답하지 않아 실행이 멈추면 안 된다
        - [x] 1.1.V 검증: 픽스처 기반 pytest — `httpx.MockTransport` 로 헤더가 제대로 실리는지,
              서버가 5xx 를 줘도 예외가 밖으로 새지 않는지
    - [x] 1.2 알림 내용을 만든다
        - 제목: 사이트 이름과 새 공고 수가 읽히게
        - 본문: 마크다운. 회사와 제목을 몇 건 보이고 나머지는 "외 N건" 으로 줄인다.
          104건을 다 넣으면 알림이 읽히지 않는다
        - **누르면 공고 원본이 열린다.** `X-Click` 은 새로 들어온 첫 공고의
          `source_url` 이고, 본문의 제목마다 그 공고 주소로 링크를 건다
        - `X-Actions` 는 넣지 않는다. 본문 링크가 닿는 곳과 같아서 단추 3개가 더 해 주는 일이 없다
        - 태그로 상태를 보인다
        - [x] 1.2.V 검증: 픽스처 기반 pytest — 1건·5건·104건일 때 본문이 각각 어떻게 줄어드는지

#### 링크가 사람이 볼 수 없는 주소일 때 (2026-08-25 결정)

**그대로 링크한다.** 알림 쪽에서 가려내지 않는다.

삼성의 `source_url` 은 `https://www.samsungcareers.com/recruit/detail.data?seqno=...` 라는 API
주소이고 누르면 JSON 이 열린다. 그 사이트는 목록에서 누르면 모달이 뜨는 구조라 공고마다 따로
열 주소가 없다.

가려내지 않는 이유는 이 값이 알림만의 값이 아니어서다. 같은 `source_url` 이
`.claude/docs/api-contract.md` 의 제공 API 로 채용공고 사이트에 이미 나가고 있다. 알림에서만
숨기면 소비 측에 나가는 값은 그대로인 채 그것이 잘못됐다는 신호만 사라진다. 알림은 이 문제가
**처음 눈에 띄는 자리**이지 고칠 자리가 아니다.

주소 모양으로 판별하지도 않는다. `detail_mode = api` 인 크롤러 중 LG·한화·현대자동차는 사람이
볼 수 있는 주소를 주고 삼성만 다르다. 갈라 주는 설정값이 없어 남는 길은 `.data` 로 끝나는지
보는 것뿐인데, 그것은 삼성 한 곳을 위한 추측이다 (`.claude/rules/core.md` 단순함 우선).

고칠 자리는 `source_url` 을 정하는 쪽이다 — 삼성 크롤러의 `link_template` 이 사람이 볼 수 있는
주소를 만들게 하거나, 만들 수 없다면 그 사실을 `.claude/site-recipes/` 에 적는다. 셀렉터·크롤러
쪽 작업이라 이 작업 파일 밖이다.
    - [x] 1.3 운영 설정에 알림 화면을 만든다
        - 켜기·끄기, 서버 URL, 토픽, 우선순위, **몇 건 이상일 때 보낼지**
        - **테스트 전송 단추.** 설정이 맞는지 확인할 길이 없으면 운영자가 못 믿는다
        - 값은 `app_settings` 에 넣는다. 새 표를 만들지 않는다
        - 이모지·아이콘 금지, 시각은 `as_time` 필터
        - [x] 1.3.V 검증: 로컬에서 화면을 열어 저장하고 테스트 전송이 실제로 도착하는지
    - [x] 1.4 실행이 끝나면 부른다
        - 새로 적재된 건수가 설정한 값 이상일 때만 보낸다
        - **건너뜀이나 실패는 알리지 않는다.** 새 공고가 들어온 것만 알린다
        - 꺼져 있으면 부르지 않는다
        - [x] 1.4.V 검증: 픽스처 기반 pytest — 신규 0건이면 안 보내고, 설정값 미만이면 안 보내고,
              꺼져 있으면 안 보내는지
    - [x] 1.5 규칙 문구를 고친다
        - `.claude/rules/core.md` 의 "Every outbound HTTP request goes through the one shared
          fetch client" 와 `.claude/rules/crawling.md` 의 "One fetch client" 를 크롤링 대상에
          대한 것으로 한정한다. 알림처럼 우리 쪽 서비스로 나가는 요청은 예외임을 적는다
        - **예외를 넓게 열지 않는다.** "우리가 운영하는 서비스" 로 좁게 쓴다
        - [x] 1.5.V 검증: 규칙 문구와 실제 코드가 어긋나지 않는지 대조

          `6deaaec` 에서 세 곳을 같이 고쳤다 — `.claude/rules/core.md`,
          `.claude/rules/crawling.md`, `.claude/hooks/guard-direct-fetch.sh`. 예외는
          `app/notify/` 하나로 좁혀 적혀 있고, 우리가 배포하지 않은 제3자 API 는 크롤링
          대상이라고 못박았다. 훅도 같이 고쳐 경고가 나지 않는다.

          **사용자 확인이 필요하다.** `.claude/rules/core.md` 는 `CLAUDE.md` 가 직접
          import 하는 파일이고 훅은 `settings.json` 에 등록된 설정이다. 문구에 동의하지
          않으면 `git revert 6deaaec` 가 아니라 그 세 파일만 되돌린다 — 같은 커밋에 알림
          링크 코드가 함께 들어 있다.

## 하지 않는 것

- 이메일·슬랙 등 다른 알림 경로
- 공고 하나마다 보내기
- 실패를 알리는 것 (지금은 새 공고만)
