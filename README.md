# AI 기반 개인 맞춤형 패션 에이전트

Qwen3-4B, FastAPI, PostgreSQL 기반의 AI 개인 맞춤형 패션 에이전트 프로젝트입니다.

## 프로젝트 개요

Qwen3-4B를 패션 추천 및 Tool Calling 데이터로 QLoRA Fine-Tuning하여
Fashion SLM(패션 특화 소형 언어 모델)을 구축하고,
Router + Tool Calling 구조의 AI Agent를 구현합니다.

사용자의 취향, 보유 의류, 목적지 날씨, Google Calendar 일정 등을
필요에 따라 조회하여 개인 맞춤형 3가지 코디를 추천합니다.

## 주요 기술

- AI Model: Qwen3-4B
- Fine-Tuning: QLoRA 4bit
- Backend: Python + FastAPI
- Database: PostgreSQL
- Frontend: JavaScript + HTML + CSS
- UI/UX: Figma
- Location: Kakao Local API
- Weather: 기상청 API
- Calendar: Google Calendar API (Read Only)

## Git Branch 전략

```text
main
└── develop
    └── feature/*
```

## 상세 프로젝트 구조

프로젝트 전체 구조, Agent Architecture, 학습 데이터, Tool 구성,
WBS 기준 개발 흐름 등은 아래 문서를 참고합니다.

→ [프로젝트 상세 구조](docs/project-structure.md)

## 외부 기능 연동 검증

- [Web Geolocation 실행 및 수동 검증](frontend/README.md)
