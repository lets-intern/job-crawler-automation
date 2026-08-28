# Tasks: fields-and-logo - Push 4

> PRD: `.claude/tasks/todo/prd-fields-and-logo.md`
> Push 범위: `companies` 표와 자동 등록. 로고 칸은 비어 있다
> 상태: 진행 중

## 관련 파일

- `app/normalize/engine.py` - 회사명을 정하는 자리. 여기서 처음 보는 이름을 만난다
- `app/settings.py`, `app/notify/settings.py` - 저장소 모듈의 본보기
- `.claude/rules/data-safety.md` - 자동으로 지우지 않는다

## 선행 조건

- Push 3 완료 (모회사·자회사가 갈려 있어야 어느 이름을 넣을지 정해진다)

## 작업

- [ ] 4.0 회사 표
    - [x] 4.1 마이그레이션. `companies (id, name, parent_name, logo_url, created_at,
          updated_at)`. `name` 은 유일하다
        - [x] 4.1.V 검증(스키마): 적용·역적용, 같은 이름 두 번 넣기가 거절되는지
    - [x] 4.2 저장소 모듈. 목록, 한 건 읽기, 로고 주소 쓰기, 모회사 이름 쓰기
        - [x] 4.2.V 검증(스키마): 넣고 읽어 값이 그대로인지 pytest
    - [ ] 4.3 정규화가 처음 보는 회사명을 만나면 행을 만든다. 로고는 비운다. 자동으로 만들지
          않으면 운영자가 회사명을 손으로 다시 치게 되고 오타 하나로 로고가 안 붙는다
        - [ ] 4.3.V 검증(정규화): 같은 회사 공고 여러 건을 정규화해도 행이 하나인지, 자회사가
              빈 건은 모회사 이름으로 행을 만들지 확인하는 pytest
    - [ ] 4.4 행을 자동으로 지우지 않는다. 공고가 다 사라진 회사도 남는다 — 지우는 것은
          운영자가 한다
        - [ ] 4.4.V 검증(스키마): 그 회사의 공고를 다 지워도 `companies` 행이 남는지 pytest
