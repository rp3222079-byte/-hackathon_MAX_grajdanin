# Запускать из корня project-root: make <команда>

.PHONY: install run-backend run-frontend run format lint
# .PHONY говорит make, что это не имена файлов, а именно команды —
# без этого, если вдруг появится файл/папка с именем "run" или "install",
# make может решить, что цель уже "собрана", и ничего не сделает.

# Установка всех зависимостей: и бэкенда, и фронтенда одной командой
install:
	cd backend && pip install -r requirements.txt
	cd frontend && npm install

# Запуск только бэкенда (Python-сервер)
run-backend:
	cd backend && python main.py

# Запуск только фронтенда (React dev-сервер)
run-frontend:
	cd frontend && npm start

# Запуск бэка и фронта одновременно (в фоне)
run:
	make run-backend & make run-frontend

# Автоформатирование кода: Python (ruff) + JS/JSX/CSS (prettier)
# Меняет файлы на месте — запускать до коммита
format:
	cd backend && ruff format .
	cd frontend && npx prettier --write .

# Проверка на ошибки и нарушения стиля без изменения файлов
# ruff check — Python, eslint — JS/JSX
lint:
	cd backend && ruff check .
	cd frontend && npx eslint . --ext .js,.jsx