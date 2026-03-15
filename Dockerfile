FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# デフォルトはrag.py（docker-compose側でCMDを上書き可能）
CMD ["python3", "rag.py"]
