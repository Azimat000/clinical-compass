# Презентация к предзащите и демо-дню

- `klinicheskiy-kompas-demo-day.pptx` — презентация, 18 слайдов (слайды 16–17 — приложение, финальный «Спасибо» последний), 16:9, речь в заметках докладчика.
- `klinicheskiy-kompas-demo-day.pdf` — та же презентация в PDF.
- `speech.md` — речь с отметками времени и точками сокращения (около 5,5 минуты).
- `metrics.json` — все цифры со слайдов, условия замера и источники. Менять цифры только здесь.
- `assets/` — снимки экранов работающего сервиса на вымышленных данных (23.10.2026).
- `build_deck.cjs` — генератор.

## Пересборка

Нужны Node и пакеты `pptxgenjs sharp react react-dom react-icons qrcode` в отдельной папке (в репозиторий не добавляются):

```bash
NODE_PATH=/путь/к/node_modules node deliverables/presentation/build_deck.cjs --url https://адрес-демо-стенда
```

Без `--url` на слайде благодарностей остаётся рамка под QR-код. Состав команды — константа `TEAM` в начале `build_deck.cjs`.

Навыки, по которым собрана презентация: `.claude/skills/demo-day-deck`, `pitch-craft`, `theme-factory` и встроенные `pptx`, `dataviz`, `humanizer`.
