FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY pyproject.toml /app/
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .[test]

COPY . /app

CMD ["python", "-m", "app.bot.main"]
